"""Vues de suivi réel et d'études rétrospectives ; actions explicites protégées."""
from .workspace import timestamp,utcnow
from .leagues import LEAGUES

LABELS={'home':'1','draw':'N','away':'2'}
NAMES={'poisson-baseline-v1':'Baseline de l’étude','poisson-recency-research-v1':'Récence · expérimental',
       'dc-correction-research-v1':'Correction des petits scores · expérimental','league-frequency':'Fréquences du championnat'}

def metric(value,percent=False):
    return '—' if value is None else f'{100*value:.1f} %' if percent else f'{value:.4f}'

def tracking_view(ws,league,query,esc,zone,link,page=1,token=None):
    from .tracking import tracking_summary
    result=tracking_summary(ws,league,query)
    p=result['performance'];disabled='' if token else ' disabled'
    content='<div class="section-head"><h2>Mes pronos suivis</h2><span>Prévisions conservées avant coup d’envoi</span></div>'
    content+='<div class="stats">'+''.join(f'<article class="stat"><span>{esc(label)}</span><strong>{esc(value)}</strong></article>' for label,value in [
        ('Pronos enregistrés',result['captured']),('En attente',result['pending']),('Résultats comparés',p['evaluated']),('Choix corrects',metric(p['accuracy'],True))])+'</div>'
    content+=f'<p>Score probabiliste : {metric(p["brier"])} · Erreur logarithmique : {metric(p["log_loss"])}. Ces mesures restent indisponibles tant que les matchs suivis ne sont pas terminés.</p>'
    content+=f'<div class="actions"><button id="track-capture"{disabled}>Enregistrer les pronos chargés</button> <button id="track-results"{disabled}>Vérifier les résultats publics</button></div><p id="lab-status" role="status"></p>'
    content+='<div class="notice">'+esc(result['notice'])+' Le suivi fonctionne pendant que le dashboard est ouvert. Les résultats publics des seuls matchs suivis sont vérifiés après le match, au plus une fois par heure et par championnat. Les mises fictives restent dans leur journal habituel.</div>'
    import json
    for filename in ('data/result-refresh-status.json','data/tracking-status.json'):
        path=ws.path(filename)
        if path.exists():
            state=json.loads(path.read_text())
            if state.get('error'):content+='<p>Suivi automatique : '+esc(state['error'])+'</p>'
            if filename.endswith('result-refresh-status.json'):
                for code,status in state.items():
                    if status.get('status')=='error' and (league=='all' or code==league):content+='<p>Import de résultats · '+esc(LEAGUES[code][0])+' : '+esc(status['error'])+'</p>'
    pages=max(1,(len(result['matches'])+17)//18);page=min(max(1,page),pages)
    content+='<div class="table-wrap"><table><thead><tr><th>Match</th><th>Prono enregistré</th><th>Résultat</th><th>Suivi</th></tr></thead><tbody>'
    ordered=sorted(result['matches'],key=lambda row:(row['status']!='pending',timestamp(row['fixture']['kickoff']).timestamp() if row['status']=='pending' else -timestamp(row['fixture']['kickoff']).timestamp()))
    for row in ordered[(page-1)*18:page*18]:
        f=row['fixture'];outcome=row['outcome'];r=row['result']
        predicted=LABELS[outcome]+' · '+metric(row['probabilities'][outcome],True)
        score=f'{r["home_goals"]} – {r["away_goals"]}' if r and r['status']=='settled' else 'Reporté' if row['status']=='rescheduled' else 'En attente'
        state='Choix correct' if r and r.get('actual')==outcome else 'Choix incorrect' if row['status']=='settled' else 'Prévision à renouveler' if row['status']=='rescheduled' else 'Avant match' if timestamp(f['kickoff'])>utcnow() else 'Résultat non publié ou non chargé'
        match=esc(f['home']+' / '+f['away'])+'<br><small>'+esc(LEAGUES[row['division']][0]+' · '+timestamp(f['kickoff']).astimezone(zone).strftime('%d/%m à %H:%M'))+'</small>'
        archived=esc(predicted)+'<br><small>'+esc('Enregistré le '+timestamp(row['created_at']).astimezone(zone).strftime('%d/%m à %H:%M'))+'</small>'
        content+='<tr><td>'+match+'</td><td>'+archived+'</td>'+''.join('<td>'+esc(v)+'</td>' for v in [score,state])+'</tr>'
    content+='</tbody></table></div>'
    if not result['matches']:content+='<p>Aucun prono enregistré pour ces filtres. Le suivi archive les prochains matchs calculables, même si leurs cotes restent indicatives.</p>'
    if pages>1:
        content+='<div class="pagination">'+(f'<a href="{esc(link(page=page-1))}">← Précédent</a>' if page>1 else '')+f'<span>Page {page} / {pages}</span>'+(f'<a href="{esc(link(page=page+1))}">Suivant →</a>' if page<pages else '')+'</div>'
    return content

def evaluation_view(ws,league,esc,token=None):
    from .evaluation import latest_evaluation
    report=latest_evaluation(ws);disabled='' if token else ' disabled'
    content='<div class="section-head"><h2>Qualité des probabilités</h2><span>Études locales · calculs Python</span></div>'
    content+=f'<div class="filters"><label>Évaluation<select id="evaluation-mode"><option value="snapshot">Étude rétrospective des archives</option><option value="observed">Dates de connaissance strictes</option></select></label><button id="evaluate"{disabled}>Comparer les modèles</button></div><p id="lab-status" role="status"></p>'
    content+='<div class="notice">Le modèle utilisé pour les pronos reste poisson-baseline-v1. Les variantes sont expérimentales. L’étude des archives ne reconstitue pas les anciennes dates de publication ; le suivi réel est visible dans « Mes pronos suivis ». « Tous les championnats » compare par défaut Ligue 1, Ligue 2 et Premier League.</div>'
    if not report:return content+'<p>Aucune étude enregistrée. La comparaison utilise les données chargées et ne fait aucun appel à une IA ou à une API.</p>'
    content+='<p>Dernière étude : '+esc(report['created_at'])+' · '+('Archives rétrospectives' if report['mode']=='snapshot' else 'Connaissance strictement antérieure')+'</p><p>'+esc(report['notice'])+'</p>'
    for code,result in report['leagues'].items():
        if league!='all' and code!=league:continue
        content+='<h3>'+esc(LEAGUES[code][0])+'</h3>'
        if result.get('error'):content+='<p>'+esc(result['error'])+'</p>';continue
        if result['synthetic']:content+='<p><b>Données SYNTHÉTIQUES · démonstration</b></p>'
        content+='<p>'+str(result['target_count'])+' matchs dans la période de test · '+str(result['skipped'])+' non évaluables. '+esc(result['method'])+'</p>'
        content+='<div class="table-wrap"><table><thead><tr><th>Modèle</th><th>Matchs</th><th>Brier ↓</th><th>Log loss ↓</th><th>Choix corrects</th><th>Écart Brier / baseline</th></tr></thead><tbody>'
        for name,model in result['models'].items():
            c=model['comparison'];delta=metric(c['delta_brier'])+(f' [{metric(c["lower"])} ; {metric(c["upper"])}]' if c['lower'] is not None else '')
            content+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [NAMES[name],model['evaluated'],metric(model['brier']),metric(model['log_loss']),metric(model['accuracy'],True),delta])+'</tr>'
        content+='</tbody></table></div><p><small>Un score plus bas est meilleur. Les écarts et intervalles portent sur les mêmes matchs ; ils ne démontrent pas un avantage de marché.</small></p>'
        content+='<details><summary>Voir la calibration de la baseline</summary><div class="table-wrap"><table><thead><tr><th>Issue</th><th>Probabilités annoncées</th><th>Matchs</th><th>Probabilité moyenne</th><th>Fréquence observée</th></tr></thead><tbody>'
        for b in result['models']['poisson-baseline-v1']['calibration']:
            content+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [LABELS[b['outcome']],metric(b['lower'],True)+' à '+metric(b['upper'],True),b['count'],metric(b['mean_probability'],True),metric(b['observed_frequency'],True)])+'</tr>'
        content+='</tbody></table></div><p>Lecture descriptive ; petits groupes instables. Aucune correction automatique des probabilités.</p></details><p><small>'+esc(result['variant_notes'])+'</small></p>'
    return content

