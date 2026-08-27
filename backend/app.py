"""
app.py — the web layer over the ntgen engine.

    python3 backend/app.py        ->  http://127.0.0.1:5001

The dividing line: this file (and store/layout beside it) owns HTTP, identity
and persistence. Everything mathematical — generation, grading, the graph,
the diagnostic — is ntgen's, called through its public functions.

Two rules this file exists to enforce:

  1. Answers for GRADABLE problems never leave the server. problem_payload()
     is the ONLY place a Problem is serialized for the client, and
     backend/leaktest.py proves the rule mechanically. Grading happens here,
     server-side, always. The one deliberate exception is POST /api/reveal:
     it returns a worked solution, but only after the problem is retired —
     a revealed problem 410s on every later grade or reveal attempt.
  2. Unparseable input is not an attempt (PROJECT.md 5.3). It is logged,
     answered with "couldn't read that", and the same problem is re-served —
     record_answer is never called for it, so streaks cannot be hurt by typos.

Deployment note: run ONE OS process only (PythonAnywhere's default worker,
or gunicorn -w 1 --threads 4). The served-problem registry and the live
diagnostics are in memory; a second process would split them. Everything
durable is on disk, so a restart is a non-event — problems on screen are
rebuilt from the student file and grade identically.
"""

import random
import re
import sys
import uuid
from pathlib import Path

# ntgen uses flat imports (from graph import ...), so it goes on sys.path
# rather than becoming a package — its tested files stay untouched. backend/
# is added too so `gunicorn backend.app:app` can find store/layout.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "ntgen"))

from flask import Flask, jsonify, request  # noqa: E402

import bkt                                                   # noqa: E402
import graph as g                                            # noqa: E402
from diagnostic import Diagnostic                            # noqa: E402
from generator import (                                      # noqa: E402
    Problem, load_templates, load_hand_authored,
    hand_authored_problem, problem_for_node,
)
from verify import safe_eval                                 # noqa: E402
from steps import steps_for                                  # noqa: E402
import curriculum as curriculum_mod                          # noqa: E402

import layout                                                # noqa: E402
import store                                                 # noqa: E402

app = Flask(__name__, static_folder=str(_HERE.parent / "frontend"),
            static_url_path="")

# Loaded once at import; the process refuses to boot on broken data, which
# beats discovering it when a student hits the first endpoint.
G = g.load_graph()
G.validate()
TEMPLATES = load_templates()
HAND = load_hand_authored()
CURRICULUM = curriculum_mod.load_curriculum()
curriculum_mod.validate(CURRICULUM, G)
POSITIONS = layout.positions(G)
DEPTHS = layout.depths(G)   # longest-path depth: the dungeon's difficulty axis
RNG = random.Random()

# The knowledge-tracing model's fixed pieces: prerequisite adjacency, per-tier
# parameters, and the set of nodes problems exist for. Per-student state is
# just {node: P(mastered)} on disk; a KnowledgeState is rebuilt per request.
ADJ = {nid: G.prereqs(nid) for nid in G.order}
PARAMS = bkt.params_for_graph(G)
AUTHORED = set(G.authored_nodes())

SERVED = {}   # problem_id -> {"student", "purpose", "node", "problem"}
DIAGS = {}    # student key -> live Diagnostic


# ---------------------------------------------------------------------------
# Input guard
# ---------------------------------------------------------------------------

MAX_INPUT_LEN = 60


def unreadable(raw: str) -> bool:
    """
    App-layer guard in front of the grader.

    normalise() maps ^ to ** and sympify EVALUATES what it parses, so
    "9^9^9^9" (a power tower), "2^999999999" (a gigabyte integer) or
    "factorial(10**9)" would pin this single-process server forever. The
    sandbox in verify.py must not change, so the guard lives here instead:
    anything no legitimate answer ever looks like gets the same
    student-facing outcome as a typo — "couldn't read that", logged, not an
    attempt.

    Thresholds are set against the measured corpus (longest real answer 33
    chars, longest digit run 13 — a binary representation) and the leak
    test walks every template's answers through this guard to keep that
    true as templates are added.
    """
    s = str(raw)
    return (
        len(s) > MAX_INPUT_LEN
        or s.count("^") + s.count("**") >= 2                            # towers
        or re.search(r"(\^|\*\*)\s*\(?\s*-?\s*\d{6}", s) is not None    # huge exponents
        or re.search(r"[A-Za-z_]\s*\(", s) is not None                  # function calls
        or re.search(r"\d{20}", s) is not None                          # absurd literals
    )


# ---------------------------------------------------------------------------
# Serving problems
# ---------------------------------------------------------------------------

def problem_payload(pid: str, p: Problem) -> dict:
    """The ONLY serializer for a Problem. Params and template_id stay
    server-side too — together they recompute the answer."""
    return {
        "problem_id": pid,
        "node": p.node,
        "node_name": G.name(p.node),
        "prompt": p.prompt,
        "answer_format": p.answer_format,
    }


