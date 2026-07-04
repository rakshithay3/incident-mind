"""GraphSAGE and PPO training skeletons.

These functions are intentionally small and explicit so the team can install
PyTorch Geometric / Stable-Baselines3 later without changing data contracts.
"""

from __future__ import annotations

from typing import Iterable

from .contracts import IncidentGraph


def build_pyg_data(incident: IncidentGraph):
    """Convert an IncidentGraph to a PyTorch Geometric Data object if available."""
    try:
        import torch
        from torch_geometric.data import Data
    except ImportError as exc:
        raise RuntimeError("install torch and torch_geometric to build PyG Data objects") from exc

    service_index = {service_id: idx for idx, service_id in enumerate(incident.service_ids)}
    x = torch.tensor([node.feature_vector() for node in incident.nodes], dtype=torch.float)
    edge_index = torch.tensor(
        [[service_index[source], service_index[target]] for source, target in incident.edges],
        dtype=torch.long,
    ).t().contiguous()
    y = torch.tensor([1 if node.service_id == incident.root_cause else 0 for node in incident.nodes], dtype=torch.long)
    return Data(x=x, edge_index=edge_index, y=y, incident_id=incident.incident_id)


def graphsage_training_loop_skeleton(incidents: Iterable[IncidentGraph], epochs: int = 1) -> None:
    """Document the intended forward/loss/optimizer flow without running training."""
    incidents = list(incidents)
    if not incidents:
        raise ValueError("training requires at least one incident")
    if epochs <= 0:
        raise ValueError("epochs must be positive")
    # Real implementation:
    # 1. Convert each IncidentGraph with build_pyg_data.
    # 2. Forward pass through GraphSAGE.
    # 3. Compute node-level cross entropy against root-cause labels.
    # 4. optimizer.zero_grad(); loss.backward(); optimizer.step().
    # 5. Log PR@1/3/5 and root-cause rank per validation incident.


def ppo_training_loop_skeleton() -> None:
    """Placeholder for Stable-Baselines3 PPO environment wiring."""
    # State: ranked GNN embeddings + visited-service history.
    # Action: agent_type x target_service.
    # Reward: +1 solve, -0.1 per step, -0.5 repeated service.
    # Validation: held-out incidents, report mttd_steps and root-cause accuracy.
