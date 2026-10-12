import csv
import io
import json
import random
from datetime import timedelta
from .workspace import utcnow, atomic_write

def seed(ws):
    if ws.path("data/history.csv").exists() or ws.path("data/fixtures.json").exists() or ws.records("journal"):
        raise ValueError("Démo refusée : workspace déjà rempli. Utiliser un workspace séparé pour conserver vos données.")
    now = utcnow()
    teams = ["Lille Démo", "Lens Démo", "Paris Démo", "Lyon Démo", "Nice Démo", "Rennes Démo"]
    rng = random.Random(42)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["event_id", "kickoff", "home", "away", "home_goals", "away_goals", "result_known_at", "source"])
    n = 0
    for day in range(100, 9, -3):
        for i in range(0, 6, 2):
            a, b = rng.sample(teams, 2)
            kick = now - timedelta(days=day)
            writer.writerow([f"synthetic-{n}", kick.isoformat(), a, b, rng.randrange(4), rng.randrange(3), (kick+timedelta(hours=3)).isoformat(), "synthetic-demo"])
            n += 1
    atomic_write(ws.path("data/history.csv"), stream.getvalue())
    rows = [{"event_id": f"demo-{i+1}", "kickoff": (now+timedelta(days=i+1)).isoformat(),
             "home": teams[i*2], "away": teams[i*2+1], "quoted_at": now.isoformat(),
             "source": "synthetic-demo", "bookmaker": "fictional-bookmaker",
             "odds": {"home": 2.1+i*.2, "draw": 3.4, "away": 3.3-i*.2}} for i in range(3)]
    atomic_write(ws.path("data/fixtures.json"), json.dumps(rows, ensure_ascii=False, indent=2))
    return {"history_matches": n, "fixtures": len(rows), "notice": "Tout est inventé. Démo technique, aucune performance prédictive réelle."}
