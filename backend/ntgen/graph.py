"""
graph.py — the prerequisite DAG and per-student mastery state.

Two responsibilities:

  1. The graph. Load number-theory-dag.json, verify it is actually a DAG, and
     answer "what can this student see right now?"
  2. Mastery. Track per-node progress and decide when a node is mastered.

Nothing here generates or grades problems — that is generator.py and verify.py.
This file only knows about structure and progress, which is why the diagnostic
(phase 3) and the web app (phase 4) can both sit on top of it unchanged.

The three states a node can be in, which are exactly the three colours in the
graph view (PROJECT.md 5.2):

    mastered   the student has proven it            solid
    frontier   unlocked, authored, not yet mastered highlighted
    locked     everything else                      greyed

"locked" deliberately includes every tier 2-3 node. Those exist so the graph
has visible depth in the demo and are never authored (PROJECT.md 3.2).
"""

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants that must not drift
# ---------------------------------------------------------------------------

# Consecutive correct answers required to master a node (PROJECT.md 5.3).
# FREEZE THIS during user testing. Changing it mid-testing makes every result
# collected before the change incomparable with everything after it.
MASTERY_STREAK = 3

# Tiers we author problems for. Tiers 2-3 render locked forever, which makes
# the graph look deep at no authoring cost.
AUTHORED_TIERS = (0, 1)


class GraphError(Exception):
    """The graph itself is broken — a cycle, or a prereq that does not exist."""


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