def serve_problem(state: dict, key: str, node: str, purpose: str):
    """Generate, register, persist. One outstanding problem per (student,
    purpose): serving a new one evicts the old, which bounds SERVED at two
    entries per student with no TTL bookkeeping."""
    p = problem_for_node(TEMPLATES, node, RNG, HAND)
    pid = uuid.uuid4().hex[:12]
    for old_pid, entry in list(SERVED.items()):
        if entry["student"] == key and entry["purpose"] == purpose:
            del SERVED[old_pid]
    SERVED[pid] = {"student": key, "purpose": purpose, "node": node, "problem": p}
    state["outstanding"] = {
        "problem_id": pid,
        "template_id": p.template_id,
        "params": store.jsonable(p.params),
        "node": node,
        "purpose": purpose,
    }
    store.save_student(key, state)
    return pid, p


def rebuild_problem(outstanding: dict):
    """Rebuild a served problem after a restart. Same template + same params
    -> same prompt, same answer, so the student never notices the server
    died with their problem on screen."""
    tid = outstanding["template_id"]
    if tid in HAND:
        return hand_authored_problem(HAND[tid])
    tpl = TEMPLATES.get(tid)
    if tpl is None:
        return None
    params = dict(outstanding["params"])
    sol = tpl.get("solution")
    answer = safe_eval(sol, params) if sol else None
    return Problem(tpl, params, tpl["prompt"].format(**params), answer)


def find_problem(state: dict, key: str, pid: str, purpose: str):
    """The Problem a submission refers to, surviving restarts. None means
    it is genuinely gone and the client should fetch a fresh one."""
    entry = SERVED.get(pid)
    if entry and entry["student"] == key and entry["purpose"] == purpose:
        return entry["problem"]
    out = state.get("outstanding")
    if out and out.get("problem_id") == pid and out.get("purpose") == purpose:
        p = rebuild_problem(out)
        if p is not None:
            SERVED[pid] = {"student": key, "purpose": purpose,
                           "node": out["node"], "problem": p}
            return p
    return None


# ---------------------------------------------------------------------------
# Knowledge state (Phase 2B: BKT is the mastery mechanic; the streak is UI)
# ---------------------------------------------------------------------------

def ensure_bkt(key: str, state: dict) -> None:
    """
    Lazy migration: student files written before Phase 2B have only the
    binary mastery dict. Map it onto probabilities once — mastered nodes
    just above the threshold, everything else at its tier prior — then one
    propagate so ancestors of mastered nodes read coherently. The unlocked
    seed is whatever the old rule had unlocked; unlocking is sticky, so a
    migration can only be generous, never a rug-pull. Streaks and attempts
    survive untouched: the pips resume exactly where the student left them.
    """
    if "bkt" in state:
        return
    mastery = state["mastery"]
    p = {nid: (bkt.P_MASTERED + 0.01) if mastery[nid]["mastered"]
         else PARAMS[nid].p_init
         for nid in G.order}
    ks = bkt.KnowledgeState(ADJ, PARAMS, p=p, authored=AUTHORED)
    ks.propagate()
    unlocked = [nid for nid in G.authored_nodes()
                if G.is_unlocked(nid, mastery) or mastery[nid]["mastered"]]
    state["bkt"] = {"version": 1, "p": ks.export(), "unlocked": unlocked}
    store.save_student(key, state)


def bkt_state(state: dict) -> bkt.KnowledgeState:
    return bkt.KnowledgeState(ADJ, PARAMS, p=state["bkt"]["p"],
                              authored=AUTHORED)


# ---------------------------------------------------------------------------
# Lesson rounds: a lesson is completed by passing a round of ROUND_SIZE
# practice problems with at least ROUND_PASS correct. The round record is
# separate from streak/attempts (those stay pure BKT/telemetry bookkeeping),
# and the verdict is computed here, server-side, never in the browser.
# ---------------------------------------------------------------------------

ROUND_SIZE = 3
ROUND_PASS = 2


def ensure_quiz(state: dict) -> None:
    # In-memory only: older student files gain the block lazily and it
    # reaches disk with the next save_student, so read-only routes never
    # rewrite a file just for loading it.
    state.setdefault("quiz", {})


def quiz_entry(state: dict, node: str) -> dict:
    return state["quiz"].setdefault(
        node, {"passed": False, "rounds": 0, "round": []})


def is_completed(state: dict, nid: str) -> bool:
    """A lesson is complete when a 2-of-3 round was passed OR the model
    already believes the node mastered. The second clause is what lets the
    diagnostic count: inferred mastery completes lessons with zero grinding."""
    q = state.get("quiz", {}).get(nid)
    if q is not None and q["passed"]:
        return True
    return state["bkt"]["p"].get(nid, 0.0) >= bkt.P_MASTERED


def effective_p(state: dict, pmap: dict) -> dict:
    """P-map for unlock decisions only: a quiz-passed node counts as
    at-threshold even when belief sits lower, so passing a round always
    unlocks the lessons behind it. Never written back to bkt.p, so the
    model's honest belief and the completion record cannot contaminate
    each other."""
    out = dict(pmap)
    for nid, q in state.get("quiz", {}).items():
        if q["passed"]:
            out[nid] = max(out.get(nid, 0.0), bkt.P_MASTERED)
    return out


