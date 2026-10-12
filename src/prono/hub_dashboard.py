"""Vue multi-championnats en lecture seule, calculée à partir des fichiers locaux."""
import html
import json
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from .leagues import LEAGUES, league_workspace
from .branding import ICON_LINK
from .model import load_history
from .workspace import utcnow, timestamp


def page(ws, params=None, token=None):
    params = params or {}
    esc = lambda value: html.escape(str(value), quote=True)
    code = params.get('league', 'all')
    if code != 'all' and code not in LEAGUES:
        raise ValueError('Championnat inconnu.')
    query = params.get('q', '').strip()[:100]
    period = params.get('period', 'upcoming')
    if period not in ('upcoming', 'today', 'all'):
        raise ValueError('Période inconnue.')
    tab = params.get('tab', 'pronos')
    if tab not in ('matches', 'results', 'coverage', 'team', 'pronos','tracking','evaluation'):
        raise ValueError('Vue inconnue.')
    page_number = max(1, int(params.get('page', '1')))
    now, zone = utcnow(), ZoneInfo(ws.config.get('coaching', {}).get('timezone', 'Europe/Paris'))
    manifest_path = ws.path('data/league-hub.json')
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    from .market_watch import public_calendar
    market = public_calendar(ws)
    selected = list(LEAGUES) if code == 'all' else [code]
    histories, errors, windows = {key: [] for key in selected}, {}, {}
    # Seules ces vues utilisent les archives ; les pronos chargent leur propre périmètre.
    for key in selected if tab in ('results', 'coverage') else []:
        try:
            child = league_workspace(ws, key)
            windows[key]=int(child.config['model']['max_history_days'])
            histories[key] = load_history(child.path('data/history.csv'))
        except (ValueError, OSError) as exc:
            histories[key], errors[key] = [], str(exc)
    selected_history = [(key, row) for key in selected for row in histories[key]]
    filtered_history = [(key, r) for key, r in selected_history if query.casefold() in (r['home']+' '+r['away']).casefold()]
    filtered_history.sort(key=lambda item: timestamp(item[1]['kickoff']), reverse=True)
    matches = []
    for row in market.get('matches', []):
        if row['division'] not in selected or query.casefold() not in (row['home']+' '+row['away']).casefold():
            continue
        kickoff = timestamp(row['kickoff'])
        if period == 'upcoming' and kickoff <= now:
            continue
        if period == 'today' and kickoff.astimezone(zone).date() != now.astimezone(zone).date():
            continue
        matches.append(row)
    matches.sort(key=lambda row: timestamp(row['kickoff']))
    def link(**changes):
        values = {'league': code, 'q': query, 'period': period, 'tab': tab, 'horizon': params.get('horizon', 'today')}
        values.update(changes)
        return '/?'+urlencode(values)
    nav = f'<a class="league {"active" if code == "all" else ""}" href="{esc(link(league="all"))}"><span>Tous les championnats</span><b>{len(LEAGUES)}</b></a>'
    country = None
    for key, (name, nation, slug) in LEAGUES.items():
        if nation != country:
            nav += f'<div class="country">{esc(nation)}</div>'
            country = nation
        nav += f'<a class="league {"active" if code == key else ""}" href="{esc(link(league=key))}"><span>{esc(name)}</span></a>'
    titles = {'pronos': 'Les pronos', 'tracking': 'Mon suivi', 'matches': 'Le calendrier',
              'results': 'Les résultats', 'team': 'L’équipe et les dossiers',
              'coverage': 'Les données et leurs sources', 'evaluation': 'Évaluer le modèle'}
    title = titles[tab]
    subtitle = 'Toutes les compétitions' if code == 'all' else LEAGUES[code][0]+' · '+LEAGUES[code][1]
    options = '<option value="all">Toutes les compétitions</option>'+''.join(f'<option value="{key}" {"selected" if key == code else ""}>{esc(nation+" · "+name)}</option>' for key, (name,nation,_) in LEAGUES.items())
    def tab_links(entries):
        return ''.join(f'<a class="tab {"chosen" if tab == value else ""}" {"aria-current=page" if tab == value else ""} href="{esc(link(tab=value))}">{label}</a>' for value,label in entries)
    tabs = tab_links([('pronos','Pronos'),('tracking','Suivi'),('matches','Calendrier')])
    advanced = tab_links([('results','Résultats'),('team','Équipe et dossiers'),('coverage','Données et sources'),('evaluation','Évaluation')])
    advanced_open = ' open' if tab in ('results','team','coverage','evaluation') else ''
    controls = f'<form method="get" class="filters"><input type="hidden" name="tab" value="{esc(tab)}"><label>Compétition<select name="league">{options}</select></label>'
    if tab not in ('coverage','evaluation'):
        controls += f'<label>Équipe<input name="q" value="{esc(query)}" placeholder="Rechercher une équipe…"></label>'
    if tab == 'matches':
        controls += '<label>Calendrier<select name="period">'+''.join(f'<option value="{value}" {"selected" if value == period else ""}>{label}</option>' for value,label in [('upcoming','À venir'),('today',"Aujourd’hui"),('all','Tout le fichier')])+'</select></label>'
    controls += '<button type="submit">Filtrer</button></form>'
    content = ''
    items = matches if tab == 'matches' else filtered_history
    per_page = 18
    pages = max(1, (len(items)+per_page-1)//per_page)
    page_number = min(page_number, pages)
    visible = items[(page_number-1)*per_page:page_number*per_page]
    if tab == 'tracking':
        from .lab_dashboard import tracking_view
        content=tracking_view(ws,code,query,esc,zone,link,max(1,int(params.get('page','1'))),token)
    elif tab == 'evaluation':
        from .lab_dashboard import evaluation_view
        content=evaluation_view(ws,code,esc,token)
    elif tab == 'pronos':
        from .pronos import selections, render
        result = selections(ws, params.get('horizon', 'today'), code, query, now)
        content = render(result, link, esc, page_number=max(1, int(params.get('page', '1'))))
        controls = f'<form method="get" class="filters"><input type="hidden" name="tab" value="pronos"><input type="hidden" name="horizon" value="{esc(result["period"])}"><label>Compétition<select name="league">{options}</select></label><label>Équipe<input name="q" value="{esc(query)}" placeholder="Rechercher une équipe…"></label><button type="submit">Filtrer</button></form>'
    elif tab == 'matches':
        content += '<div class="section-head"><h2>Le calendrier du marché</h2><span>Heures locales · '+esc(str(zone))+'</span></div>'
        content += '<div class="match-grid">'
        for row in visible:
            kickoff = timestamp(row['kickoff']).astimezone(zone)
            prices = ''
            for offer in row['offers']:
                prices += '<div class="offer"><small>'+esc(offer['bookmaker'])+'</small><div class="prices">'+''.join(f'<div><span>{label}</span><b>{offer["odds"][outcome]:.2f}</b></div>' for outcome,label in [('home','1'),('draw','N'),('away','2')])+'</div></div>'
            started = timestamp(row['kickoff']) <= now
            from .identity import freshness
            health=freshness(row,now,float(ws.config['data']['max_odds_age_hours']))
            revisions=f'<p>Horaire mis à jour · {len(row["schedule_revisions"])} changement(s) conservé(s).</p>' if row.get('schedule_revisions') else ''
            if row.get('identity_warning'):revisions+='<p>'+esc(row['identity_warning'])+'</p>'
            content += f'''<article class="match"><div class="match-top"><span>{esc(LEAGUES[row['division']][0])}</span><time>{kickoff.strftime('%d/%m · %H:%M')}</time></div><h3>{esc(row['home'])}<em>vs</em>{esc(row['away'])}</h3>{prices or '<p>Cotes indisponibles pour les bookmakers pris en charge.</p>'}{revisions}<footer><span class="dot"></span>{'Match commencé · ' if started else ''}Cotation non horodatée · observation<br>{esc(health)}</footer></article>'''
        content += '</div>'
        if not matches:
            content += '<div class="empty"><h3>Aucune rencontre dans cette sélection</h3><p>Essayez un autre championnat ou « Tout le fichier ». Le fournisseur public ne couvre que son calendrier publié, pas toutes les rencontres à venir.</p></div>'
    elif tab == 'results':
        content += '<div class="section-head"><h2>Les derniers résultats chargés</h2><span>'+str(len(filtered_history))+' matchs · filtres actifs</span></div><div class="table-wrap"><table><thead><tr><th>Date</th><th>Championnat</th><th>Domicile</th><th>Score</th><th>Extérieur</th></tr></thead><tbody>'
        for key, row in visible:
            content += '<tr>'+''.join(f'<td>{esc(value)}</td>' for value in [timestamp(row['kickoff']).astimezone(zone).strftime('%d/%m/%Y %H:%M'), LEAGUES[key][0], row['home'], f"{row['home_goals']} – {row['away_goals']}", row['away']])+'</tr>'
        content += '</tbody></table></div>'
        if not visible:
            content += '<div class="empty">Aucun résultat pour ces filtres.</div>'
    elif tab == 'team':
        from .context import contexts
        roles = [
            ('coach', 'Coach coordinateur', 'Croise les avis, explique les désaccords et conserve la décision finale.'),
            ('sports-journalist', 'Journaliste sportif', 'Actualité des deux clubs, déclarations, blessures et suspensions. Sources lues et datées.'),
            ('lineup-analyst', 'Expert effectif', 'Absents, incertains, retours et onze officiel. Distingue probable et confirmé.'),
            ('bookmaker-expert', 'Expert bookmakers', 'Qualité des cotes, règles du marché et mouvements documentés par plusieurs captures.'),
            ('match-analyst', 'Analyste sportif', 'Contexte tactique, calendrier, récupération et limites de la baseline.'),
            ('market-analyst', 'Analyste du marché', 'Explique marge, probabilités implicites et écarts calculés par les outils.'),
            ('risk-manager', 'Responsable des limites', 'Vérifie fraîcheur, exposition fictive et motifs d’abstention.'),
            ('performance-analyst', 'Analyste des performances', 'Bilan du journal, qualité prédictive et taille des échantillons.')]
        enabled = ws.config['agents']['enabled']
        content = '<div class="section-head"><h2>Une équipe pour préparer chaque match</h2><span>Rôles configurés · exécutés sur demande dans votre assistant</span></div><div class="match-grid">'
        for key, name, description in roles:
            content += f'<article class="match"><div class="eyebrow">{"ACTIVÉ" if key in enabled else "DÉSACTIVÉ"}</div><h3>{esc(name)}</h3><p>{esc(description)}</p></article>'
        content += '</div><div class="notes"><h3>Demander une analyse complète</h3><p>Dans votre assistant : « Prépare un dossier complet sur ce match : dernières nouvelles, absents, compositions, cotes et avis des spécialistes. »</p><p>Les recherches sont effectuées par l’assistant avec ses outils web. Cette page ne lance pas de modèles en arrière-plan. Les informations sourcées ne modifient pas les probabilités par intuition.</p></div><h2>Dossiers de contexte archivés</h2>'
        event_ids = {r['event_id'] for r in market.get('matches', []) if r['division'] in selected}
        dossiers = [d for d in contexts(ws) if (code == 'all' or d['event_id'] in event_ids)
                    and query.casefold() in (d['home']+' '+d['away']).casefold()]
        if not dossiers:
            content += '<div class="empty">Aucun dossier sourcé archivé. Les rôles sont prêts ; aucune recherche de club n’est présentée comme déjà effectuée.</div>'
        for dossier in dossiers[:20]:
            content += f'<article class="notes"><h3>{esc(dossier["home"])} / {esc(dossier["away"])}</h3><p>Dossier archivé · vérifier les évolutions depuis le {esc(dossier["as_of"])}.</p>'
            for fact in dossier['findings']:
                status_label = {'confirmed':'Confirmé par la source','reported':'Rapporté','uncertain':'Incertain','contradicted':'Contradiction'}[fact['status']]
                content += f'<p><b>{status_label} · {esc(fact["team"])}</b> — {esc(fact["claim"])}<br>'
                for source in fact['sources']:
                    content += f'<a href="{esc(source["url"])}">{esc(source["title"])}</a> · '
                content += '</p>'
            content += '<p>Manques : '+esc('; '.join(dossier['missing']))+'</p></article>'
    else:
        content += '<div class="section-head"><h2>Ce qui est réellement disponible</h2><span>Couverture explicite, aucun chiffre inventé</span></div><div class="table-wrap"><table><thead><tr><th>Championnat</th><th>Résultats</th><th>Début des archives</th><th>Dernier match</th><th>Fenêtre du modèle</th><th>Import</th></tr></thead><tbody>'
        for key in selected:
            rows = histories[key]
            last = max((timestamp(r['kickoff']) for r in rows), default=None)
            first=min((timestamp(r['kickoff']) for r in rows),default=None)
            status = manifest.get('leagues', {}).get(key, {})
            calendar_status=market.get('europe_sources',{}).get(key,{})
            issue = errors.get(key) or (status.get('message') if status.get('status') == 'error' else None) or (calendar_status.get('message') if calendar_status.get('status')=='error' else None)
            availability = ('Disponible · '+str(status['rejected'])+' résultat(s) exclus avec trace') if status.get('rejected') else ('Disponible' if rows else 'À importer')
            window=f'{windows[key]/365.25:.0f} ans maximum' if key in windows else '—'
            content += '<tr>'+''.join(f'<td>{esc(value)}</td>' for value in [LEAGUES[key][0], len(rows), first.strftime('%d/%m/%Y') if first else '—', last.strftime('%d/%m/%Y') if last else '—', window, issue or availability])+'</tr>'
        content += '</tbody></table></div><div class="notes"><h3>Sources et limites</h3><p>Championnats nationaux : <a href="https://www.football-data.co.uk/data.php">Football-Data</a>. Coupes d’Europe : <a href="https://www.espn.com/soccer/scoreboard/_/league/uefa.champions">ESPN</a>, horaires UTC et résultats à 90 minutes ; prolongations et tirs au but exclus. Chaque collecte conserve sa source et sa copie brute. Les horaires Football-Data sont interprétés en Europe/London ; ESPN fournit les heures UTC.</p><p>Les cotes publiques n’ont pas d’heure exacte de cotation : elles restent indicatives et ne sont jamais transmises au moteur de simulation. Une API horodatée est nécessaire pour des analyses exploitables.</p><p>Les résultats sont connus du système à leur collecte. Aucun backtest historique valide n’est revendiqué avec ces seules archives. Absences et compositions : indisponibles.</p><p>Les trois coupes UEFA sont incluses. Les autres coupes et les sélections nationales restent hors catalogue. La baseline des coupes d’Europe est exploratoire et ne mélange pas leurs résultats avec ceux des ligues nationales.</p></div>'
    if tab in ('matches', 'results') and pages > 1:
        content += '<div class="pagination">'
        if page_number > 1:
            content += f'<a href="{esc(link(page=page_number-1))}">← Précédent</a>'
        content += f'<span>Page {page_number} / {pages}</span>'
        if page_number < pages:
            content += f'<a href="{esc(link(page=page_number+1))}">Suivant →</a>'
        content += '</div>'
    collected = ' · '.join(d['label']+' : '+timestamp(d['collected_at']).astimezone(zone).strftime('%d/%m/%Y à %H:%M') for d in market['datasets'] if d.get('collected_at')) or 'non effectuée'
    errors_count = sum(v.get('status') == 'error' for v in manifest.get('leagues', {}).values())
    import_warning = f'<div class="notice">{errors_count} import(s) en échec. Consultez Couverture & sources ; les données précédentes sont conservées.</div>' if errors_count else ''
    collection_note = f'<details class="collection"><summary>Dates de collecte et limites des cotes</summary><p>{esc(collected)}. Heure de cotation inconnue : simulations bloquées pour ces cotes.</p></details>' if tab in ('matches','coverage') else ''
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(title)} · AI Prono Coach</title>{ICON_LINK}<style>{CSS}</style></head><body>
<a class="skip-link" href="#content">Aller au contenu</a><aside><a class="brand" href="/"><img class="brand-icon" src="/icon.svg" alt="" width="32" height="32"> PRONO<span>COACH / FOOTBALL</span></a><p class="sidebar-guide">Choisir un match.<br>Comprendre le prono.<br>Suivre le résultat.</p><details class="competitions"{' open' if code != 'all' else ''}><summary>Les compétitions</summary>{nav}</details><div class="sidebar-foot">SIMULATIONS FICTIVES<br>Modèle non calibré</div></aside><main data-token="{esc(token or '')}"><header><div class="eyebrow">FOOTBALL · MODE FICTIF</div><a class="pill" href="/chat?{esc(urlencode({'league':code,'period':params.get('horizon','today')}))}">Parler au coach →</a></header><h1>{esc(title)}</h1><p class="intro">{esc(subtitle)} · Probabilités non calibrées, aucune rentabilité démontrée.</p>
<nav class="tabs" aria-label="Navigation principale">{tabs}</nav><details class="advanced"{advanced_open}><summary>Outils et données</summary><nav class="secondary-nav" aria-label="Outils et données">{advanced}</nav></details>{import_warning}{controls}{collection_note}<section id="content" tabindex="-1">{content}</section>
<footer class="page-foot">AI PRONO COACH · {now.astimezone(zone).strftime('%d.%m.%Y')} · Suivi selon la configuration, pendant l’ouverture du tableau</footer></main>{'<script src="/dashboard.js" defer></script>' if tab in ('tracking','evaluation') else ''}</body></html>'''



CSS = '''
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#182423;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:inherit;text-decoration:none}aside{position:fixed;inset:0 auto 0 0;width:246px;background:#132b27;color:#d5e3dd;padding:30px 18px;overflow-y:auto}.brand{display:block;font-size:29px;font-weight:850;letter-spacing:3px;padding:0 14px 30px;color:#f6f9f1}.brand span{display:block;font-size:9px;letter-spacing:2px;color:#b6d195;margin-top:6px}.nav-heading,.country{font-size:10px;letter-spacing:1.5px;color:#88a69d;margin:18px 13px 8px}.league{padding:9px 13px;display:flex;justify-content:space-between;gap:8px;border-radius:7px;font-size:12px}.league:hover{background:#28443c}.league.active{background:#d5eea5;color:#163326;font-weight:700}.league b{font-size:10px;opacity:.7}.sidebar-foot{padding:30px 14px;color:#89a59c;line-height:1.9;font-size:10px;letter-spacing:1px}main{margin-left:246px;padding:32px 40px;max-width:1760px}header{display:flex;justify-content:space-between;align-items:center;gap:10px}.eyebrow{font-size:10px;font-weight:800;letter-spacing:1.8px;color:#667c70}.pill{border:1px solid #d4e1d5;border-radius:20px;padding:8px 12px;color:#47704b;font-size:11px;background:#eef5e9}h1{font-size:clamp(28px,3.1vw,47px);letter-spacing:-1.8px;margin:30px 0 10px;font-weight:750}.intro{color:#75807b;margin:0 0 30px;line-height:1.6}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.stat{padding:21px;background:#fff;border:1px solid #e2e7e3;border-radius:12px}.stat>span{font-size:12px;color:#6c7971}.stat strong{display:block;font-size:32px;font-weight:650;letter-spacing:-1px;margin:10px 0}.stat small{font-size:10px;color:#909b94}.notice{border:1px solid #e5dbc0;background:#fbf7ec;color:#827043;border-radius:9px;padding:14px 18px;font-size:11px;line-height:1.7;margin:20px 0 26px}.tabs{display:flex;flex-wrap:wrap;gap:28px;border-bottom:1px solid #dce2df}.tab{padding:0 0 16px;color:#7a847e;font-weight:600;font-size:13px}.chosen{border-bottom:3px solid #264c3d;color:#183c2d}.filters{display:flex;gap:14px;align-items:end;background:white;padding:18px;border:1px solid #e2e7e3;border-radius:10px;margin:22px 0 30px}.filters label{display:grid;gap:7px;font-size:10px;font-weight:700;color:#738178;flex:1}select,input{width:100%;min-width:0;border:1px solid #dfe5e1;border-radius:6px;padding:11px;background:#fafcfb;color:#253c30;font:12px inherit}button{background:#254d3d;color:white;border:0;border-radius:6px;padding:12px 19px;font-weight:650;cursor:pointer}.section-head{display:flex;justify-content:space-between;align-items:center;gap:15px;margin-bottom:20px}.section-head h2,.panel h2{font-size:18px;letter-spacing:-.4px;margin:0}.section-head>span{font-size:10px;color:#869089}.match-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.match{background:#fff;border:1px solid #e0e6e2;border-radius:12px;padding:18px}.match-top{display:flex;justify-content:space-between;gap:8px;font-size:10px;color:#778a7d}.match-top>span{color:#355f46;font-weight:700}h3{font-size:17px;line-height:1.5;margin:20px 0}h3 em{display:block;font-size:10px;font-weight:400;font-style:normal;color:#a4afa8;margin:4px 0}.offer small{display:block;color:#8a968d;font-size:10px;margin:11px 0 6px}.prices{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.prices>div{display:flex;justify-content:space-between;padding:10px 9px;background:#f4f7f3;border:1px solid #e9eee5;border-radius:6px}.prices span{font-size:10px;color:#839079}.prices b{font-size:12px}.match footer{font-size:9px;color:#988047;border-top:1px solid #edf0eb;padding-top:12px;margin-top:18px}.dot{display:inline-block;background:#bf9b55;width:5px;height:5px;border-radius:50%;margin-right:5px}.empty{padding:40px;background:#fff;border:1px dashed #d2dcd4;border-radius:12px;text-align:center;color:#718078}.empty p{max-width:600px;margin:12px auto;line-height:1.8}.table-wrap{overflow:auto;background:white;border:1px solid #e1e6e1;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:12px}th{text-align:left;color:#8a958d;background:#f9fbf8;font-size:10px}td,th{padding:15px;border-bottom:1px solid #edf0eb}td:nth-child(4){font-weight:650}.notes{background:white;padding:24px;border-radius:12px;margin-top:20px}.notes p{color:#778379;line-height:1.8}.notes a{text-decoration:underline}.pagination{display:flex;justify-content:center;gap:25px;align-items:center;margin:28px;font-size:12px}.pagination a{background:white;border:1px solid #dce4dc;padding:9px 13px;border-radius:5px}.bottom-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:35px}.panel{padding:25px;background:#eef2e9;border:1px solid #dfe5d7;border-radius:12px}.panel p{font-size:11px;color:#7b8979;line-height:1.9}.panel h2{margin:10px 0}.panel a{font-size:11px;font-weight:700;color:#46633f}.bar-row{display:grid;grid-template-columns:65px 1fr 43px;align-items:center;gap:13px;font-size:10px;color:#72836c;margin-top:17px}.track{height:7px;background:#dce4d3;border-radius:4px;overflow:hidden}.track i{display:block;height:100%;background:#6d8e50;border-radius:4px}.page-foot{color:#9ba59d;font-size:9px;letter-spacing:1px;padding:35px 0 0}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #80a44c;outline-offset:3px}@media(min-width:1500px){.match-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}@media(max-width:1100px){main{padding:28px 24px}.match-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.stats{grid-template-columns:repeat(2,1fr)}.filters{flex-wrap:wrap}.filters label{flex:1 1 40%}}@media(max-width:700px){aside{display:none}main{margin:0;padding:22px 16px}.match-grid,.bottom-grid{grid-template-columns:1fr}.stats{gap:9px}.stat{padding:15px}.stat strong{font-size:27px}.section-head{align-items:start;flex-direction:column}.tabs{gap:17px}.tab{font-size:11px}.filters label{flex:1 1 100%}h1{letter-spacing:-1px}.pill{font-size:9px}.eyebrow{font-size:9px}.table-wrap{max-width:100%}}
'''

CSS += """
.sidebar-guide{color:#d5e3dd;line-height:2;padding:0 14px 20px}.competitions>summary{padding:12px;color:#d5e3dd}
summary{cursor:pointer;font-weight:600}summary:focus-visible{outline:3px solid #80a44c;outline-offset:3px}
.advanced{margin-top:18px;color:#405d4c}.secondary-nav{display:flex;flex-wrap:wrap;gap:22px;padding-top:20px}
.match details{margin-top:14px;line-height:1.6;font-size:13px}.collection{margin:0 0 24px;color:#536657;font-size:13px;line-height:1.7}.intro{margin-bottom:24px;color:#536657}
.tab{font-size:14px;color:#536657}.tabs{gap:28px}.filters label{font-size:12px;color:#536657}
select,input{font:inherit}.match footer{font-size:12px;line-height:1.6;color:#79632c}.match-top{font-size:12px}
.section-head>span{font-size:12px;color:#536657}.notice{font-size:13px;color:#695a34}.empty{color:#536657}
.skip-link{position:absolute;top:-100px;left:16px;background:white;padding:14px;z-index:2}.skip-link:focus{top:12px}
@media(max-width:700px){.tab{font-size:14px}.pill{font-size:12px}.secondary-nav{gap:16px}.filters button{width:100%}}
"""

CSS += ".brand-icon{vertical-align:middle;border-radius:8px}"