class Graph:
    def __init__(self, data: dict):
        self.meta = data.get("meta", {})
        self.tiers = {t["id"]: t for t in data.get("tiers", [])}
        self._raw_nodes = data["nodes"]
        self.nodes = {n["id"]: n for n in self._raw_nodes}
        # file order, used wherever output should be deterministic
        self.order = [n["id"] for n in self._raw_nodes]

        # reverse edges, built once: prereq -> [nodes that require it]
        self._dependents = {nid: [] for nid in self.nodes}
        for n in self._raw_nodes:
            for p in n.get("prereqs", []):
                if p in self._dependents:
                    self._dependents[p].append(n["id"])

    # -- basic accessors ----------------------------------------------------

    def __contains__(self, node_id):
        return node_id in self.nodes

    def __len__(self):
        return len(self.nodes)

    def name(self, node_id):
        return self.nodes[node_id]["name"]

    def tier(self, node_id):
        return self.nodes[node_id]["tier"]

    def prereqs(self, node_id):
        """Direct prerequisites — the edges pointing INTO this node."""
        return list(self.nodes[node_id].get("prereqs", []))

    def dependents(self, node_id):
        """Nodes that list this one as a prerequisite — the outgoing edges."""
        return list(self._dependents[node_id])

    def is_authored(self, node_id):
        return self.tier(node_id) in AUTHORED_TIERS

    def authored_nodes(self):
        return [nid for nid in self.order if self.is_authored(nid)]

    # -- transitive relationships (the diagnostic in phase 3 needs these) ----

    def ancestors(self, node_id):
        """Every node this one transitively depends on."""
        seen, stack = set(), list(self.prereqs(node_id))
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in self.nodes:
                continue
            seen.add(cur)
            stack.extend(self.prereqs(cur))
        return seen

    def descendants(self, node_id):
        """Every node that transitively depends on this one."""
        seen, stack = set(), list(self.dependents(node_id))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.dependents(cur))
        return seen

    def learning_path(self, targets):
        """
        A walkable route covering `targets` and everything they depend on,
        ordered so no node appears before its prerequisites.

        Use this rather than trusting a hand-written path: it is correct by
        construction, and it answers "what would I have to learn to reach
        node X" for any X.
        """
        needed = set()
        for t in targets:
            if t in self.nodes:
                needed.add(t)
                needed |= self.ancestors(t)
        return [nid for nid in self.topological_order() if nid in needed]

    def topological_order(self):
        """
        Nodes ordered so every node appears after all of its prerequisites.

        Kahn's algorithm. Doubles as the cycle check: if some node never
        reaches in-degree zero, it is part of a cycle and never gets emitted.
        """
        indegree = {nid: len(self.prereqs(nid)) for nid in self.nodes}
        # seed in file order so the output is stable run to run
        queue = [nid for nid in self.order if indegree[nid] == 0]
        out = []
        while queue:
            cur = queue.pop(0)
            out.append(cur)
            for dep in self.dependents(cur):
                indegree[dep] -= 1
                if indegree[dep] == 0:
                    queue.append(dep)
        return out

    # -- validation ---------------------------------------------------------

    def validate(self, available_nodes=None):
        """
        Structural check. Raises GraphError on anything that would silently
        corrupt the app; returns a list of human-readable warnings otherwise.

        `available_nodes` is the set of node ids that actually have problems
        (generated templates or hand-authored). Pass it to get coverage
        warnings.
        """
        errors, warnings = [], []

        # duplicate ids would have been silently collapsed by the dict build
        if len(self._raw_nodes) != len(self.nodes):
            seen, dupes = set(), set()
            for n in self._raw_nodes:
                (dupes if n["id"] in seen else seen).add(n["id"])
            errors.append(f"duplicate node ids: {sorted(dupes)}")

        # A prereq pointing at a node that does not exist is the dangerous
        # typo: the node it belongs to can never unlock, and nothing else
        # would ever notice.
        for nid in self.order:
            for p in self.prereqs(nid):
                if p not in self.nodes:
                    errors.append(f"{nid}: prereq {p!r} does not exist")
            if nid in self.prereqs(nid):
                errors.append(f"{nid}: lists itself as a prerequisite")

        # cycle detection
        if not errors:
            ordered = self.topological_order()
            if len(ordered) != len(self.nodes):
                stuck = sorted(set(self.nodes) - set(ordered))
                errors.append(f"graph is cyclic; nodes in or after a cycle: {stuck}")

        if errors:
            raise GraphError("; ".join(errors))

        # --- warnings: real problems, but not corruption ---
        declared = self.meta.get("node_count")
        if declared is not None and declared != len(self.nodes):
            warnings.append(
                f"meta.node_count says {declared} but the file has {len(self.nodes)}"
            )

        # meta.demo_path must be WALKABLE: a student following it in order
        # must never reach a node whose prerequisites they have not mastered.
        # A path that skips a prereq looks fine in the file and produces an
        # incoherent demo — a node lighting up while its parent is still grey.
        walked = set()
        for nid in self.meta.get("demo_path", []):
            if nid not in self.nodes:
                warnings.append(f"meta.demo_path references unknown node {nid!r}")
                continue
            missing = [p for p in self.prereqs(nid) if p not in walked]
            if missing:
                warnings.append(
                    f"meta.demo_path: {nid} comes before its prereq(s) "
                    f"{', '.join(missing)}"
                )
            walked.add(nid)

        if available_nodes is not None:
            for nid in self.authored_nodes():
                if nid not in available_nodes:
                    warnings.append(f"{nid} (tier {self.tier(nid)}) has no problems")
            for nid in available_nodes:
                if nid not in self.nodes:
                    warnings.append(f"problems exist for unknown node {nid!r}")
                elif not self.is_authored(nid):
                    warnings.append(
                        f"{nid} is tier {self.tier(nid)} but has problems — "
                        f"tiers 2-3 are meant to stay locked"
                    )

        return warnings

    # -- student-facing state ----------------------------------------------

    def prereqs_met(self, node_id, mastery):
        """Pure graph question: are all direct prerequisites mastered?"""
        return all(is_mastered(mastery, p) for p in self.prereqs(node_id))

    def is_unlocked(self, node_id, mastery):
        """
        Can this node be served right now?

        Two conditions, kept separate on purpose: the prerequisites must be
        mastered (a graph fact) AND we must have authored the tier (a
        curriculum decision).
        """
        return self.is_authored(node_id) and self.prereqs_met(node_id, mastery)

    def frontier(self, mastery):
        """Unlocked but not yet mastered — where the student works next."""
        return [
            nid for nid in self.order
            if not is_mastered(mastery, nid) and self.is_unlocked(nid, mastery)
        ]

    def mastered(self, mastery):
        return [nid for nid in self.order if is_mastered(mastery, nid)]

    def locked(self, mastery):
        """Everything that is neither mastered nor on the frontier."""
        done = set(self.mastered(mastery)) | set(self.frontier(mastery))
        return [nid for nid in self.order if nid not in done]

    def status(self, mastery):
        """
        One call for the graph view: {node_id: "mastered"|"frontier"|"locked"}.
        """
        out = {}
        for nid in self.order:
            if is_mastered(mastery, nid):
                out[nid] = "mastered"
            elif self.is_unlocked(nid, mastery):
                out[nid] = "frontier"
            else:
                out[nid] = "locked"
        return out

    def newly_unlocked(self, before, after):
        """
        Nodes that became available between two mastery states — what the
        unlock animation fires on (PROJECT.md 5.2).
        """
        was = {nid for nid, s in self.status(before).items() if s == "frontier"}
        now = {nid for nid, s in self.status(after).items() if s == "frontier"}
        return [nid for nid in self.order if nid in now - was]


