"""
layout.py — where each node sits in the graph view.

The layout is computed once at server start, not in the browser: the graph's
structure never changes at runtime (only its colours do), so shipping x,y in
/api/graph keeps graph.js down to "place circles, draw curves, swap classes".

Row = longest-path depth, not tier. Tier-rows would cram all 14 tier-1 nodes
into one unreadable line; depth spreads the DAG into ~13 narrow levels where
every edge points strictly downward — divisibility alone at the top, rsa at
the bottom, greyed depth below the student's coloured region.

Column = barycenter of prerequisites (a node hangs below the average of its
parents), ties broken by file order so the layout is identical run to run.
"""

WIDTH, HEIGHT = 900.0, 1300.0
MARGIN_X, MARGIN_Y = 80.0, 60.0

# Eyeballed horizontal corrections applied after the barycenter pass.
# Stays empty until the checkpoint-B eyeball test; fill in {node_id: dx}.
NUDGE = {}


def depths(graph):
    """Longest path from a root to each node. Topological order guarantees
    every prerequisite's depth exists before it is needed."""
    depth = {}
    for nid in graph.topological_order():
        ps = graph.prereqs(nid)
        depth[nid] = 0 if not ps else 1 + max(depth[p] for p in ps)
    return depth


def positions(graph):
    """{node_id: (x, y)} in a WIDTH x HEIGHT viewBox."""
    depth = depths(graph)
    n_levels = max(depth.values()) + 1

    rows = {}
    for nid in graph.order:  # file order — the deterministic tie-break
        rows.setdefault(depth[nid], []).append(nid)

    file_pos = {nid: i for i, nid in enumerate(graph.order)}
    pos = {}
    for level in range(n_levels):
        row = rows.get(level, [])

        def barycenter(nid):
            placed = [pos[p][0] for p in graph.prereqs(nid) if p in pos]
            return sum(placed) / len(placed) if placed else WIDTH / 2

        row.sort(key=lambda nid: (barycenter(nid), file_pos[nid]))

        step = (WIDTH - 2 * MARGIN_X) / (len(row) + 1)
        y = MARGIN_Y + (HEIGHT - 2 * MARGIN_Y) * (level / max(n_levels - 1, 1))
        for i, nid in enumerate(row, 1):
            x = MARGIN_X + step * i + NUDGE.get(nid, 0)
            pos[nid] = (round(x, 1), round(y, 1))
    return pos
