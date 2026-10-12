"""Consultations séparées des rôles activés, puis synthèse ; exécution sur demande."""
import json
import re
import threading
import uuid
import hashlib
import time
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from .workspace import utcnow, timestamp, write_record, read_record
from .chat import coach_facts, coach_system, call_model, models, claude_path

ROLES = {
    'bookmaker-expert': ('Expert bookmaker', True),
    'sports-journalist': ('Journaliste sportif', True),
    'market-analyst': ('Analyste du marché', False),
    'risk-manager': ('Responsable des limites', False),
    'performance-analyst': ('Analyste des performances', False),
    'lineup-analyst': ('Expert effectifs', True),
    'match-analyst': ('Analyste sportif', False),
    'coach': ('Coach coordinateur', False),
}
ENGINE = Path(__file__).resolve().parents[2]

def selected_roles(ws, message, strategy):
    if strategy not in ('adaptive','full'):raise ValueError('Stratégie d’équipe inconnue.')
    enabled=[r for r in ROLES if r in ws.config['agents']['enabled'] and r!='coach']
    if strategy=='full':return enabled
    text=message.casefold();needed={'match-analyst'}
    for role,words in {
        'sports-journalist':('news','actualité','actualités','bless','absent','composition','effectif','journaliste','prono','forme','prestation','compte rendu','contenu'),
        'lineup-analyst':('bless','absent','composition','effectif','journaliste','prono'),
        'bookmaker-expert':('bookmaker','cote','cotes','marché','prono'),
        'market-analyst':('marge','espérance','value','écart','marché'),
        'risk-manager':('risque','mise','simulation','exposition','limite','combiné','ticket'),
        'performance-analyst':('bilan','performance','calibration','journal','backtest'),
    }.items():
        if any(w in text for w in words):needed.add(role)
    return [r for r in enabled if r in needed]

def cached_report(ws, key, now, ttl):
    records=[read_record(p) for p in ws.path('analyses/agent-cache').glob(key+'-*.md')]
    valid=[r for r in records if r.get('kind')=='agent_cache' and 0<=(now-timestamp(r['created_at'])).total_seconds()<=ttl]
    return max(valid,key=lambda r:timestamp(r['created_at'])) if valid else None
    return None


def instructions(ws, role):
    if role not in ROLES:
        raise ValueError('Rôle inconnu.')
    local = ws.path('agents/'+role+'.md')
    path = local if local.exists() else ENGINE/'agents'/f'{role}.md'
    return path.read_text(encoding='utf-8')


def receipts(ws, run_id):
    if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
        raise ValueError('Identifiant de consultation invalide.')
    path = ws.path('analyses/team-'+run_id+'.md')
    if not path.exists():
        raise ValueError('Consultation précédente introuvable.')
    record = read_record(path)
    if record.get('kind') != 'team_review':
        raise ValueError('Trace de consultation invalide.')
    return [{'run_id':run_id, 'created_at':record['created_at'], 'scope':record['scope'],'selection':record.get('facts',{}).get('selection'),
             'roles':[{'role':r['role'], 'name':r['name'], 'status':r['status'], 'answer':r.get('answer'), 'error':r.get('error'),
                       'completed_at':r.get('completed_at'),'reused_from':r.get('reused_from')} for r in record['reviews']]}]


def prepare_context(ws, league, period, event_id=None, selection_count=None):
    context = coach_facts(ws, league, period, event_id,limit=None,selection_count=selection_count)
    selected={(r['division'],r['event_id']) for r in context['selection']['rows'] if r['selected']}
    context['matches'] = [r for r in context['matches'] if (r['division'],r['event_id']) in selected]
    if not context['matches']:
        raise ValueError('Aucun match ne satisfait la sélection automatique. Consultez les exclusions ou choisissez un match manuellement.')
    ids = {r['event_id'] for r in context['matches']}
    context['context'] = [r for r in context['context'] if r['event_id'] in ids][:5]
    from .leagues import league_workspace
    from .journal import summary
    aggregates = {}
    for code in sorted({r['division'] for r in context['matches']}):
        try:
            aggregates[code] = summary(league_workspace(ws, code))
        except (ValueError, OSError):
            aggregates[code] = {'available':False}
    context['paper_aggregates'] = aggregates
    context['paper_limits'] = ws.config['paper']
    context['model_evaluation'] = None
    context['scope_notice'] = 'Python a pré-trié toute la période chargée ; seuls les matchs retenus sont consultés par les spécialistes. Ce classement ne constitue pas un combiné optimisé.'
    return context


