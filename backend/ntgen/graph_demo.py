"""
graph_demo.py — CHECKPOINT 2. Run: python3 backend/ntgen/graph_demo.py

Loads the DAG, validates it, then simulates a student mastering their way
along the demo path and prints how the three states move at each step.

What to look for:
  - a fresh student's frontier is ONLY divisibility (everything else has an
    unmastered prerequisite)
  - mastering a node unlocks exactly the nodes whose prereqs are now all done,
    and nothing else
  - tier 2-3 nodes never leave "locked", even at the very end
"""

import graph as g


def bar(status, order):
    """One character per node, in file order: # mastered, + frontier, . locked."""
    glyph = {"mastered": "#", "frontier": "+", "locked": "."}
    return "".join(glyph[status[nid]] for nid in order)


def show(G, mastery, label):
    st = G.status(mastery)
    frontier = G.frontier(mastery)
    print(f"\n{label}")
    print(f"  {bar(st, G.order)}")
    print(f"  mastered {len(G.mastered(mastery)):2}   "
          f"frontier {len(frontier):2}   locked {len(G.locked(mastery)):2}")
    print(f"  can work on now: {', '.join(frontier) if frontier else '(nothing)'}")


def main():
    G = g.load_graph()
    warnings = G.validate()
    print("=" * 66)
    print("GRAPH VALIDATION")
    print("=" * 66)
    print(f"  {len(G)} nodes, acyclic, every prereq resolves")
    print(f"  tiers: " + ", ".join(
        f"{t['id']}={sum(1 for n in G.order if G.tier(n) == t['id'])}"
        for t in G.tiers.values()))
    print(f"  authored (tiers {g.AUTHORED_TIERS}): {len(G.authored_nodes())} nodes")
    for w in warnings:
        print(f"  warning: {w}")

    print("\n" + "=" * 66)
    print("A FRESH STUDENT")
    print("=" * 66)
    mastery = g.new_mastery(G)
    print("  legend: # mastered   + frontier   . locked   (nodes in file order)")
    show(G, mastery, "before answering anything")

    print("\n" + "=" * 66)
    print(f"MASTERY MECHANIC: {g.MASTERY_STREAK} CONSECUTIVE CORRECT")
    print("=" * 66)
    print("  answering divisibility, with one deliberate slip:")
    for correct in [True, True, False, True, True, True]:
        just = g.record_answer(mastery, "divisibility", correct)
        mark = "correct" if correct else "WRONG  "
        note = "   <- mastered" if just else ""
        print(f"    {mark}  streak now {g.progress(mastery, 'divisibility')}{note}")
    print("  the wrong answer reset the streak to 0 — consecutive means consecutive")

    print("\n" + "=" * 66)
    print("WALKING A LEARNING PATH")
    print("=" * 66)
    declared = G.meta["demo_path"]
    path = G.learning_path(declared)
    added = [n for n in path if n not in declared]
    print(f"  meta.demo_path lists {len(declared)} nodes.")
    if added:
        print("  It is NOT walkable on its own — learning_path() had to insert")
        print(f"  {', '.join(added)} to satisfy prerequisites.")
    else:
        print("  It is walkable as written: every node's prereqs come earlier.")
        print("  (validate() enforces this — it caught three violations here on")
        print("   2026-08-19, before the path was repaired.)")
    print()
    mastery = g.new_mastery(G)
    for node in path:
        assert G.is_unlocked(node, mastery), f"{node} was not unlocked!"
        before = {k: dict(v) for k, v in mastery.items()}
        # master it the honest way: MASTERY_STREAK correct answers in a row
        for _ in range(g.MASTERY_STREAK):
            g.record_answer(mastery, node, True)
        unlocked = G.newly_unlocked(before, mastery)
        opened = f"  unlocks: {', '.join(unlocked)}" if unlocked else "  unlocks: -"
        print(f"  mastered {node:<20}{opened}")
    print("\n  (every step asserted the node was actually unlocked first)")

    show(G, mastery, "after the whole path")

    still_locked = G.locked(mastery)
    print("\n" + "=" * 66)
    print("WHAT IS STILL LOCKED, AND WHY")
    print("=" * 66)
    for nid in still_locked:
        tier = G.tier(nid)
        if tier not in g.AUTHORED_TIERS:
            why = f"tier {tier} — never authored, locked by design"
        else:
            missing = [p for p in G.prereqs(nid) if not g.is_mastered(mastery, p)]
            why = f"needs {', '.join(missing)}"
        print(f"  {nid:<24} {why}")

    tiers_23 = [n for n in still_locked if G.tier(n) not in g.AUTHORED_TIERS]
    print(f"\n  {len(tiers_23)} of the {len(still_locked)} locked nodes are tier 2-3.")
    print("  They stay grey forever — that is what makes the graph look deep")
    print("  in the demo without authoring a single problem for them.")


if __name__ == "__main__":
    main()
