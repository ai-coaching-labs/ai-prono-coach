"""xG Understat descriptifs : collecte explicite, captures immuables, lecture locale."""

import gzip
import hashlib
import io
import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from .workspace import number, timestamp, utcnow
from .identity import team_resolver
from .domestic_form import ALIASES
from .leagues import EUROPE

LEAGUES = {'F1': 'Ligue_1', 'E0': 'EPL', 'D1': 'Bundesliga', 'I1': 'Serie_A', 'SP1': 'La_liga'}
EXTRA_ALIASES = {
    'F1': {'Paris Saint Germain': 'Paris SG'},
    'E0': {'Wolverhampton Wanderers': 'Wolves', 'Nottingham Forest': "Nott'm Forest", 'Tottenham Hotspur': 'Tottenham'},
    'D1': {'RasenBallsport Leipzig': 'RB Leipzig'},
    'SP1': {'Atletico Madrid': 'Ath Madrid'},
}
MAX_BYTES = 8_000_000


def fetch_season(code, season):
    league = LEAGUES[code]
    url = f'https://understat.com/getLeagueData/{league}/{season}'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'AI-Prono-Coach/0.3.10 (personal research)',
        'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
        'Referer': f'https://understat.com/league/{league}/{season}',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Réponse Understat trop volumineuse.')
        if raw.startswith(b'\x1f\x8b'):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Réponse Understat décompressée trop volumineuse.')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get('dates'), list):
            raise ValueError('Format Understat non reconnu.')
        return payload
    except urllib.error.HTTPError as exc:
        raise ValueError(f'Understat HTTP {exc.code} : aucune nouvelle capture.') from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError('Understat indisponible ou réponse compressée invalide.') from exc


def normalize_matches(raw):
    rows, excluded = [], {}
    seen = set()
    for match in raw:
        if not isinstance(match, dict):
            raise ValueError('Rencontre Understat invalide.')
        if match.get('isResult') is not True:
            excluded['not_finished'] = excluded.get('not_finished', 0) + 1
            continue
        values = (match.get('xG') or {})
        if any(values.get(side) is None for side in ('h', 'a')):
            excluded['xg_missing'] = excluded.get('xg_missing', 0) + 1
            continue
        ident = str(match['id'])
        if not ident.isdecimal() or ident in seen:
            raise ValueError('Identifiant Understat absent ou dupliqué.')
        seen.add(ident)
        provider_time = str(match['datetime'])
        parsed = datetime.fromisoformat(provider_time)
        # Ne pas inventer le fuseau manquant : deux jours de marge pour les dates naïves.
        after = (datetime.combine(parsed.date() + timedelta(days=2), datetime.min.time(), timezone.utc)
                 if parsed.tzinfo is None else parsed.astimezone(timezone.utc))
        row = {'id': ident, 'provider_datetime': provider_time, 'match_date': parsed.date().isoformat(),
               'date_status': 'timezone_unverified' if parsed.tzinfo is None else 'verified_timezone',
               'usable_after': after.isoformat()}
        for side, key in [('h', 'home'), ('a', 'away')]:
            team = match[side]
            if not str(team.get('id', '')).isdecimal() or not isinstance(team.get('title'), str) or not team['title'].strip():
                raise ValueError('Identité de club Understat invalide.')
            if isinstance(values[side], bool) or isinstance(match['goals'][side], bool):
                raise ValueError('Valeur Understat invalide.')
            goals = number(match['goals'][side], 0, 30)
            if not goals.is_integer():
                raise ValueError('Buts Understat non entiers.')
            row[key] = {'id': str(team['id']), 'name': team['title'],
                        'goals': int(goals), 'xg': number(values[side], 0, 100)}
        if row['home']['id'] == row['away']['id']:
            raise ValueError('Équipes Understat identiques.')
        rows.append(row)
    return rows, excluded