def record_round_answer(state: dict, node: str, correct: bool) -> dict:
    """Append one result to the node's round; the third result settles the
    verdict and clears the round, so a retry is simply the next problem
    (every serve generates fresh params, so retry problems are new by
    construction). `passed` is sticky: review rounds after a pass can
    never un-complete a lesson."""
    q = quiz_entry(state, node)
    q["round"].append(bool(correct))
    results, verdict = list(q["round"]), None
    if len(results) >= ROUND_SIZE:
        verdict = "passed" if sum(results) >= ROUND_PASS else "failed"
        q["rounds"] += 1
        if verdict == "passed":
            q["passed"] = True
        q["round"] = []
    return {"index": len(results), "results": results, "verdict": verdict}


def round_payload(q: dict) -> dict:
    """The mid-round view (for /api/problem and the unparseable path):
    index is the 1-based slot the student is currently on."""
    return {"index": len(q["round"]) + 1, "results": list(q["round"]),
            "verdict": None}


def progress_str(p: float) -> str:
    """What the tooltip shows: 'mastered' past the threshold, else percent
    (floored, so 94.9% never reads as the 95 it hasn't reached)."""
    if p >= bkt.P_MASTERED:
        return "mastered"
    return f"{int(p * 100 + 1e-9)}%"


def node_status(nid: str, pmap: dict, unlocked: set) -> str:
    """Three states for the UI. Unlocking is sticky, colour is honest: a
    node that crossed 0.95 and later faded reads 'frontier' again —
    clickable, amber-ish, telling the truth."""
    if pmap[nid] >= bkt.P_MASTERED:
        return "mastered"
    if nid in unlocked:
        return "frontier"
    return "locked"


def moved_payload(moved: dict) -> dict:
    """The per-answer delta map the frontend animates. Sub-millipoint
    drift is noise, not news."""
    return {nid: round(d, 3) for nid, d in moved.items() if abs(d) >= 0.0005}


def state_payload(state: dict) -> dict:
    """Everything the graph view needs, straight off the engine."""
    mastery = state["mastery"]
    pmap = state["bkt"]["p"]
    unlocked = set(state["bkt"]["unlocked"])
    quiz = state.get("quiz", {})
    return {
        "nodes": {
            nid: {
                "status": node_status(nid, pmap, unlocked),
                "source": mastery[nid]["source"],
                "streak": mastery[nid]["streak"],
                "attempts": mastery[nid]["attempts"],
                "p": round(pmap[nid], 3),
                "progress": progress_str(pmap[nid]),
                "completed": is_completed(state, nid),
                "quiz_passed": bool(quiz.get(nid, {}).get("passed")),
                # The same sticky set the /api/problem 403 gate reads, so
                # the lessons page and practice can never disagree.
                "lesson_unlocked": nid in unlocked,
            }
            for nid in G.order
        },
        "frontier": [nid for nid in G.order
                     if nid in unlocked and pmap[nid] < bkt.P_MASTERED],
    }


def live_diag(key: str, state: dict) -> Diagnostic:
    """The student's diagnostic, rebuilt from history when memory is cold.
    A Diagnostic is a pure function of its answer history (deterministic
    tie-breaks), so replay IS recovery — refreshes and restarts land in
    exactly the same place."""
    d = DIAGS.get(key)
    if d is None:
        d = Diagnostic(G)
        for node, ok in state["diagnostic"]["history"]:
            d.record(node, bool(ok))
        DIAGS[key] = d
    return d


def finish_diagnostic(key: str, state: dict, d: Diagnostic) -> dict:
    """Persist result() exactly once, at the moment the search completes.
    The calibrated probabilities and the unlock seed replace the BKT block;
    streaks and attempts are NOT touched (they are UI history, not belief)."""
    res = d.result()
    state["bkt"] = {"version": 1, "p": res["p"], "unlocked": res["unlocked"]}
    for nid, src in res["source"].items():
        state["mastery"][nid]["source"] = src
    state["diagnostic"]["done"] = True
    state["outstanding"] = None
    store.save_student(key, state)
    DIAGS.pop(key, None)
    return {
        "done": True,
        "question_number": d.asked,
        "max_questions": d.max_questions,
        "summary": d.summary(),
        "status": state_payload(state),
    }


def load_or_404(key: str):
    state = store.load_student(key)
    if state is None:
        return None, (jsonify({"error": "unknown_student"}), 404)
    ensure_bkt(key, state)
    ensure_quiz(state)
    ensure_dungeon(state)
    return state, None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/api/login")
