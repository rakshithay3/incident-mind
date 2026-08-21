"""RCAEval data loading utilities.

The loader accepts either a single incident JSON file or a dataset directory with
an `incidents/` folder. It validates node and edge counts so P1 can confirm the
RCAEval export matches expectations before training.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from .contracts import FEATURES, IncidentGraph, ServiceNode


def load_incident(path: str | Path) -> IncidentGraph:
    path = Path(path)
    if path.suffix.lower() == ".json":
        return _load_incident_json(path)
    if path.suffix.lower() == ".csv":
        return _load_incident_csv(path)
    raise ValueError(f"unsupported RCAEval incident format: {path.suffix}")


def load_dataset(path: str | Path) -> List[IncidentGraph]:
    root = Path(path)
    incident_dir = root / "incidents"
    search_dir = incident_dir if incident_dir.exists() else root
    incidents = [load_incident(file) for file in sorted(search_dir.glob("*.json"))]
    if not incidents:
        incidents = [load_incident(file) for file in sorted(search_dir.glob("*.csv"))]
    if not incidents:
        raise ValueError(f"no incident JSON/CSV files found in {search_dir}")
    return incidents


def summarize_dataset(incidents: Iterable[IncidentGraph]) -> Dict[str, object]:
    incidents = list(incidents)
    node_counts = sorted({len(incident.nodes) for incident in incidents})
    edge_counts = sorted({len(incident.edges) for incident in incidents})
    root_cause_count = sum(1 for incident in incidents if incident.root_cause)
    return {
        "incident_count": len(incidents),
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "root_cause_labels": root_cause_count,
    }


def _load_incident_json(path: Path) -> IncidentGraph:
    raw = json.loads(path.read_text(encoding="utf-8"))
    nodes = [
        ServiceNode(
            service_id=item["service_id"],
            features=_coerce_features(item.get("features", item)),
            label=item.get("label"),
        )
        for item in raw["nodes"]
    ]
    edges = [(edge["source"], edge["target"]) if isinstance(edge, Mapping) else tuple(edge) for edge in raw["edges"]]
    graph = IncidentGraph(
        incident_id=raw.get("incident_id", path.stem),
        timestamp=raw.get("timestamp", ""),
        nodes=nodes,
        edges=[(str(source), str(target)) for source, target in edges],
        root_cause=raw.get("root_cause"),
        metadata=raw.get("metadata", {}),
    )
    graph.validate()
    return graph


def _load_incident_csv(path: Path) -> IncidentGraph:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty RCAEval CSV: {path}")
    nodes = [
        ServiceNode(
            service_id=row["service_id"],
            features=_coerce_features(row),
            label=row.get("label") or None,
        )
        for row in rows
    ]
    edge_text = rows[0].get("edges", "")
    edges = []
    for edge in edge_text.split(";"):
        if "->" in edge:
            source, target = edge.split("->", 1)
            edges.append((source.strip(), target.strip()))
    graph = IncidentGraph(
        incident_id=rows[0].get("incident_id") or path.stem,
        timestamp=rows[0].get("timestamp") or "",
        nodes=nodes,
        edges=edges,
        root_cause=rows[0].get("root_cause") or None,
    )
    graph.validate()
    return graph


def _coerce_features(raw: Mapping[str, object], feature_names=FEATURES) -> Dict[str, float]:
    features: Dict[str, float] = {}
    for name in feature_names:
        value = raw.get(name, 0.0)
        features[name] = float(value or 0.0)
    return features
