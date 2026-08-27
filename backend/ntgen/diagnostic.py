"""
diagnostic.py — find where a student's knowledge stops, in about six questions.

The idea. A linear quiz that walks the curriculum from the start wastes every
question on a strong student and never reaches the interesting part. Instead we
search the prerequisite graph, and since Phase 2B every answer also feeds a
live Bayesian Knowledge Tracing model (bkt.py) — the same one that drives
mastery afterwards — so each question visibly moves several nodes at once.

Two mechanisms run side by side, on purpose:

  THE SETS (proven, from the original bisection). A correct answer implies the
  node's PREREQUISITES; a wrong one rules out its DEPENDENTS:

      pass  ->  ANCESTORS   inferred mastered
      fail  ->  DESCENDANTS inferred locked

  (The build spec states this the other way round — see plan.md. Inferring
  that a pass implies mastery of everything downstream would hand a student a
  frontier far past what they can actually do.) The sets also prune the
  question pool: without them a weak student would be served the six deepest
  nodes, because a wrong answer never lifts anything.

  THE MODEL (BKT). Each answer is a real observation: Bayes posterior, then
  propagation along the edges. This produces the per-node probabilities and
  the {node: delta} map the frontend animates ("1 answer -> 9 skills updated").

Question selection: question 1 is anchored at `congruence` (PROJECT.md 5.1 —
the boundary between school math and contest math). After that,
KnowledgeState.most_informative() picks the authored node with the highest
p(1-p) * sqrt(1 + ancestors) — most uncertain, weighted toward probes whose
answer moves the most of the graph — excluding nodes the sets have already
classified.

Why result() must CALIBRATE (as-built delta 5 in BKT_SPEC.md): the backward
pass lifts prerequisites to at most 0.85 * P <= 0.85, which is below the 0.95
mastery threshold — so with one observation per node, nothing could ever
unlock and every student would finish at the root. The sets are the proven
verdict, so they set the final priors: tested-correct nodes are floored at
0.96, inferred-known at 0.95 (the dashed "prove it" look — one wrong answer
honestly drops them), tested-wrong keep their observed low posterior, and
inferred-unknown are capped at 0.40. No propagation runs after calibration:
it would let a capped dependent lift a tested-wrong node back up. Tested
beats inferred, exactly as before.

Every conclusion is tagged `tested` or `inferred`. Inference is a guess and
the UI must never present it as a measurement.

A Diagnostic is a pure function of its answer history (deterministic
tie-breaks everywhere), so replaying the history IS recovery after a restart.
"""

import bkt


# Where the search starts (PROJECT.md 5.1).
START_NODE = "congruence"

# Question budget. "Do not ask 40 questions. Ask ~6."
MAX_QUESTIONS = 6

# Calibration levels. Tested mastery sits above the inferred floor so a
# measured node survives one slip a touch better than a guessed one.
P_TESTED = 0.96
P_INFERRED = bkt.P_MASTERED          # 0.95 — exactly at the threshold
P_UNKNOWN_CAP = 0.40                 # inferred-locked nodes end at most here


