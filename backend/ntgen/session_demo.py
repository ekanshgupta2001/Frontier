"""
session_demo.py — CHECKPOINT 3.  ** PRE-BKT, DOES NOT RUN ANY MORE **

Phase 2B (2026-08-22) changed Diagnostic.result() from a binary mastery dict
to {"p", "unlocked", "source"} — see BKT_SPEC.md. This walkthrough narrates
the OLD binary flow and is kept only as checkpoint-3 history; the live flow
it demonstrated is now exercised by backend/leaktest.py end to end, and the
model itself by `python3 backend/ntgen/fit_bkt.py`.

    python3 backend/ntgen/session_demo.py                 simulated students
    python3 backend/ntgen/session_demo.py --interactive   take the diagnostic yourself

Part 1 runs the diagnostic against students whose real knowledge level is
known in advance, so the frontier it finds can be checked rather than admired.
Part 2 runs one student end to end: diagnostic -> frontier -> practice ->
mastery -> unlock, which is exactly the flow the web app will wrap.
"""

import random
import sys

import graph as g
from diagnostic import Diagnostic, SimulatedStudent, MAX_QUESTIONS, START_NODE
from generator import load_templates, load_hand_authored, problem_for_node


# Students to check the diagnostic against. Each is described by the deepest
# nodes they know; SimulatedStudent closes that set downwards.
PROFILES = [
    ("knows nothing",            []),
    ("early tier 0",             ["primes"]),
    ("finished tier 0",          ["euclidean", "divisor_functions", "digit_rules"]),
    ("into tier 1",              ["mod_arith", "bezout"]),
    ("most of tier 1",           ["crt", "fermat_little"]),
    ("everything authored",      ["order", "wilson", "pigeonhole_nt", "digit_rules"]),
]


def wrong_answer_for(p):
    """
    Something this problem will definitely grade wrong. Hardcoding "0" would
    quietly become a CORRECT answer whenever the real answer is 0, and the
    script would then claim a wrong answer was wrong while it was right.
    """
    for candidate in ["0", "1", "none", "-1", "zzz"]:
        if not p.check(candidate):
            return candidate
    return "zzz"


def show_diagnostic(G, label, knows, slip_on=None, verbose=True):
    student = SimulatedStudent(G, knows, slip_on=slip_on)
    d = Diagnostic(G)
    d.run(student.answer)
    s = d.summary()

    print(f"\n  {label}  (actually knows {len(student.knows)} nodes)")
    for i, (node, ok) in enumerate(d.history, 1):
        print(f"    Q{i}  {node:<20} {'correct' if ok else 'wrong'}")
    print(f"    -> {s['questions']} questions, "
          f"{len(s['inferred_mastered'])} nodes inferred mastered, "
          f"{len(s['inferred_locked'])} inferred locked")
    print(f"    diagnostic frontier: {', '.join(s['frontier']) or '(none)'}")
    if verbose:
        true_f = student.true_frontier()
        print(f"    true frontier:       {', '.join(true_f) or '(none)'}")
        hit = set(s["frontier"]) & set(true_f)
        if hit:
            verdict = f"overlaps on {', '.join(sorted(hit))}"
        elif not true_f:
            verdict = "student has finished everything authored"
        else:
            # not a failure by itself: with 6 questions the search brackets the
            # frontier, it does not pin every branch of the graph
            verdict = "no exact overlap — bracketed, not pinned"
        print(f"    check: {verdict}")
    return d, student


def part1(G):
    print("=" * 70)
    print("PART 1 — DOES IT FIND THE RIGHT FRONTIER?")
    print("=" * 70)
    print(f"  start node: {START_NODE}   budget: {MAX_QUESTIONS} questions")
    for label, knows in PROFILES:
        show_diagnostic(G, label, knows)

    print("\n" + "=" * 70)
    print("TESTED BEATS INFERRED")
    print("=" * 70)
    print("  A student who knows tier 0 but slips on the congruence question.")
    print("  The slip drags inferences down with it — but anything we go on to")
    print("  TEST directly overrides the guess.")
    d, student = show_diagnostic(
        G, "tier 0, slips on congruence",
        ["euclidean", "divisor_functions", "digit_rules"], slip_on=["congruence"],
    )
    mastery = d.result()
    print("\n    node          mastered  source")
    for n in ["congruence", "divisibility", "gcd_lcm", "euclidean", "mod_arith"]:
        e = mastery[n]
        print(f"    {n:<13} {str(e['mastered']):<9} {e['source']}")


