"""Dashboard loopback : lecture et opérations explicites protégées par un jeton."""
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import threading
from urllib.parse import urlsplit, parse_qs
from .journal import summary
from .analysis import fixtures
from .briefing import daily_briefing
from .branding import ICON_SVG, ICON_LINK
from .history_import import history_status

def page(ws):
    stats = summary(ws)
    matches = fixtures(ws)
    esc = lambda v: html.escape(str(v), quote=True)
    brief = daily_briefing(ws)
    history = history_status(ws)
    dataset = 'DÉMONSTRATION SYNTHÉTIQUE' if history['synthetic'] else 'DONNÉES SOURCÉES' if history['rows'] else 'HISTORIQUE ABSENT'
    daily_rows = ''.join(f"<li>{esc(i['fixture']['home'])} / {esc(i['fixture']['away'])} — {esc(i['kickoff_local'])} : {esc(i['reason'])}{' — Données SYNTHÉTIQUES' if i['synthetic'] else ''}</li>" for i in brief['matches'])
    daily_actions = ''.join(f'<li>{esc(action)}</li>' for action in brief['next_steps'])
    cards = ''.join(f'<article><small>{label}</small><strong>{esc(value)}</strong></article>' for label, value in [
        ("Solde fictif", f'{stats["balance"]:.2f} u'), ("Résultat fictif", f'{stats["net_pnl"]:+.2f} u'),
        ("Exposition ouverte", f'{stats["open_exposure"]:.2f} u'), ("Paris clôturés", stats["settled_count"])])
    rows = ''.join('<tr>'+''.join(f'<td>{esc(v)}</td>' for v in [f['home']+' / '+f['away'], f['kickoff'], f['odds']['home'], f['odds']['draw'], f['odds']['away'], f['source']])+'</tr>' for f in matches)
    return f'''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>AI Prono Coach</title>{ICON_LINK}
<style>body{{background:#101820;color:#edf4f7;font:16px system-ui;max-width:1100px;margin:60px auto;padding:0 24px}}h1{{font-size:42px}}.tag{{color:#85dfb7;letter-spacing:3px;font-size:12px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}}article{{background:#1b2934;border:1px solid #2d4352;border-radius:14px;padding:24px}}small{{color:#a2b6c5}}strong{{display:block;font-size:28px;margin-top:12px}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{padding:14px;text-align:left;border-bottom:1px solid #2d4352}}section{{overflow-x:auto}}p{{color:#a2b6c5;line-height:1.7}}code{{color:#85dfb7}}a{{color:#85dfb7}}</style>
<span class="tag">WORKSPACE PRIVÉ · SIMULATION · {dataset}</span><h1>AI Prono Coach</h1><p>Des chiffres vérifiables. Des décisions expliquées. Aucun placement de pari.</p>
<h2>Historique sportif</h2><p>{history['rows']} résultats · {len(history['teams'])} équipes · Dernier match : {esc(history['latest_kickoff'] or 'indisponible')}.</p><p>{esc(history['notice'])}</p><details><summary>Équipes et sources</summary><p>{esc(', '.join(history['teams']))}</p><p>{esc(' · '.join(history['sources']))}</p></details>
<div class="cards">{cards}</div><h2>Point du {esc(brief['date'])} · {esc(brief['timezone'])}</h2><p>{esc(brief['notice'])}</p><ul>{daily_rows or '<li>Aucun match chargé pour cette journée.</li>'}</ul><ul>{daily_actions}</ul><p>Absences et compositions : indisponibles.</p><h2>Matchs chargés</h2><section><table><thead><tr><th>Match</th><th>Coup d'envoi UTC</th><th>1</th><th>N</th><th>2</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></section>
<h2>Parler au coach</h2><p>Dans votre assistant : « Fais le point sur les matchs du jour », « Fais le bilan de mon journal fictif ».<br>Pour analyser une rencontre, utiliser son identifiant chargé. <a href="/chat">Ouvrir le chat intégré · Local ou Claude</a>.</p>
<p>{esc(stats['notice'])}</p><p><a href="/api/summary">Résumé JSON</a> · Tableau en lecture seule, recharger pour actualiser.</p></html>'''

