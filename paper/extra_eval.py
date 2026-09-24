import json, random, statistics as st
from incidentmind_p1.loader import load_dataset
from incidentmind_p1.gnn_scorer import GraphSAGEScorer
from incidentmind_p1.training import load_checkpoint
from priority.impact_weights import PriorityWeightedScorer
import sys; sys.path.insert(0,'scripts'); import evaluate_ppo as ev
enc, stats = load_checkpoint('models/graphsage.pt'); gs=GraphSAGEScorer(enc,stats); pw=PriorityWeightedScorer(gs)
sm_path=sys.argv[1] if len(sys.argv)>1 else '../sm'  # usage: python3 paper/extra_eval.py <compiled ShopMind dir>
sm=load_dataset(sm_path); re1=load_dataset('data/rcaeval_re1'); _,_,t=ev.split_incidents(re1,42)
def hits(sc, incs, k):
    return [1 if inc.root_cause in [s.service_id for s in sorted(sc.score_graph(inc), key=lambda s:s.rank)][:k] else 0 for inc in incs]
def ci(x, B=10000):
    rng=random.Random(0); n=len(x); m=[sum(rng.choice(x) for _ in range(n))/n for _ in range(B)]; m.sort(); return (m[int(.025*B)], m[int(.975*B)])
out={}
for name,sc,incs in [('sm_gs',gs,sm),('sm_pw',pw,sm),('re1_gs',gs,t)]:
    out[name]={k:(sum(hits(sc,incs,k))/len(incs), ci(hits(sc,incs,k))) for k in (1,3,5)}
# app-service-only random baseline: 7 candidates
out['sm_candidates']=sorted({i.root_cause for i in sm})
# random PR@k against all nodes vs only services that are ever a root cause
for name, incs in (('sm', sm), ('re1', t)):
    n_nodes=len(incs[0].nodes); n_cand=len({i.root_cause for i in (sm if name=='sm' else re1)})
    out[f'{name}_random']={f'all_nodes_pr{k}':min(k,n_nodes)/n_nodes for k in (1,3,5)} | {f'candidates_pr{k}':min(k,n_cand)/n_cand for k in (1,3,5)}
print(json.dumps(out,indent=1))
