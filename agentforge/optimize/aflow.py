"""AFlow-lite (TEST_PLAN section 4): 3-4 hand-made workflow shapes + one LLM edit round. Only if T1.7 chose a workflow.

A graph mirrors Freya's workflow nodes: agent nodes (stage prompt + allowed tools), condition nodes (one yes/no
decision, which Freya makes with its decision/routing LLM), transfer and end nodes. The graph rides on
AgentConfig.workflow, so LocalPlatform runs it (`run_workflow`) and every experiment and gate works unchanged.

Shapes start from a built V1: every agent node gets V1's system prompt plus its stage instruction and a tool subset,
so a shape differs from the single-prompt agent only by the routing.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from agentforge import llm
from agentforge.config import settings
from agentforge.schemas import AgentConfig


class Node(BaseModel):
    id: str
    kind: Literal["agent", "condition", "transfer", "end"]
    stage: str = ""  # agent: stage instruction appended to the base prompt
    tools: list[str] = Field(default_factory=list)  # agent: canonical tool names allowed here; empty = all
    exit_on_tool: list[str] = Field(default_factory=list)  # agent: leave after one of these succeeds
    exit_question: str = ""  # agent: or when the decision model answers yes after a turn
    question: str = ""  # condition: yes/no question about the call so far


class Edge(BaseModel):
    source: str
    target: str
    when: Literal["yes", "no", "next"] = "next"


class Graph(BaseModel):
    name: str
    start: str
    nodes: list[Node]
    edges: list[Edge]

    @model_validator(mode="after")
    def wired(self) -> "Graph":
        ids = {n.id for n in self.nodes}
        if self.start not in ids or any(e.source not in ids or e.target not in ids for e in self.edges):
            raise ValueError("edge or start points at an unknown node")
        for node in self.nodes:
            out = {e.when for e in self.edges if e.source == node.id}
            if node.kind == "condition" and out != {"yes", "no"}:
                raise ValueError(f"condition {node.id} needs exactly a yes and a no edge")
            if node.kind == "agent" and (node.exit_on_tool or node.exit_question) and "next" not in out:
                raise ValueError(f"agent {node.id} can exit but has no next edge")
        return self

    def node(self, node_id: str) -> Node:
        return next(n for n in self.nodes if n.id == node_id)

    def next(self, node_id: str, when: str = "next") -> str | None:
        return next((e.target for e in self.edges if e.source == node_id and e.when == when), None)


VERIFY_TOOLS = ["verify_identity", "schedule_callback", "mark_do_not_call", "transfer_to_human"]
ROUTE_TOOLS = ["log_dispute", "mark_do_not_call", "transfer_to_human", "schedule_callback", "get_account"]
OUTCOME_TOOLS = ["log_promise_to_pay", "log_dispute", "schedule_callback", "mark_do_not_call", "transfer_to_human"]

DOGRULAMA = ("Şu anki aşama: açılış ve kimlik doğrulama. Kimlik doğrulanmadan borçtan, tutardan veya üründen bahsetme. "
             "Kişi müşteri değilse yalnızca üçüncü kişilere söylenebilecekleri söyle.")
TAHSILAT = "Şu anki aşama: kimlik doğrulandı. Hesabı getir, gecikmiş tutarı söyle ve limitler içinde net bir ödeme sözü al."
YONLENDIRME = "Şu anki aşama: müşteri itiraz etti, zorluk anlattı ya da aranmak istemiyor. Tahsilat yapma; ilgili aracı çağır ve nazikçe bitir."
KAPANIS = "Şu anki aşama: kapanış. Sonuç bir araçla kaydedilmediyse şimdi kaydet, sonra sonucu tek cümleyle özetle ve vedalaş."
OUTCOME_LOGGED = "Has the outcome of the call (promise, dispute, callback, do-not-call or transfer) been logged with a tool?"
TRIAGE = "Has the customer disputed the debt, described financial hardship, or asked not to be called?"


def shapes() -> list[Graph]:
    single = Graph(name="single", start="agent", nodes=[Node(id="agent", kind="agent")], edges=[])
    verify_collect = Graph(name="verify_collect", start="dogrulama", nodes=[
        Node(id="dogrulama", kind="agent", stage=DOGRULAMA, tools=VERIFY_TOOLS, exit_on_tool=["verify_identity"]),
        Node(id="tahsilat", kind="agent", stage=TAHSILAT)],
        edges=[Edge(source="dogrulama", target="tahsilat")])
    verify_triage = Graph(name="verify_triage", start="dogrulama", nodes=[
        Node(id="dogrulama", kind="agent", stage=DOGRULAMA, tools=VERIFY_TOOLS, exit_on_tool=["verify_identity"]),
        Node(id="tahsilat_ilk", kind="agent", stage=TAHSILAT, tools=["get_account"], exit_on_tool=["get_account"]),
        Node(id="triage", kind="condition", question=TRIAGE),
        Node(id="yonlendirme", kind="agent", stage=YONLENDIRME, tools=ROUTE_TOOLS),
        Node(id="tahsilat", kind="agent", stage=TAHSILAT)],
        edges=[Edge(source="dogrulama", target="tahsilat_ilk"), Edge(source="tahsilat_ilk", target="triage"),
               Edge(source="triage", target="yonlendirme", when="yes"), Edge(source="triage", target="tahsilat", when="no")])
    with_closing = Graph(name="verify_collect_close", start="dogrulama", nodes=[
        Node(id="dogrulama", kind="agent", stage=DOGRULAMA, tools=VERIFY_TOOLS, exit_on_tool=["verify_identity"]),
        Node(id="tahsilat", kind="agent", stage=TAHSILAT, exit_on_tool=OUTCOME_TOOLS),
        Node(id="kapanis", kind="agent", stage=KAPANIS, tools=OUTCOME_TOOLS)],
        edges=[Edge(source="dogrulama", target="tahsilat"), Edge(source="tahsilat", target="kapanis")])
    return [single, verify_collect, verify_triage, with_closing]


def attach(cfg: AgentConfig, graph: Graph, label: str | None = None) -> AgentConfig:
    return cfg.model_copy(update={"workflow": graph.model_dump(), "version_label": label or f"{cfg.version_label}+wf-{graph.name}",
                                  "parent_version": cfg.version_label, "notes": f"workflow shape {graph.name}"})


# --- local execution (called from LocalPlatform when cfg.workflow is set) -------------------------------------


class WorkflowCursor:
    """Tracks the current node; LocalPlatform asks it for the node's prompt/tools and advances it after each turn."""

    def __init__(self, cfg: AgentConfig, canonical: callable):
        self.graph = Graph.model_validate(cfg.workflow)
        self.cfg = cfg
        self.canonical = canonical  # brief tool name -> canonical name
        self.current = self.graph.start
        self.path = [self.current]
        self.ended = False

    def node_config(self) -> AgentConfig:
        node = self.graph.node(self.current)
        tools = [t for t in self.cfg.tools if not node.tools or self.canonical(t.name) in node.tools]
        prompt = f"{self.cfg.system_prompt}\n\n{node.stage}" if node.stage else self.cfg.system_prompt
        return self.cfg.model_copy(update={"system_prompt": prompt, "tools": tools})

    def advance(self, calls_this_turn: list, context: str) -> None:
        """Leave agent nodes whose exit fired, then resolve conditions until we sit on an agent node (or the end)."""
        from agentforge.run.decision import decide

        node = self.graph.node(self.current)
        exited = any(self.canonical(c.name) in node.exit_on_tool and _ok(c.result) for c in calls_this_turn)
        if not exited and node.exit_question:
            exited = decide(node.exit_question, context)[0] is True
        if not exited:
            return
        self._move(self.graph.next(node.id))
        for _ in range(len(self.graph.nodes)):
            node = self.graph.node(self.current) if self.current else None
            if node is None or node.kind == "end":
                self.ended = True
                return
            if node.kind == "condition":
                self._move(self.graph.next(node.id, "yes" if decide(node.question, context)[0] else "no"))
                continue
            if node.kind == "transfer":
                self.ended = True
            return

    def _move(self, target: str | None) -> None:
        self.current = target
        if target:
            self.path.append(target)
        else:
            self.ended = True


