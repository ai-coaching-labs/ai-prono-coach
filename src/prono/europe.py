"""Calendrier ESPN public des coupes UEFA, résultats à 90 minutes et cotes indicatives."""
import csv
import gzip
import io
import json
import re
import urllib.request
import urllib.error
from datetime import timedelta
from .workspace import utcnow, timestamp, number, atomic_write
from .leagues import EUROPE, league_workspace
from .history_import import FIELDS
from .model import load_history

BASE='https://site.api.espn.com/apis/site/v2/sports/soccer/'
NOTICE='Source ESPN publique. Résultats à 90 minutes seulement ; prolongations et tirs au but exclus. Collecte ≠ date de cotation. Aucun mélange avec les championnats nationaux.'

def fetch(code, dates):
    url=BASE+EUROPE[code]+'/scoreboard?dates='+dates+'&limit=1000'
    try:
        with urllib.request.urlopen(url,timeout=30) as response:raw=response.read(12_000_001)
        if len(raw)>12_000_000:raise ValueError('Capture ESPN trop volumineuse.')
        if raw[:2]==b'\x1f\x8b':raw=gzip.decompress(raw)
        if len(raw)>12_000_000:raise ValueError('Capture ESPN décompressée trop volumineuse.')
        data=json.loads(raw)
    except (urllib.error.URLError,TimeoutError,UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('Calendrier ESPN indisponible ; données précédentes conservées.') from exc
    if not isinstance(data,dict) or not isinstance(data.get('events'),list):raise ValueError('Format ESPN invalide.')
    if not any(l.get('slug')==EUROPE[code] for l in data.get('leagues',[])):raise ValueError('Compétition ESPN différente.')
    if len(data['events'])>=1000:raise ValueError('Capture ESPN tronquée : import refusé.')
    return url,data

def decimal_odds(value):
    american=number(value)
    if abs(american)<100:raise ValueError('Cote américaine invalide.')
    return 1+american/100 if american>0 else 1+100/abs(american)

def normalize(data, code, source, collected_at):
    collected=timestamp(collected_at);matches=[];results=[];rejected=[];seen=set()
    for event in data['events']:
        try:
            comps=event.get('competitions',[])
            if len(comps)!=1:raise ValueError('Rencontre ambiguë.')
            c=comps[0];status=c.get('status',{});kind=status.get('type',{})
            if not c.get('timeValid',False):raise ValueError('Heure du match non confirmée.')
            kickoff=timestamp(c['date']);ident='espn-'+code+'-'+str(event['id'])
            if ident in seen:raise ValueError('Match dupliqué.')
            seen.add(ident)
            teams={t['homeAway']:t for t in c['competitors']}
            if len(c['competitors'])!=2 or set(teams)!={'home','away'}:raise ValueError('Équipes invalides.')
            home,away=[teams[k]['team']['displayName'].strip() for k in ('home','away')]
            if not home or not away or home==away:raise ValueError('Équipes invalides.')
            common={'event_id':ident,'kickoff':kickoff.isoformat(),'home':home,'away':away,'source':source}
            if kind.get('completed') is True:
                # Le score ESPN peut inclure les prolongations : ne jamais le traiter comme du 1N2 à 90 min.
                if kind.get('name')!='STATUS_FULL_TIME' or status.get('period')!=2:raise ValueError('Résultat hors temps réglementaire ou durée inconnue.')
                if kickoff>=collected:raise ValueError('Résultat futur refusé.')
                scores=[int(teams[k]['score']) for k in ('home','away')]
                if any(s<0 or s>30 for s in scores):raise ValueError('Score invalide.')
                results.append({**common,'home_goals':scores[0],'away_goals':scores[1],'result_known_at':collected.isoformat()})
            elif kind.get('state')=='pre' and kind.get('name')=='STATUS_SCHEDULED':
                offers=[]
                for odds in c.get('odds',[]):
                    if not isinstance(odds,dict):continue
                    try:
                        provider=odds['provider']['name'];market=odds['moneyline']
                        # Triplet courant complet du même bookmaker ; aucune combinaison open/close.
                        prices={k:decimal_odds(market[k]['close']['odds']) for k in ('home','draw','away')}
                        if not provider:raise ValueError('Bookmaker absent.')
                        offers.append({'bookmaker':provider,'odds':prices})
                    except (KeyError,TypeError,ValueError):continue
                matches.append({**common,'division':code,'offers':offers,'collected_at':collected.isoformat(),'quoted_at':None,
                                'status':'unverified_quote_time','analysis_eligible':False,'source_state':kind['name']})
            # Les états en cours, reportés ou annulés ne sont ni un résultat ni un futur prono.
        except (KeyError,TypeError,ValueError) as exc:rejected.append({'event_id':event.get('id'),'reason':str(exc)})
    return {'matches':matches,'results':results,'rejected':rejected,'notice':NOTICE}

def archive(ws, code, dates):
    url,data=fetch(code,dates);when=utcnow()
    path=ws.path('data/sources/espn-'+code+'-'+dates+'-'+when.strftime('%Y%m%dT%H%M%S%f')+'.json')
    atomic_write(path,json.dumps({'source':url,'collected_at':when.isoformat(),'data':data},ensure_ascii=False))
    return normalize(data,code,url,when.isoformat())

def sync_europe(ws, codes=None):
    from .identity import register_matches,price_changes
    codes=list(EUROPE) if codes is None else list(codes)
    if not codes or any(c not in EUROPE for c in codes):raise ValueError('Coupe d’Europe inconnue.')
    path=ws.path('data/europe-watch.json');previous=json.loads(path.read_text()) if path.exists() else {'matches':[]}
    matches=previous['matches'];statuses={};now=utcnow()
    # Mois courant et suivant : pas d’import infini ni d’appel à une API de cotes payante.
    months=list(dict.fromkeys([now.strftime('%Y%m'),(now.replace(day=28)+timedelta(days=4)).strftime('%Y%m')]))
    for code in codes:
        try:
            league_workspace(ws,code,create=True)
            incoming=[];rejected=[]
            for month in months:
                part=archive(ws,code,month);incoming.extend(part['matches']);rejected.extend(part['rejected'])
            incoming=[f for f in incoming if timestamp(f['kickoff'])>now]
            enriched=register_matches(ws,{'matches':incoming,'collected_at':now.isoformat()})['matches']
            matches=[f for f in matches if f['division']!=code]+enriched
            statuses[code]={'status':'ok','matches':len(enriched),'rejected':len(rejected),'collected_at':now.isoformat()}
        except (ValueError,OSError) as exc:statuses[code]={'status':'error','message':str(exc),'previous_preserved':True}
    result={'collected_at':now.isoformat(),'matches':matches,'sources':{**previous.get('sources',{}),**statuses},'notice':NOTICE,
            'price_changes':price_changes(previous['matches'],matches)}
    atomic_write(path,json.dumps(result,ensure_ascii=False,indent=2))
    return {'matches':sum(v.get('matches',0) for v in statuses.values()),'sources':statuses,'offers':sum(len(f['offers']) for f in matches),'notice':NOTICE}

def sync_europe_history(ws, seasons):
    from .leagues import division_for
    code=division_for(ws);existing=load_history(ws.path('data/history.csv'))
    if any(not r['source'].startswith(BASE+EUROPE[code]+'/scoreboard?') for r in existing):raise ValueError('Historique d’une autre source : import refusé.')
    years=set()
    for season in seasons:
        if not re.fullmatch(r'\d{4}',season) or int(season[2:])!=(int(season[:2])+1)%100:raise ValueError('Saison invalide.')
        years.update([2000+int(season[:2]),2000+int(season[:2])+1])
    if not years:raise ValueError('Saisons requises.')
    current=utcnow().year;records={r['event_id']:r for r in existing};rejected=0
    for year in sorted(y for y in years if y<=current and (code!='UECL' or y>=2021)):
        part=archive(ws,code,str(year));rejected+=len(part['rejected'])
        for row in part['results']:
            k=timestamp(row['kickoff']);season_year=k.year if k.month>=7 else k.year-1
            if f'{season_year%100:02d}{(season_year+1)%100:02d}' not in seasons:continue
            previous=records.get(row['event_id'])
            if previous:
                if any(previous[f]!=row[f] for f in ('kickoff','home','away','home_goals','away_goals')):raise ValueError('Résultat ESPN corrigé : capture conservée, revue manuelle requise.')
                continue
            records[row['event_id']]=row
    output=io.StringIO();writer=csv.DictWriter(output,fieldnames=FIELDS);writer.writeheader()
    writer.writerows(sorted(records.values(),key=lambda r:timestamp(r['kickoff'])))
    atomic_write(ws.path('data/history.csv'),output.getvalue())
    return {'history_rows':len(records),'added':len(records)-len(existing),'rejected':rejected,'notice':NOTICE}
