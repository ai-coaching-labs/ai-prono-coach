"""Lecture locale des consultations archivées, sans appel au modèle ni recalcul."""
from datetime import datetime, timezone
import re

from .workspace import read_record, timestamp

RUN_ID = re.compile(r'[a-f0-9]{32}')


def _record(ws, run_id):
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError('Identifiant de consultation invalide.')
    path = ws.path('analyses/team-' + run_id + '.md')
    if not path.is_file() or path.is_symlink():
        raise ValueError('Consultation archivée introuvable.')
    record = read_record(path)
    if not isinstance(record, dict) or record.get('kind') != 'team_review' or record.get('run_id') != run_id:
        raise ValueError('Trace de consultation invalide.')
    if record.get('status') not in ('completed', 'error') or not isinstance(record.get('scope'), list):
        raise ValueError('Consultation archivée incomplète.')
    if any(not isinstance(row, dict) or not isinstance(row.get('match'), str) for row in record['scope']):
        raise ValueError('Matchs archivés invalides.')
    if not isinstance(record.get('facts', {}), dict) or not isinstance(record.get('reviews', []), list):
        raise ValueError('Avis archivés invalides.')
    if record['status'] == 'completed' and not isinstance(record.get('answer'), str):
        raise ValueError('Verdict archivé indisponible.')
    return record


def _metadata(record):
    date = record.get('created_at')
    if date:
        date = timestamp(date).isoformat()
    return {'run_id': record['run_id'], 'created_at': date,
            'provider': record.get('provider'), 'model': record.get('model'),
            'status': record['status'], 'scope': record['scope'],
            'question': record.get('question', '')}


def list_reviews(ws, query='', offset=0, limit=5):
    if not isinstance(query, str) or len(query) > 200 or not 0 <= offset <= 100000 or not 1 <= limit <= 50:
        raise ValueError('Recherche ou pagination invalide.')
    rows, skipped = [], 0
    for path in ws.path('analyses').glob('team-*.md'):
        run_id = path.stem.removeprefix('team-')
        if not RUN_ID.fullmatch(run_id):
            continue
        try:
            row = _metadata(_record(ws, run_id))
            labels = [r.get('match', '') for r in row['scope'] if isinstance(r, dict)]
            if query.strip().casefold() not in ' '.join(labels).casefold():
                continue
            rows.append(row)
        except (ValueError, OSError, TypeError):
            skipped += 1
    earliest = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda r: (timestamp(r['created_at']) if r['created_at'] else earliest, r['run_id']), reverse=True)
    return {'analyses': rows[offset:offset+limit], 'total': len(rows), 'offset': offset,
            'limit': limit, 'skipped': skipped}


def archived_review(ws, run_id):
    record = _record(ws, run_id)
    result = {**_metadata(record), 'reviews': record.get('reviews', []),
              'selection': record.get('facts', {}).get('selection'), 'archived': True}
    if record['status'] == 'completed':
        result['result'] = {'answer': record['answer'], 'model': record.get('model'),
                            'run_id': run_id, 'stats': record.get('stats', {})}
    else:
        result['error'] = record.get('error', 'Analyse interrompue.')
    return result