def login():
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
    key = store.slugify(name)
    if not key:
        return jsonify({"error": "name_required"}), 400
    with store.LOCK:
        state = store.load_student(key)
        if state is None:
            state = {
                "display_name": name,
                "created": store.timestamp(),
                "mastery": g.new_mastery(G),
                "diagnostic": {"done": False, "history": []},
                "outstanding": None,
            }
            store.save_student(key, state)
        ensure_bkt(key, state)
        ensure_dungeon(state)
    phase = "practice" if state["diagnostic"]["done"] else "diagnostic"
    dg = state["dungeon"]
    return jsonify({"student": key,
                    "display_name": state["display_name"],
                    "phase": phase,
                    # equipped cosmetics ride on login so every page can
                    # dress the header without an extra request; title is
                    # the display label, color an id the CSS maps to a hue
                    "color": dg["cosmetics"]["color"],
                    "title": title_label(dg)})


@app.get("/api/graph")
def graph_route():
    # Pure structure — no student data, fetched once and cached client-side.
    return jsonify({
        "nodes": [
            {"id": nid, "name": G.name(nid), "tier": G.tier(nid),
             "authored": G.is_authored(nid),
             "x": POSITIONS[nid][0], "y": POSITIONS[nid][1]}
            for nid in G.order
        ],
        "edges": [[p, nid] for nid in G.order for p in G.prereqs(nid)],
    })


@app.get("/api/state")
def state_route():
    key = store.slugify(request.args.get("student", ""))
    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        return jsonify(state_payload(state))


@app.post("/api/diagnostic/start")
def diagnostic_start():
    key = store.slugify((request.get_json(silent=True) or {}).get("student", ""))
    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        if state["diagnostic"]["done"]:
            d = live_diag(key, state)
            return jsonify({"done": True, "summary": d.summary(),
                            "status": state_payload(state)})
        d = live_diag(key, state)

        # After a refresh the SAME question comes back, not a reroll.
        out = state.get("outstanding")
        pid, p = None, None
        if out and out.get("purpose") == "diagnostic":
            pid = out["problem_id"]
            p = find_problem(state, key, pid, "diagnostic")
        if p is None:
            node = d.next_node()
            if node is None:
                return jsonify(finish_diagnostic(key, state, d))
            pid, p = serve_problem(state, key, node, "diagnostic")
        return jsonify({
            "done": False,
            "question_number": d.asked + 1,
            "max_questions": d.max_questions,
            "problem": problem_payload(pid, p),
        })


@app.post("/api/diagnostic/answer")
def diagnostic_answer():
    body = request.get_json(silent=True) or {}
    key = store.slugify(body.get("student", ""))
    pid = str(body.get("problem_id", ""))
    skip = bool(body.get("skip"))
    raw = "" if skip else str(body.get("answer", ""))

    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        if state["diagnostic"]["done"]:
            return jsonify({"error": "diagnostic_done"}), 409
        p = find_problem(state, key, pid, "diagnostic")
        if p is None:
            return jsonify({"error": "problem_expired"}), 410
        d = live_diag(key, state)

        if skip:
            grade = "wrong"
        elif unreadable(raw):
            grade = "unparseable"
        else:
            grade = p.grade(raw)

        store.log_event({
            "student": key, "purpose": "diagnostic", "node": p.node,
            "template_id": p.template_id, "params": p.params,
            "raw": None if skip else raw, "grade": grade, "skipped": skip,
        })

        if grade == "unparseable":
            # Not an attempt: the same question returns and question_number
            # holds — a typo cannot consume one of the six questions.
            return jsonify({
                "grade": grade,
                "done": False,
                "question_number": d.asked + 1,
                "max_questions": d.max_questions,
                "problem": problem_payload(pid, p),
            })

        correct = grade == "correct"
        moved = d.record(p.node, correct)
        state["diagnostic"]["history"].append([p.node, correct])
        state["outstanding"] = None
        SERVED.pop(pid, None)

        if d.is_done() or d.next_node() is None:
            resp = finish_diagnostic(key, state, d)
            resp["grade"] = grade
            resp["moved"] = moved_payload(moved)
            return jsonify(resp)

        new_pid, new_p = serve_problem(state, key, d.next_node(), "diagnostic")
        return jsonify({
            "grade": grade,
            "done": False,
            "question_number": d.asked + 1,
            "max_questions": d.max_questions,
            # what this one answer did to the model — the frontend's
            # "updated N skills" moment
            "moved": moved_payload(moved),
            "problem": problem_payload(new_pid, new_p),
        })


@app.get("/api/problem")
def problem_route():
    key = store.slugify(request.args.get("student", ""))
    node = request.args.get("node", "")
    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        if node not in G:
            return jsonify({"error": "unknown_node"}), 404
        # The sticky unlocked set is the single serving gate: mastered nodes
        # stay practicable for review (they're in it), tier 2/3 never enter
        # it, and a faded former-master is still in it. Passed quiz rounds
        # feed it too (via effective_p in answer_route), so a lesson shown
        # unlocked on /learn is always servable here. Locked never serves.
        if node not in state["bkt"]["unlocked"]:
            return jsonify({"error": "node_locked"}), 403
        pid, p = serve_problem(state, key, node, "practice")
        q = quiz_entry(state, node)
        return jsonify({
            "problem": problem_payload(pid, p),
            "streak": state["mastery"][node]["streak"],
            "progress": progress_str(state["bkt"]["p"][node]),
            "round": round_payload(q),
            "quiz_passed": q["passed"],
            "completed": is_completed(state, node),
        })


