"""Scores probabilistes et calibration descriptive, calculés sans modèle de langage."""
import math
from .model import OUTCOMES
from .workspace import number

def score(probabilities, actual):
    if actual not in OUTCOMES:raise ValueError('Résultat 1N2 invalide.')
    p={k:number(probabilities[k],0,1) for k in OUTCOMES}
    if abs(sum(p.values())-1)>1e-6:raise ValueError('Probabilités non normalisées.')
    return {'brier':sum((p[k]-(k==actual))**2 for k in OUTCOMES),
            'log_loss':-math.log(max(p[actual],1e-15))}

def performance(rows):
    if not rows:return {'evaluated':0,'brier':None,'log_loss':None,'accuracy':None,'calibration':[]}
    scores=[score(r['probabilities'],r['actual']) for r in rows]
    bins=[]
    for outcome in OUTCOMES:
        for b in range(5):
            selected=[r for r in rows if min(4,int(r['probabilities'][outcome]*5))==b]
            if selected:
                bins.append({'outcome':outcome,'lower':b/5,'upper':(b+1)/5,'count':len(selected),
                             'mean_probability':sum(r['probabilities'][outcome] for r in selected)/len(selected),
                             'observed_frequency':sum(r['actual']==outcome for r in selected)/len(selected)})
    return {'evaluated':len(rows),'brier':sum(s['brier'] for s in scores)/len(rows),
            'log_loss':sum(s['log_loss'] for s in scores)/len(rows),
            'accuracy':sum(max(r['probabilities'],key=r['probabilities'].get)==r['actual'] for r in rows)/len(rows),
            'calibration':bins,'notice':'Calibration descriptive ; petits groupes instables, aucune probabilité corrigée automatiquement.'}