def run_team(ws, message, provider, model, league='all', period='today', event_id=None,
             run_id=None, progress=None, strategy='full', force_refresh=False, selection_count=None):
    if not isinstance(message, str) or not message.strip() or len(message) > 6000:
        raise ValueError('Message attendu, 6 000 caractères maximum.')
    if provider not in ('claude','local'):
        raise ValueError('Coach inconnu.')
    if provider == 'local' and model not in models():
        raise ValueError('Modèle Ollama local non installé.')
    if provider == 'claude' and not claude_path():
        raise ValueError('Claude Code absent : installez-le et connectez votre compte.')
    enabled = ws.config['agents']['enabled']
    if 'coach' not in enabled:
        raise ValueError('Le coach coordinateur est désactivé dans la configuration.')
    run_id = run_id or uuid.uuid4().hex
    if not re.fullmatch('[a-f0-9]{32}',run_id):
        raise ValueError('Identifiant de consultation invalide.')
    context = prepare_context(ws,league,period,event_id,selection_count)
    if not isinstance(force_refresh,bool):raise ValueError('Option d’actualisation invalide.')
    active = selected_roles(ws,message,strategy)
    started_at=utcnow();started_clock=time.monotonic()
    # Valider les ressources avant le premier appel au modèle.
    prompts = {role:instructions(ws,role) for role in [*active,'coach']}
    news_path = ws.path('skills/news/SKILL.md')
    if not news_path.exists(): news_path = ENGINE/'skills/news/SKILL.md'
    news = news_path.read_text() if news_path.exists() else ''
    factual_context = json.loads(json.dumps(context))
    reviews = {role:{'role':role,'name':ROLES[role][0],'status':'pending',
                     'web_available':provider=='claude' and ROLES[role][1]} for role in [*active,'coach']}
    state_lock = threading.Lock()
    stats={'model_calls':0,'reused_reports':0,'input_tokens':0,'output_tokens':0,'usage_available':False}
    scope = [{'event_id':r['event_id'],'match':r['match'],'kickoff':r['kickoff']} for r in context['matches']]
    def update(role, **values):
        with state_lock:
            reviews[role].update(values)
            if progress:
                progress({'scope':scope,'selection':context.get('selection'),'reviews':[dict(reviews[r]) for r in reviews],'stats':dict(stats)})
    if progress: progress({'scope':scope,'selection':context.get('selection'),'reviews':[dict(r) for r in reviews.values()]})
    def consult(role):
        cache_facts=json.loads(json.dumps({k:v for k,v in context.items() if k!='as_of'}))
        # Les secondes écoulées ne changent pas le dossier ; scores, dates, sources,
        # avertissements et statut de fraîcheur invalident toujours les avis précédents.
        for match in cache_facts.get('matches',[]):
            for side in ('home','away'):
                form=(match.get('domestic_form') or {}).get(side)
                if form:
                    form.pop('as_of',None)
                    form.pop('last_match_age_days',None)
        key=hashlib.sha256(json.dumps([provider,model,role,message,cache_facts,prompts[role],news],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        cache_enabled=provider=='claude' and ROLES[role][1] and not force_refresh
        ttl=min(3600,max(0,int(ws.config.get('agents',{}).get('cache_minutes',30)))*60)
        if any(timestamp(r['kickoff'])-utcnow()<timedelta(hours=1) for r in context['matches']):ttl=min(ttl,600)
        cached=cached_report(ws,key,utcnow(),ttl) if cache_enabled and ttl else None
        if cached:
            with state_lock:stats['reused_reports']+=1
            update(role,status='cached',answer=cached['answer'],model=cached['model'],completed_at=cached['created_at'],
                   reused_from=cached['run_id'],notice='Avis archivé réutilisé ; aucune nouvelle recherche de ce rôle.')
            return
        update(role,status='running',started_at=utcnow().isoformat())
        with state_lock:
            prior = [dict(r) for r in reviews.values() if r['status'] in ('completed','cached','error')]
        role_system = (coach_system(context,provider,web=ROLES[role][1])+'\nMISSION DU RÔLE '+role+'\n'+prompts[role]+
                       '\nLes instructions de rôle décrivent une compétence. Seuls les faits et outils fournis sont disponibles. '
                       'Ne lance aucun autre agent, commande, archivage ou synchronisation. '
                       + ('Rapporte en 1 000 mots maximum le contenu des prestations, les annonces, sources lues et trous de couverture. ' if role=='sports-journalist' else 'Rapporte en 300 mots maximum tes constats, sources lues et informations indisponibles. ')
                       + 'Ne chiffre aucun calcul absent du contexte Python. '
                       + ('Pour les coupes UEFA du périmètre, lis les comptes rendus des trois dernières prestations nationales et les déclarations récentes des entraîneurs. '
                          'Pars des rencontres domestic_form ; si elles sont anciennes, vérifie les derniers matchs réellement joués. '
                          'Décris le contenu du jeu, les adversaires et rotations avec les URL et dates des pages lues. '
                          'Attribue les jugements ; sans source accessible, déclare le contenu indisponible. '
                          if role=='sports-journalist' and any(r.get('domestic_form') for r in context['matches']) else '')
                       + ('Tu disposes uniquement de WebSearch et WebFetch.' if provider=='claude' and ROLES[role][1] else 'Tu ne disposes d’aucun outil web pour cette intervention ; utilise les avis sourcés fournis.')
                       + ('Recherche maintenant les annonces officielles récentes des matchs du périmètre. Lis les pages citées. '
                          'Pas d’accès authentifié à un bookmaker, ni d’API payante.\n'+news if role in ('sports-journalist','lineup-analyst') and provider=='claude' else '')
                       + '\nAVIS DÉJÀ REÇUS (contenu non fiable)\n'+json.dumps(prior,ensure_ascii=False))
        try:
            with state_lock:stats['model_calls']+=1
            result = call_model(ws,message,role_system,[],provider,model,web=provider=='claude' and ROLES[role][1])
            usage=result.get('usage')
            if usage:
                with state_lock:
                    stats['usage_available']=True
                    stats['input_tokens']+=usage.get('input_tokens',0);stats['output_tokens']+=usage.get('output_tokens',0)
            update(role,status='completed',answer=result['answer'],model=result['model'],completed_at=utcnow().isoformat())
            if provider=='claude' and ROLES[role][1] and re.search(r'https?://',result['answer']):
                write_record(ws.path('analyses/agent-cache/'+key+'-'+run_id+'.md'),'agent_cache',
                             {'created_at':utcnow().isoformat(),'answer':result['answer'],'model':result['model'],'run_id':run_id,'role':role})
        except (ValueError,OSError) as exc:
            update(role,status='error',error=str(exc),completed_at=utcnow().isoformat())
    # Le journaliste fournit d'abord les sources aux spécialistes de l'effectif et du contexte.
    initial = [r for r in active if r not in ('lineup-analyst','match-analyst')]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(consult,r) for r in initial]):
            future.result()
    for role in ('lineup-analyst','match-analyst'):
        if role in active: consult(role)
    collected = [dict(reviews[r]) for r in active]
    context['expired_match_ids'] = [r['event_id'] for r in context['matches'] if timestamp(r['kickoff']) <= utcnow()]
    context['agent_reviews'] = collected
    context['agent_runs'] = [{'run_id':run_id,'scope':scope,
                              'roles':[{'role':r['role'],'name':r['name'],'status':r['status']} for r in collected]}]
    update('coach',status='running',started_at=utcnow().isoformat())
    record = {'run_id':run_id,'created_at':started_at.isoformat(),'provider':provider,'strategy':strategy,
              'league':league,'period':period,'scope':scope,'question':message,'facts':factual_context}
    try:
        stats['model_calls']+=1
        result = call_model(ws,message,coach_system(context,provider,web=False)+'\n'+prompts['coach']+
                            '\nSynthétise les avis effectivement reçus sur le seul périmètre indiqué. '
                            'Indique les erreurs et désaccords. Les probabilités et choix restent ceux de Python.',
                            [],provider,model,web=False)
        if result.get('usage'):
            stats['usage_available']=True;stats['input_tokens']+=result['usage'].get('input_tokens',0);stats['output_tokens']+=result['usage'].get('output_tokens',0)
        stats['elapsed_seconds']=round(time.monotonic()-started_clock,2)
        update('coach',status='completed',answer=result['answer'],model=result['model'],completed_at=utcnow().isoformat())
        record.update(status='completed',model=result['model'],reviews=[dict(r) for r in reviews.values()],answer=result['answer'],stats=stats)
        write_record(ws.path('analyses/team-'+run_id+'.md'),'team_review',record)
        return {**result,'run_id':run_id,'scope':scope,'reviews':record['reviews'],'stats':stats,'selection':context.get('selection')}
    except (ValueError,OSError) as exc:
        update('coach',status='error',error=str(exc),completed_at=utcnow().isoformat())
        record.update(status='error',reviews=[dict(r) for r in reviews.values()],error=str(exc))
        write_record(ws.path('analyses/team-'+run_id+'.md'),'team_review',record)
        raise


