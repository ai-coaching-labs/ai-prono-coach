"""Baseline Poisson, indépendant du LLM. Ne démontre aucun avantage de marché."""
import csv
import math
from datetime import timedelta
from .workspace import timestamp, number

OUTCOMES = ("home", "draw", "away")

def load_history(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"event_id", "kickoff", "home", "away", "home_goals", "away_goals", "result_known_at", "source"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Colonnes d'historique manquantes, voir docs/data-contract.md.")
        rows = []
        ids = set()
        for row in reader:
            if not row["event_id"] or row["event_id"] in ids:
                raise ValueError("Identifiant historique absent ou dupliqué.")
            ids.add(row["event_id"])
            kickoff = timestamp(row["kickoff"])
            known = timestamp(row["result_known_at"])
            if known <= kickoff:
                raise ValueError("Un résultat doit être connu après le coup d'envoi.")
            if not row["source"].strip() or not row["home"].strip() or not row["away"].strip() or row["home"] == row["away"]:
                raise ValueError("Équipes ou source invalides.")
            for key in ("home_goals", "away_goals"):
                n = number(row[key], 0, 30)
                if not n.is_integer():
                    raise ValueError("Nombre de buts entier requis.")
                row[key] = int(n)
            rows.append(row)
        return rows

def poisson(rate, n):
    return math.exp(-rate) * rate ** n / math.factorial(n)

def score_probabilities(lh, la, rho=0.0):
    """Même grille 0–40 ; chaque masse Poisson n'est calculée qu'une fois."""
    hp, ap = [math.exp(-lh)], [math.exp(-la)]
    for n in range(1,41):
        hp.append(hp[-1]*lh/n); ap.append(ap[-1]*la/n)
    factors = {(0,0):1-lh*la*rho,(0,1):1+lh*rho,(1,0):1+la*rho,(1,1):1-rho}
    if min(factors.values()) <= 0: raise ValueError('Correction de score invalide.')
    p = dict.fromkeys(OUTCOMES,0.0)
    for i,x in enumerate(hp):
        for j,y in enumerate(ap):
            p['home' if i>j else 'away' if j>i else 'draw'] += x*y*factors.get((i,j),1)
    total=sum(p.values())
    return {k:v/total for k,v in p.items()}

def predict(history, home, away, as_of, config):
    cutoff = timestamp(as_of) if isinstance(as_of, str) else as_of
    lower = cutoff - timedelta(days=int(config["max_history_days"]))
    rows = [r for r in history if lower <= timestamp(r["kickoff"]) < cutoff and timestamp(r["result_known_at"]) < cutoff]
    return predict_rows(rows,home,away,cutoff,config)

def predict_rows(rows, home, away, cutoff, config, half_life_days=None, correction=False):
    """Calcul sur des lignes déjà sélectionnées. Le filtre de connaissance reste dans predict."""
    home_rows = [r for r in rows if home in (r["home"], r["away"])]
    away_rows = [r for r in rows if away in (r["home"], r["away"])]
    counts = {"home": len(home_rows), "away": len(away_rows), "league": len(rows)}
    recent_cutoff=cutoff-timedelta(days=730)
    sample_period={'max_history_days':int(config['max_history_days']),'recent_days':730,
                   'home_oldest':min((r['kickoff'] for r in home_rows),key=timestamp,default=None),
                   'away_oldest':min((r['kickoff'] for r in away_rows),key=timestamp,default=None),
                   'home_latest':max((r['kickoff'] for r in home_rows),key=timestamp,default=None),
                   'away_latest':max((r['kickoff'] for r in away_rows),key=timestamp,default=None),
                   'home_recent':sum(timestamp(r['kickoff'])>=recent_cutoff for r in home_rows),
                   'away_recent':sum(timestamp(r['kickoff'])>=recent_cutoff for r in away_rows)}
    if min(len(home_rows), len(away_rows)) < int(config["min_matches_per_team"]):
        return {"available": False, "reason": "Historique insuffisant pour au moins une équipe.", "sample": counts,"sample_period":sample_period}
    weights={id(r):math.exp(-math.log(2)*(cutoff-timestamp(r['kickoff'])).total_seconds()/86400/half_life_days) if half_life_days else 1.0 for r in rows}
    weight=sum(weights.values())
    league_home = (sum(weights[id(r)]*r["home_goals"] for r in rows) + 1.4 * 10) / (weight + 10)
    league_away = (sum(weights[id(r)]*r["away_goals"] for r in rows) + 1.1 * 10) / (weight + 10)
    average = (league_home + league_away) / 2
    prior = int(config["prior_matches"])
    def strength(team, team_rows):
        scored = sum(weights[id(r)]*(r["home_goals"] if r["home"] == team else r["away_goals"]) for r in team_rows)
        conceded = sum(weights[id(r)]*(r["away_goals"] if r["home"] == team else r["home_goals"]) for r in team_rows)
        count=sum(weights[id(r)] for r in team_rows)
        return ((scored + prior * average) / (count + prior) / average,
                (conceded + prior * average) / (count + prior) / average)
    ha, hd = strength(home, home_rows)
    aa, ad = strength(away, away_rows)
    lh, la = min(8, max(.05, league_home * ha * ad)), min(8, max(.05, league_away * aa * hd))
    rho=0.0
    if correction:
        # Ajuster rho uniquement sur les scores de l'échantillon d'entraînement.
        teams={r[k] for r in rows for k in ('home','away')}
        strengths={t:strength(t,[r for r in rows if t in (r['home'],r['away'])]) for t in teams}
        low=[]
        for r in rows:
            if max(r['home_goals'],r['away_goals'])>1: continue
            h,d=strengths[r['home']];a,e=strengths[r['away']]
            x,y=min(8,max(.05,league_home*h*e)),min(8,max(.05,league_away*a*d))
            low.append((r['home_goals'],r['away_goals'],x,y,weights[id(r)]))
        best=-math.inf
        for candidate in [0]+[n/100 for n in range(-15,16) if n]:
            if min(1-lh*la*candidate,1+lh*candidate,1+la*candidate,1-candidate)<=0: continue
            score=0.0
            for i,j,x,y,w in low:
                factor={(0,0):1-x*y*candidate,(0,1):1+x*candidate,(1,0):1+y*candidate,(1,1):1-candidate}[(i,j)]
                if factor<=0:score=-math.inf;break
                score+=w*math.log(factor)
            if score>best:best,rho=score,candidate
    version='poisson-baseline-v1' if not half_life_days and not correction else 'dc-correction-research-v1' if correction else 'poisson-recency-research-v1'
    return {"available": True, "probabilities": score_probabilities(lh,la,rho),
            "expected_goals": {"home": lh, "away": la}, "sample": counts,
            "model": version, "as_of": cutoff.isoformat(),"sample_period":sample_period,
            **({'parameters':{'half_life_days':half_life_days,'rho':rho}} if version!='poisson-baseline-v1' else {}),
            "limitations": ["Modèle non calibré : aucune rentabilité démontrée.",
                            "Absences, compositions et xG non intégrés.",
                            "Indépendance des buts et forces stationnaires supposées."]+
                           (["Historique élargi : des effectifs et niveaux anciens participent au calcul."] if int(config['max_history_days'])>730 else [])}

def compare(probabilities, odds):
    prices = {k: number(odds[k], 1.000001) for k in OUTCOMES}
    implied = {k: 1 / prices[k] for k in OUTCOMES}
    overround = sum(implied.values())
    rows = []
    for k in OUTCOMES:
        p = number(probabilities[k], 0, 1)
        rows.append({"outcome": k, "odds": prices[k], "probability": p,
                     "implied_probability": implied[k], "market_probability_no_vig": implied[k] / overround,
                     "edge": p - implied[k] / overround, "expected_return_per_unit": p * prices[k] - 1})
    if abs(sum(probabilities.values()) - 1) > 1e-6:
        raise ValueError("La somme des probabilités doit être 1.")
    return {"overround": overround - 1, "outcomes": rows}