def save_capture(ws, code, season, payload, collected_at):
    collected_at = timestamp(collected_at.isoformat())
    rows, excluded = normalize_matches(payload['dates'])
    digest = hashlib.sha256(json.dumps(payload['dates'], sort_keys=True, allow_nan=False).encode()).hexdigest()
    path = ws.path(f'data/xg/understat/{code}-{season}-{digest}.json')
    if path.exists():
        existing = json.loads(path.read_text())
        if existing.get('content_sha256') != digest:
            raise ValueError('Empreinte de capture Understat contradictoire.')
        return {'path': str(path), 'reused': True, 'matches': len(rows), 'collected_at': existing['collected_at'], 'excluded': excluded}
    capture = {'schema_version': 1, 'source': 'understat', 'division': code, 'season': season,
               'source_url': f'https://understat.com/league/{LEAGUES[code]}/{season}',
               'collected_at': collected_at.isoformat(), 'content_sha256': digest,
               'raw_matches': payload['dates'], 'matches': rows, 'excluded': excluded}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.understat-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(capture, ensure_ascii=False, allow_nan=False))
        try:
            os.link(temp, path)
        except FileExistsError:
            existing = json.loads(path.read_text())
            return {'path': str(path), 'reused': True, 'matches': len(rows), 'collected_at': existing['collected_at'], 'excluded': excluded}
    finally:
        os.unlink(temp)
    return {'path': str(path), 'reused': False, 'matches': len(rows), 'collected_at': capture['collected_at'], 'excluded': excluded}


def sync_xg(ws, codes=None, seasons=None):
    now = utcnow()
    current = now.year if now.month >= 7 else now.year - 1
    codes = list(LEAGUES) if codes is None else list(dict.fromkeys(codes))
    years = [current, current - 1] if seasons is None else list(dict.fromkeys(int(s) for s in seasons))
    if not codes or any(code not in LEAGUES for code in codes):
        raise ValueError('Understat couvre ici F1, E0, D1, I1 et SP1 uniquement.')
    if not years or any(year < 2014 or year > current for year in years):
        raise ValueError(f'Saisons Understat : années de début entre 2014 et {current}.')
    results = []
    for code in codes:
        for season in years:
            try:
                payload = fetch_season(code, season)
                result = save_capture(ws, code, season, payload, utcnow())
                results.append({'division': code, 'season': season, 'status': 'ok', **result})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                results.append({'division': code, 'season': season, 'status': 'error', 'reason': str(exc)})
    return {'source': 'understat', 'imports': results,
            'notice': 'xG descriptifs, sans modification du Poisson. Saison courante et précédente par défaut ; années antérieures sur demande. Collecte actuelle, jamais une disponibilité historique revendiquée.'}


def summary(rows, size):
    chosen = rows[:size]
    n = len(chosen)
    result = {'requested': size, 'played': n}
    for field in ['xg_for', 'xg_against', 'goals_for', 'goals_against']:
        result[field] = sum(r[field] for r in chosen)
        result[field + '_per_match'] = result[field] / n if n else None
    return result