@app.post("/api/answer")
def answer_route():
    body = request.get_json(silent=True) or {}
    key = store.slugify(body.get("student", ""))
    pid = str(body.get("problem_id", ""))
    raw = str(body.get("answer", ""))

    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        p = find_problem(state, key, pid, "practice")
        if p is None:
            return jsonify({"error": "problem_expired"}), 410

        grade = "unparseable" if unreadable(raw) else p.grade(raw)
        store.log_event({
            "student": key, "purpose": "practice", "node": p.node,
            "template_id": p.template_id, "params": p.params,
            "raw": raw, "grade": grade, "skipped": False,
        })

        mastery = state["mastery"]
        if grade == "unparseable":
            # Streak untouched, model untouched, round slot untouched,
            # problem still live — the student retypes. A typo is not
            # evidence about anything and never consumes a round slot.
            return jsonify({
                "grade": grade,
                "streak": mastery[p.node]["streak"],
                "progress": progress_str(state["bkt"]["p"][p.node]),
                "just_mastered": False,
                "newly_unlocked": [],
                "hint": None,
                "round": round_payload(quiz_entry(state, p.node)),
            })

        # Streak/attempts keep their old bookkeeping (they drive the pips and
        # week-3 telemetry); BELIEF is the model's. record_answer's mastered
        # flag is vestigial now — its return value is deliberately ignored.
        g.record_answer(mastery, p.node, grade == "correct")

        ks = bkt_state(state)
        p_before = ks.p[p.node]
        moved = ks.observe(p.node, grade == "correct")
        state["bkt"]["p"] = ks.export()
        just_mastered = p_before < bkt.P_MASTERED <= ks.p[p.node]
        # Round before unlock: a round passed by THIS answer must feed the
        # unlock decision in this same response, so the child appears in
        # newly_unlocked the moment the verdict lands. effective_p treats
        # quiz-passed nodes as at-threshold; bkt.unlock_additions itself
        # is unchanged.
        rnd = record_round_answer(state, p.node, grade == "correct")
        additions = bkt.unlock_additions(G.authored_nodes(), G.prereqs,
                                         effective_p(state, ks.p),
                                         state["bkt"]["unlocked"])
        state["bkt"]["unlocked"].extend(additions)

        state["outstanding"] = None
        SERVED.pop(pid, None)
        store.save_student(key, state)

        return jsonify({
            "grade": grade,
            "streak": mastery[p.node]["streak"],
            "progress": progress_str(ks.p[p.node]),
            "just_mastered": just_mastered,
            "newly_unlocked": additions,
            "moved": moved_payload(moved),
            # The hint, never the answer — the next problem is fresh anyway.
            "hint": (p.hint or None) if grade == "wrong" else None,
            "round": rnd,
            "lesson_completed": is_completed(state, p.node),
            "status": state_payload(state),
        })


@app.post("/api/reveal")
def reveal_route():
    """Give up on the current practice problem: streak resets, the problem
    is retired, and only then does a worked solution leave the server.

    A surrender is NOT an attempt (PROJECT.md 5.3) — reset_streak touches
    nothing but the streak, and the event logs as grade "revealed" so week-3
    analysis can count surrenders separately. Practice only: a diagnostic
    problem_id mismatches on purpose inside find_problem and 410s.
    """
    body = request.get_json(silent=True) or {}
    key = store.slugify(body.get("student", ""))
    pid = str(body.get("problem_id", ""))

    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        p = find_problem(state, key, pid, "practice")
        if p is None:
            return jsonify({"error": "problem_expired"}), 410

        store.log_event({
            "student": key, "purpose": "practice", "node": p.node,
            "template_id": p.template_id, "params": p.params,
            "raw": None, "grade": "revealed", "skipped": False,
        })

        # The cost, then the retirement — persisted BEFORE the solution
        # exists in any response. Both resurrection paths (SERVED and the
        # persisted outstanding) die here, so a revealed problem can never
        # be graded: the 410 survives even a server restart.
        #
        # A surrender is also EVIDENCE: the wrong-answer posterior with no
        # learning credit (mastery is earned by answering, not by reading),
        # propagated like any observation. Still not an attempt.
        mastery = state["mastery"]
        g.reset_streak(mastery, p.node)
        ks = bkt_state(state)
        moved = ks.observe_reveal(p.node)
        state["bkt"]["p"] = ks.export()
        # A reveal is a wrong slot in the round; otherwise the 2-of-3 check
        # is gameable by reading the worked solution mid-round for free.
        # The round is its own record: record_answer still never fires here,
        # so "a surrender is not an attempt" stays literally true. No unlock
        # call either: a reveal never raises belief and never passes a
        # round, so nothing new can unlock.
        rnd = record_round_answer(state, p.node, False)
        state["outstanding"] = None
        SERVED.pop(pid, None)
        store.save_student(key, state)

        return jsonify({
            "steps": steps_for(p),
            "streak": mastery[p.node]["streak"],
            "progress": progress_str(ks.p[p.node]),
            "moved": moved_payload(moved),
            "round": rnd,
            "status": state_payload(state),
        })


