"""
bkt.py — Bayesian Knowledge Tracing over the prerequisite DAG.

Standard BKT models ONE skill as a hidden Markov model with two states
(not-mastered / mastered) and four parameters. We run one BKT chain per
node, then add a propagation step that moves evidence along the
prerequisite edges. The propagation is ours, not standard, and it is
documented honestly as a heuristic below.

Reference for the base model: Corbett & Anderson (1995), "Knowledge
tracing: Modeling the acquisition of procedural knowledge."

DELIBERATE DEVIATION from the textbook (BKT_SPEC.md §6, resolved as
option 1): the learning transition applies only on CORRECT answers.
A wrong answer is the Bayes posterior alone, so it strictly lowers
P(M) — a student never watches a node brighten after missing it.

Pure stdlib, deterministic, no I/O — this module runs inside both the
selftest and leaktest gates on every change.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

P_MASTERED = 0.95        # mastery threshold on P(M)
BACKWARD_LIFT = 0.85     # evidence flowing down to prerequisites, damped
FORWARD_CAP = 0.25       # a weak prerequisite caps its dependents
_EPS = 1e-9              # movement smaller than this is "didn't move"


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class NodeParams:
    """The four BKT parameters for a single node."""
    p_init: float = 0.15   # P(mastered before any practice)
    p_learn: float = 0.30  # P(transition to mastered after a correct attempt)
    p_slip: float = 0.10   # P(wrong | mastered)
    p_guess: float = 0.20  # P(right | not mastered)

    def clamp(self):
        """
        Identifiability guard. If slip + guess >= 1 the model degenerates:
        being wrong becomes evidence FOR mastery. This is a known BKT
        failure mode and any fitted values MUST be constrained to avoid it.
        """
        self.p_slip = min(max(self.p_slip, 0.01), 0.30)
        self.p_guess = min(max(self.p_guess, 0.01), 0.40)
        self.p_init = min(max(self.p_init, 0.01), 0.85)
        self.p_learn = min(max(self.p_learn, 0.01), 0.60)
        return self


# Live-app defaults. slip/guess/learn are uniform because the pacing bound
# below is parameter-dependent: with these values, 3 consecutive corrects
# reach P >= 0.95 from ANY starting prior (0 -> .30 -> .761 -> .954, and the
# update is monotone in p), while 2 corrects from a cold prior do not. That
# preserves the "about 3 in a row" feel students already know. Only the
# prior varies by tier — tier 0 is schoolwork many students half-know.
# (The reference per-tier slip/guess profiles broke the bound: guess=.22
# lands at 0.948 after 3 corrects from a collapsed prior.)
TIER_PARAMS = {
    0: NodeParams(p_init=0.20),
    1: NodeParams(p_init=0.10),
    2: NodeParams(p_init=0.10),
    3: NodeParams(p_init=0.10),
}


def params_for_graph(graph):
    """{node_id: NodeParams} from a graph.Graph, by tier (fresh copies)."""
    return {nid: NodeParams(**vars(TIER_PARAMS[graph.tier(nid)]))
            for nid in graph.order}


# ---------------------------------------------------------------------------
# Core BKT update
# ---------------------------------------------------------------------------

def posterior(p_mastered: float, correct: bool, prm: NodeParams) -> float:
    """
    Step 1 of the update: given the observation, what is P(mastered NOW,
    before any learning happens)? This is plain Bayes.

        P(correct | mastered)     = 1 - slip
        P(correct | not mastered) = guess
    """
    if correct:
        num = p_mastered * (1 - prm.p_slip)
        den = num + (1 - p_mastered) * prm.p_guess
    else:
        num = p_mastered * prm.p_slip
        den = num + (1 - p_mastered) * (1 - prm.p_guess)
    if den <= 0:
        return p_mastered
    return num / den


def transition(p_post: float, prm: NodeParams) -> float:
    """
    Step 2: the student may have LEARNED from the attempt. Mastery is
    absorbing — once mastered, never forgotten (by this step; the forward
    cap in propagation can still honestly lower a value).
    """
    return p_post + (1 - p_post) * prm.p_learn


def update(p_mastered: float, correct: bool, prm: NodeParams) -> float:
    """
    One full single-node update. Transition applies on correct answers
    only (see module docstring) — a wrong answer strictly lowers P(M).
    """
    post = posterior(p_mastered, correct, prm)
    return transition(post, prm) if correct else post


def p_correct(p_mastered: float, prm: NodeParams) -> float:
    """Predicted probability the student answers correctly. Used for fitting."""
    return p_mastered * (1 - prm.p_slip) + (1 - p_mastered) * prm.p_guess


# ---------------------------------------------------------------------------
# Prerequisite propagation  -- THE PART THAT IS OURS
# ---------------------------------------------------------------------------
#
# HONESTY NOTE, read this before defending it to a judge:
#
# Exact Bayesian inference over a joint distribution on 35 correlated
# nodes is expensive and needs data we do not have. What follows is a
# documented HEURISTIC, not principled inference. Say so if asked --
# "it's an approximation with a monotonicity constraint" is a much
# better answer than pretending it is exact.
#
# The assumption: mastery is monotone along prerequisite edges. If a
# student can do CRT, they can almost certainly do the Euclidean
# algorithm underneath it. So P(prereq) should never sit far below
# P(dependent).
#
# Backward pass (evidence flows DOWN to prereqs):
#     P(prereq) <- max(P(prereq), BACKWARD_LIFT * P(node))
#
# Forward pass (weak prereqs cap dependents):
#     P(node) <- min(P(node), FORWARD_CAP + min over prereqs of P(prereq))
#
# ORDER MATTERS and is load-bearing: backward runs FIRST, so an answer
# that lifts a node to X also lifts its prereqs to >= 0.85*X before the
# cap applies, and 0.25 + 0.85*X > X always — a directly practiced node
# can never be capped away from mastery. (A guard exempting practiced
# nodes from the cap was considered and rejected as unnecessary.)


class KnowledgeState:
    def __init__(self, graph: Dict[str, List[str]],
                 params: Dict[str, NodeParams],
                 p: Optional[Dict[str, float]] = None,
                 authored=None):
        """
        graph:    node_id -> list of prereq node_ids (insertion order is
                  the deterministic tie-break order everywhere below)
        params:   node_id -> NodeParams
        p:        optional persisted {node_id: P(M)} to resume from; any
                  node it lacks starts at that node's p_init
        authored: optional set of node_ids problems exist for — the only
                  nodes most_informative() may pick (default: all)
        """
        self.graph = graph
        self.params = params
        self.authored = set(authored) if authored is not None else set(graph)
        p = p or {}
        self.p = {n: float(p[n]) if n in p else params[n].p_init
                  for n in graph}
        self._order = self._topo_order()
        self._anc = {}

    def export(self) -> Dict[str, float]:
        """Persistable {node_id: P(M)}. Round-trips exactly through JSON."""
        return dict(self.p)

    def _topo_order(self) -> List[str]:
        """Topological order. Also proves the graph is acyclic."""
        seen, order, visiting = set(), [], set()

        def visit(n):
            if n in seen:
                return
            if n in visiting:
                raise ValueError(f"cycle in prerequisite graph at {n!r}")
            visiting.add(n)
            for pr in self.graph[n]:
                if pr not in self.graph:
                    raise ValueError(f"node {n!r} lists unknown prereq {pr!r}")
                visit(pr)
            visiting.discard(n)
            seen.add(n)
            order.append(n)

        for n in self.graph:
            visit(n)
        return order

    def observe(self, node: str, correct: bool) -> Dict[str, float]:
        """
        Record one answer. Returns {node_id: delta} for every node whose
        probability moved -- the frontend animates exactly these.
        """
        before = dict(self.p)
        self.p[node] = update(self.p[node], correct, self.params[node])
        self.propagate()
        return {n: self.p[n] - before[n] for n in self.p
                if abs(self.p[n] - before[n]) > _EPS}

    def observe_reveal(self, node: str) -> Dict[str, float]:
        """
        The student surrendered and was shown the worked solution. That is
        evidence they can't do it yet: the wrong-answer posterior, with no
        learning credit (mastery is earned by answering, not by reading).
        Under transition-on-correct-only this is exactly a wrong observe;
        it gets its own name so call sites and the event log stay legible.
        """
        return self.observe(node, correct=False)

    def propagate(self):
        # Public because migration calls it once to make hand-set priors
        # coherent (e.g. legacy binary mastery mapped onto probabilities).
        # backward: reverse topological order, evidence flows to prereqs
        for n in reversed(self._order):
            for pr in self.graph[n]:
                lifted = BACKWARD_LIFT * self.p[n]
                if lifted > self.p[pr]:
                    self.p[pr] = lifted
        # forward: a weak prereq caps its dependents
        for n in self._order:
            if self.graph[n]:
                cap = FORWARD_CAP + min(self.p[pr] for pr in self.graph[n])
                if cap < self.p[n]:
                    self.p[n] = cap

    def mastered(self):
        return {n for n, v in self.p.items() if v >= P_MASTERED}

    def frontier(self):
        """Unlocked (all prereqs mastered) but not yet mastered."""
        m = self.mastered()
        return {n for n in self.graph
                if n not in m and all(pr in m for pr in self.graph[n])}

    def most_informative(self, exclude=()):
        """
        Next DIAGNOSTIC question: the authored node whose answer we can
        least predict, weighted toward nodes with many ancestors.

        IMPORTANT -- do NOT restrict this to the frontier.

        An earlier version picked only frontier nodes. That silently
        destroyed the whole point of the model: early on the frontier is
        just the graph's roots, roots have no prerequisites, so every
        answer moved exactly one node and no evidence ever propagated.
        The diagnostic is a binary SEARCH -- it must probe deep, because
        a correct answer at `crt` is what lifts five ancestors at once.

        The pool IS restricted to authored nodes (the app can only serve
        problems for those) minus `exclude`; deep authored nodes like
        `order` (14 ancestors) keep the probe-deep intent alive. Ties
        break to graph insertion order — selection is deterministic.

        (Practice mode is different: it serves from the unlocked set so
        students are never handed something they cannot yet do.)
        """
        best, best_score = None, -1.0
        excluded = set(exclude)
        for n in self.graph:                    # insertion order = tie-break
            if n not in self.authored or n in excluded:
                continue
            p = self.p[n]
            uncertainty = p * (1 - p)                 # peaks at p = 0.5
            reach = 1 + len(self._ancestors(n))       # propagation payoff
            score = uncertainty * (reach ** 0.5)
            if score > best_score:
                best, best_score = n, score
        return best

    def _ancestors(self, node: str) -> set:
        if node not in self._anc:
            out, stack = set(), list(self.graph[node])
            while stack:
                n = stack.pop()
                if n not in out:
                    out.add(n)
                    stack.extend(self.graph[n])
            self._anc[node] = out
        return self._anc[node]


# ---------------------------------------------------------------------------
# Sticky unlock
# ---------------------------------------------------------------------------

def unlock_additions(authored_order, prereqs_of, p, unlocked,
                     threshold=P_MASTERED):
    """
    Which authored nodes join the student's grow-only unlocked set now?
    A node qualifies when every prerequisite sits at P >= threshold, or
    when the node itself does (mastered => practicable, whatever its
    prereqs currently read). Nodes never leave the set — unlocking is
    sticky by decision; only the colour is honest.

    authored_order: authored node_ids in graph file order (result order)
    prereqs_of:     node_id -> list of prereq node_ids
    p:              {node_id: P(M)}
    unlocked:       the student's current unlocked set/list
    """
    have = set(unlocked)
    out = []
    for n in authored_order:
        if n in have:
            continue
        if p.get(n, 0.0) >= threshold or \
                all(p.get(q, 0.0) >= threshold for q in prereqs_of(n)):
            out.append(n)
    return out
