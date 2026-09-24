"""Numbers for the paper's localisation and dispatch tables.

Usage (repo root, venv active):
    PYTHONPATH=. python3 paper/full_eval.py --shopmind-dataset ../sm > paper/full_eval_out.json

--shopmind-dataset is a folder of compiled incident JSONs, e.g. the unzipped
shopmind_evaluation_dataset_labelfree.zip written by package_evaluation.py.

Added in the Sep 2026 review (existing output keys unchanged):
  * dispatch rows 'D' (sequential greedy = PR@budget) and 'PPO_mask'
    (same policy, visited actions masked at inference);
  * exact McNemar for PPO and PPO_mask vs C and vs D, on both datasets;
  * edge ablation: the same trained GraphSAGE scored with edges removed
    ('*_gs_noedges'), i.e. the model acting as a per-node MLP.
"""

import argparse
import dataclasses
import json
import statistics as st
import sys
from collections import defaultdict

from stable_baselines3 import PPO

from incidentmind_p1.contracts import precision_at_k
from incidentmind_p1.dispatch import PPODispatcher
from incidentmind_p1.gnn_scorer import GraphSAGEScorer
from incidentmind_p1.loader import load_dataset
from incidentmind_p1.scoring import AnomalyScorer
from incidentmind_p1.training import load_checkpoint

sys.path.insert(0, "scripts")
import evaluate_ppo as ev  # noqa: E402


class NoEdgeScorer:
    """Scores each incident with its edges removed (graph ablation)."""

    def __init__(self, base):
        self.base = base

    def score_graph(self, incident):
        return self.base.score_graph(dataclasses.replace(incident, edges=[]))


def rankeval(scorer, incs):
    by = defaultdict(list)
    for inc in incs:
        ids = [s.service_id for s in sorted(scorer.score_graph(inc), key=lambda s: s.rank)]
        r = ids.index(inc.root_cause) + 1
        row = [precision_at_k(ids, inc.root_cause, k) for k in (1, 3, 5)] + [r]
        by[inc.metadata.get("fault_type", "?")].append(row)
        by["ALL"].append(row)
    return {
        f: dict(n=len(v), pr1=st.fmean(x[0] for x in v), pr3=st.fmean(x[1] for x in v),
                pr5=st.fmean(x[2] for x in v), mttd=st.fmean(x[3] for x in v))
        for f, v in by.items()
    }


def safe(fn):
    def w(*a, **k):
        try:
            return fn(*a, **k)
        except ValueError:
            return (5, False)
    return w


def dispatch_eval(scorer, incs, ppo, ppo_mask):
    res = {}
    res["PPO"] = [ev.run_episode_ppo(ppo, scorer, i) for i in incs]
    res["PPO_mask"] = [ev.run_episode_ppo(ppo_mask, scorer, i) for i in incs]
    res["A"] = [safe(ev.run_episode_baseline_a)(scorer, i, seed=42) for i in incs]
    res["B"] = [safe(ev.run_episode_baseline_b)(scorer, i, seed=42) for i in incs]
    res["C"] = [ev.run_episode_greedy(scorer, i) for i in incs]
    res["D"] = [ev.run_episode_baseline_d(scorer, i) for i in incs]
    summ = {}
    for k, v in res.items():
        solved = [s for s, ok in v if ok]
        summ[k] = dict(solve=len(solved) / len(v), steps_solved=(st.fmean(solved) if solved else None),
                       steps_all=st.fmean(s for s, _ in v),
                       solved_at_step={n: solved.count(n) for n in sorted(set(solved))})
    pf = defaultdict(dict)
    for k, v in res.items():
        g = defaultdict(list)
        for inc, (s, ok) in zip(incs, v):
            g[inc.metadata.get("fault_type", "?")].append(ok)
        for f, l in g.items():
            pf[f][k] = sum(l) / len(l)
    mc = {}
    for x in ("PPO", "PPO_mask"):
        for y in ("C", "D"):
            x_only, y_only, p = ev.mcnemar(res[x], res[y])
            mc[f"{x}_vs_{y}"] = dict(x_only=x_only, y_only=y_only, p=p)
    nanom = [sum(1 for s in scorer.score_graph(i) if s.status == "anomalous") for i in incs]
    return summ, dict(pf), res, st.fmean(nanom), mc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shopmind-dataset", default="../sm")
    ap.add_argument("--re1-dataset", default="data/rcaeval_re1")
    ap.add_argument("--graphsage-model", default="models/graphsage.pt")
    ap.add_argument("--ppo-model", default="models/ppo_dispatch.zip")
    args = ap.parse_args()

    enc, stats = load_checkpoint(args.graphsage_model)
    gs = GraphSAGEScorer(enc, stats)
    gs_noedges = NoEdgeScorer(gs)
    zs = AnomalyScorer()
    policy = PPO.load(args.ppo_model)
    ppo = PPODispatcher(policy)
    ppo_mask = PPODispatcher(policy, mask_visited=True)
    re1 = load_dataset(args.re1_dataset)
    _, _, re1_test = ev.split_incidents(re1, 42)
    sm = load_dataset(args.shopmind_dataset)
    out = {}

    out["re1_test_gs"] = rankeval(gs, re1_test)
    out["re1_test_gs_noedges"] = rankeval(gs_noedges, re1_test)
    out["re1_test_z"] = rankeval(zs, re1_test)
    out["re1_all_z"] = rankeval(zs, re1)
    out["sm_gs"] = rankeval(gs, sm)
    out["sm_gs_noedges"] = rankeval(gs_noedges, sm)
    out["sm_z"] = rankeval(zs, sm)

    s1, p1, _r1, n1, mc1 = dispatch_eval(gs, re1_test, ppo, ppo_mask)
    out["re1_dispatch"], out["re1_dispatch_pf"], out["re1_mean_anom"], out["re1_mcnemar"] = s1, p1, n1, mc1
    s2, p2, r2, n2, mc2 = dispatch_eval(gs, sm, ppo, ppo_mask)
    out["sm_dispatch"], out["sm_dispatch_pf"], out["sm_mean_anom"], out["sm_mcnemar"] = s2, p2, n2, mc2
    # kept for continuity with the earlier draft
    out["sm_mcnemar_ppo_vs_c"] = dict(ppo_only=mc2["PPO_vs_C"]["x_only"], c_only=mc2["PPO_vs_C"]["y_only"])
    out["sm_mcnemar_p"] = mc2["PPO_vs_C"]["p"]

    out["re1_split"] = dict(n=len(re1), test=len(re1_test), test_faults={
        f: sum(1 for i in re1_test if i.metadata.get("fault_type") == f)
        for f in set(i.metadata.get("fault_type") for i in re1_test)})
    out["re1_nodes"] = sorted({len(i.nodes) for i in re1})
    out["re1_edges"] = sorted({len(i.edges) for i in re1})
    out["sm_nodes"] = [n.service_id for n in sm[0].nodes]
    out["sm_edges"] = sm[0].edges
    out["sm_edge_counts"] = sorted({len(i.edges) for i in sm})
    out["sm_faults"] = {f: sum(1 for i in sm if i.metadata.get("fault_type") == f)
                        for f in set(i.metadata.get("fault_type") for i in sm)}
    out["sm_root_cause_candidates"] = sorted({i.root_cause for i in sm})
    out["re1_root_cause_candidates"] = sorted({i.root_cause for i in re1})
    out["stats"] = dict(means=stats.means, stds=stats.stds, feats=stats.feature_names)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
