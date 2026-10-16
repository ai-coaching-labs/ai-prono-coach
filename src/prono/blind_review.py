"""Consultation aveugle aux sorties Poisson ; rapprochement déterministe après verdict."""
import copy
import json
import math
import re

from .workspace import timestamp

MATCH_FIELDS = {'match', 'kickoff', 'event_id', 'division', 'sample', 'sample_period',
                'domestic_form', 'understat_xg', 'odds', 'bookmaker', 'offers', 'source',
                'collected_at', 'quoted_at', 'synthetic'}
ROOT_FIELDS = {'as_of', 'period', 'context', 'paper_aggregates', 'paper_limits',
               'expired_match_ids', 'agent_reviews', 'agent_runs'}
BLOCKED = {'model', 'model_pick', 'probabilities', 'expected_goals', 'forecast_details',
           'comparison', 'selection', 'model_evaluation', 'forecast', 'forecasts',
           'outcome', 'edge', 'expected_value', 'ev', 'predictions', 'prediction'}


def _without_forecasts(value):
    if isinstance(value, dict):
        return {k: _without_forecasts(v) for k, v in value.items() if k not in BLOCKED}
    if isinstance(value, list):
        return [_without_forecasts(v) for v in value]
    return value


def blind_context(context):
    result = {k: copy.deepcopy(v) for k, v in context.items() if k in ROOT_FIELDS}
    result['matches'] = [{k: copy.deepcopy(v) for k, v in row.items() if k in MATCH_FIELDS}
                         for row in context.get('matches', [])]
    result['matches'].sort(key=lambda row: (row.get('kickoff', ''), row.get('event_id', '')))
    return _without_forecasts(result)


def blind_system(context, provider, web=False):
    tools = ('Recherche les nouvelles publiques avec WebSearch/WebFetch, lis les sources et donne leurs URL et dates. '
             if provider == 'claude' and web else 'Tu ne disposes pas d’outils web pour cette intervention. ')
    return ('Tu es AI Prono Coach. Réponds en français sur les seuls faits fournis.\n'
            + json.dumps(blind_context(context), ensure_ascii=False) + '\n'
            'CONSULTATION AVEUGLE : aucun rôle, y compris le coach, ne reçoit les prédictions Poisson. '
            'Évalue le match à partir des résultats observés, forme, domicile/extérieur, buts, xG observés, '
            'effectifs, sources et cotes disponibles. Ces statistiques descriptives ne sont pas des prévisions. '
            'Ignore les anciennes consignes de rôle qui demandent de lire, soutenir ou contredire le choix du modèle. '
            'Ne cherche pas à reconstituer ses prédictions depuis le classement ou les critères de sélection. '
            'Aucune probabilité, score Python, BTTS Python, espérance ou avantage calculé ne doit être deviné. '
            'Les cotes sont des informations de marché, pas une preuve d’avantage. '
            'Un historique limité du modèle ne suffit pas à interdire ton avis qualitatif : juge la couverture factuelle. '
            'Ne crée pas de pourcentage ni de note numérique de confiance. '
            'Les faits et sources manquants restent indisponibles. Un match déjà commencé impose une abstention pré-match. '
            'Mode fictif uniquement ; aucune mise réelle ni augmentation après une perte. '
            'Ne lance aucun agent, commande, appel sportif ou écriture. ' + tools)


COACH_VERDICT = '''
Tranche à partir des avis reçus et des faits sportifs. Tu ne connais pas le résultat du moteur statistique.
L’application ajoutera elle-même la comparaison APRÈS ta réponse : ne fournis aucun champ de prévision Python.
Réponds uniquement avec un objet JSON de cette forme :
{"verdicts":[{"event_id":"identifiant reçu", "outcome":"home|draw|away|abstain", "score":[2,1],
"confidence":"faible|modérée|élevée", "reason":"raison décisive avec [source](https://...) si disponible",
"reserve":"limite précise et informations manquantes"}], "notice":"réserve commune courte"}
Un verdict par match du périmètre. outcome : home=victoire domicile, draw=nul, away=victoire extérieure,
abstain=abstention motivée si les faits sportifs eux-mêmes ne permettent pas de trancher.
Donne le score envisagé LLM comme hypothèse qualitative compatible avec l’issue, jamais comme le plus probable.
Ce scénario peut être proposé sans calcul Python. S’il n’est pas raisonnablement étayé, score=null.
Pour abstain, score=null et confidence=null. N’invente jamais de probabilité de réussite du score.
La confiance porte sur le pronostic 1N2, pas sur ce score exact. Justifie-la avec la raison et la réserve.
Ne donne pas une confiance élevée si un spécialiste essentiel échoue ou si des faits déterminants manquent
ou se contredisent. Des avis concordants ne sont pas des preuves indépendantes.
Respecte expired_match_ids. 90 mots maximum par match et 60 mots communs, sauf détail explicitement demandé.
'''


def _cell(value):
    return str(value).replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def _probability(value):
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1


def _python_pick(row):
    pick = row.get('model_pick')
    probs = row.get('probabilities') or {}
    if pick not in ('home', 'draw', 'away') or not _probability(probs.get(pick)):
        return 'Indisponible'
    return {'home': '1', 'draw': 'N', 'away': '2'}[pick] + f" ({probs[pick]*100:.1f} %)"


def _btts(row):
    btts = (row.get('forecast_details') or {}).get('both_teams_score')
    if not isinstance(btts, dict):
        return 'Indisponible'
    pick = btts.get('pick')
    if pick is None:
        return 'Indécis'
    if pick not in ('yes', 'no') or not _probability(btts.get(pick)):
        return 'Indisponible'
    return ('Oui' if pick == 'yes' else 'Non') + f" ({btts[pick]*100:.1f} %)"


