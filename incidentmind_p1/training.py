"""GraphSAGE model and PPO training wiring.

GraphSAGE is chosen over GCN specifically because it is inductive: it learns
a per-node aggregation function rather than a fixed adjacency-conditioned
transform, so a model trained on RCAEval (Online Boutique) graphs can run
inference on an unseen ShopMind topology without retraining. That inductive
generalization is the paper's core novelty claim, so this module must never
be trained on ShopMind -- ShopMind is validation-only.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from .contracts import FEATURES, IncidentGraph


@dataclass
class FeatureStats:
    """Per-feature mean/std fitted on the TRAINING split only.

    RCAEval's raw features span wildly different scales (error_rate ~0.01-0.3
    vs p99_latency in the hundreds/thousands). Feeding that straight into
    SAGEConv produces logits in the tens/hundreds, which saturates the
    classifier and stalls Adam -- observed as loss frozen at ln(2) with
    every node predicted 50/50 regardless of input. Z-normalizing fixes it.

    Must be fit on training incidents and reused (not refit) at inference
    time on ShopMind/held-out incidents, exactly like you'd persist a
    scaler.pkl alongside a trained sklearn/torch model.
    """

    means: Tuple[float, ...]
    stds: Tuple[float, ...]
    feature_names: Tuple[str, ...] = FEATURES

    @classmethod
    def fit(cls, incidents: Iterable[IncidentGraph], feature_names=FEATURES) -> "FeatureStats":
        columns = {name: [] for name in feature_names}
        for incident in incidents:
            for node in incident.nodes:
                for name, value in zip(feature_names, node.feature_vector(feature_names)):
                    columns[name].append(value)
        means = tuple(statistics.fmean(values) for values in columns.values())
        stds = tuple((statistics.pstdev(values) or 1.0) if len(values) > 1 else 1.0 for values in columns.values())
        return cls(means=means, stds=stds, feature_names=tuple(feature_names))

    def transform(self, vector: Iterable[float]) -> List[float]:
        return [(v - m) / s for v, m, s in zip(vector, self.means, self.stds)]


def build_pyg_data(incident: IncidentGraph, stats: Optional[FeatureStats] = None):
    """Convert an IncidentGraph to a PyTorch Geometric Data object.

    Pass the FeatureStats fitted on the training split so features are
    normalized consistently between training and inference (including on
    unseen ShopMind topologies).
    """
    try:
        import torch
        from torch_geometric.data import Data
    except ImportError as exc:
        raise RuntimeError("install torch and torch_geometric to build PyG Data objects") from exc

    service_index = {service_id: idx for idx, service_id in enumerate(incident.service_ids)}
    raw_vectors = [node.feature_vector(FEATURES) for node in incident.nodes]
    if stats is not None:
        raw_vectors = [stats.transform(vector) for vector in raw_vectors]
    x = torch.tensor(raw_vectors, dtype=torch.float)

    # GraphSAGE needs edges in both directions -- anomaly signal must be able
    # to propagate from a root-cause node to its downstream victims AND from
    # a victim back toward its upstream cause, since at inference time we
    # don't know which direction the fault is flowing in yet.
    src, dst = [], []
    for source, target in incident.edges:
        src.append(service_index[source])
        dst.append(service_index[target])
        src.append(service_index[target])
        dst.append(service_index[source])
    edge_index = torch.tensor([src, dst], dtype=torch.long) if src else torch.zeros((2, 0), dtype=torch.long)

    y = torch.tensor(
        [1 if node.service_id == incident.root_cause else 0 for node in incident.nodes],
        dtype=torch.long,
    )
    return Data(x=x, edge_index=edge_index, y=y, incident_id=incident.incident_id)


class GraphSAGEEncoder:
    """3-layer GraphSAGE anomaly localizer.

    Lazily built on first use so importing this module never requires torch
    to be installed (mirrors build_pyg_data's ImportError pattern).
    Architecture: 5-dim input (cpu, memory, latency, error_rate, p99_latency)
    -> 64 -> 64 -> 128-dim node embedding -> 2-class root-cause logit head.
    """

    def __init__(self, in_channels: int = len(FEATURES), hidden_channels: int = 64, out_channels: int = 128):
        try:
            import torch.nn as nn
            from torch_geometric.nn import SAGEConv
        except ImportError as exc:
            raise RuntimeError("install torch and torch_geometric to build GraphSAGEEncoder") from exc

        class _Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.conv1 = SAGEConv(in_channels, hidden_channels)
                self.conv2 = SAGEConv(hidden_channels, hidden_channels)
                self.conv3 = SAGEConv(hidden_channels, out_channels)
                self.classifier = nn.Linear(out_channels, 2)  # [normal, root_cause]
                self.relu = nn.ReLU()
                self.dropout = nn.Dropout(0.2)

            def forward(self, x, edge_index):
                h = self.relu(self.conv1(x, edge_index))
                h = self.dropout(h)
                h = self.relu(self.conv2(h, edge_index))
                embedding = self.conv3(h, edge_index)
                logits = self.classifier(embedding)
                return embedding, logits

        self.model = _Net()

    def parameters(self):
        return self.model.parameters()

    def forward(self, x, edge_index):
        return self.model(x, edge_index)

    def train(self):
        self.model.train()

    def eval(self):
        self.model.eval()


@dataclass
class EpochResult:
    epoch: int
    loss: float


def train_graphsage(
    incidents: Iterable[IncidentGraph],
    encoder: Optional[GraphSAGEEncoder] = None,
    epochs: int = 50,
    lr: float = 0.01,
    stats: Optional[FeatureStats] = None,
) -> Tuple["GraphSAGEEncoder", List[EpochResult], FeatureStats]:
    """Train GraphSAGE for node-level root-cause classification.

    incidents must ALL be from the training split (RCAEval Online Boutique).
    Never pass ShopMind incidents here -- ShopMind is the held-out
    generalization test for the inductive-learning claim.

    Returns (encoder, loss_history, feature_stats). Persist feature_stats
    alongside the model checkpoint and reuse it (never refit) when scoring
    held-out RCAEval incidents or ShopMind.
    """
    try:
        import torch
        import torch.nn.functional as F
    except ImportError as exc:
        raise RuntimeError("install torch and torch_geometric to train GraphSAGE") from exc

    incidents = list(incidents)
    if not incidents:
        raise ValueError("training requires at least one incident")
    if epochs <= 0:
        raise ValueError("epochs must be positive")

    stats = stats or FeatureStats.fit(incidents)
    encoder = encoder or GraphSAGEEncoder()
    optimizer = torch.optim.Adam(encoder.parameters(), lr=lr)
    graphs = [build_pyg_data(incident, stats=stats) for incident in incidents]

    history: List[EpochResult] = []
    encoder.train()
    for epoch in range(1, epochs + 1):
        epoch_loss = 0.0
        for graph in graphs:
            optimizer.zero_grad()
            _, logits = encoder.forward(graph.x, graph.edge_index)
            # Root-cause node is a tiny minority class (1 of N per graph) --
            # weight it up so the model doesn't collapse to "predict normal
            # for everything" and still score ~100% accuracy.
            num_nodes = graph.y.size(0)
            weight = torch.tensor([1.0, max(1.0, float(num_nodes - 1))])
            loss = F.cross_entropy(logits, graph.y, weight=weight)
            loss.backward()
            optimizer.step()
            epoch_loss += float(loss.item())
        history.append(EpochResult(epoch=epoch, loss=epoch_loss / len(graphs)))
    encoder.eval()
    return encoder, history, stats


def score_incident(
    encoder: GraphSAGEEncoder, incident: IncidentGraph, stats: Optional[FeatureStats] = None
) -> List[Tuple[str, float]]:
    """Return (service_id, root_cause_probability) ranked descending.

    Pass the SAME FeatureStats returned by train_graphsage -- refitting
    stats on the incident being scored (especially a single ShopMind
    snapshot) reintroduces the same silent-bug pattern as the old
    self-referential baseline in scoring.py.
    """
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("install torch and torch_geometric to score with GraphSAGE") from exc

    graph = build_pyg_data(incident, stats=stats)
    encoder.eval()
    with torch.no_grad():
        _, logits = encoder.forward(graph.x, graph.edge_index)
        probs = torch.softmax(logits, dim=1)[:, 1]  # P(root_cause)
    scored = list(zip(incident.service_ids, (float(p) for p in probs)))
    return sorted(scored, key=lambda item: item[1], reverse=True)


def ppo_training_loop_skeleton() -> None:
    """Placeholder for Stable-Baselines3 PPO environment wiring.

    Deferred until score_incident() above is producing real (non-random)
    rankings on held-out RCAEval incidents -- PPO's state is the GNN's
    ranked embeddings, so training it against an untrained GNN just teaches
    the policy to fit noise.

    Planned shape:
      State:  ranked GraphSAGE embeddings (N x 128) + visited-service
              one-hot history.
      Action: agent_type (log/metrics/code) x target_service, discrete.
      Reward: +1.0 solve, -0.1/step, -0.5 repeated service.
      Algo:   PPO (Stable-Baselines3), clipped surrogate objective, entropy
              bonus for exploration. Chosen over DQN/A2C for stability in
              the low-data regime (500 simulated incidents).
      Validation: held-out incidents, report mttd_steps + root-cause
              accuracy via evaluation.evaluate_ranking.
    """