def serve(ws, port=8766):
    token = secrets.token_urlsafe(32)
    operation_lock = threading.Lock()
    from .team import TeamJobs
    team_jobs = TeamJobs(ws)
    from .evaluation import EvaluationJobs
    evaluation_jobs=EvaluationJobs(ws)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Ne rien exposer hors loopback, ni servir de fichiers du disque.
            if self.headers.get('Host', '').split(':')[0] not in ('127.0.0.1', 'localhost'):
                self.send_error(403)
                return
            parsed = urlsplit(self.path)
            job_path = parsed.path.startswith('/api/chat/jobs/')
            if (job_path or parsed.path=='/api/evaluation') and not secrets.compare_digest(self.headers.get('X-Prono-Token',''),token):
                self.send_error(403)
                return
            if parsed.path not in ('/', '/icon.svg', '/api/summary', '/chat', '/chat.js', '/dashboard.js','/api/evaluation','/api/tracking','/api/chat/options', '/api/chat/matches') and not job_path:
                self.send_error(404)
                return
            try:
                if parsed.path == '/icon.svg':
                    payload = ICON_SVG.encode()
                elif parsed.path=='/api/evaluation':
                    payload=json.dumps(evaluation_jobs.get(),ensure_ascii=False).encode()
                elif parsed.path=='/api/tracking':
                    from .tracking import tracking_summary
                    payload=json.dumps(tracking_summary(ws),ensure_ascii=False).encode()
                elif parsed.path=='/dashboard.js':
                    from .lab_dashboard import SCRIPT
                    payload=SCRIPT.encode()
                elif job_path:
                    payload = json.dumps(team_jobs.get(parsed.path.rsplit('/',1)[-1]),ensure_ascii=False).encode()
                elif parsed.path == '/api/chat/matches':
                    from .chat import coach_facts
                    params = {key:values[-1] for key,values in parse_qs(parsed.query).items()}
                    result = coach_facts(ws,params.get('league','all'),params.get('period','today'),limit=None,
                                         selection_count=int(params.get('count',ws.config.get('selection',{}).get('default_count',3))))
                    selected={(r['division'],r['event_id']) for r in result['selection']['rows'] if r['selected']}
                    payload = json.dumps({'matches':[{'event_id':r['event_id'],'name':r['match'],'domestic_form':r.get('domestic_form')} for r in result['matches']],
                                          'selection':result['selection'],'preview':[r for r in result['matches'] if (r['division'],r['event_id']) in selected]},ensure_ascii=False).encode()
                elif parsed.path == '/chat':
                    from .chat import page as chat_page
                    payload = chat_page(token).encode()
                elif parsed.path == '/chat.js':
                    from .chat import SCRIPT
                    payload = SCRIPT.encode()
                elif parsed.path == '/api/chat/options':
                    from .chat import models, claude_status
                    from .leagues import LEAGUES
                    from .team import ROLES
                    from .shortlist import validate_count
                    payload = json.dumps({'models': models(), 'claude': claude_status(),
                                          'roles':[{'role':r,'name':v[0]} for r,v in ROLES.items() if r in ws.config['agents']['enabled']],
                                          'selection_default_count':validate_count(ws.config.get('selection',{}).get('default_count',3)),
                                          'leagues': [{'code':k,'name':v[0]} for k,v in LEAGUES.items()]}, ensure_ascii=False).encode()
                elif parsed.path == '/':
                    if ws.path('data/league-hub.json').exists():
                        from .hub_dashboard import page as hub_page
                        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
                        payload = hub_page(ws, params,token).encode()
                    else:
                        payload = page(ws).encode()
                else:
                    payload = json.dumps(summary(ws), ensure_ascii=False).encode()
            except ValueError:
                self.send_error(400, 'Invalid request or workspace data')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml' if parsed.path == '/icon.svg' else 'text/javascript; charset=utf-8' if parsed.path in ('/chat.js','/dashboard.js') else 'text/html; charset=utf-8' if parsed.path in ('/', '/chat') else 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)
        def do_POST(self):
            host = self.headers.get('Host', '')
            if host.split(':')[0] not in ('127.0.0.1', 'localhost') or not secrets.compare_digest(self.headers.get('X-Prono-Token',''), token):
                self.send_error(403)
                return
            if self.headers.get('Origin') not in (None, 'http://'+host):
                self.send_error(403)
                return
            if self.path not in ('/api/chat', '/api/refresh','/api/tracking','/api/evaluation'):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 100_000:
                    raise ValueError('Message trop volumineux ou vide.')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body,dict):
                    raise ValueError('Une demande JSON structurée est requise.')
                if self.path=='/api/evaluation':
                    result=evaluation_jobs.start(body.get('league','all'),body.get('mode','snapshot'))
                elif self.path=='/api/tracking':
                    from .tracking import tick
                    if body.get('action') not in ('capture','results'):raise ValueError('Action de suivi inconnue.')
                    if not operation_lock.acquire(blocking=False):raise ValueError('Une mise à jour est déjà en cours.')
                    try:result=tick(ws,refresh=body['action']=='results')
                    finally:operation_lock.release()
                elif self.path == '/api/chat':
                    from .chat import reply
                    from .team import explicit_team_request
                    if body.get('mode') not in (None,'coach','team'):
                        raise ValueError('Mode d’analyse inconnu.')
                    if body.get('mode') == 'team' or explicit_team_request(body['message']):
                        result = {'job_id':team_jobs.start(body)}
                    else:
                        previous = team_jobs.receipts(body['last_team_run']) if body.get('last_team_run') else []
                        result = reply(ws, body['message'], body.get('model',''), body.get('history'), body.get('league','all'), body.get('provider','local'), body.get('period','today'),previous,body.get('event_id'),body.get('selection_count'))
                else:
                    from .leagues import LEAGUES, sync_leagues
                    from .market_watch import sync_markets
                    league = body.get('league','all')
                    if league != 'all' and league not in LEAGUES:
                        raise ValueError('Championnat inconnu.')
                    if not operation_lock.acquire(blocking=False):
                        raise ValueError('Une mise à jour est déjà en cours.')
                    try:
                        if body['action'] == 'markets':
                            facts = sync_markets(ws)
                            result = {'message': f"Calendrier actualisé : {facts['matches']} matchs et {facts['offers']} triplets de cotes publiques. Heure de cotation inconnue : observation uniquement."}
                        elif body['action'] == 'history':
                            facts = sync_leagues(ws,codes=None if league=='all' else [league])
                            failed = sum(v['status']=='error' for v in facts['leagues'].values())
                            result = {'message': f"Historiques mis à jour. {failed} import(s) en échec ; consulter Couverture & sources."}
                        else:
                            raise ValueError('Opération inconnue.')
                        from .tracking import tick
                        result['tracking']=tick(ws)
                    finally:
                        operation_lock.release()
                payload = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                payload = json.dumps({'error':str(exc)}, ensure_ascii=False).encode()
                self.send_response(400)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *args):
            pass
    with ThreadingHTTPServer(('127.0.0.1', port), Handler) as server:
        from .tracking import start_worker
        stop=start_worker(ws,operation_lock)
        print(f'Dashboard : http://127.0.0.1:{port} — Ctrl+C pour arrêter.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:stop.set()
