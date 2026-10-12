"""Dossiers de faits sourcés, séparés des probabilités déterministes."""
import hashlib
import json
from datetime import date
from urllib.parse import urlparse
from .analysis import fixtures
from .workspace import timestamp, utcnow, write_record

STATUSES = {'confirmed', 'reported', 'uncertain', 'contradicted'}
CATEGORIES = {'injury', 'suspension', 'lineup', 'club_news', 'schedule', 'tactics', 'market'}
SOURCE_TYPES = {'club', 'league', 'federation', 'journalist', 'media'}


def import_context(ws, payload, now=None):
    now = timestamp((now or utcnow()).isoformat())
    event_id = payload['event_id']
    known = fixtures(ws)
    from .market_watch import public_calendar
    known += public_calendar(ws)['matches']
    matches = [f for f in known if f['event_id'] == event_id]
    if len(matches) != 1:
        raise ValueError('Match absent ou ambigu dans le calendrier local.')
    fixture = matches[0]
    kickoff = timestamp(fixture['kickoff'])
    as_of = timestamp(payload['as_of'])
    if as_of > now or as_of >= kickoff or now >= kickoff:
        raise ValueError('Dossier pré-match uniquement, sans date future.')
    findings = payload['findings']
    if not isinstance(findings, list) or len(findings) > 100:
        raise ValueError('Liste de faits attendue (100 maximum).')
    clean = []
    for finding in findings:
        if finding['category'] not in CATEGORIES or finding['status'] not in STATUSES:
            raise ValueError('Catégorie ou statut du fait invalide.')
        if finding['team'] not in (fixture['home'], fixture['away'], 'match'):
            raise ValueError('Équipe étrangère au match.')
        text = finding['claim']
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError('Résumé factuel attendu, pas un article complet.')
        sources = finding['sources']
        if not isinstance(sources, list) or not sources:
            raise ValueError('Chaque fait exige une source consultée.')
        validated_sources = []
        for source in sources:
            parsed = urlparse(source['url'])
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('URL de source publique invalide.')
            if source['type'] not in SOURCE_TYPES or not str(source['title']).strip():
                raise ValueError('Type et titre de source requis.')
            checked = timestamp(source['checked_at'])
            if checked > as_of:
                raise ValueError('Source vérifiée après la date du dossier.')
            published = source.get('published_at')
            if published is not None and timestamp(published) > checked:
                raise ValueError('Publication après la vérification.')
            publication_date = source.get('publication_date')
            if publication_date is not None and date.fromisoformat(publication_date) > checked.date():
                raise ValueError('Date de publication future.')
            validated_sources.append({key: source.get(key) for key in ('url', 'title', 'type', 'checked_at', 'published_at', 'publication_date')})
        clean.append({'team': finding['team'], 'category': finding['category'], 'status': finding['status'],
                      'claim': text, 'sources': validated_sources})
    missing = payload.get('missing', [])
    if not isinstance(missing, list) or any(not isinstance(v, str) for v in missing):
        raise ValueError('Informations manquantes : liste de textes attendue.')
    result = {'event_id': event_id, 'home': fixture['home'], 'away': fixture['away'],
              'kickoff': fixture['kickoff'], 'as_of': as_of.isoformat(), 'created_at': now.isoformat(),
              'findings': clean, 'missing': missing, 'probabilities_modified': False,
              'notice': 'Contrôle de structure et de dates uniquement ; les sources doivent avoir été lues par le journaliste.'}
    digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:20]
    path = ws.path(f'analyses/context-{digest}.md')
    prose = f"## Dossier : {fixture['home']} / {fixture['away']}\n\n"
    for finding in clean:
        prose += f"- [{finding['status']}] {finding['team']} — {finding['claim']}\n"
        for source in finding['sources']:
            prose += f"  Source : {source['url']} ; vérifiée {source['checked_at']}.\n"
    prose += '\nManques : '+('; '.join(missing) or 'Non renseignés.')
    write_record(path, 'match_context', result, prose)
    return {'saved_to': str(path), **result}


def contexts(ws, event_id=None):
    rows = [r for r in ws.records('analyses') if r['kind'] == 'match_context' and (event_id is None or r['event_id'] == event_id)]
    return sorted(rows, key=lambda r: timestamp(r['as_of']), reverse=True)
