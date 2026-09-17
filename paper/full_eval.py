import json, statistics as st, random, sys
from collections import defaultdict
from stable_baselines3 import PPO
from incidentmind_p1.loader import load_dataset
from incidentmind_p1.contracts import precision_at_k
from incidentmind_p1.gnn_scorer import GraphSAGEScorer
from incidentmind_p1.scoring import AnomalyScorer
from incidentmind_p1.training import load_checkpoint, build_pyg_data
from incidentmind_p1.dispatch import PPODispatcher, baseline_a, baseline_b, greedy_baseline_c
sys.path.insert(0,'scripts')
import evaluate_ppo as ev

enc, stats = load_checkpoint('models/graphsage.pt')
gs = GraphSAGEScorer(enc, stats); zs = AnomalyScorer()
ppo = PPODispatcher(PPO.load('models/ppo_dispatch.zip'))
re1 = load_dataset('data/rcaeval_re1'); _,_,re1_test = ev.split_incidents(re1, 42)
sm = load_dataset('../sm')
out = {}

def rankeval(scorer, incs, key):
    by = defaultdict(list)
    for inc in incs:
        ids = [s.service_id for s in sorted(scorer.score_graph(inc), key=lambda s: s.rank)]
        r = ids.index(inc.root_cause)+1
        row = [precision_at_k(ids, inc.root_cause, k) for k in (1,3,5)] + [r]
        by[inc.metadata.get('fault_type','?')].append(row); by['ALL'].append(row)
    return {f: dict(n=len(v), pr1=st.fmean(x[0] for x in v), pr3=st.fmean(x[1] for x in v), pr5=st.fmean(x[2] for x in v), mttd=st.fmean(x[3] for x in v)) for f,v in by.items()}

def safe(fn):
    def w(*a, **k):
        try: return fn(*a, **k)
        except ValueError: return (5, False)
    return w

def dispatch_eval(scorer, incs):
    res = {}
    res['PPO'] = [ev.run_episode_ppo(ppo, scorer, i) for i in incs]
    res['A'] = [safe(ev.run_episode_baseline_a)(scorer, i, seed=42) for i in incs]
    res['B'] = [safe(ev.run_episode_baseline_b)(scorer, i, seed=42) for i in incs]
    res['C'] = [ev.run_episode_greedy(scorer, i) for i in incs]
    summ = {}
    for k,v in res.items():
        solved=[s for s,ok in v if ok]
        summ[k]=dict(solve=len(solved)/len(v), steps_solved=(st.fmean(solved) if solved else None), steps_all=st.fmean(s for s,_ in v))
    # per fault
    pf = defaultdict(dict)
    for k,v in res.items():
        g=defaultdict(list)
        for inc,(s,ok) in zip(incs,v): g[inc.metadata.get('fault_type','?')].append(ok)
        for f,l in g.items(): pf[f][k]=sum(l)/len(l)
    # anomalous count
    nanom=[sum(1 for s in scorer.score_graph(i) if s.status=='anomalous') for i in incs]
    return summ, dict(pf), res, st.fmean(nanom)

out['re1_test_gs']=rankeval(gs, re1_test, 're1')
out['re1_test_z']=rankeval(zs, re1_test, 're1')
out['re1_all_z']=rankeval(zs, re1, 're1')
out['sm_gs']=rankeval(gs, sm, 'sm')
out['sm_z']=rankeval(zs, sm, 'sm')
s1,p1,r1,n1=dispatch_eval(gs, re1_test); out['re1_dispatch']=s1; out['re1_dispatch_pf']=p1; out['re1_mean_anom']=n1
s2,p2,r2,n2=dispatch_eval(gs, sm); out['sm_dispatch']=s2; out['sm_dispatch_pf']=p2; out['sm_mean_anom']=n2
# paired: PPO vs C on SM (McNemar)
b=sum(1 for (x,y) in zip(r2['PPO'],r2['C']) if x[1] and not y[1]); c=sum(1 for (x,y) in zip(r2['PPO'],r2['C']) if y[1] and not x[1])
out['sm_mcnemar_ppo_vs_c']=dict(ppo_only=b, c_only=c)
from scipy.stats import binomtest
out['sm_mcnemar_p']=binomtest(b, b+c, 0.5).pvalue if b+c else None
# RE1 composition
out['re1_split']=dict(n=len(re1), test=len(re1_test), test_faults={f:sum(1 for i in re1_test if i.metadata.get('fault_type')==f) for f in set(i.metadata.get('fault_type') for i in re1_test)})
out['re1_nodes']=sorted({len(i.nodes) for i in re1}); out['re1_edges']=sorted({len(i.edges) for i in re1})
out['sm_nodes']=[n.service_id for n in sm[0].nodes]; out['sm_edges']=sm[0].edges
out['sm_faults']={f:sum(1 for i in sm if i.metadata.get('fault_type')==f) for f in set(i.metadata.get('fault_type') for i in sm)}
out['stats']=dict(means=stats.means, stds=stats.stds, feats=stats.feature_names)
print(json.dumps(out, indent=1, default=str))
