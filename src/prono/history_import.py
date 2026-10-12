"""Import explicite des résultats de Ligue 1, avec provenance et collecte conservées."""
import csv
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from .model import load_history
from .workspace import atomic_write, timestamp, utcnow

FIELDS = ['event_id', 'kickoff', 'home', 'away', 'home_goals', 'away_goals', 'result_known_at', 'source']
NOTICE = ('Résultats connus au moment de la collecte uniquement : aucune date de disponibilité '
          'historique supposée. Ces archives ne permettent pas, seules, un backtest chronologique. '
          'Les heures du fournisseur sont interprétées en Europe/London ; les cotes du CSV ne sont pas importées.')

class CSVText(str):
    """Texte décodé sans remplacement de caractères, avec provenance des octets reçus."""
    def __new__(cls,text,encoding,raw):
        value=super().__new__(cls,text);value.source_encoding=encoding;value.source_bytes=raw;return value


def normalize_history(content, season, collected_at, division="F1", rejected=None):
    collected_at = timestamp(collected_at)
    reader = csv.DictReader(io.StringIO(content.lstrip('\ufeff')))
    required = {'Div', 'Date', 'Time', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG'}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('Colonnes Football-Data manquantes.')
    rows, seen = [], set()
    for line, raw in enumerate(reader, 2):
        if not any(raw.values()):
            continue
        if raw['Div'] != division:
            raise ValueError(f'Compétition différente de {division}.')
        if rejected is not None and not raw.get('FTHG') and not raw.get('FTAG'):
            rejected.append({'line': line, 'home': raw.get('HomeTeam'), 'away': raw.get('AwayTeam'),
                             'reason': 'Résultat non fourni : rencontre exclue, aucun score supposé.'})
            continue
        # Pas de résultat ou d'heure inventés pour compléter un fichier partiel.
        if not all(raw.get(k, '').strip() for k in required):
            raise ValueError('Résultat incomplet : date, heure, équipes et scores obligatoires.')
        local = datetime.strptime(raw['Date'] + ' ' + raw['Time'], '%d/%m/%Y %H:%M')
        kickoff = timestamp(local.replace(tzinfo=ZoneInfo('Europe/London')).isoformat())
        if kickoff >= collected_at:
            raise ValueError('Résultat daté dans le futur ou au moment de la collecte.')
        goals = [int(raw[k]) for k in ('FTHG', 'FTAG')]
        if any(g < 0 or g > 30 for g in goals):
            raise ValueError('Score invalide.')
        home, away = raw['HomeTeam'].strip(), raw['AwayTeam'].strip()
        if home == away:
            raise ValueError('Équipes identiques.')
        identity = f'{kickoff.isoformat()}|{home}|{away}'
        ident = f'fd-{division}-' + hashlib.sha256(identity.encode()).hexdigest()[:20]
        if ident in seen:
            raise ValueError('Match dupliqué dans la source.')
        seen.add(ident)
        rows.append(dict(zip(FIELDS, [ident, kickoff.isoformat(), home, away, *goals,
                                     collected_at.isoformat(), f'https://www.football-data.co.uk/mmz4281/{season}/{division}.csv'])))
    if not rows:
        raise ValueError('Source vide.')
    return rows


def fetch_csv(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = response.read(4_000_001)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError('Archives sportives indisponibles ; aucun historique remplacé.') from exc
    if len(payload) > 4_000_000:
        raise ValueError('Archive trop volumineuse.')
    try:return CSVText(payload.decode('utf-8-sig'),'utf-8-sig',payload)
    except UnicodeDecodeError:
        try:return CSVText(payload.decode('cp1252'),'windows-1252',payload)
        except UnicodeDecodeError:raise ValueError('Encodage de l’archive non reconnu ; aucun historique remplacé.') from None


def sync_history(ws, seasons):
    seasons = sorted(set(seasons))
    if not seasons or any(not re.fullmatch(r'\d{4}', s) or int(s[2:]) != (int(s[:2])+1) % 100 for s in seasons):
        raise ValueError('Saisons attendues : 2425 2526, par exemple.')
    from .leagues import division_for
    division = division_for(ws)
    from .leagues import EUROPE
    if division in EUROPE:
        from .europe import sync_europe_history
        return sync_europe_history(ws,seasons)
    existing = load_history(ws.path('data/history.csv'))
    fixtures_path = ws.path('data/fixtures.json')
    fixtures = json.loads(fixtures_path.read_text()) if fixtures_path.exists() else []
    if any(r['source'] == 'synthetic-demo' for r in existing + fixtures):
        raise ValueError('Créer un workspace réel séparé : les données synthétiques sont conservées.')
    if any(not (r['source'].startswith('https://www.football-data.co.uk/mmz4281/') and r['source'].endswith(f'/{division}.csv')) for r in existing):
        raise ValueError('Historique d’une autre source : utiliser un workspace séparé.')
    records = {r['event_id']: r for r in existing}
    sources = []
    rejected_total = 0
    for season in seasons:
        url = f'https://www.football-data.co.uk/mmz4281/{season}/{division}.csv'
        content = fetch_csv(url)
        collected = utcnow()
        # Conserver une capture brute, même si une correction impose une revue manuelle.
        digest = hashlib.sha256(content.encode()).hexdigest()
        archive = ws.path(f'data/sources/{season}-{collected.strftime("%Y%m%dT%H%M%S%f")}.csv')
        atomic_write(archive, content)
        raw_archive=None
        if getattr(content,'source_encoding',None)=='windows-1252':
            raw_archive=archive.with_suffix('.raw.csv');raw_archive.write_bytes(content.source_bytes)
        rejected = []
        incoming = normalize_history(content, season, collected.isoformat(), division, rejected)
        rejected_total += len(rejected)
        meta = {'url': url, 'collected_at': collected.isoformat(), 'sha256_utf8': digest,
                'source_timezone': 'Europe/London', 'notice': NOTICE, 'rejected': rejected}
        if isinstance(content,CSVText):meta.update(source_encoding=content.source_encoding,sha256_raw=hashlib.sha256(content.source_bytes).hexdigest(),raw_archive=raw_archive.name if raw_archive else None)
        atomic_write(archive.with_suffix('.json'), json.dumps(meta, ensure_ascii=False, indent=2))
        sources.append(meta)
        for row in incoming:
            previous = records.get(row['event_id'])
            if previous:
                if any(str(previous[k]) != str(row[k]) for k in FIELDS if k != 'result_known_at'):
                    raise ValueError('Source corrigée : capture conservée, historique non modifié. Revue manuelle requise.')
                continue  # Ne pas repousser la date de première connaissance.
            records[row['event_id']] = row
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(sorted(records.values(), key=lambda r: timestamp(r['kickoff'])))
    atomic_write(ws.path('data/history.csv'), output.getvalue())
    return {'history_rows': len(records), 'added': len(records)-len(existing), 'rejected': rejected_total, 'sources': sources, 'notice': NOTICE}


def history_status(ws):
    rows = load_history(ws.path('data/history.csv'))
    teams = sorted({r[k] for r in rows for k in ('home', 'away')})
    return {'rows': len(rows), 'teams': teams, 'sources': sorted({r['source'] for r in rows}),
            'synthetic': any(r['source'] == 'synthetic-demo' for r in rows),
            'latest_kickoff': max((r['kickoff'] for r in rows), key=timestamp, default=None),
            'notice': NOTICE if any('football-data.co.uk' in r['source'] for r in rows) else 'Historique local.'}
