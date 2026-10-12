"""Catalogue des divisions européennes Football-Data, un workspace par compétition."""
import json
from .workspace import Workspace, atomic_write, utcnow

def history_seasons(ws,code,now=None):
    now=now or utcnow();current=now.year if now.month>=7 else now.year-1
    years=int(ws.config.get('europe',{}).get('history_years',10)) if code in EUROPE else int(ws.config.get('domestic',{}).get('history_years',5))
    if not 1<=years<=20:raise ValueError('Profondeur historique attendue : 1 à 20 ans.')
    first=max(current-years,2021) if code=='UECL' else current-years
    return [f'{y%100:02d}{(y+1)%100:02d}' for y in range(first,current+1)]

LEAGUES = {
    'F1': ('Ligue 1', 'France', 'ligue1'), 'F2': ('Ligue 2', 'France', 'ligue2'),
    'E0': ('Premier League', 'Angleterre', 'e0'), 'E1': ('Championship', 'Angleterre', 'e1'),
    'E2': ('League One', 'Angleterre', 'e2'), 'E3': ('League Two', 'Angleterre', 'e3'),
    'EC': ('National League', 'Angleterre', 'ec'),
    'D1': ('Bundesliga', 'Allemagne', 'd1'), 'D2': ('2. Bundesliga', 'Allemagne', 'd2'),
    'I1': ('Serie A', 'Italie', 'i1'), 'I2': ('Serie B', 'Italie', 'i2'),
    'SP1': ('La Liga', 'Espagne', 'sp1'), 'SP2': ('La Liga 2', 'Espagne', 'sp2'),
    'N1': ('Eredivisie', 'Pays-Bas', 'n1'), 'B1': ('Pro League', 'Belgique', 'b1'),
    'P1': ('Primeira Liga', 'Portugal', 'p1'), 'T1': ('Süper Lig', 'Turquie', 't1'),
    'G1': ('Super League', 'Grèce', 'g1'),
    'SC0': ('Premiership', 'Écosse', 'sc0'), 'SC1': ('Championship', 'Écosse', 'sc1'),
    'SC2': ('League One', 'Écosse', 'sc2'), 'SC3': ('League Two', 'Écosse', 'sc3'),
    'UCL': ('Ligue des champions', 'Coupes d’Europe', 'ucl'),
    'UEL': ('Ligue Europa', 'Coupes d’Europe', 'uel'),
    'UECL': ('Conference League', 'Coupes d’Europe', 'uecl'),
}
EUROPE = {'UCL':'uefa.champions','UEL':'uefa.europa','UECL':'uefa.europa.conf'}


def division_for(ws):
    value = ws.config['data'].get('football_data_division')
    if value is None and ws.config['data']['sport_key'] == 'soccer_france_ligue_one':
        value = 'F1'
    if value not in LEAGUES:
        raise ValueError('Division Football-Data non configurée ou non prise en charge.')
    return value


def league_workspace(ws, code, create=False):
    if code not in LEAGUES:
        raise ValueError('Championnat inconnu.')
    root = ws.path('data/workspaces/' + LEAGUES[code][2])
    if create and not (root/'config/workspace.toml').exists():
        # Configuration locale indépendante ; aucun secret ou profil utilisateur copié.
        base = ws.path('config/workspace.toml').read_text()
        atomic_write(root/'config/workspace.toml', base)
        overrides='[data]\nfootball_data_division = '+json.dumps(code)+'\nsport_key = ""\n'
        if code in EUROPE:overrides+='\n[model]\nmax_history_days = '+str(int(ws.config.get('europe',{}).get('max_history_days',3653)))+'\n'
        atomic_write(root/'config/workspace.user.toml',overrides)
        for folder in ('journal', 'analyses', 'rapports', 'memory'):
            (root/folder).mkdir(parents=True, exist_ok=True)
    child = Workspace(root)
    # Les anciens workspaces peuvent suivre le réglage du hub sans réécriture de leurs fichiers.
    import tomllib
    user_path=root/'config/workspace.user.toml'
    overrides=tomllib.loads(user_path.read_text()) if user_path.exists() else {}
    if 'max_history_days' not in overrides.get('model',{}):
        child.config['model']['max_history_days']=int(ws.config.get('europe',{}).get('max_history_days',3653)) if code in EUROPE else int(ws.config['model']['max_history_days'])
    if division_for(child) != code:
        raise ValueError('La configuration du workspace ne correspond pas au championnat.')
    return child


def sync_leagues(ws, seasons=None, markets=False, codes=None):
    from .history_import import sync_history
    from .market_watch import sync_markets
    # Un échec de championnat est visible et n'annule pas les autres imports.
    codes = list(LEAGUES) if codes is None else codes
    if not codes or any(code not in LEAGUES for code in codes):
        raise ValueError('Championnat inconnu.')
    path = ws.path('data/league-hub.json')
    previous = json.loads(path.read_text()) if path.exists() else {}
    results = previous.get('leagues', {})
    for code in codes:
        try:
            child = league_workspace(ws, code, create=True)
            selected_seasons=history_seasons(ws,code) if seasons is None else seasons
            result = sync_history(child, selected_seasons)
            results[code] = {'status': 'ok', 'rows': result['history_rows'], 'added': result['added'],
                             'rejected': result['rejected'], 'seasons': selected_seasons, 'collected_at': utcnow().isoformat()}
        except (ValueError, OSError) as exc:
            results[code] = {'status': 'error', 'message': str(exc)}
    market_result = previous.get('markets')
    if markets:
        try:
            market_result = sync_markets(ws)
        except (ValueError, OSError) as exc:
            market_result = {'status': 'error', 'message': str(exc)}
    result = {'collected_at': utcnow().isoformat(), 'seasons': seasons,
              'leagues': results, 'markets': market_result}
    atomic_write(ws.path('data/league-hub.json'), json.dumps(result, ensure_ascii=False, indent=2))
    return result
