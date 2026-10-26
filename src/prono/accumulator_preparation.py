"""Préparation explicite des combinés : contrôles, cotes déclarées, équipe existante."""
from collections import Counter
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4
import json
from math import log1p

from .accumulators import _verdicts, propose, indicative_quotes
from .analysis import fixtures, validate_fixture
from .leagues import EUROPE, league_workspace
from .presentation import html_fragment
from .pronos import selections
from .workspace import atomic_write, number, timestamp, utcnow, write_record


def automatic_matches(rows):
    """Préparation bornée, même bookmaker et équipes distinctes ; aucun appel IA."""
    groups = {}
    ordered = sorted((r for r in rows if r['quote_ready']), key=lambda r: (
        -r['selection_score'], -r['selection_probability'], timestamp(r['kickoff']),
        r['division'], r['event_id']))
    for r in ordered:
        group = groups.setdefault(r['bookmaker'], [])
        used = {t.casefold() for x in group for t in x['teams']}
        if len(group) < 15 and not used.intersection(t.casefold() for t in r['teams']):
            group.append(r)
    viable = [g for g in groups.values() if len(g) >= 2]
    if not viable:
        return []
    chosen = min(viable, key=lambda g: (-sum(r['selection_score'] for r in g),
                                       -len(g), g[0]['bookmaker']))
    return [r['event_id'] for r in chosen]


def preparation(ws, period='today', league='all', now=None, quote_mode='indicative'):
    now = now or utcnow()
    if quote_mode not in ('indicative', 'verified'):
        raise ValueError('Mode de cotes inconnu.')
    facts = selections(ws, period, league, now=now)
    if quote_mode == 'indicative':
        facts = {**facts, 'matches': indicative_quotes(facts['matches'])}
    reviews, issues = _verdicts(ws, now)
    issues.extend(facts['issues'])
    excluded, rows = [], []
    ids = Counter(r['fixture']['event_id'] for r in facts['matches'])
    age = timedelta(hours=float(ws.config['data']['max_odds_age_hours']))
    for r in facts['matches']:
        f = r['fixture']
        reason = None
        if r['synthetic']:
            reason = 'Données synthétiques.'
        elif not r['model'].get('available'):
            reason = 'Historique insuffisant pour le calcul Python.'
        elif ids[f['event_id']] != 1:
            reason = 'Identifiant de match ambigu entre compétitions.'
        elif timestamp(f['kickoff']) <= now:
            reason = 'Match déjà commencé.'
        if reason:
            excluded.append({'match': f['home'] + ' / ' + f['away'], 'reason': reason})
            continue
        quote_ready = False
        if f.get('quoted_at') and f.get('odds') and f.get('bookmaker'):
            quoted = timestamp(f['quoted_at'])
            quote_ready = now - age <= quoted <= now and quoted < timestamp(f['kickoff'])
        review = reviews.get((r['division'], f['event_id']))
        coach_current = bool(review and review['blind'] and now - age <= review['started'] <= now
                             and review['completed'] < timestamp(f['kickoff'])
                             and review['fact'].get('match') == f['home'] + ' / ' + f['away']
                             and timestamp(review['fact']['kickoff']) == timestamp(f['kickoff']))
        verdict = review['verdict'] if coach_current else {}
        probabilities = r['model']['probabilities']
        pick = max(probabilities, key=probabilities.get)
        p = probabilities[pick]
        odds = f.get('odds', {}).get(pick)
        fraction = min(.99, float(ws.config['paper']['unit']) / float(ws.config['paper']['starting_balance']))
        score = (p * log1p(fraction * (odds - 1)) + (1 - p) * log1p(-fraction)) if odds else 0
        rows.append({'division': r['division'], 'event_id': f['event_id'],
                     'teams': [f['home'], f['away']], 'selection_score': score,
                     'selection_probability': p,
                     'match': f['home'] + ' / ' + f['away'], 'kickoff': f['kickoff'],
                     'quote_ready': quote_ready or (quote_mode == 'indicative' and bool(f.get('odds') and f.get('bookmaker'))),
                     'indicative': not quote_ready, 'coach_current': coach_current,
                     'coach_outcome': verdict.get('outcome'), 'coach_reason': verdict.get('reason', ''),
                     'bookmaker': f.get('bookmaker', ''), 'quoted_at': f.get('quoted_at'),
                     'odds': f.get('odds', {}), 'source_url': f.get('source_url', ''),
                     'quote_source': f.get('source', '')})
    rows.sort(key=lambda r: (not r['quote_ready'], timestamp(r['kickoff']), r['division'], r['event_id']))
    automatic_ids = automatic_matches(rows)
    proposed = propose(ws, float(ws.config['paper']['unit']) * 5, period, league, now=now,
                       allow_indicative=quote_mode == 'indicative', event_ids=automatic_ids or None)
    return {'period': period, 'league': league, 'quote_mode': quote_mode, 'matches': rows, 'excluded': excluded,
            'issues': issues, 'scanned': len(facts['matches']),
            'automatic_event_ids': automatic_ids,
            'simulation_ready': bool(proposed['tickets']), 'diagnostics': proposed,
            'quote_ready_count': sum(r['quote_ready'] for r in rows),
            'coach_current_count': sum(r['coach_current'] for r in rows)}


