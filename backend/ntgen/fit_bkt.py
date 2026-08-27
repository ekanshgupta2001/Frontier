"""
fit_bkt.py — solve the cold-start problem.  OFFLINE DEMO ONLY.

Run it directly:  python3 backend/ntgen/fit_bkt.py
It is never imported by the app, the selftest, or the leaktest — the
numeric-gradient fit below is far too slow for a gate.

We have no student data. So: generate synthetic students with KNOWN
mastery, simulate their answers, fit BKT parameters to those answers,
and check the fitted model recovers the truth.

This is both a real fitting pipeline and a judge-facing demo in its own
right: "here is a student who knows tier 0 but not tier 1 -- watch the
model find that in six questions."

Uses plain gradient descent in logit space. Swap in PyTorch autograd if
you want the framework on your resume; the math is identical.

Note: bkt.update() applies the learning transition on correct answers
only (BKT_SPEC.md as-built delta 1), so the spec §6 "wrong answer went
up" output no longer reproduces here. That is the point.
"""

import json
import math
import random
from pathlib import Path

from bkt import NodeParams, KnowledgeState, update, p_correct


# ---------------------------------------------------------------------------
# Synthetic students
# ---------------------------------------------------------------------------

# Ground-truth profiles the synthetic students actually follow. These are
# deliberately NOT the live app's serving parameters (bkt.TIER_PARAMS) —
# the whole exercise is recovering unknown truth from observed answers.
TRUE_PARAMS = {
    "tier0": NodeParams(p_init=0.55, p_learn=0.35, p_slip=0.08, p_guess=0.22),
    "tier1": NodeParams(p_init=0.12, p_learn=0.25, p_slip=0.12, p_guess=0.18),
}


def make_student(graph, tiers, true_frontier_tier, rng):
    """
    A student who genuinely knows everything below `true_frontier_tier`
    and nothing at or above it. This is the ground truth we test against.
    """
    return {n: (tiers[n] < true_frontier_tier) for n in graph}


def simulate_answer(knows: bool, prm: NodeParams, rng) -> bool:
    """Generate an observed answer from true mastery, with slip and guess."""
    if knows:
        return rng.random() > prm.p_slip
    return rng.random() < prm.p_guess


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------

def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def nll(sequences, prm: NodeParams) -> float:
    """
    Negative log-likelihood of observed answer sequences under `prm`.
    Each sequence is a list of booleans for ONE node, ONE student.
    """
    total = 0.0
    for seq in sequences:
        p = prm.p_init
        for correct in seq:
            pc = p_correct(p, prm)
            pc = min(max(pc, 1e-6), 1 - 1e-6)
            total -= math.log(pc if correct else 1 - pc)
            p = update(p, correct, prm)
    return total


def fit(sequences, iters=400, lr=0.35, seed=0):
    """
    Gradient descent in logit space so parameters stay in (0,1) without
    projection. Gradients are numerical -- with 4 parameters that is
    cheaper than deriving them and impossible to get wrong.
    """
    rng = random.Random(seed)
    theta = [logit(0.2), logit(0.3), logit(0.1), logit(0.2)]

    def unpack(t):
        return NodeParams(sigmoid(t[0]), sigmoid(t[1]),
                          sigmoid(t[2]), sigmoid(t[3])).clamp()

    eps = 1e-4
    for _ in range(iters):
        base = nll(sequences, unpack(theta))
        grad = []
        for i in range(4):
            bumped = list(theta)
            bumped[i] += eps
            grad.append((nll(sequences, unpack(bumped)) - base) / eps)
        norm = max(1.0, math.sqrt(sum(g * g for g in grad)))
        theta = [t - lr * g / norm for t, g in zip(theta, grad)]

    return unpack(theta)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def load_graph(path=None):
    path = Path(path) if path else Path(__file__).with_name("number-theory-dag.json")
    data = json.loads(path.read_text())
    graph = {n["id"]: list(n.get("prereqs", [])) for n in data["nodes"]}
    tiers = {n["id"]: n["tier"] for n in data["nodes"]}
    return graph, tiers


def main():
    rng = random.Random(20260819)
    graph, tiers = load_graph()

    # keep tiers 0-1 only, matching the authored curriculum
    graph = {n: [p for p in ps if tiers[p] <= 1]
             for n, ps in graph.items() if tiers[n] <= 1}
    tiers = {n: tiers[n] for n in graph}

    print("=" * 66)
    print("PART 1 — PARAMETER RECOVERY")
    print("=" * 66)
    truth = NodeParams(p_init=0.20, p_learn=0.30, p_slip=0.09, p_guess=0.21)
    seqs = []
    for _ in range(200):
        p, seq = truth.p_init, []
        for _ in range(10):
            knows = rng.random() < p
            correct = simulate_answer(knows, truth, rng)
            seq.append(correct)
            p = update(p, correct, truth)
        seqs.append(seq)

    fitted = fit(seqs)
    print(f"{'param':<10}{'true':>8}{'fitted':>10}{'error':>9}")
    for name in ["p_init", "p_learn", "p_slip", "p_guess"]:
        t, f = getattr(truth, name), getattr(fitted, name)
        print(f"{name:<10}{t:>8.3f}{f:>10.3f}{abs(t-f):>9.3f}")

    print()
    print("=" * 66)
    print("PART 2 — FINDING A SYNTHETIC STUDENT'S FRONTIER")
    print("=" * 66)
    params = {n: NodeParams(**vars(TRUE_PARAMS["tier0" if tiers[n] == 0 else "tier1"]))
              for n in graph}
    state = KnowledgeState(graph, params)
    student = make_student(graph, tiers, true_frontier_tier=1, rng=rng)
    print("Ground truth: knows all of tier 0, none of tier 1.\n")

    asked = []
    for q in range(1, 7):
        node = state.most_informative(exclude=asked)
        asked.append(node)
        correct = simulate_answer(student[node], params[node], rng)
        deltas = state.observe(node, correct)
        moved = sorted(deltas.items(), key=lambda kv: -abs(kv[1]))[:4]
        mark = "correct" if correct else "wrong  "
        print(f"Q{q}: {node:<22} {mark}   {len(deltas)} nodes moved")
        for n, d in moved:
            print(f"       {n:<22} {d:+.3f} -> {state.p[n]:.2f}")

    print()
    t0 = [n for n in graph if tiers[n] == 0]
    t1 = [n for n in graph if tiers[n] == 1]
    print(f"mean P(mastered), tier 0: {sum(state.p[n] for n in t0)/len(t0):.2f}  (truth: high)")
    print(f"mean P(mastered), tier 1: {sum(state.p[n] for n in t1)/len(t1):.2f}  (truth: low)")


if __name__ == "__main__":
    main()