# ---------------------------------------------------------------------------
# Dungeon runs: the Challenges page's game mode. A run is a small server-side
# state machine (hearts, streak, score, boss gauntlet) living in the student
# file; rooms are ordinary served problems with purpose "dungeon", so the
# answer pipeline, the leak test and the node_locked invariant all apply
# unchanged. The client renders snapshots of this state and never computes
# a verdict, a heart, or a point.
# ---------------------------------------------------------------------------

DUNGEON_LIVES = 3
BOSS_EVERY = 5      # room 5, 10, 15... is a boss
BOSS_SIZE = 3       # gauntlet length; need BOSS_PASS correct to win
BOSS_PASS = 2
SCORE_BASE = 10
BOSS_BONUS = 100

# (bosses_beaten needed, kind, id, label). Unlocks are DERIVED from the one
# persisted counter, so there is nothing to migrate and nothing to forge.
# Color ids map to CSS custom properties client-side; no hex leaves here.
COSMETIC_LADDER = [
    (1,  "color", "sage",   "Sage"),
    (2,  "title", "prime_slayer",       "Prime Slayer"),
    (3,  "color", "teal",   "Teal"),
    (4,  "title", "modular_marauder",   "Modular Marauder"),
    (5,  "color", "sky",    "Sky"),
    (6,  "title", "divisor_of_destiny", "Divisor of Destiny"),
    (8,  "color", "violet", "Violet"),
    (10, "title", "euclids_heir",       "Euclid's Heir"),
    (12, "color", "amber",  "Amber"),
    (15, "title", "keeper_of_residues", "Keeper of Residues"),
    (20, "color", "rose",   "Rose"),
    (25, "title", "frontier_legend",    "Frontier Legend"),
]


def ensure_dungeon(state: dict) -> None:
    # Same lazy pattern as ensure_quiz: in memory now, on disk with the
    # next save_student.
    state.setdefault("dungeon", {
        "run": None,
        "records": {"best_depth": 0, "runs": 0, "bosses_beaten": 0},
        "cosmetics": {"color": None, "title": None},
    })


def streak_multiplier(streak: int) -> int:
    # 0-2 -> x1, 3-5 -> x2, 6-9 -> x3, 10+ -> x4
    if streak >= 10:
        return 4
    if streak >= 6:
        return 3
    if streak >= 3:
        return 2
    return 1


def run_ladder(state: dict) -> list:
    """The run's difficulty ramp: the student's unlocked authored nodes,
    shallowest first. Built from the same sticky set the /api/problem 403
    gate reads, so the dungeon cannot serve a locked node. Snapshotted at
    run start: mid-run unlocks extend the sticky set but never reshuffle a
    live run — the NEXT run picks them up."""
    unlocked = set(state["bkt"]["unlocked"])
    # iterating G.order makes the depth-sort's tie-break file order, the
    # same determinism rule the layout uses
    return sorted((n for n in G.order if n in unlocked and n in AUTHORED),
                  key=lambda n: DEPTHS[n])


def room_is_boss(room: int) -> bool:
    return room % BOSS_EVERY == 0


def ensure_boss(run: dict) -> None:
    if room_is_boss(run["room"]) and run["boss"] is None:
        run["boss"] = {"results": []}


def room_node(run: dict) -> str:
    """Which node the current room draws from. A pure function of the run
    state, so a refresh or server restart lands in the same room asking
    about the same skill."""
    ladder = run["ladder"]
    deep = ladder[-min(3, len(ladder)):]
    if room_is_boss(run["room"]):
        # bosses pull from the deepest unlocked skills, one per gauntlet slot
        return deep[len(run["boss"]["results"]) % len(deep)]
    # ordinal among non-boss rooms: room 6 is the 5th ordinary room
    i = run["room"] - 1 - (run["room"] - 1) // BOSS_EVERY
    if i < len(ladder):
        return ladder[i]
    return deep[(i - len(ladder)) % len(deep)]   # past the end: stay deep


def dungeon_run_payload(run: dict) -> dict:
    return {
        "lives": run["lives"],
        "room": run["room"],
        "depth": run["depth"],
        "streak": run["streak"],
        "multiplier": streak_multiplier(run["streak"]),
        "score": run["score"],
        "is_boss": room_is_boss(run["room"]),
        # same index/results shape as the lesson round payload, so the
        # frontend pip code and the leak-test allowlist are both reused
        "boss": ({"index": len(run["boss"]["results"]) + 1,
                  "results": list(run["boss"]["results"])}
                 if run["boss"] else None),
    }


def dungeon_records_payload(dg: dict) -> dict:
    return dict(dg["records"])


