"""
Structural Causal Model (SCM) Builder.

Constructs and maintains a directed acyclic graph (DAG) representing
causal dependencies between macro-intents and KPI nodes.

Used to:
  1. Disambiguate root causes during causal co-drift events.
  2. Propagate interventional predictions (do-calculus queries).
  3. Generate explanations for automated remediation plans.

Graph structure:
    Nodes  → MacroIntent or KPI metric node
    Edges  → Directed causal arrows (cause → effect) with weights
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import networkx as nx


class NodeType(str, Enum):
    MACRO_INTENT = "macro_intent"
    KPI = "kpi"
    RESOURCE = "resource"


@dataclass
class CausalNode:
    node_id: str
    node_type: NodeType
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CausalEdge:
    cause_id: str
    effect_id: str
    weight: float = 1.0        # Causal strength [0, 1]
    lag_steps: int = 1         # Temporal lag
    confidence: float = 1.0    # Statistical confidence


@dataclass
class InterventionResult:
    """Result of a do-calculus intervention query."""
    intervened_node: str
    intervention_value: float
    predicted_effects: dict[str, float]   # node_id → predicted delta
    causal_path: list[str]
    explanation: str


class SCMBuilder:
    """
    Constructs a Structural Causal Model as a weighted directed graph.

    Provides:
      - Node / edge registration
      - Topological ordering (for propagation)
      - Root-cause tracing (ancestors of a drifted node)
      - Simple do-calculus intervention simulation
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._nodes: dict[str, CausalNode] = {}

    # ------------------------------------------------------------------ #
    # Graph construction                                                   #
    # ------------------------------------------------------------------ #

    def add_node(self, node: CausalNode) -> None:
        self._nodes[node.node_id] = node
        self._graph.add_node(
            node.node_id,
            label=node.label,
            node_type=node.node_type.value,
            **node.metadata,
        )

    def add_edge(self, edge: CausalEdge) -> None:
        if edge.cause_id not in self._graph:
            raise ValueError(f"Cause node '{edge.cause_id}' not in graph.")
        if edge.effect_id not in self._graph:
            raise ValueError(f"Effect node '{edge.effect_id}' not in graph.")
        self._graph.add_edge(
            edge.cause_id,
            edge.effect_id,
            weight=edge.weight,
            lag=edge.lag_steps,
            confidence=edge.confidence,
        )

    # ------------------------------------------------------------------ #
    # Causal queries                                                       #
    # ------------------------------------------------------------------ #

    def ancestors_of(self, node_id: str) -> list[str]:
        """Return all ancestor nodes (potential root causes)."""
        return list(nx.ancestors(self._graph, node_id))

    def descendants_of(self, node_id: str) -> list[str]:
        """Return all descendant nodes (downstream effects)."""
        return list(nx.descendants(self._graph, node_id))

    def causal_path(self, source: str, target: str) -> list[str] | None:
        """Shortest directed causal path from source to target."""
        try:
            return nx.shortest_path(self._graph, source, target)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def root_cause_candidates(self, drifted_nodes: list[str]) -> list[str]:
        """
        Among drifted nodes, return those with no drifted ancestors —
        they are the most likely root causes.
        """
        drifted_set = set(drifted_nodes)
        candidates: list[str] = []
        for node in drifted_nodes:
            ancestors = set(self.ancestors_of(node))
            if not ancestors.intersection(drifted_set):
                candidates.append(node)
        return candidates

    def topological_order(self) -> list[str]:
        """Return nodes in causal topological order (causes first)."""
        try:
            return list(nx.topological_sort(self._graph))
        except nx.NetworkXUnfeasible:
            return list(self._graph.nodes)

    # ------------------------------------------------------------------ #
    # Do-calculus intervention simulation                                  #
    # ------------------------------------------------------------------ #

    def intervene(
        self,
        node_id: str,
        delta: float,
        propagation_decay: float = 0.6,
    ) -> InterventionResult:
        """
        Simulate an intervention on node_id with magnitude delta.

        Propagates the effect downstream, decaying by propagation_decay
        at each hop (multiplied by edge weight and confidence).
        """
        if node_id not in self._graph:
            raise ValueError(f"Node '{node_id}' not in SCM graph.")

        predicted: dict[str, float] = {}
        queue: list[tuple[str, float]] = [(node_id, delta)]
        visited: set[str] = set()

        while queue:
            current, magnitude = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            if current != node_id:
                predicted[current] = magnitude

            for successor in self._graph.successors(current):
                edge_data = self._graph.edges[current, successor]
                weight = edge_data.get("weight", 1.0)
                confidence = edge_data.get("confidence", 1.0)
                propagated = magnitude * propagation_decay * weight * confidence
                if abs(propagated) > 0.001:
                    queue.append((successor, propagated))

        # Find full causal path from intervened node to most affected
        main_path: list[str] = [node_id]
        if predicted:
            most_affected = max(predicted, key=lambda k: abs(predicted[k]))
            path = self.causal_path(node_id, most_affected)
            if path:
                main_path = path

        explanation = (
            f"Intervening on '{node_id}' with Δ={delta:+.3f} propagates to "
            f"{len(predicted)} downstream nodes. "
            f"Primary path: {' → '.join(main_path)}."
        )

        return InterventionResult(
            intervened_node=node_id,
            intervention_value=delta,
            predicted_effects=predicted,
            causal_path=main_path,
            explanation=explanation,
        )

    # ------------------------------------------------------------------ #
    # Graph introspection                                                  #
    # ------------------------------------------------------------------ #

    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def is_acyclic(self) -> bool:
        return nx.is_directed_acyclic_graph(self._graph)

    def summary(self) -> dict[str, Any]:
        return {
            "nodes": self.node_count(),
            "edges": self.edge_count(),
            "is_dag": self.is_acyclic(),
            "topological_order": self.topological_order(),
        }

    def to_edge_list(self) -> list[dict[str, Any]]:
        edges = []
        for u, v, data in self._graph.edges(data=True):
            edges.append({"cause": u, "effect": v, **data})
        return edges