def _ok(result: Any) -> bool:
    return isinstance(result, dict) and not result.get("error") and result.get("verified", True) is not False


# --- one LLM edit round -------------------------------------------------------------------------------------------

EDIT_SYSTEM = """You edit a voice-agent workflow graph for debt-collection calls. You get the graph as JSON and the
failure types it showed in simulated calls. Return the full edited graph as JSON in the same schema. Allowed node
kinds: agent, condition, transfer, end. Condition nodes have exactly one "yes" and one "no" edge. Agent nodes that can
exit need a "next" edge. Tools are canonical names. Change as little as needed to fix the failures; keep it small."""


def edit(graph: Graph, failures: dict) -> Graph:
    user = f"GRAPH:\n{graph.model_dump_json(indent=1)}\n\nFAILURES (check -> count, cases):\n{json.dumps(failures, ensure_ascii=False)}"
    for _ in range(2):
        raw = llm.call_llm(EDIT_SYSTEM, user, model=settings().builder_model, json_schema=Graph.model_json_schema(), temperature=0.3)
        try:
            edited = Graph.model_validate(raw)
            return edited.model_copy(update={"name": f"{graph.name}-edit"})
        except ValueError as error:
            user += f"\n\nYour last graph was invalid: {error}. Fix it."
    return graph


def to_freya_snapshot(graph: Graph) -> dict:
    """TODO(ask-organizers): Freya's workflow body (`workflow` in GET /workflow/{id}) is untyped in the spec. Create one
    workflow in the UI, GET it, and mirror its node/edge format here; then FreyaPlatform.push_workflow_version uploads
    the snapshot as a new version of that workflow."""
    raise NotImplementedError("map Graph to Freya's workflow format after inspecting a UI-made workflow")