class Diagnostic:
    def __init__(self, graph, start=START_NODE, max_questions=MAX_QUESTIONS):
        self.graph = graph
        self.start = start
        self.max_questions = max_questions

        adj = {nid: graph.prereqs(nid) for nid in graph.order}
        self.ks = bkt.KnowledgeState(adj, bkt.params_for_graph(graph),
                                     authored=set(graph.authored_nodes()))

        self.known = set()      # believed mastered
        self.unknown = set()    # believed not mastered
        self.tested = {}        # node -> bool, only nodes actually asked
        self.history = []       # [(node, correct)] in order

    # -- driving the session ------------------------------------------------

    @property
    def asked(self):
        return len(self.history)

    def _pool(self):
        """Authored nodes we have not yet placed on either side."""
        return [
            n for n in self.graph.authored_nodes()
            if n not in self.known and n not in self.unknown
        ]

    def next_node(self):
        """Which node to ask about next, or None when the search is done."""
        if self.asked >= self.max_questions:
            return None
        pool = self._pool()
        if not pool:
            return None
        if self.asked == 0 and self.start in pool:
            return self.start
        # Highest-information probe among the unclassified authored nodes.
        return self.ks.most_informative(exclude=self.known | self.unknown)

    def record(self, node, correct):
        """
        Fold one answer into both mechanisms. Returns the BKT moved-map
        {node_id: delta} so the caller can show what one answer did.
        """
        self.history.append((node, correct))
        self.tested[node] = bool(correct)

        moved = self.ks.observe(node, bool(correct))

        if correct:
            implied = {node} | self.graph.ancestors(node)
            gain, lose = self.known, self.unknown
        else:
            implied = {node} | self.graph.descendants(node)
            gain, lose = self.unknown, self.known

        for n in implied:
            # A node we actually tested keeps its measured result. Only
            # inferences get overwritten — this is what keeps one careless
            # slip from erasing a demonstrated success.
            if n != node and n in self.tested:
                continue
            gain.add(n)
            lose.discard(n)

        return moved

    def is_done(self):
        return self.asked >= self.max_questions or not self._pool()

    def run(self, answer_fn):
        """
        Drive the whole session. `answer_fn(node) -> bool` decides whether the
        student got that node's question right.
        """
        while not self.is_done():
            node = self.next_node()
            if node is None:
                break
            self.record(node, answer_fn(node))
        return self.result()

    # -- output -------------------------------------------------------------

    def result(self):
        """
        The student's starting knowledge state:

            {"p":        {node_id: P(mastered)},   # calibrated, see module doc
             "unlocked": [node_id, ...],           # the sticky unlock seed
             "source":   {node_id: "tested"|"inferred"}}
        """
        p = self.ks.export()
        source = {}
        for n in self.known:
            tested = self.tested.get(n) is True
            p[n] = max(p[n], P_TESTED if tested else P_INFERRED)
            source[n] = "tested" if tested else "inferred"
        for n in self.unknown:
            if self.tested.get(n) is False:
                source[n] = "tested"      # keep the observed low posterior
            else:
                p[n] = min(p[n], P_UNKNOWN_CAP)
                source[n] = "inferred"
        # NO propagate here — calibration is final (module docstring).

        unlocked = bkt.unlock_additions(
            self.graph.authored_nodes(), self.graph.prereqs, p, set())
        return {"p": p, "unlocked": unlocked, "source": source}

    def summary(self):
        """Counts for a results screen."""
        res = self.result()
        p, unlocked = res["p"], set(res["unlocked"])
        tested_pass = [n for n, ok in self.tested.items() if ok]
        tested_fail = [n for n, ok in self.tested.items() if not ok]
        return {
            "questions": self.asked,
            "tested_pass": tested_pass,
            "tested_fail": tested_fail,
            "inferred_mastered": sorted(self.known - set(self.tested)),
            "inferred_locked": sorted(
                n for n in self.unknown - set(self.tested)
                if self.graph.is_authored(n)
            ),
            "frontier": [n for n in self.graph.order
                         if n in unlocked and p[n] < bkt.P_MASTERED],
        }


# ---------------------------------------------------------------------------
# Testing aid
# ---------------------------------------------------------------------------

class SimulatedStudent:
    """
    A student with a known knowledge level, for checking that the diagnostic
    lands where it should. `knows` is closed downwards: knowing a node implies
    knowing everything it depends on.
    """

    def __init__(self, graph, knows, slip_on=None):
        self.graph = graph
        self.knows = set()
        for n in knows:
            self.knows.add(n)
            self.knows |= graph.ancestors(n)
        # nodes this student answers wrong despite knowing them, to exercise
        # the tested-beats-inferred rule
        self.slip_on = set(slip_on or ())

    def answer(self, node):
        if node in self.slip_on:
            return False
        return node in self.knows

    def true_frontier(self):
        """What the student should actually be working on."""
        return [
            n for n in self.graph.authored_nodes()
            if n not in self.knows
            and all(p in self.knows for p in self.graph.prereqs(n))
        ]