def cosmetics_payload(dg: dict) -> dict:
    n = dg["records"]["bosses_beaten"]
    return {
        "color": dg["cosmetics"]["color"],
        "title": dg["cosmetics"]["title"],
        "ladder": [{"at": at, "kind": kind, "id": cid, "label": label,
                    "unlocked": n >= at}
                   for at, kind, cid, label in COSMETIC_LADDER],
    }


def title_label(dg: dict):
    tid = dg["cosmetics"]["title"]
    if not tid:
        return None
    for _at, kind, cid, label in COSMETIC_LADDER:
        if kind == "title" and cid == tid:
            return label
    return None


def end_run(state: dict, key: str) -> bool:
    """Death and flee share this: record the depth, count the run, clear it.
    Returns whether this run set a new best. Retires any dungeon problem
    still on screen so a dead run's problem 410s forever."""
    dg = state["dungeon"]
    run = dg["run"]
    new_best = run["depth"] > dg["records"]["best_depth"]
    dg["records"]["best_depth"] = max(dg["records"]["best_depth"], run["depth"])
    dg["records"]["runs"] += 1
    dg["run"] = None
    out = state.get("outstanding")
    if out and out.get("purpose") == "dungeon":
        state["outstanding"] = None
    for old_pid, entry in list(SERVED.items()):
        if entry["student"] == key and entry["purpose"] == "dungeon":
            del SERVED[old_pid]
    return new_best


@app.get("/api/dungeon/state")
def dungeon_state_route():
    key = store.slugify(request.args.get("student", ""))
    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        dg = state["dungeon"]
        return jsonify({"records": dungeon_records_payload(dg),
                        "cosmetics": cosmetics_payload(dg),
                        "active": dg["run"] is not None})


@app.post("/api/dungeon/start")
def dungeon_start():
    key = store.slugify((request.get_json(silent=True) or {}).get("student", ""))
    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        # the ladder is built from the diagnostic's unlock seed; without a
        # placement there is no ladder to climb
        if not state["diagnostic"]["done"]:
            return jsonify({"error": "diagnostic_required"}), 409
        dg = state["dungeon"]
        resuming = dg["run"] is not None
        if not resuming:
            ladder = run_ladder(state)
            if not ladder:
                return jsonify({"error": "diagnostic_required"}), 409
            dg["run"] = {"lives": DUNGEON_LIVES, "room": 1, "depth": 0,
                         "streak": 0, "score": 0, "ladder": ladder,
                         "boss": None}
        run = dg["run"]
        ensure_boss(run)

        # After a refresh the SAME problem comes back, not a reroll — but
        # only for a run that already existed; a fresh run never adopts a
        # stale problem.
        pid, p = None, None
        out = state.get("outstanding")
        if resuming and out and out.get("purpose") == "dungeon":
            pid = out["problem_id"]
            p = find_problem(state, key, pid, "dungeon")
        if p is None:
            pid, p = serve_problem(state, key, room_node(run), "dungeon")
        return jsonify({
            "run": dungeon_run_payload(run),
            "problem": problem_payload(pid, p),
            "records": dungeon_records_payload(dg),
            "cosmetics": cosmetics_payload(dg),
        })


