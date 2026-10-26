"""Propositions locales de doubles et triples fictifs, sans écriture ni réseau."""
from itertools import combinations
from collections import Counter
from math import floor, prod, log1p
import copy

from .journal import summary
from .leagues import EUROPE, LEAGUES, league_workspace
from .presentation import html_fragment
from .pronos import selections
from .workspace import number, read_record, timestamp, utcnow

NOTICE = (
    "Propositions fictives, non inscrites au journal et budget non réservé. "
    "Probabilités Poisson non calibrées ; produits calculés sous hypothèse d’indépendance, "
    "non vérifiée. Une espérance positive ne prouve ni avantage ni rentabilité. "
    "Un taux de réussite global de 60 % ne donne pas la probabilité de chaque match."
)


def _verdicts(ws, now):
    """Le dernier avis prime, y compris une abstention ; jamais de repli favorable."""
    latest, issues = {}, []
    for path in sorted(ws.path('analyses').glob('team-*.md')):
        try:
            r = read_record(path)
            if r.get('kind') != 'team_review' or r.get('status') != 'completed':
                continue
            started = timestamp(r['created_at'])
            coach = next(x for x in r.get('reviews', []) if x.get('role') == 'coach')
            completed = timestamp(coach['completed_at'])
            if not started <= completed <= now or coach.get('status') != 'completed':
                raise ValueError('Dates ou état du coach invalides.')
            facts = r.get('facts', {}).get('matches', [])
            for fact in facts:
                timestamp(fact['kickoff'])
                key = (fact['division'], fact['event_id'])
                if key in latest and latest[key]['completed'] >= completed:
                    continue
                matches = [v for v in r.get('llm_verdicts', []) if v.get('event_id') == fact['event_id']]
                latest[key] = {
                    'completed': completed, 'started': started, 'fact': fact,
                    'verdict': matches[0] if len(matches) == 1 else {},
                    'blind': str(r.get('blind_protocol', '')).startswith('all-roles-blind-'),
                    'run_id': r.get('run_id'),
                }
        except (ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
            issues.append({'archive': path.name, 'reason': 'Archive coach inutilisable : ' + str(exc)})
    return latest, issues


def indicative_quotes(rows):
    """Copie de travail des prix observés, sans inventer d’heure de cotation."""
    counts = Counter(offer['bookmaker'] for r in rows for offer in r['fixture'].get('offers', [])
                     if offer.get('bookmaker') and offer.get('odds'))
    result = copy.deepcopy(rows)
    for r in result:
        f = r['fixture']
        if f.get('odds') and f.get('bookmaker'):
            continue
        offers = [o for o in f.get('offers', []) if o.get('bookmaker') and o.get('odds')]
        if offers:
            offer = min(offers, key=lambda o: (-counts[o['bookmaker']], o['bookmaker']))
            f.update(bookmaker=offer['bookmaker'], odds=offer['odds'])
    return result


def propose(ws, budget, period='today', league='all', query='', now=None, ticket_mode='auto', allow_indicative=False, event_ids=None):
    now = now or utcnow()
    if ticket_mode not in ('auto', 'doubles', 'triples'):
        raise ValueError('Format attendu : auto, doubles ou triples.')
    budget = number(budget, 0, 1000000)
    unit = number(ws.config['paper']['unit'], 0.01)
    result = selections(ws, period, league, query, now)
    if event_ids is not None:
        from .shortlist import validate_event_ids
        validate_event_ids(event_ids)
        result = {**result, 'matches': [r for r in result['matches'] if r['fixture']['event_id'] in event_ids]}
    if allow_indicative:
        result = {**result, 'matches': indicative_quotes(result['matches'])}
    reviews, issues = _verdicts(ws, now)
    issues.extend(result['issues'])
    # Le plafond du hub s’applique au total des expositions déjà ouvertes.
    stats = [summary(ws)]
    for code in LEAGUES:
        child_path = ws.path('data/workspaces/' + LEAGUES[code][2] + '/config/workspace.toml')
        if child_path.exists():
            stats.append(summary(league_workspace(ws, code)))
    exposure = sum(s['open_exposure'] for s in stats)
    capital = (number(ws.config['paper']['starting_balance'], 0)
               + sum(s['net_pnl'] for s in stats) - exposure)
    available = max(0, min(
        budget, number(ws.config['paper']['max_open_exposure'], 0) - exposure,
        capital,
    ))
    capacity = min(5, floor((available + 1e-10) / unit))
    if available < unit:
        issues.append({'reason': 'Budget utilisable inférieur à une unité fixe : vérifier le budget, le solde et l’exposition ouverte.'})
    if capital <= unit:
        capacity = 0
        issues.append({'reason': 'Solde fictif libre insuffisant : une unité engagerait tout le solde.'})
    eligible, excluded = [], []
    max_age = number(ws.config['data']['max_odds_age_hours'], 0)
    for row in result['matches']:
        f = row['fixture']
        key = (row['division'], f['event_id'])
        review = reviews.get(key)
        reasons = list(row['reasons'])
        warnings = []
        if row['division'] in EUROPE:
            warnings.append('Coupe d’Europe : modèle exploratoire, validation spécifique absente.')
        indicative = not f.get('quoted_at') or any('Cotes périmées' in reason for reason in reasons)
        if allow_indicative:
            reasons = [reason for reason in reasons if not reason.startswith((
                'Cotes indicatives :', 'Cotes périmées.',
                'Espérance théorique non positive pour l’issue la plus probable.'))]
        if not f.get('odds') or not f.get('bookmaker'):
            reasons.append('Aucune cote 1N2 disponible pour ce match.')
        if row['synthetic']:
            reasons.append('Données synthétiques exclues.')
        if not review:
            reasons.append('Avis coach archivé indisponible.')
        else:
            v, fact = review['verdict'], review['fact']
            if not review['blind']:
                reasons.append('Avis antérieur au protocole aveugle exclu.')
            if (now - review['started']).total_seconds() > max_age * 3600:
                reasons.append('Avis coach à actualiser.')
            if (fact.get('match') != f['home'] + ' / ' + f['away']
                    or timestamp(fact['kickoff']) != timestamp(f['kickoff'])
                    or review['completed'] >= timestamp(f['kickoff'])):
                reasons.append('Identité ou horaire modifié depuis l’avis coach.')
            if v.get('outcome') not in ('home', 'draw', 'away'):
                reasons.append('Coach en abstention ou verdict inexploitable.')
            if allow_indicative and v.get('confidence') == 'faible':
                warnings.append('Confiance faible du coach : scénario fragile.')
            elif v.get('confidence') not in ('modérée', 'élevée'):
                reasons.append('Confiance coach faible ou indisponible.')
            if (row['model'].get('available') and f.get('odds')
                    and v.get('outcome') in ('home', 'draw', 'away')):
                probability = number(row['model']['probabilities'][v['outcome']], 0, 1)
                odds = number(f['odds'][v['outcome']], 1.000001)
                if probability * odds <= 1:
                    if allow_indicative:
                        warnings.append('Espérance théorique non positive pour ce pronostic.')
                    else:
                        reasons.append('Espérance théorique non positive pour le choix du coach.')
        if reasons:
            excluded.append({'match': f['home'] + ' / ' + f['away'], 'reasons': reasons})
            continue
        eligible.append({
            'division': row['division'], 'event_id': f['event_id'],
            'match': f['home'] + ' / ' + f['away'], 'home': f['home'], 'away': f['away'],
            'kickoff': f['kickoff'], 'outcome': v['outcome'], 'probability': probability,
            'odds': odds, 'bookmaker': f['bookmaker'], 'quoted_at': f.get('quoted_at'),
            'collected_at': f.get('collected_at'), 'indicative': indicative,
            'source': f['source'], 'coach_run_id': review['run_id'],
            'coach_at': review['completed'].isoformat(), 'reason': v.get('reason', ''),
            'reserve': v.get('reserve', ''), 'confidence': v['confidence'],
            'warnings': warnings,
        })
    candidates = []
    sizes = (2, 3) if ticket_mode == 'auto' else (2,) if ticket_mode == 'doubles' else (3,)
    risk_excluded = 0
    for size in sizes if capacity else ():
        for legs in combinations(eligible, size):
            teams = {name.casefold() for leg in legs for name in (leg['home'], leg['away'])}
            if len(teams) != 2 * size or len({leg['bookmaker'] for leg in legs}) != 1:
                continue
            probability = prod(leg['probability'] for leg in legs)
            odds = prod(leg['odds'] for leg in legs)
            # Utilité logarithmique de l’unité fixe, pas de dimensionnement de mise.
            fraction = unit / capital
            log_growth = (probability * log1p(fraction * (odds - 1))
                          + (1 - probability) * log1p(-fraction))
            if log_growth <= 0 and not allow_indicative:
                risk_excluded += 1
                continue
            ticket_warnings = sorted({warning for leg in legs for warning in leg['warnings']})
            if probability * odds <= 1:
                ticket_warnings.append('Espérance nette du combiné non positive : projection défavorable selon le modèle.')
            if log_growth <= 0:
                ticket_warnings.append('Critère de risque non positif : scénario comparatif uniquement.')
            candidates.append({'legs': list(legs), 'type': 'double' if size == 2 else 'triple',
                               'warnings': ticket_warnings, 'exploratory': allow_indicative,
                               'probability_under_independence': probability,
                               'odds': odds, 'break_even_probability': 1 / odds,
                               'expected_net_under_independence': unit * (probability * odds - 1),
                               'expected_log_growth_under_independence': log_growth,
                               'stake': unit, 'gross_return_if_win': unit * odds,
                               'net_if_win': unit * (odds - 1), 'net_if_loss': -unit,
                               'selection_reason': 'Retenu selon le compromis calculé entre probabilité, '
                                   'cote et poids de l’unité fixe dans le solde fictif libre. '
                                   'Les tickets suivants partageant une équipe déjà retenue sont écartés.'})
    # Heuristique explicite, aucun optimum de portefeuille revendiqué.
    candidates.sort(key=lambda t: (-t['expected_log_growth_under_independence'],
                                   -t['probability_under_independence'], len(t['legs']),
                                   tuple((l['division'], l['event_id']) for l in t['legs'])))
    tickets, used_teams = [], set()
    for ticket in candidates:
        teams = {n.casefold() for l in ticket['legs'] for n in (l['home'], l['away'])}
        if len(tickets) >= capacity:
            break
        if teams & used_teams:
            continue
        tickets.append(ticket)
        used_teams.update(teams)
    spent = unit * len(tickets)
    return {'mode': 'paper', 'quote_mode': 'indicative' if allow_indicative else 'verified',
            'ticket_mode': ticket_mode, 'created_at': now.isoformat(), 'budget': budget,
            'ranking_capital': capital, 'risk_excluded_count': risk_excluded,
            'unit': unit, 'open_exposure': exposure, 'usable_budget': available,
            'proposed_total': spent, 'unused_budget': max(0, budget - spent),
            'tickets': tickets, 'eligible_count': len(eligible), 'excluded': excluded,
            'issues': issues, 'notice': NOTICE + (' Cotes indicatives acceptées : projections exploratoires, '
                'retours estimés, sans validation de mise ni inscription au journal. '
                'Les avis faibles et les espérances négatives restent visibles comme scénarios comparatifs.' if allow_indicative else ''),
            'method': 'Doubles et triples selon le format choisi, même bookmaker par ticket, '
                      'sans équipe ni match partagé entre tickets. '
                      'Tri par croissance logarithmique espérée du solde fictif libre, '
                      'calculée pour une unité fixe sous hypothèse d’indépendance. '
                      + ('En exploration, les avis faibles et critères non positifs sont signalés sans exclusion. '
                         if allow_indicative else 'Les tickets dont ce critère est nul ou négatif sont exclus. ')
                      +
                      'Le classement équilibre cote, probabilité et risque de perte ; '
                      'cette méthode ne garantit pas la meilleure répartition possible. '
                      'Au plus cinq tickets, sans obligation de consommer le budget. '
                      'Avis coach âgés au plus de la durée de validité configurée des cotes.'}


def render(result, esc, zone=None, submitted=True, coach_url='/chat'):
    frag = lambda name, **values: html_fragment('accumulators.html', name, **values)
    if not submitted:
        return frag('ready')
    from datetime import timezone

    zone = zone or timezone.utc
    date = lambda value: esc(timestamp(value).astimezone(zone).strftime('%d/%m/%Y %H:%M %Z')) if value else 'inconnue'
    tickets = ''
    labels = {'home': '1', 'draw': 'N', 'away': '2'}
    for i, t in enumerate(result['tickets'], 1):
        legs = ''.join(frag('leg', match=esc(l['match']), outcome=labels[l['outcome']],
                            kickoff=date(l['kickoff']), confidence=esc(l['confidence']),
                            probability=f"{100*l['probability']:.1f}",
                            reason=esc(l['reason']), reserve=esc(l['reserve']),
                            coach_at=date(l['coach_at']), quoted_at=date(l['quoted_at']),
                            quote_quality='indicative' if l.get('indicative') else 'datée',
                            collected_at=date(l.get('collected_at')),
                            odds=f"{l['odds']:.2f}") for l in t['legs'])
        tickets += frag('ticket', index=i, kind=esc(t['type'].capitalize()), legs=legs,
                        warnings=esc(' '.join(t['warnings'])) or 'Aucune réserve supplémentaire liée aux filtres.',
                        purpose='Scénario comparatif exploratoire' if t['exploratory'] else 'Proposition fictive avec filtres stricts',
                        selection_reason=esc(t['selection_reason']), bookmaker=esc(t['legs'][0]['bookmaker']),
                        stake=f"{t['stake']:.2f}", odds=f"{t['odds']:.2f}",
                        probability=f"{100*t['probability_under_independence']:.1f}",
                        threshold=f"{100*t['break_even_probability']:.1f}",
                        gross=f"{t['gross_return_if_win']:.2f}", net=f"{t['net_if_win']:.2f}",
                        loss=f"{t['net_if_loss']:.2f}", ev=f"{t['expected_net_under_independence']:.2f}")
    if not tickets:
        tickets = frag('empty')
    counts = Counter(reason for row in result['excluded'] for reason in set(row['reasons']))
    blockers = ''.join(frag('excluded', match=f'{count} match(s)', reasons=esc(reason))
                       for reason, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:3])
    blockers += ''.join(frag('excluded', match='Budget ou données', reasons=esc(row['reason']))
                        for row in result['issues'])
    if not result['tickets'] and not blockers:
        blockers = frag('excluded', match='Composition des tickets', reasons=(
            'Pas assez de matchs compatibles avec le format choisi, le même bookmaker, '
            'des équipes distinctes et le critère de risque.'))
    feedback = frag('feedback',
                    message=(f"Calcul terminé : {len(result['tickets'])} combiné(s) proposé(s)."
                             if result['tickets'] else 'Calcul terminé : aucun combiné admissible.'),
                    blockers=blockers if not result['tickets'] else '',
                    actions=frag('actions', coach_url=esc(coach_url)) if not result['tickets'] else '')
    exclusions = ''.join(frag('excluded', match=esc(r['match']),
                              reasons=esc(' '.join(r['reasons']))) for r in result['excluded'])
    exclusions += ''.join(frag('excluded', match=esc(r.get('division', r.get('archive', 'Données'))),
                               reasons=esc(r['reason'])) for r in result['issues'])
    return frag('result', feedback=feedback, notice=esc(result['notice']), method=esc(result['method']),
                count=len(result['tickets']), total=f"{result['proposed_total']:.2f}",
                risk_excluded=result['risk_excluded_count'],
                unused=f"{result['unused_budget']:.2f}", tickets=tickets, exclusions=exclusions)
