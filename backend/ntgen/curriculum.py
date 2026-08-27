"""
curriculum.py — parse and validate curriculum.md, the in-app teaching content.

One authored artifact: curriculum.md is human-editable AND what the app serves
(GET /api/curriculum). This module turns it into a payload and refuses to load
a malformed or DAG-inconsistent file — the process fails at boot, not in front
of a student.

Format contract (load-bearing, documented in curriculum.md's own preamble):

    # Tier <n> — <name>          starts a tier; next *italic* line is its blurb
    ## <number> <name>           starts a lesson (e.g. "## 1.5 Modular inverses")
    id: <node_id>                first line under the heading
    prereqs: <a, b> | none       second line
    **<Section>.** <text>        one paragraph per section
    # Beyond — ...               captured whole as the "beyond" text
    # Appendix — ...             ignored (builder notes, not student-facing)

Required sections per lesson: Concept, Key results, Worked example,
Common mistakes, Problem types. Optional: Implementation note.
"""

import re
from pathlib import Path


REQUIRED = ["concept", "key_results", "worked_example", "common_mistakes",
            "problem_types"]

# "**Worked example.** text" -> field name + text
_SECTION_NAMES = {
    "Concept": "concept",
    "Key results": "key_results",
    "Worked example": "worked_example",
    "Common mistakes": "common_mistakes",
    "Problem types": "problem_types",
    "Implementation note": "note",
}


class CurriculumError(Exception):
    """curriculum.md is malformed or disagrees with the DAG."""


def load_curriculum(path=None) -> dict:
    path = Path(path) if path else Path(__file__).parent / "curriculum.md"
    text = path.read_text(encoding="utf-8")

    tiers, lessons, beyond = [], {}, None
    tier = None          # current tier dict
    lesson = None        # current lesson dict
    mode = "preamble"    # preamble | tier | lesson | beyond | appendix

    def close_lesson():
        nonlocal lesson
        if lesson is None:
            return
        missing = [s for s in REQUIRED if not lesson.get(s)]
        if missing:
            raise CurriculumError(
                f"lesson {lesson.get('id') or lesson['number']}: "
                f"missing section(s) {missing}")
        if not lesson.get("id"):
            raise CurriculumError(f"lesson {lesson['number']}: no id: line")
        lessons[lesson["id"]] = lesson
        tier["lessons"].append(lesson["id"])
        lesson = None

    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue

        if block.startswith("## "):
            close_lesson()
            m = re.match(r"## (\d+\.\d+)\s+(.+)", block.splitlines()[0])
            if not m:
                raise CurriculumError(f"bad lesson heading: {block[:60]!r}")
            if tier is None:
                raise CurriculumError(f"lesson {m.group(1)} appears before any tier")
            lesson = {"number": m.group(1), "name": m.group(2).strip(),
                      "tier": tier["tier"]}
            mode = "lesson"
            continue

        if block.startswith("# "):
            close_lesson()
            head = block.splitlines()[0]
            m = re.match(r"# Tier (\d+) — (.+)", head)
            if m:
                tier = {"tier": int(m.group(1)), "name": m.group(2).strip(),
                        "blurb": "", "lessons": []}
                tiers.append(tier)
                mode = "tier"
            elif head.startswith("# Beyond"):
                beyond = "\n\n".join(block.splitlines()[1:]).strip()
                mode = "beyond"
            elif head.startswith("# Appendix"):
                mode = "appendix"
            else:
                mode = "preamble"
            continue

        if mode == "tier" and block.startswith("*") and block.endswith("*"):
            tier["blurb"] = block.strip("*").strip()
            continue

        if mode == "beyond":
            beyond = (beyond + "\n\n" + block) if beyond else block
            continue

        if mode == "lesson":
            m = re.match(r"id:\s*(\S+)\s*\nprereqs:\s*(.*)", block)
            if m:
                lesson["id"] = m.group(1)
                p = m.group(2).strip()
                lesson["prereqs"] = ([] if p == "none"
                                     else [x.strip() for x in p.split(",")])
                continue
            m = re.match(r"\*\*(.+?)\.\*\*\s*(.+)", block, re.DOTALL)
            if m:
                name = m.group(1)
                if name not in _SECTION_NAMES:
                    raise CurriculumError(
                        f"lesson {lesson.get('id') or lesson['number']}: "
                        f"unknown section {name!r}")
                lesson[_SECTION_NAMES[name]] = " ".join(m.group(2).split())
                continue
            raise CurriculumError(
                f"lesson {lesson.get('id') or lesson['number']}: "
                f"unrecognised block {block[:60]!r}")

    close_lesson()

    if not tiers or not lessons:
        raise CurriculumError("no tiers or no lessons parsed")
    return {"tiers": tiers, "lessons": lessons, "beyond": beyond or ""}


def validate(curriculum: dict, graph) -> None:
    """The doc is the source of truth for edges — so the doc and the DAG must
    agree exactly, and every authored node must have a lesson."""
    for lid, lesson in curriculum["lessons"].items():
        if lid not in graph:
            raise CurriculumError(f"lesson {lid}: no such node in the DAG")
        if graph.tier(lid) != lesson["tier"]:
            raise CurriculumError(
                f"lesson {lid}: doc says tier {lesson['tier']}, "
                f"DAG says tier {graph.tier(lid)}")
        doc_edges = sorted(lesson["prereqs"])
        dag_edges = sorted(graph.prereqs(lid))
        if doc_edges != dag_edges:
            raise CurriculumError(
                f"lesson {lid}: prereqs disagree — doc {doc_edges}, "
                f"DAG {dag_edges}")
    authored = {nid for nid in graph.order if graph.is_authored(nid)}
    missing = authored - set(curriculum["lessons"])
    if missing:
        raise CurriculumError(f"authored nodes with no lesson: {sorted(missing)}")