def load_graph(path=None) -> Graph:
    path = Path(path) if path else Path(__file__).parent / "number-theory-dag.json"
    return Graph(json.loads(path.read_text()))


# ---------------------------------------------------------------------------
# Mastery state
# ---------------------------------------------------------------------------
# Shape, per the handoff:
#   { node_id: {"streak": int, "attempts": int, "correct": int,
#               "mastered": bool, "source": "tested"|"inferred"|None} }
#
# `source` is set by the phase 3 diagnostic. A node marked mastered because a
# harder node was answered correctly is a GUESS, and the UI must be able to
# tell that apart from something the student actually demonstrated.

def new_mastery(graph: Graph) -> dict:
    return {
        nid: {
            "streak": 0,
            "attempts": 0,
            "correct": 0,
            "mastered": False,
            "source": None,
        }
        for nid in graph.nodes
    }


def is_mastered(mastery: dict, node_id: str) -> bool:
    entry = mastery.get(node_id)
    return bool(entry and entry["mastered"])


def record_answer(mastery: dict, node_id: str, correct: bool) -> bool:
    """
    Record one answer. Returns True if this answer just mastered the node.

    A wrong answer resets the streak to zero — three consecutive correct means
    consecutive. Mastery itself is sticky: once earned it is not revoked by a
    later slip, so the graph never flickers backwards in front of a student.
    """
    entry = mastery[node_id]
    entry["attempts"] += 1
    if correct:
        entry["correct"] += 1
        entry["streak"] += 1
    else:
        entry["streak"] = 0

    if not entry["mastered"] and entry["streak"] >= MASTERY_STREAK:
        entry["mastered"] = True
        entry["source"] = "tested"
        return True
    return False


def reset_streak(mastery: dict, node_id: str) -> None:
    """
    The cost of a reveal (give up): streak to zero, nothing else.

    A surrender is NOT an attempt (PROJECT.md 5.3 defines attempts as
    parseable submissions), so attempts/correct/mastered stay untouched and
    week-3 accuracy stats stay clean — record_answer remains the only
    attempt-writer. No mastered-guard: mastery is sticky and progress()
    reports "mastered" regardless of streak, so revealing while re-practising
    a mastered node is harmless.
    """
    mastery[node_id]["streak"] = 0


def set_mastered(mastery: dict, node_id: str, value: bool, source: str) -> None:
    """
    Set mastery directly, without answering questions. Only the diagnostic
    should call this, and it must say whether the conclusion was `tested` or
    `inferred`.
    """
    entry = mastery[node_id]
    entry["mastered"] = value
    entry["source"] = source


def progress(mastery: dict, node_id: str) -> str:
    """Human-readable streak toward mastery, e.g. '2/3'."""
    entry = mastery[node_id]
    if entry["mastered"]:
        return "mastered"
    return f"{min(entry['streak'], MASTERY_STREAK)}/{MASTERY_STREAK}"