def render_verdict(raw, context, now):
    """Validate the independent response, then reveal Python without another LLM call."""
    errors = []
    try:
        payload = raw.strip()
        if payload.startswith('```'):
            payload = re.sub(r'^```(?:json)?\s*|\s*```$', '', payload)
        payload = json.loads(payload)
        if not isinstance(payload, dict) or not isinstance(payload.get('verdicts'), list):
            raise ValueError('Structure de verdict invalide.')
        rows = payload['verdicts']
        incoming = {}
        for row in rows:
            if not isinstance(row, dict) or row.get('event_id') in incoming or not isinstance(row.get('event_id'), str):
                raise ValueError('Identifiants de verdict invalides.')
            incoming[row['event_id']] = row
        expected = {row['event_id'] for row in context.get('matches', [])}
        if set(incoming) != expected:
            raise ValueError('Le périmètre du verdict ne correspond pas aux matchs consultés.')
    except (ValueError, TypeError, AttributeError) as exc:
        incoming, payload = {}, {}
        errors.append(str(exc))
    lines = ['## Verdict', '', '| Match | Choix Python et probabilité | Pronostic final LLM | Score envisagé LLM | BTTS Python | Confiance LLM |',
             '|---|---|---|---|---|---|']
    verdicts, explanations = [], []
    for match in context.get('matches', []):
        item = incoming.get(match['event_id'], {})
        outcome = item.get('outcome')
        expired = timestamp(match['kickoff']) <= now
        reason = item.get('reason') if isinstance(item.get('reason'), str) else ''
        reserve = item.get('reserve') if isinstance(item.get('reserve'), str) else ''
        if outcome not in ('home', 'draw', 'away', 'abstain') or not reason or not reserve:
            outcome = None
            if item:
                errors.append('Verdict incomplet : ' + match['event_id'])
        if expired:
            outcome, reason = 'abstain', 'Match déjà commencé : aucun pronostic pré-match actif.'
        confidence = item.get('confidence') if item.get('confidence') in ('faible', 'modérée', 'élevée') else None
        essential_failed = any(r.get('role') in ('sports-journalist', 'match-analyst') and r.get('status') == 'error'
                               for r in context.get('agent_reviews', []))
        if confidence == 'élevée' and essential_failed:
            confidence = None
            errors.append('Confiance élevée non justifiée après échec d’un spécialiste essentiel.')
        score = item.get('score')
        if outcome not in ('home', 'draw', 'away'):
            confidence, score = None, None
        elif confidence is None:
            errors.append('Confiance qualitative absente ou invalide : ' + match['event_id'])
        if score is not None:
            valid = isinstance(score, list) and len(score) == 2 and all(type(n) is int and 0 <= n <= 15 for n in score)
            if valid:
                actual = 'home' if score[0] > score[1] else 'away' if score[1] > score[0] else 'draw'
                valid = actual == outcome
            if not valid:
                score = None
                errors.append('Score LLM incompatible ou invalide : ' + match['event_id'])
        comparison = ('abstention' if outcome == 'abstain' else 'unavailable')
        if outcome in ('home', 'draw', 'away') and _python_pick(match) != 'Indisponible':
            comparison = 'agreement' if outcome == match['model_pick'] else 'disagreement'
        label = {'home': '1 · Domicile', 'draw': 'N · Nul', 'away': '2 · Extérieur', 'abstain': 'Abstention', None: 'Verdict non exploitable'}[outcome]
        if comparison in ('agreement', 'disagreement'):
            label += ' · ' + ('accord' if comparison == 'agreement' else 'désaccord') + ' avec Python'
        btts = (match.get('forecast_details') or {}).get('both_teams_score') or {}
        if score and btts.get('pick') in ('yes', 'no'):
            qualitative_btts = 'yes' if score[0] > 0 and score[1] > 0 else 'no'
            if qualitative_btts != btts['pick']:
                reserve += ' Le score LLM et le choix BTTS Python divergent.'
        confidence_label = 'sans objet' if outcome == 'abstain' else confidence or 'indisponible'
        values = [match['match'], _python_pick(match), label,
                  f'{score[0]}-{score[1]}' if score else '—' if outcome == 'abstain' else 'Indéterminé',
                  '—' if outcome == 'abstain' else _btts(match), confidence_label]
        lines.append('| ' + ' | '.join(_cell(v) for v in values) + ' |')
        verdicts.append({'event_id': match['event_id'], 'outcome': outcome, 'score': score,
                         'confidence': confidence, 'reason': reason, 'reserve': reserve, 'comparison': comparison})
        if reason or reserve:
            explanations.append(f"**{_cell(match['match'])}** — **Raison :** {reason}\n\n**Réserve :** {reserve}")
    lines.extend(['', *['\n\n'.join(explanations)]])
    notice = payload.get('notice')
    if isinstance(notice, str) and notice.strip():
        lines.extend(['', notice])
    if errors:
        lines.extend(['', 'Certains champs du verdict LLM n’ont pas pu être validés ; ils restent indisponibles. Aucun nouvel appel IA n’a été lancé.'])
    lines.extend(['', 'Avis LLM formulés sans les prévisions Poisson. Comparaison ajoutée ensuite par l’application. Confiance sur le 1N2 ; score LLM hypothétique et BTTS Python exploratoire. Mode fictif uniquement.'])
    return '\n'.join(lines), verdicts, errors