def save_quote(ws, body, now=None):
    """L’heure de cotation est déclarée, jamais déduite de la date de saisie."""
    now = now or utcnow()
    code, event_id = body['division'], body['event_id']
    rows = selections(ws, body.get('period', 'today'), code, now=now)['matches']
    matches = [r for r in rows if r['fixture']['event_id'] == event_id]
    if len(matches) != 1:
        raise ValueError('Match absent ou ambigu dans la période choisie.')
    row = matches[0]
    f = row['fixture']
    if (code in EUROPE or row['synthetic'] or not row['model'].get('available')
            or timestamp(f['kickoff']) <= now or body.get('kickoff') != f['kickoff']):
        raise ValueError('Match non admissible ou horaire modifié : recharger la préparation.')
    bookmaker = body.get('bookmaker', '')
    source_url = body.get('source_url', '')
    if not isinstance(bookmaker, str) or not 1 <= len(bookmaker.strip()) <= 100:
        raise ValueError('Nom du bookmaker requis.')
    if not isinstance(source_url, str) or len(source_url) > 2000:
        raise ValueError('Lien source invalide.')
    url = urlsplit(source_url)
    if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
        raise ValueError('Lien public du bookmaker requis (http ou https).')
    quoted = timestamp(body['quoted_at'])
    if not now - timedelta(hours=float(ws.config['data']['max_odds_age_hours'])) <= quoted <= now:
        raise ValueError('Heure de cotation future ou trop ancienne. Ne pas utiliser la date de saisie à sa place.')
    fixture = validate_fixture({
        'event_id': event_id, 'home': f['home'], 'away': f['away'], 'kickoff': f['kickoff'],
        'bookmaker': bookmaker.strip(), 'source': 'manual-user-entry', 'source_url': source_url,
        'quoted_at': quoted.isoformat(), 'collected_at': now.isoformat(),
        'odds': {k: number(body['odds'][k], 1.000001, 10000) for k in ('home', 'draw', 'away')},
    })
    child = league_workspace(ws, code)
    previous = fixtures(child)
    if sum(r['event_id'] == event_id for r in previous) > 1:
        raise ValueError('Plusieurs cotes existent pour ce match : correction explicite requise.')
    capture_id = uuid4().hex
    write_record(child.path('analyses/odds-' + capture_id + '.md'), 'odds_capture', {
        'created_at': now.isoformat(), 'fixture': fixture,
        'previous_fixtures': [r for r in previous if r['event_id'] == event_id],
        'notice': 'Cotes et heure déclarées par l’utilisateur ; aucune vérification externe effectuée.',
    })
    updated = [fixture if r['event_id'] == event_id else r for r in previous]
    if not any(r['event_id'] == event_id for r in previous):
        updated.append(fixture)
    atomic_write(child.path('data/fixtures.json'), json.dumps(updated, ensure_ascii=False, indent=2))
    return {'saved': True, 'capture_id': capture_id,
            'message': 'Cotes enregistrées et ancienne capture conservée. Données déclarées par l’utilisateur.'}


