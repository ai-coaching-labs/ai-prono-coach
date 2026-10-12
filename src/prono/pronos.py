"""Sélections de travail pré-match : calcul local, aucun pari ni appel réseau."""
import json
from datetime import timedelta
from zoneinfo import ZoneInfo
from .analysis import fixtures, analyze
from .leagues import LEAGUES, league_workspace
from .model import load_history, predict
from .journal import journal, summary
from .workspace import utcnow, timestamp


def selections(ws, period='today', league='all', query='', now=None):
    now = timestamp((now or utcnow()).isoformat())
    zone = ZoneInfo(ws.config.get('coaching', {}).get('timezone', 'Europe/Paris'))
    today = now.astimezone(zone).date()
    if period not in ('today', 'next3'):
        raise ValueError('Période attendue : today ou next3.')
    start, end = (today, today) if period == 'today' else (today+timedelta(days=1), today+timedelta(days=3))
    if league != 'all' and league not in LEAGUES:
        raise ValueError('Championnat inconnu.')
    codes = list(LEAGUES) if league == 'all' else [league]
    from .market_watch import public_calendar
    watch = public_calendar(ws)['matches']
    rows, issues = [], []
    for code in codes:
        try:
            child = league_workspace(ws, code)
            history = load_history(child.path('data/history.csv'))
            verified = fixtures(child)
            stats, entries = summary(child), journal(child)
        except (ValueError, OSError) as exc:
            issues.append({'division': code, 'reason': str(exc)})
            continue
        # Une même rencontre ne doit pas apparaître deux fois si une capture horodatée existe.
        identity = lambda f: (f['home'], f['away'], timestamp(f['kickoff']))
        known = {identity(f) for f in verified}
        inputs = [(f, True) for f in verified] + [(f, False) for f in watch if f['division'] == code and identity(f) not in known]
        from .identity import team_resolver
        normalize=team_resolver(ws,code)
        normalized=[{**r,'home':normalize(r['home']),'away':normalize(r['away'])} for r in history]
        for fixture, verified_quote in inputs:
            kickoff = timestamp(fixture['kickoff'])
            day = kickoff.astimezone(zone).date()
            if kickoff <= now or not start <= day <= end:
                continue
            if query.casefold() not in (fixture['home']+' '+fixture['away']).casefold():
                continue
            reasons, comparison = [], None
            if verified_quote:
                try:
                    result = analyze(child, fixture['event_id'], now)
                    model = result['model']
                    comparison = result.get('comparison')
                    if result['status'] == 'stale_odds':
                        reasons.append('Cotes périmées.')
                except ValueError as exc:
                    model = {'available': False}
                    reasons.append(str(exc))
            else:
                # Prévision indépendante des cotes : aucune comparaison ou espérance calculée.
                model = predict(normalized, normalize(fixture['home']), normalize(fixture['away']), now, child.config['model'])
                reasons.append('Cotes indicatives : simulation fictive non validée, fraîcheur inconnue.')
            outcome = None
            if not model['available']:
                reasons.append(model.get('reason', 'Analyse indisponible.'))
            else:
                probabilities = model['probabilities']
                ranked = sorted(probabilities, key=probabilities.get, reverse=True)
                if abs(probabilities[ranked[0]]-probabilities[ranked[1]]) < 1e-12:
                    reasons.append('Issues les plus probables à égalité.')
                else:
                    outcome = ranked[0]
            chosen = next((r for r in (comparison or {}).get('outcomes', []) if r['outcome'] == outcome), None)
            if chosen and chosen['expected_return_per_unit'] <= 0:
                reasons.append('Espérance théorique non positive pour l’issue la plus probable.')
            if any(r['event_id'] == fixture['event_id'] for r in entries):
                reasons.append('Simulation déjà inscrite pour ce match.')
            unit = float(child.config['paper']['unit'])
            if stats['available_balance'] < unit or stats['open_exposure']+unit > float(child.config['paper']['max_open_exposure']):
                reasons.append('Limite de simulation atteinte.')
            from .leagues import EUROPE
            if code in EUROPE:reasons.append('Coupe d’Europe : baseline exploratoire, validation spécifique encore absente.')
            rows.append({'division': code, 'fixture': fixture, 'kickoff_local': kickoff.astimezone(zone).isoformat(),
                         'model': model, 'outcome': outcome, 'comparison': chosen,
                         'status': 'abstention' if reasons else 'candidate', 'reasons': reasons,
                         'context_notice': 'Avis des agents et compositions à vérifier ; non intégrés à la baseline.',
                         'synthetic': fixture['source'] == 'synthetic-demo' or any(r['source'] == 'synthetic-demo' for r in history)})
    from .leagues import EUROPE
    if any(r['division'] in EUROPE for r in rows):
        from .domestic_form import DomesticForm
        domestic=DomesticForm(ws,now.isoformat())
        for row in rows:
            if row['division'] in EUROPE:row['domestic_form']=domestic.match(row['fixture'])
    rows.sort(key=lambda r: (r['status'] != 'candidate', timestamp(r['fixture']['kickoff'])))
    return {'created_at': now.isoformat(), 'start': start.isoformat(), 'end': end.isoformat(),
            'timezone': str(zone), 'period': period, 'matches': rows, 'issues': issues,
            'candidates': sum(r['status'] == 'candidate' for r in rows),
            'notice': 'Sélections à étudier séparément en fictif, pas un ticket à jouer ensemble. Modèle non calibré ; une espérance positive ne prouve aucun avantage.'}