SCRIPT='''
const main=document.querySelector('main'),token=main?.dataset.token,labStatus=document.getElementById('lab-status');
async function labJson(response){const data=await response.json();if(!response.ok)throw Error(data.error||'Demande refusée.');return data;}
function labBusy(busy){for(const id of ['evaluate','track-capture','track-results']){const el=document.getElementById(id);if(el)el.disabled=busy;}}
async function labAction(url,data){labBusy(true);labStatus.textContent='Calcul en cours…';try{const result=await labJson(await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Prono-Token':token},body:JSON.stringify(data)}));if(url==='/api/evaluation'){while(true){const job=await labJson(await fetch('/api/evaluation',{headers:{'X-Prono-Token':token}}));labStatus.textContent='Comparaison en cours · '+(job.current_league||'préparation');if(job.status==='completed')break;if(job.status==='error')throw Error(job.error);await new Promise(r=>setTimeout(r,1000));}}location.reload();}catch(e){labStatus.textContent=e.message;labBusy(false);}}
document.getElementById('track-capture')?.addEventListener('click',()=>labAction('/api/tracking',{action:'capture'}));
document.getElementById('track-results')?.addEventListener('click',()=>labAction('/api/tracking',{action:'results'}));
document.getElementById('evaluate')?.addEventListener('click',()=>labAction('/api/evaluation',{league:new URLSearchParams(location.search).get('league')||'all',mode:document.getElementById('evaluation-mode').value}));
'''