def start_preparation(ws, body, team_jobs):
    period, league = body.get('period', 'today'), body.get('league', 'all')
    plan = preparation(ws, period, league, quote_mode=body.get('quote_mode', 'indicative'))
    selection_mode = body.get('selection_mode', 'manual' if body.get('event_ids') else 'auto')
    if selection_mode not in ('auto', 'manual'):
        raise ValueError('Mode de sélection inconnu.')
    ids = plan['automatic_event_ids'] if selection_mode == 'auto' else body.get('event_ids')
    from .shortlist import validate_event_ids
    ids = validate_event_ids(ids)
    if not ids or len(ids) < 2:
        raise ValueError('Choisir de deux à quinze matchs à préparer.')
    selected = [r for r in plan['matches'] if r['event_id'] in ids]
    if len(selected) != len(ids) or not all(r['quote_ready'] for r in selected):
        raise ValueError('Aucune cote admissible pour au moins un match choisi. Utiliser les cotes indicatives ou renseigner des cotes datées.')
    if 'coach' not in ws.config['agents']['enabled']:
        raise ValueError('Le coach est désactivé dans la configuration.')
    from .chat import claude_status
    state = claude_status()
    if not state['available']:
        raise ValueError(state['message'])
    # Les calculs restent masqués par run_team, comme dans le chat existant.
    job_id = team_jobs.start({
        'message': 'Analyse les matchs choisis avant leur coup d’envoi. Le journaliste vérifie '
                   'les dernières nouvelles et les effectifs ; l’analyste sportif donne son avis ; '
                   'le coach rend un verdict indépendant 1N2 ou une abstention motivée, '
                   'avec ses raisons et réserves sourcées. Ne calcule aucune probabilité. '
                   'Utilise uniquement le parcours essentiel, sans renfort supplémentaire.',
        'provider': 'claude', 'mode': 'team', 'strategy': 'adaptive',
        'period': period, 'league': league, 'event_ids': ids,
        'selection_count': len(ids), 'force_refresh': True,
    })
    return {'job_id': job_id, 'event_ids': ids}


def render_preparation(plan, esc, zone, options, format_value='auto', budget=''):
    frag = lambda name, **values: html_fragment('accumulator-preparation.html', name, **values)
    rows = ''
    for i, r in enumerate(plan['matches']):
        odds = r['odds']
        rows += frag('match', index=i, division=esc(r['division']), event_id=esc(r['event_id']),
                     auto_selected='true' if r['event_id'] in plan['automatic_event_ids'] else 'false',
                     kickoff=esc(r['kickoff']), match=esc(r['match']),
                     kickoff_local=esc(timestamp(r['kickoff']).astimezone(zone).strftime('%d/%m %H:%M')),
                     checked='checked' if r['event_id'] in plan['automatic_event_ids'] else '',
                     quote_status=('Cotes indicatives disponibles' if r['quote_ready'] and r['indicative'] else 'Cotes datées disponibles' if r['quote_ready'] else 'Cotes à renseigner'),
                     coach_status=('Avis coach récent : ' + {'home':'1', 'draw':'N', 'away':'2', 'abstain':'abstention'}.get(r['coach_outcome'], 'inexploitable')
                                   if r['coach_current'] else 'Avis coach à préparer'),
                     coach_reason=esc(r['coach_reason']),
                     model_notice=('Coupe d’Europe : modèle exploratoire, validation spécifique absente.'
                                   if r['division'] in EUROPE else ''),
                     quote_source=esc(r['quote_source']),
                     bookmaker=esc(r['bookmaker']), source_url=esc(r['source_url']),
                     home=esc(odds.get('home', '')), draw=esc(odds.get('draw', '')), away=esc(odds.get('away', '')),
                     quoted_local=(esc(timestamp(r['quoted_at']).astimezone(zone).strftime('%Y-%m-%dT%H:%M'))
                                   if r['quoted_at'] else ''),
                     quote_ready='true' if r['quote_ready'] else 'false')
    reasons = Counter(r['reason'] for r in plan['excluded'])
    excluded = ''.join(frag('excluded', reason=esc(reason), count=count)
                       for reason, count in sorted(reasons.items(), key=lambda p: -p[1]))
    return frag('page', period=esc(plan['period']), league=esc(plan['league']), options=options,
                today='selected' if plan['period'] == 'today' else '',
                next3='selected' if plan['period'] == 'next3' else '',
                quote_mode=esc(plan['quote_mode']),
                indicative_selected='selected' if plan['quote_mode'] == 'indicative' else '',
                verified_selected='selected' if plan['quote_mode'] == 'verified' else '',
                scanned=plan['scanned'], count=len(plan['matches']), rows=rows, budget=esc(budget),
                automatic_count=len(plan['automatic_event_ids']),
                quote_ready=plan['quote_ready_count'], coach_ready=plan['coach_current_count'],
                excluded=excluded, ready='true' if plan['simulation_ready'] else 'false',
                budget_hidden='' if plan['simulation_ready'] else 'hidden',
                auto='selected' if format_value == 'auto' else '',
                doubles='selected' if format_value == 'doubles' else '',
                triples='selected' if format_value == 'triples' else '',
                message=('Sélection prête : tu peux maintenant indiquer ton budget fictif.'
                         if plan['simulation_ready'] else
                         'Le budget sera disponible lorsqu’au moins un combiné sera admissible. '
                         'Lance l’analyse de la sélection automatique. Les cotes indicatives sont acceptées en exploration.'))