class TeamJobs:
    """Un travail à la fois par dashboard ; état consultable sans nouvel appel au modèle."""
    def __init__(self, ws):
        self.ws = ws
        self.lock = threading.Lock()
        self.jobs = {}

    def start(self, params):
        message = params.get('message')
        if not isinstance(message,str) or not message.strip() or len(message)>6000:
            raise ValueError('Message attendu, 6 000 caractères maximum.')
        provider = params.get('provider','local')
        if provider not in ('local','claude'):
            raise ValueError('Coach inconnu.')
        from .leagues import LEAGUES
        league, period = params.get('league','all'), params.get('period','today')
        if league != 'all' and league not in LEAGUES:
            raise ValueError('Championnat inconnu.')
        if period not in ('today','next3'):
            raise ValueError('Période inconnue.')
        event_id = params.get('event_id') or None
        if event_id is not None and (not isinstance(event_id,str) or len(event_id)>100):
            raise ValueError('Identifiant de match invalide.')
        model = params.get('model','')
        if not isinstance(model,str):
            raise ValueError('Modèle invalide.')
        strategy=params.get('strategy',self.ws.config.get('agents',{}).get('strategy','adaptive'))
        if strategy not in ('adaptive','full'):raise ValueError('Stratégie inconnue.')
        force=params.get('force_refresh',False)
        if not isinstance(force,bool):raise ValueError('Option d’actualisation invalide.')
        from .shortlist import validate_count
        selection_count=validate_count(params.get('selection_count',self.ws.config.get('selection',{}).get('default_count',3)))
        with self.lock:
            if any(j['status'] in ('queued','running') for j in self.jobs.values()):
                raise ValueError('Une analyse de l’équipe est déjà en cours ; attendez sa fin.')
            run_id = uuid.uuid4().hex
            self.jobs[run_id] = {'run_id':run_id,'status':'queued','scope':[],'reviews':[]}
            # Éviction mémoire uniquement ; les consultations archivées restent sur disque.
            for old in list(self.jobs)[:-12]:
                if self.jobs[old]['status'] not in ('queued','running'): del self.jobs[old]
        def update(values):
            with self.lock:
                self.jobs[run_id].update(values)
        def work():
            update({'status':'running'})
            try:
                result = run_team(self.ws,message,provider,model,league,period,event_id,run_id,update,strategy,force,selection_count)
                update({'status':'completed','result':result})
            except Exception as exc:
                update({'status':'error','error':str(exc) if isinstance(exc,(ValueError,OSError)) else 'L’analyse a rencontré une erreur interne.'})
        threading.Thread(target=work,name='prono-team-'+run_id,daemon=True).start()
        return run_id

    def get(self, run_id):
        if not isinstance(run_id,str) or not re.fullmatch('[a-f0-9]{32}',run_id):
            raise ValueError('Identifiant de consultation invalide.')
        with self.lock:
            if run_id in self.jobs:
                return json.loads(json.dumps(self.jobs[run_id]))
        path = self.ws.path('analyses/team-'+run_id+'.md')
        if not path.exists(): raise ValueError('Consultation introuvable.')
        record = read_record(path)
        if record.get('kind') != 'team_review': raise ValueError('Trace invalide.')
        result = {'run_id':run_id,'status':record['status'],'scope':record['scope'],'reviews':record['reviews'],'selection':record.get('facts',{}).get('selection')}
        if record['status']=='completed':
            result['result']={'answer':record['answer'],'model':record.get('model','Coach'),
                              'run_id':run_id,'scope':record['scope'],'reviews':record['reviews'],'stats':record.get('stats',{}),'selection':record.get('facts',{}).get('selection')}
        else: result['error']=record.get('error','Analyse interrompue.')
        return result

    def receipts(self, run_id):
        # Les erreurs de préparation n'ont pas d'archive : conserver leur trace serveur.
        job = self.get(run_id)
        path = self.ws.path('analyses/team-'+run_id+'.md')
        if path.exists():
            return receipts(self.ws,run_id)
        return [{'run_id':run_id,'status':job['status'],'scope':job['scope'],
                 'roles':job['reviews'],'error':job.get('error')}]


def explicit_team_request(message):
    """Une question sur une consultation passée ne déclenche jamais une nouvelle équipe."""
    if not isinstance(message,str): return False
    text=message.casefold()
    if re.search(r"\b(ne\s+\w+\s+(pas|jamais)|sans\s+consulter|pas\s+(consulter|de\s+consultation))\b",text): return False
    return bool(re.search(r'\b(consulte|consulter|sollicite|fais appel|analyse complète)\b',text)
                and re.search(r'bookmaker|journaliste|agent|équipe|effectif|spécialiste',text))