@app.post("/api/dungeon/answer")
def dungeon_answer():
    body = request.get_json(silent=True) or {}
    key = store.slugify(body.get("student", ""))
    pid = str(body.get("problem_id", ""))
    raw = str(body.get("answer", ""))

    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        dg = state["dungeon"]
        run = dg["run"]
        if run is None:
            return jsonify({"error": "no_active_run"}), 409
        # The outstanding slot is shared with lesson practice; if a lesson
        # answer evicted this problem (or a restart lost it), the 410 sends
        # the client back through /start, which re-serves the SAME room —
        # hearts, depth and score live in the run, not the problem, so
        # nothing is lost.
        p = find_problem(state, key, pid, "dungeon")
        if p is None:
            return jsonify({"error": "problem_expired"}), 410

        grade = "unparseable" if unreadable(raw) else p.grade(raw)
        store.log_event({
            "student": key, "purpose": "dungeon", "node": p.node,
            "template_id": p.template_id, "params": p.params,
            "raw": raw, "grade": grade, "skipped": False,
        })

        if grade == "unparseable":
            # A typo is not an attempt anywhere in this app: no heart, no
            # streak reset, same problem stays on screen.
            return jsonify({
                "grade": grade, "outcome": None, "gained": 0,
                "run": dungeon_run_payload(run),
                "hint": None, "newly_unlocked": [], "reward": None,
                "records": dungeon_records_payload(dg), "new_best": False,
                "problem": problem_payload(pid, p),
            })

        correct = grade == "correct"
        # Dungeon answers are real evidence: telemetry and belief update
        # exactly as in practice, so a good run can unlock new lessons.
        # record_round_answer is deliberately NOT called — the 2-of-3
        # lesson record is the lessons page's; the boss keeps its own.
        g.record_answer(state["mastery"], p.node, correct)
        ks = bkt_state(state)
        ks.observe(p.node, correct)
        state["bkt"]["p"] = ks.export()
        additions = bkt.unlock_additions(G.authored_nodes(), G.prereqs,
                                         effective_p(state, ks.p),
                                         state["bkt"]["unlocked"])
        state["bkt"]["unlocked"].extend(additions)

        gained, reward, outcome = 0, None, None
        if room_is_boss(run["room"]):
            run["boss"]["results"].append(correct)
            if correct:
                # streak first, then the multiplier — three corrects from
                # zero score 10, 10, 20
                run["streak"] += 1
                gained = SCORE_BASE * streak_multiplier(run["streak"])
                run["score"] += gained
            else:
                run["streak"] = 0
            wins = sum(run["boss"]["results"])
            losses = len(run["boss"]["results"]) - wins
            if wins >= BOSS_PASS:
                outcome = "boss_won"
                run["score"] += BOSS_BONUS
                gained += BOSS_BONUS
                run["depth"] += 1
                run["room"] += 1
                run["boss"] = None
                dg["records"]["bosses_beaten"] += 1
                for at, kind, cid, label in COSMETIC_LADDER:
                    if at == dg["records"]["bosses_beaten"]:
                        reward = {"kind": kind, "id": cid, "label": label}
                        break
            elif losses > BOSS_SIZE - BOSS_PASS:
                # the gauntlet is one fight: losing it costs exactly one
                # heart, however many of the three were missed
                outcome = "boss_lost"
                run["lives"] -= 1
                run["boss"] = {"results": []}
            else:
                outcome = "boss_progress"
        else:
            if correct:
                run["streak"] += 1
                gained = SCORE_BASE * streak_multiplier(run["streak"])
                run["score"] += gained
                run["depth"] += 1
                run["room"] += 1
                outcome = "advance"
            else:
                run["lives"] -= 1
                run["streak"] = 0
                outcome = "retry"   # same room, fresh problem

        state["outstanding"] = None
        SERVED.pop(pid, None)

        new_best, next_problem = False, None
        if run["lives"] <= 0:
            outcome = "dead"
            snapshot = dungeon_run_payload(run)   # final state, 0 hearts
            new_best = end_run(state, key)
            store.save_student(key, state)
        else:
            ensure_boss(run)   # advancing may have landed on a boss door
            npid, np = serve_problem(state, key, room_node(run), "dungeon")
            next_problem = problem_payload(npid, np)
            snapshot = dungeon_run_payload(run)

        return jsonify({
            "grade": grade,
            "outcome": outcome,
            "gained": gained,
            "run": snapshot,
            "hint": (p.hint or None) if grade == "wrong" else None,
            "newly_unlocked": additions,
            "reward": reward,
            "records": dungeon_records_payload(dg),
            "new_best": new_best,
            "problem": next_problem,
        })


@app.post("/api/dungeon/flee")
def dungeon_flee():
    key = store.slugify((request.get_json(silent=True) or {}).get("student", ""))
    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        dg = state["dungeon"]
        if dg["run"] is None:
            return jsonify({"error": "no_active_run"}), 409
        new_best = end_run(state, key)
        store.save_student(key, state)
        return jsonify({"records": dungeon_records_payload(dg),
                        "cosmetics": cosmetics_payload(dg),
                        "active": False, "new_best": new_best})


@app.post("/api/dungeon/cosmetic")
def dungeon_cosmetic():
    body = request.get_json(silent=True) or {}
    key = store.slugify(body.get("student", ""))
    with store.LOCK:
        state, err = load_or_404(key)
        if err:
            return err
        dg = state["dungeon"]
        n = dg["records"]["bosses_beaten"]
        for kind in ("color", "title"):
            if kind not in body:
                continue
            value = body[kind]
            if value is None:
                dg["cosmetics"][kind] = None
                continue
            step = next((s for s in COSMETIC_LADDER
                         if s[1] == kind and s[2] == value), None)
            if step is None:
                return jsonify({"error": "unknown_cosmetic"}), 404
            if n < step[0]:
                # the server owns the ladder: an unearned id is refused no
                # matter what the client claims
                return jsonify({"error": "cosmetic_locked"}), 403
            dg["cosmetics"][kind] = value
        store.save_student(key, state)
        return jsonify({"cosmetics": cosmetics_payload(dg)})


@app.get("/api/curriculum")
def curriculum_route():
    # Static teaching content, open to read — lessons carry no student data
    # and no problem answers (worked examples are fixed pedagogy, not keys).
    return jsonify(CURRICULUM)


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/learn")
def learn_page():
    return app.send_static_file("learn.html")


@app.get("/practice")
def practice_page():
    return app.send_static_file("practice.html")


if __name__ == "__main__":
    # threaded is fine (store.LOCK serializes mutation); a second PROCESS is
    # not — see the module docstring. debug stays off: the werkzeug debugger
    # is remote code execution, and the reloader would wipe SERVED/DIAGS.
    # Port 5001, not 5000: macOS AirPlay Receiver squats on 5000 and answers
    # 403 whenever this app is down, which reads as an authorization bug.
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