class UnderstatForm:
    def __init__(self, ws, as_of):
        self.ws, self.as_of = ws, timestamp(as_of)
        self.issues = []
        self.resolvers, self.aliases = {}, {}
        for code in LEAGUES:
            resolve = team_resolver(ws, code)
            self.resolvers[code] = resolve
            self.aliases[code] = {resolve(a): resolve(b) for a, b in {**ALIASES.get(code, {}), **EXTRA_ALIASES.get(code, {})}.items()}
        latest, conflicts = {}, set()
        for path in ws.path('data/xg/understat').glob('*.json'):
            try:
                capture = json.loads(path.read_text())
                if not isinstance(capture, dict) or capture.get('schema_version') != 1 or capture.get('source') != 'understat' or capture['division'] not in LEAGUES:
                    raise ValueError('Contrat de capture invalide.')
                known = timestamp(capture['collected_at'])
                if known >= self.as_of:
                    continue
                digest = hashlib.sha256(json.dumps(capture['raw_matches'], sort_keys=True, allow_nan=False).encode()).hexdigest()
                if digest != capture['content_sha256'] or normalize_matches(capture['raw_matches'])[0] != capture['matches']:
                    raise ValueError('Contenu de capture Understat altéré.')
                key = (capture['division'], capture['season'])
                previous = latest.get(key)
                if previous and known == timestamp(previous['collected_at']) and capture['content_sha256'] != previous['content_sha256']:
                    conflicts.add(key)
                    raise ValueError('Captures contradictoires au même instant.')
                if previous is None or known > timestamp(previous['collected_at']):
                    latest[key] = capture
                    conflicts.discard(key)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.issues.append({'file': path.name, 'reason': str(exc)})
        self.captures = [value for key, value in latest.items() if key not in conflicts]

    def canonical(self, code, name):
        resolve = self.resolvers[code]
        value = resolve(name)
        return self.aliases[code].get(value, value)

    def team(self, name, kickoff, division):
        cutoff = min(self.as_of, timestamp(kickoff))
        base = {'available': False, 'team': name, 'as_of': cutoff.isoformat(), 'source': 'understat',
                'load_issues': self.issues,
                'notice': 'xG de tirs observés, distincts des buts attendus du Poisson. Source nationale seulement ; paramètres et probabilités du modèle inchangés.'}
        if division not in LEAGUES and division not in EUROPE:
            return {**base, 'reason': 'Compétition non couverte par cette intégration Understat.'}
        codes = [division] if division in LEAGUES else list(LEAGUES)
        found = {}
        for capture in self.captures:
            code = capture['division']
            if code not in codes or timestamp(capture['collected_at']) >= cutoff:
                continue
            target = self.canonical(code, name)
            for match in capture['matches']:
                if timestamp(match['usable_after']) >= cutoff:
                    continue
                age = (cutoff.date() - date.fromisoformat(match['match_date'])).days
                if not 0 <= age <= int(self.ws.config.get('form', {}).get('max_history_days', 180)):
                    continue
                for side, other in [('home', 'away'), ('away', 'home')]:
                    if self.canonical(code, match[side]['name']) != target:
                        continue
                    key = (code, match[side]['id'])
                    found.setdefault(key, {})[match['id']] = {
                        'source_event_id': match['id'], 'match_date': match['match_date'],
                        'provider_datetime': match['provider_datetime'], 'date_status': match['date_status'],
                        'venue': side, 'opponent': match[other]['name'],
                        'xg_for': match[side]['xg'], 'xg_against': match[other]['xg'],
                        'goals_for': match[side]['goals'], 'goals_against': match[other]['goals'],
                        'collected_at': capture['collected_at'], 'source_url': capture['source_url'],
                    }
        if len(found) != 1:
            return {**base, 'reason': 'Identité Understat ambiguë.' if found else 'Aucun xG admissible chargé pour cette équipe. Actualiser les xG explicitement.'}
        key, matches = next(iter(found.items()))
        rows = sorted(matches.values(), key=lambda r: (r['match_date'], r['source_event_id']), reverse=True)
        warnings = []
        if len(rows) < 10:
            warnings.append(f'Échantillon partiel : {len(rows)} matchs disponibles sur 10.')
        stale = (cutoff.date() - date.fromisoformat(rows[0]['match_date'])).days > int(self.ws.config.get('form', {}).get('stale_after_days', 21))
        if stale:
            warnings.append('Dernier match chargé ancien : forme actuelle à revérifier.')
        if any(r['date_status'] == 'timezone_unverified' for r in rows):
            warnings.append('Fuseau des dates Understat non établi : jour courant et veille exclus par prudence ; aucune heure de coup d’envoi inférée.')
        return {**base, 'available': True, 'division': key[0], 'stale': stale, 'warnings': warnings,
                'last5': summary(rows, 5), 'last10': summary(rows, 10),
                'home_last5': summary([r for r in rows if r['venue'] == 'home'], 5),
                'away_last5': summary([r for r in rows if r['venue'] == 'away'], 5),
                'sources': sorted({r['source_url'] for r in rows[:10]}),
                'knowledge_dates': sorted({r['collected_at'] for r in rows[:10]}),
                'matches_included': min(3, len(rows)), 'matches_newest_first': rows[:3]}