def render(result, link, esc, page_number=1):
    from urllib.parse import urlencode
    labels = {'home': '1 · Domicile', 'draw': 'N · Nul', 'away': '2 · Extérieur'}
    rows = result['matches']
    pages = max(1, (len(rows)+17)//18)
    page_number = min(max(1, page_number), pages)
    content = '<div class="section-head"><h2>Les pronos du modèle</h2><span>'+esc(result['start'])+' → '+esc(result['end'])+' · '+esc(result['timezone'])+'</span></div>'
    content += '<nav class="tabs">'+''.join(f'<a class="tab {"chosen" if result["period"] == key else ""}" href="{esc(link(horizon=key))}">{label}</a>' for key,label in [('today',"Aujourd’hui"),('next3','Les 3 prochains jours · demain à J+3')])+'</nav>'
    picks = sum(r['model']['available'] and r['outcome'] is not None for r in rows)
    content += f'<p>{picks} prono(s) calculé(s) · {len(rows)} rencontre(s) avant coup d’envoi · {result["candidates"]} simulation(s) fictive(s) à étudier.</p>'
    content += '<div class="notice">'+esc(result['notice'])+' L’issue affichée est la plus probable du modèle, pas nécessairement une issue majoritaire. Aucun appel d’agent IA ni recherche d’actualité n’est effectué par cette page.</div>'
    content += '<div class="match-grid" style="margin-top:20px">'
    for row in rows[(page_number-1)*18:page_number*18]:
        f, model = row['fixture'], row['model']
        content += f'<article class="match"><div class="match-top"><span>{esc(LEAGUES[row["division"]][0])}</span><time>{esc(row["kickoff_local"][:16].replace("T", " · "))}</time></div><h3>{esc(f["home"])}<em>vs</em>{esc(f["away"])}</h3>'
        content += '<div class="eyebrow">'+('PRONO CALCULÉ' if model['available'] and row['outcome'] is not None else 'PAS DE CHOIX DU MODÈLE')+'</div>'
        if row['synthetic']:
            content += '<p>Données SYNTHÉTIQUES · démonstration</p>'
        if model['available']:
            pick = labels.get(row['outcome'], 'Égalité · aucun choix')
            team = f['home'] if row['outcome'] == 'home' else f['away'] if row['outcome'] == 'away' else 'Match nul' if row['outcome'] == 'draw' else ''
            content += '<p><b>Prono du modèle : '+esc(pick)+' — '+esc(team)+'</b></p><div class="prices">'
            for key in ('home','draw','away'):
                content += f'<div><span>{labels[key].split(" · ")[0]}</span><b>{100*model["probabilities"][key]:.1f}%</b></div>'
            content += f'</div><details><summary>Détails du calcul et de l’historique</summary><p><small>Échantillons : {model["sample"]["home"]} / {model["sample"]["away"]} matchs. Calcul au {esc(model["as_of"])}.</small></p>'
            sample_period=model.get('sample_period',{})
            if sample_period:
                years=sample_period['max_history_days']/365.25
                content+=f'<p><small>Historique : {years:.0f} ans maximum · dont {sample_period["home_recent"]} / {sample_period["away_recent"]} matchs sur les deux dernières années.</small></p>'
                if sample_period['max_history_days']>730:content+='<p><small>Des effectifs anciens participent au calcul ; davantage de matchs ne garantit pas une meilleure prévision.</small></p>'
            content += '</details>'
        if row.get('domestic_form'):
            content+='<details><summary>Forme en championnat · contexte des analystes</summary>'
            for side in ('home','away'):
                form=row['domestic_form'][side]
                content+='<p><b>'+esc(form['team'])+'</b> : '
                if not form['available']:content+=esc(form['reason'])
                else:
                    recent=form['last5'];full=form['last10']
                    content+=f'{recent["played"]} derniers matchs chargés : {recent["wins"]} V / {recent["draws"]} N / {recent["losses"]} D, {recent["goals_for"]} buts pour / {recent["goals_against"]} contre. Sur {full["played"]} matchs : {full["points"]} points.'
                    content+=' Dernier match : '+esc(form['latest_kickoff'][:10])+'. '
                    content+=esc(' '.join(form['warnings']))
                content+='</p>'
            content+='<small>'+esc(row['domestic_form']['notice'])+'</small></details>'
        if f.get('offers'):
            content += '<details><summary>Cotes enregistrées · 1 / N / 2</summary>'
            for offer in f['offers']:
                content += '<p>'+esc(offer['bookmaker'])+' : '+ ' / '.join(f'{offer["odds"][key]:.2f}' for key in ('home','draw','away'))+'</p>'
            content += '<small>Cotes indicatives ; date de cotation inconnue.</small></details>'
        if row['comparison']:
            c = row['comparison']
            content += f'<p>Cote : {c["odds"]:.2f} · {esc(f["bookmaker"])}<br><small>Cotée le {esc(f["quoted_at"])}</small></p>'
            content += f'<p>Espérance théorique : {c["expected_return_per_unit"]:+.3f} unité par unité fictive.</p>'
        content += '<p><small>Simulation fictive : '+('à étudier' if row['status'] == 'candidate' else 'abstention')+'</small></p>'
        content += '<ul>'+''.join('<li>'+esc(reason)+'</li>' for reason in row['reasons'])+'</ul>'
        coach_query = urlencode({'league':row['division'],'period':result['period'],'event':f['event_id']})
        content += f'<p><a class="pill" href="/chat?{esc(coach_query)}">Comprendre ce match →</a></p>'
        content += '<p><small>'+esc(row['context_notice'])+'</small></p><footer>poisson-baseline-v1 · Probabilités non calibrées</footer></article>'
    content += '</div>'
    if not rows:
        other = 'next3' if result['period'] == 'today' else 'today'
        label = 'Voir les trois prochains jours' if other == 'next3' else 'Voir aujourd’hui'
        content += '<div class="empty"><h3>Aucun match chargé pour cette période</h3><p>Essayez une autre période ou une autre compétition. Le calendrier public ne couvre pas toutes les rencontres.</p>'+f'<a class="pill" href="{esc(link(horizon=other))}">{label} →</a></div>'
    if result['issues']:
        content += '<details><summary>Championnats non évalués</summary><ul>'+''.join('<li>'+esc(LEAGUES[i['division']][0]+': '+i['reason'])+'</li>' for i in result['issues'])+'</ul></details>'
    if pages > 1:
        content += '<div class="pagination">'
        if page_number > 1:
            content += f'<a href="{esc(link(page=page_number-1))}">← Précédent</a>'
        content += f'<span>Page {page_number} / {pages}</span>'
        if page_number < pages:
            content += f'<a href="{esc(link(page=page_number+1))}">Suivant →</a>'
        content += '</div>'
    return content