# -----------------------------------------------------------------------
# Pre-built SCM for the reference self-driving network topology
# -----------------------------------------------------------------------

def build_network_scm() -> SCMBuilder:
    """
    Construct the reference SCM for the three-intent self-driving network.

    Topology:
        queue_depth (I_tel) ──▶ ingest_lag (I_tel)
              │
              ▼
        inference_throughput (I_anl) ──▶ model_latency (I_anl)
              │
              ▼
        api_p99_latency (I_api) ──▶ error_rate (I_api)
    """
    scm = SCMBuilder()

    nodes = [
        CausalNode("tel_queue_depth",        NodeType.KPI,          "Telemetry Queue Depth",        {"intent": "I_tel"}),
        CausalNode("tel_ingest_lag",         NodeType.KPI,          "Telemetry Ingest Lag",          {"intent": "I_tel"}),
        CausalNode("anl_inference_tput",     NodeType.KPI,          "Analytics Inference Throughput",{"intent": "I_anl"}),
        CausalNode("anl_model_latency",      NodeType.KPI,          "Analytics Model Latency",       {"intent": "I_anl"}),
        CausalNode("api_p99_latency",        NodeType.KPI,          "API Gateway p99 Latency",       {"intent": "I_api"}),
        CausalNode("api_error_rate",         NodeType.KPI,          "API Gateway Error Rate",        {"intent": "I_api"}),
        CausalNode("I_tel",                  NodeType.MACRO_INTENT, "Telemetry Intent"),
        CausalNode("I_anl",                  NodeType.MACRO_INTENT, "Analytics Intent"),
        CausalNode("I_api",                  NodeType.MACRO_INTENT, "API Gateway Intent"),
    ]
    for n in nodes:
        scm.add_node(n)

    edges = [
        # Intra-intent: Telemetry
        CausalEdge("tel_queue_depth",    "tel_ingest_lag",      weight=0.85, lag_steps=1,  confidence=0.9),
        CausalEdge("I_tel",              "tel_queue_depth",     weight=1.0,  lag_steps=0,  confidence=1.0),
        CausalEdge("tel_ingest_lag",     "I_tel",               weight=0.7,  lag_steps=1,  confidence=0.85),
        # Cross-intent: Telemetry → Analytics
        CausalEdge("tel_ingest_lag",     "anl_inference_tput",  weight=0.75, lag_steps=2,  confidence=0.8),
        # Intra-intent: Analytics
        CausalEdge("anl_inference_tput", "anl_model_latency",   weight=0.6,  lag_steps=1,  confidence=0.85),
        CausalEdge("I_anl",              "anl_inference_tput",  weight=1.0,  lag_steps=0,  confidence=1.0),
        # Cross-intent: Analytics → API
        CausalEdge("anl_model_latency",  "api_p99_latency",     weight=0.7,  lag_steps=2,  confidence=0.75),
        # Intra-intent: API
        CausalEdge("api_p99_latency",    "api_error_rate",      weight=0.8,  lag_steps=1,  confidence=0.9),
        CausalEdge("I_api",              "api_p99_latency",     weight=1.0,  lag_steps=0,  confidence=1.0),
    ]
    for e in edges:
        scm.add_edge(e)

    return scm
