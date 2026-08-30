"""Train the PPO dispatch policy against RE1 (Online Boutique) incidents.

NEVER pass ShopMind incidents to this script -- ShopMind is held out
entirely for post-training cross-topology generalization validation.
Training the dispatch policy on it would leak the same generalization test
we're trying to prove.

Usage:
    PYTHONPATH=. python scripts/train_ppo.py \
        --dataset data/sample_rcaeval \
        --timesteps 20000 \
        --output models/ppo_dispatch.zip
"""

from __future__ import annotations

import argparse
from pathlib import Path

from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor

from incidentmind_p1.loader import load_dataset
from incidentmind_p1.ppo_env import DispatchEnv
from incidentmind_p1.scoring import AnomalyScorer


def main() -> None:
    parser = argparse.ArgumentParser(description="Train PPO dispatch policy")
    parser.add_argument("--dataset", required=True, help="RE1 training dataset directory (NEVER ShopMind)")
    parser.add_argument("--timesteps", type=int, default=20_000)
    parser.add_argument("--output", default="models/ppo_dispatch.zip")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    incidents = load_dataset(args.dataset)
    print(f"Loaded {len(incidents)} training incidents from {args.dataset}")

    scorer = AnomalyScorer()
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
