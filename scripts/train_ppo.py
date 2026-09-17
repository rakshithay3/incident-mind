"""Train the PPO dispatch policy against RE1 (Online Boutique) incidents.

NEVER pass ShopMind incidents to this script -- ShopMind is held out
entirely for post-training cross-topology generalization validation.
Training the dispatch policy on it would leak the same generalization test
we're trying to prove.

By default this also holds out the same val/test split used by
scripts/train_and_evaluate.py (60/20/20, seed=42) and trains PPO on the
60% train split ONLY -- otherwise PPO would see incidents that are supposed
to stay held out for evaluating GNN+PPO together later. Pass --split all
only if you explicitly want PPO trained on every incident in --dataset
(e.g. a throwaway smoke test).

Usage:
    PYTHONPATH=. python scripts/train_ppo.py \
        --dataset data/rcaeval_re1 \
        --timesteps 20000 \
        --output models/ppo_dispatch.zip
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor

from incidentmind_p1.loader import load_dataset
from incidentmind_p1.ppo_env import DispatchEnv
from incidentmind_p1.scoring import AnomalyScorer


def split_incidents(incidents, seed: int):
    """Same 60/20/20 split convention as scripts/train_and_evaluate.py."""
    shuffled = incidents[:]
    random.Random(seed).shuffle(shuffled)
    n = len(shuffled)
    n_train, n_val = int(n * 0.6), int(n * 0.2)
    return shuffled[:n_train], shuffled[n_train:n_train + n_val], shuffled[n_train + n_val:]


def main() -> None:
    parser = argparse.ArgumentParser(description="Train PPO dispatch policy")
    parser.add_argument("--dataset", required=True, help="RE1 training dataset directory (NEVER ShopMind)")
    parser.add_argument("--timesteps", type=int, default=20_000)
    parser.add_argument("--output", default="models/ppo_dispatch.zip")
    parser.add_argument("--seed", type=int, default=42, help="Must match train_and_evaluate.py's seed to keep the same held-out split")
    parser.add_argument(
        "--split",
        choices=["train", "all"],
        default="train",
        help="'train' (default) uses only the 60%% train split, matching GraphSAGE's held-out eval set. "
             "'all' trains on every incident in --dataset (smoke tests only).",
    )
    parser.add_argument(
        "--graphsage-model",
        default=None,
        help="Path to a GraphSAGE checkpoint from scripts/train_and_evaluate.py --save-model "
             "(e.g. models/graphsage.pt). Strongly recommended: PPO's state should be the GNN's "
             "ranked output, not the z-score fallback -- training against an untrained/absent "
             "GNN just teaches the policy to fit noise. If omitted, falls back to AnomalyScorer "
             "(peer z-score) with a warning.",
    )
    args = parser.parse_args()

    incidents = load_dataset(args.dataset)
    print(f"Loaded {len(incidents)} incidents from {args.dataset}")

    if args.graphsage_model:
        from incidentmind_p1.gnn_scorer import GraphSAGEScorer
        from incidentmind_p1.training import load_checkpoint

        encoder, stats = load_checkpoint(args.graphsage_model)
        scorer = GraphSAGEScorer(encoder, stats)
        print(f"Scoring with trained GraphSAGE checkpoint: {args.graphsage_model}")
    else:
        print("WARNING: no --graphsage-model given -- falling back to AnomalyScorer (peer z-score). "
              "This does NOT match the paper's GNN+PPO architecture; pass --graphsage-model for real runs.")
        scorer = AnomalyScorer()

    if args.split == "train":
        train_incidents, val_incidents, test_incidents = split_incidents(incidents, args.seed)
        print(f"Using 60/20/20 split (seed={args.seed}): train={len(train_incidents)} "
              f"val={len(val_incidents)} test={len(test_incidents)} -- training PPO on train split only")
        incidents = train_incidents
    else:
        print(f"--split all: training PPO on all {len(incidents)} incidents (no held-out set)")

    env = Monitor(DispatchEnv(incidents, scorer=scorer, seed=args.seed))

    model = PPO(
        "MlpPolicy",
        env,
        verbose=1,
        seed=args.seed,
        ent_coef=0.01,  # entropy bonus for exploration, per the planned design
    )
    model.learn(total_timesteps=args.timesteps)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(output_path))
    print(f"Saved trained PPO policy to {output_path}")


if __name__ == "__main__":
    main()