def part2(G, templates, hand, rng):
    print("\n" + "=" * 70)
    print("PART 2 — ONE STUDENT, END TO END")
    print("=" * 70)

    student = SimulatedStudent(G, ["mod_arith", "bezout"])
    d = Diagnostic(G)
    d.run(student.answer)
    mastery = d.result()

    print("\n  DIAGNOSTIC")
    for i, (node, ok) in enumerate(d.history, 1):
        print(f"    Q{i}  {node:<20} {'correct' if ok else 'wrong'}")

    status = G.status(mastery)
    counts = {s: sum(1 for v in status.values() if v == s) for s in
              ("mastered", "frontier", "locked")}
    print(f"\n  GRAPH VIEW: {counts['mastered']} mastered, "
          f"{counts['frontier']} frontier, {counts['locked']} locked")
    glyph = {"mastered": "#", "frontier": "+", "locked": "."}
    print("    " + "".join(glyph[status[n]] for n in G.order))
    print("    # mastered  + frontier  . locked")

    frontier = G.frontier(mastery)
    print(f"    frontier: {', '.join(frontier)}")

    # Practise the node that opens up the most — that is the one worth
    # showing, and it is what a good UI would recommend.
    def would_unlock(node):
        trial = {k: dict(v) for k, v in mastery.items()}
        g.set_mastered(trial, node, True, "tested")
        return len(G.newly_unlocked(mastery, trial))

    target = max(frontier, key=would_unlock)
    print(f"\n  PRACTICE at {target} — {G.name(target)}")
    print(f"    chosen because mastering it unlocks {would_unlock(target)} more node(s)")
    print(f"    needs {g.MASTERY_STREAK} consecutive correct to master")

    before = {k: dict(v) for k, v in mastery.items()}
    # this student gets the first one wrong, then finds their feet
    script = [False, True, True, True]
    for correct in script:
        p = problem_for_node(templates, target, rng, hand)
        answer = str(p._answer) if correct else wrong_answer_for(p)
        graded = p.check(answer)
        just = g.record_answer(mastery, target, graded)
        print(f"\n    Q: {p.prompt}")
        print(f"       typed {answer!r} -> {'correct' if graded else 'wrong'}"
              f"   streak {g.progress(mastery, target)}")
        if just:
            print(f"       *** {target} MASTERED ***")

    unlocked = G.newly_unlocked(before, mastery)
    print(f"\n  UNLOCKED: {', '.join(unlocked) if unlocked else '(nothing new)'}")
    print(f"  frontier is now: {', '.join(G.frontier(mastery))}")


def interactive(G, templates, hand, rng):
    print("=" * 70)
    print("DIAGNOSTIC — answer as best you can, or press enter to skip")
    print("=" * 70)
    d = Diagnostic(G)
    while not d.is_done():
        node = d.next_node()
        if node is None:
            break
        p = problem_for_node(templates, node, rng, hand)
        print(f"\n  Q{d.asked + 1}  [{G.name(node)}]")
        print(f"      {p.prompt}")
        print(f"      ({p.answer_format})")
        try:
            typed = input("      > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  cancelled")
            return
        correct = bool(typed) and p.check(typed)
        print(f"      {'correct' if correct else 'not quite'}")
        d.record(node, correct)

    mastery = d.result()
    s = d.summary()
    print("\n" + "=" * 70)
    print("YOUR MAP")
    print("=" * 70)
    status = G.status(mastery)
    for tier in g.AUTHORED_TIERS:
        row = [n for n in G.order if G.tier(n) == tier]
        print(f"\n  tier {tier}:")
        for n in row:
            mark = {"mastered": "[#]", "frontier": "[>]", "locked": "[ ]"}[status[n]]
            src = mastery[n]["source"]
            tag = f"  ({src})" if src else ""
            print(f"    {mark} {G.name(n)}{tag}")
    print(f"\n  Work on next: {', '.join(s['frontier']) or '(nothing unlocked)'}")
    print("  [#] mastered   [>] available now   [ ] locked")
    print("  (tested = we asked you; inferred = deduced from the graph)")


def main():
    G = g.load_graph()
    G.validate()
    templates = load_templates()
    hand = load_hand_authored()
    rng = random.Random(20260819)

    if "--interactive" in sys.argv:
        interactive(G, templates, hand, rng)
        return

    part1(G)
    part2(G, templates, hand, rng)
    print("\n  (run with --interactive to take the diagnostic yourself)")


if __name__ == "__main__":
    main()
