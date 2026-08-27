"""
leaktest.py — proves no answer ever leaves the server.

    python3 backend/leaktest.py    (exit 0 = pass)

Runs beside backend/ntgen/selftest.py as the second half of the standing gate:

    python3 backend/ntgen/selftest.py && python3 backend/leaktest.py

It drives full sessions through the API in-process (Flask test_client, no
network, no server) and holds every response to four checks:

  1. Key allowlist — every dict key in every response must be expected.
     A future debug field that dumps a Problem fails here.
  2. Forbidden keys — answer, solution, params, template_id etc. hard-fail
     anywhere (params + template_id together recompute the answer).
  3. Problem payloads carry EXACTLY the five public fields.
  4. Answer-value scan — the computed answer of every problem served in the
     session must not appear anywhere in the response outside display text.

It also asserts the behavioural rules the UI will rely on: unparseable input
advances nothing (PROJECT.md 5.3), skip consumes a diagnostic question, a
server restart mid-problem grades identically after the rebuild, and the
input guard in app.py rejects no legitimate answer in the whole corpus.

One deliberate exception to "no answer ever": POST /api/reveal (give up)
returns a worked solution — but only for a problem the server has already
retired. reveal_check() proves the retirement is total: the revealed
problem 410s on every later grade or reveal, even across a restart, and a
surrender never counts as an attempt.
"""

import json
import os
import random
import re
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "ntgen"))

# Point the store at a throwaway directory BEFORE the app is imported, so
# nothing here can ever touch real student files.
os.environ["NTGEN_DATA_DIR"] = tempfile.mkdtemp(prefix="ntgen-leaktest-")

import app as webapp                    # noqa: E402
from generator import generate          # noqa: E402
from selftest import format_variants    # noqa: E402
from verify import is_sentinel, safe_eval  # noqa: E402


NODE_IDS = set(webapp.G.order)

ALLOWED_KEYS = {
    # problem payload (exactly these five inside "problem")
    "problem_id", "node", "node_name", "prompt", "answer_format", "problem",
    # session
    "student", "display_name", "phase", "ok", "error",
    # diagnostic
    "done", "question_number", "max_questions", "summary", "questions",
    "tested_pass", "tested_fail", "inferred_mastered", "inferred_locked",
    # graph + state
    "nodes", "edges", "status", "source", "streak", "attempts", "progress",
    "frontier", "id", "name", "tier", "authored", "x", "y",
    # grading
    "grade", "just_mastered", "newly_unlocked", "hint",
    # lesson rounds (the 2-of-3 quiz): booleans and slot counters only,
    # no answer material can travel through them
    "round", "index", "results", "verdict", "completed", "quiz_passed",
    "lesson_completed", "lesson_unlocked", "rounds",
    # knowledge tracing: per-node P(mastered) and the per-answer delta map
    "p", "moved",
    # the reveal's worked solution — the one answer-bearing field, and only
    # ever for an already-retired problem (see reveal_check)
    "steps",
    # dungeon runs: booleans, enums, cosmetic ids/labels and slot counters
    # only — no answer material can travel through any of them
    "run", "lives", "room", "depth", "score", "multiplier", "gained",
    "is_boss", "boss", "outcome", "reward", "kind", "label", "at",
    "records", "best_depth", "runs", "bosses_beaten", "new_best",
    "cosmetics", "color", "title", "ladder", "unlocked", "active",
    # curriculum payload (static teaching content, /api/curriculum)
    "tiers", "lessons", "blurb", "number", "prereqs", "concept",
    "key_results", "worked_example", "common_mistakes", "problem_types",
    "note", "beyond",
} | NODE_IDS

FORBIDDEN_KEYS = {
    "answer", "_answer", "solution", "check_spec", "also_accept", "selftest",
    "distractor_expr", "distractor_note", "why", "params", "template_id",
}

PROBLEM_KEYS = {"problem_id", "node", "node_name", "prompt", "answer_format"}

# Removed before the answer-value scan: display text that legitimately
# contains numbers (a prompt contains its params), structural counters, and
# random ids. Everything that survives is enums and node ids — any answer
# value found there is a real leak.
SCRUB = {
    "prompt", "answer_format", "hint", "node_name", "name", "display_name",
    "created", "updated", "ts", "streak", "attempts", "question_number",
    "max_questions", "x", "y", "tier", "questions", "progress", "problem_id",
    # round slot counters: 1..3 by construction, not answer material
    "index", "rounds",
    # dungeon numerics: hearts, floors, points and boss-count thresholds —
    # small structural integers that would false-positive against small
    # served answers exactly like the round counters above
    "lives", "room", "depth", "score", "multiplier", "gained", "at",
    "best_depth", "runs", "bosses_beaten",
    # identity echo — the client sent this value itself, it can't leak
    "student",
    # the reveal's steps deliberately state the answer of a RETIRED problem;
    # selftest's check #7 is the compensating control on their content
    "steps",
    # curriculum prose legitimately contains numbers (worked examples,
    # formulas) — fixed pedagogy, not answer keys
    "blurb", "concept", "key_results", "worked_example", "common_mistakes",
    "problem_types", "note", "beyond", "number",
    # knowledge-tracing floats: "0.87" stringifies containing "87" — a pure
    # model probability would false-positive against a served answer of 87
    "p", "moved",
}


def fmt(value):
    if isinstance(value, (tuple, list)):
        return ", ".join(str(v) for v in value)
    return str(value)


def correct_answer(p):
    """What a right student would type. Condition-checked problems have no
    stored answer, so one is built from the template's own selftest.good."""
    a = p._answer
    if a is None:
        a = safe_eval(p._template["selftest"]["good"][0], p.params)
    if is_sentinel(a) or (isinstance(a, (list, tuple)) and len(a) == 0):
        return "none"  # an empty solution set is answered in words
    return fmt(a)


def wrong_answer_for(p):
    """Something this problem definitely grades wrong — never unparseable,
    since that would not consume the attempt we are trying to test."""
    for cand in ["0", "1", "none", "-1", "0, 0", "zzz"]:
        if p.grade(cand) == "wrong":
            return cand
    raise AssertionError(f"no wrong answer found for {p.prompt}")


# ---------------------------------------------------------------------------
# Response checking
# ---------------------------------------------------------------------------

def _walk_keys(obj, path, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                out.append(f"forbidden key {k!r} at {path}")
            elif k not in ALLOWED_KEYS:
                out.append(f"unexpected key {k!r} at {path}")
            _walk_keys(v, f"{path}.{k}", out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_keys(v, f"{path}[{i}]", out)


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in SCRUB}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _leaves(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _leaves(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _leaves(v, out)
    else:
        out.append(obj)


class Checker:
    """Accumulates every answer served during a session and audits every
    response against all of them."""

    def __init__(self):
        self.answers = set()
        self.problems = []
        self.checked = 0

    def note_problem(self, p):
        self.answers.add(correct_answer(p))
        if p._answer is not None:
            self.answers.add(str(p._answer))

    def audit(self, url, body):
        self.checked += 1
        out = []
        _walk_keys(body, url, out)

        for container in [body] + ([body["status"]] if isinstance(body.get("status"), dict) else []):
            prob = container.get("problem") if isinstance(container, dict) else None
            if isinstance(prob, dict) and set(prob) != PROBLEM_KEYS:
                out.append(f"problem payload keys {sorted(prob)} != expected at {url}")

        leaves = []
        _leaves(_scrub(body), leaves)
        for a in self.answers:
            for leaf in leaves:
                s = str(leaf)
                if (len(a) >= 2 and a in s) or (len(a) == 1 and a == s):
                    out.append(f"answer value {a!r} leaked in {url}: {s!r}")
        for f in out:
            self.problems.append(f)


# ---------------------------------------------------------------------------
# Session driver
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, name, checker):
        self.c = webapp.app.test_client()
        self.checker = checker
        self.name = name
        body = self.post("/api/login", {"name": name})
        self.key = body["student"]

    def _audit(self, url, resp):
        body = resp.get_json()
        assert body is not None, f"non-JSON response from {url}"
        # register any served problem's answer BEFORE auditing, so the very
        # response that introduces a problem is scanned against its answer
        prob = body.get("problem")
        if isinstance(prob, dict):
            entry = webapp.SERVED.get(prob.get("problem_id"))
            if entry:
                self.checker.note_problem(entry["problem"])
        self.checker.audit(url, body)
        return body

    def post(self, url, payload, expect=200):
        r = self.c.post(url, json=payload)
        assert r.status_code == expect, f"{url}: {r.status_code} != {expect}"
        return self._audit(url, r)

    def get(self, url, expect=200):
        r = self.c.get(url)
        assert r.status_code == expect, f"{url}: {r.status_code} != {expect}"
        return self._audit(url, r)

    def served(self, body):
        pid = body["problem"]["problem_id"]
        return pid, webapp.SERVED[pid]["problem"]

    # -- flows --------------------------------------------------------------

    def diagnostic(self, policy):
        """policy(node, question_number) -> 'correct' | 'wrong' | 'skip'."""
        body = self.post("/api/diagnostic/start", {"student": self.key})
        garbage_done = False
        while not body["done"]:
            pid, p = self.served(body)
            qn = body["question_number"]

            if not garbage_done:
                # Unparseable must change nothing: same problem, same count.
                r = self.post("/api/diagnostic/answer",
                              {"student": self.key, "problem_id": pid,
                               "answer": "@@@"})
                assert r["grade"] == "unparseable", r
                assert r["question_number"] == qn, "unparseable consumed a question"
                assert r["problem"]["problem_id"] == pid, "unparseable rerolled the problem"
                garbage_done = True

            action = policy(p.node, qn)
            payload = {"student": self.key, "problem_id": pid}
            if action == "skip":
                payload["skip"] = True
            else:
                payload["answer"] = (correct_answer(p) if action == "correct"
                                     else wrong_answer_for(p))
            body = self.post("/api/diagnostic/answer", payload)
            if not body["done"]:
                assert body["question_number"] == qn + 1, "question count drifted"
        return body

    def practice_to_mastery(self, node):
        """One wrong, one unparseable, then correct until mastered — checks
        every streak rule from PROJECT.md 5.3 along the way."""
        body = self.get(f"/api/problem?student={self.key}&node={node}")
        pid, p = self.served(body)

        r = self.post("/api/answer", {"student": self.key, "problem_id": pid,
                                      "answer": wrong_answer_for(p)})
        assert r["grade"] == "wrong" and r["streak"] == 0, r
        assert r["hint"] is None or isinstance(r["hint"], str)
        # the wrong answer opened the 2-of-3 round with a wrong slot
        assert r["round"] == {"index": 1, "results": [False],
                              "verdict": None}, r["round"]

        body = self.get(f"/api/problem?student={self.key}&node={node}")
        pid, p = self.served(body)
        r = self.post("/api/answer", {"student": self.key, "problem_id": pid,
                                      "answer": "??"})
        assert r["grade"] == "unparseable" and r["streak"] == 0, r
        # a typo consumes no round slot: still waiting on slot 2
        assert r["round"] == {"index": 2, "results": [False],
                              "verdict": None}, r["round"]

        # the problem survived the unparseable submission — grade it now
        r = self.post("/api/answer", {"student": self.key, "problem_id": pid,
                                      "answer": correct_answer(p)})
        assert r["grade"] == "correct" and r["streak"] == 1, r
        assert r["round"]["results"] == [False, True], r["round"]

        last, corrects, saw_pass = r, 1, False
        while not last["just_mastered"]:
            body = self.get(f"/api/problem?student={self.key}&node={node}")
            pid, p = self.served(body)
            last = self.post("/api/answer",
                             {"student": self.key, "problem_id": pid,
                              "answer": correct_answer(p)})
            assert last["grade"] == "correct", last
            if last["round"]["verdict"] == "passed":
                # wrong-correct-correct is 2 of 3: the round passes on the
                # SECOND correct, one answer before BKT mastery, and the
                # lesson completes right there
                saw_pass = True
                assert last["lesson_completed"], last
                assert sum(last["round"]["results"]) >= 2, last["round"]
            corrects += 1
            # The pacing theorem (bkt.py / selftest check_bkt): from ANY
            # prior, 3 consecutive corrects cross 0.95. If this trips, the
            # parameters or the propagation pass order broke.
            assert corrects <= 4, "mastery took >4 consecutive corrects"
        assert saw_pass, "the 2-of-3 round never reached a passed verdict"
        # In THIS deterministic flow (one wrong, then corrects from a
        # post-diagnostic low prior) mastery lands exactly on the 3rd
        # correct, so the familiar streak reading still holds.
        assert last["streak"] == 3, last
        assert last["status"]["nodes"][node]["p"] >= 0.95, last["status"]["nodes"][node]
        assert node in last["moved"], "the practiced node itself didn't move"
        return last

    def restart_check(self, node):
        """Serve, wipe server memory, submit — the rebuild from the student
        file must grade the same problem correctly."""
        body = self.get(f"/api/problem?student={self.key}&node={node}")
        pid, p = self.served(body)
        answer = correct_answer(p)
        webapp.SERVED.clear()
        webapp.DIAGS.clear()
        r = self.post("/api/answer", {"student": self.key, "problem_id": pid,
                                      "answer": answer})
        assert r["grade"] == "correct", f"restart rebuild failed to grade: {r}"

    def reveal_check(self, node):
        """The give-up flow: a reveal costs the streak (and ONLY the streak),
        retires the problem permanently — restart included — and is the one
        response allowed to carry an answer."""
        # build a visible streak so the reset is observable
        body = self.get(f"/api/problem?student={self.key}&node={node}")
        pid, p = self.served(body)
        r = self.post("/api/answer", {"student": self.key, "problem_id": pid,
                                      "answer": correct_answer(p)})
        assert r["grade"] == "correct" and r["streak"] >= 1, r

        before = self.get(f"/api/state?student={self.key}")
        attempts_before = before["nodes"][node]["attempts"]

        body = self.get(f"/api/problem?student={self.key}&node={node}")
        pid, p = self.served(body)
        r = self.post("/api/reveal", {"student": self.key, "problem_id": pid})
        assert set(r) == {"steps", "streak", "progress", "moved", "round",
                          "status"}, sorted(r)
        # a reveal is a wrong slot in the round (the 2-of-3 check must not
        # be gameable by reading solutions), while attempts stay untouched
        assert r["round"]["results"][-1] is False, r["round"]
        assert isinstance(r["steps"], list) and r["steps"], r["steps"]
        assert all(isinstance(s, str) and s for s in r["steps"]), r["steps"]
        assert not any("{" in s for s in r["steps"]), "placeholder in steps"
        assert r["streak"] == 0, r
        assert re.fullmatch(r"\d{1,3}%|mastered", r["progress"]), r["progress"]
        # a surrender is evidence: the node's P(mastered) must drop
        assert r["moved"].get(node, 0) < 0, "reveal applied no evidence"
        assert r["status"]["nodes"][node]["p"] < before["nodes"][node]["p"], \
            "reveal did not lower P(mastered)"
        assert r["status"]["nodes"][node]["attempts"] == attempts_before, \
            "a surrender must not count as an attempt"

        # the revealed problem is dead: no grade, no second reveal
        self.post("/api/answer", {"student": self.key, "problem_id": pid,
                                  "answer": correct_answer(p)}, expect=410)
        self.post("/api/reveal", {"student": self.key, "problem_id": pid},
                  expect=410)

        # retirement survives a restart: reveal, wipe memory, still 410
        body = self.get(f"/api/problem?student={self.key}&node={node}")
        pid, p = self.served(body)
        self.post("/api/reveal", {"student": self.key, "problem_id": pid})
        webapp.SERVED.clear()
        webapp.DIAGS.clear()
        self.post("/api/answer", {"student": self.key, "problem_id": pid,
                                  "answer": "1"}, expect=410)
        self.post("/api/reveal", {"student": self.key, "problem_id": pid},
                  expect=410)

        # positive twin: a restart BEFORE the reveal must not block it —
        # find_problem's rebuild path has to feed steps_for
        body = self.get(f"/api/problem?student={self.key}&node={node}")
        pid, p = self.served(body)
        webapp.SERVED.clear()
        r = self.post("/api/reveal", {"student": self.key, "problem_id": pid})
        assert r["steps"], "reveal after restart produced no steps"

    def _dungeon_served(self, body):
        """served() plus the dungeon's core invariant: every problem it
        serves must come from the sticky unlocked set."""
        pid, p = self.served(body)
        st = webapp.store.load_student(self.key)
        assert p.node in set(st["bkt"]["unlocked"]), \
            f"dungeon served locked node {p.node}"
        return pid, p

    def dungeon_flow(self):
        """A full run through the game mode: hearts, streak multiplier math,
        the room-5 boss gauntlet, cosmetics, restart survival, death and a
        clean second run. Every response is audited like everything else."""
        quiz_before = json.loads(json.dumps(
            webapp.store.load_student(self.key).get("quiz", {})))

        st = self.get(f"/api/dungeon/state?student={self.key}")
        assert st["active"] is False and st["records"]["runs"] == 0, st

        body = self.post("/api/dungeon/start", {"student": self.key})
        run = body["run"]
        assert run["lives"] == 3 and run["room"] == 1 and run["depth"] == 0, run
        assert run["is_boss"] is False and run["boss"] is None, run
        pid, p = self._dungeon_served(body)

        # start again must RESUME the same problem, not reroll it
        body2 = self.post("/api/dungeon/start", {"student": self.key})
        assert body2["problem"]["problem_id"] == pid, "start rerolled a live problem"

        # unparseable consumes nothing: no heart, same room, same problem
        r = self.post("/api/dungeon/answer",
                      {"student": self.key, "problem_id": pid, "answer": "@@@"})
        assert r["grade"] == "unparseable" and r["outcome"] is None, r
        assert r["run"]["lives"] == 3 and r["run"]["room"] == 1, r["run"]
        assert r["problem"]["problem_id"] == pid, "unparseable rerolled the problem"

        # wrong: one heart, streak zeroed, SAME room, fresh problem
        r = self.post("/api/dungeon/answer",
                      {"student": self.key, "problem_id": pid,
                       "answer": wrong_answer_for(p)})
        assert r["grade"] == "wrong" and r["outcome"] == "retry", r
        assert r["run"]["lives"] == 2 and r["run"]["room"] == 1, r["run"]
        assert r["run"]["streak"] == 0 and r["gained"] == 0, r
        assert r["hint"] is None or isinstance(r["hint"], str), r
        pid, p = self._dungeon_served(r)

        # multiplier math is exact: streak increments FIRST, then the lookup,
        # so three corrects from zero gain 10, 10, 20 (x2 kicks in at 3)
        for streak, mult, gain, total in [(1, 1, 10, 10), (2, 1, 10, 20),
                                          (3, 2, 20, 40)]:
            r = self.post("/api/dungeon/answer",
                          {"student": self.key, "problem_id": pid,
                           "answer": correct_answer(p)})
            assert r["grade"] == "correct" and r["outcome"] == "advance", r
            assert r["run"]["streak"] == streak, r["run"]
            assert r["run"]["multiplier"] == mult, r["run"]
            assert r["gained"] == gain and r["run"]["score"] == total, r
            pid, p = self._dungeon_served(r)

        # fourth correct lands on room 5: the boss door, gauntlet armed
        r = self.post("/api/dungeon/answer",
                      {"student": self.key, "problem_id": pid,
                       "answer": correct_answer(p)})
        assert r["outcome"] == "advance" and r["run"]["room"] == 5, r["run"]
        assert r["run"]["is_boss"] is True, r["run"]
        assert r["run"]["boss"] == {"index": 1, "results": []}, r["run"]
        assert r["run"]["depth"] == 4 and r["run"]["score"] == 60, r["run"]
        pid, p = self._dungeon_served(r)

        # gauntlet: first correct is progress, second settles the win early
        r = self.post("/api/dungeon/answer",
                      {"student": self.key, "problem_id": pid,
                       "answer": correct_answer(p)})
        assert r["outcome"] == "boss_progress", r
        assert r["run"]["boss"]["results"] == [True], r["run"]
        pid, p = self._dungeon_served(r)
        r = self.post("/api/dungeon/answer",
                      {"student": self.key, "problem_id": pid,
                       "answer": correct_answer(p)})
        assert r["outcome"] == "boss_won", r
        # slot streak 6 -> x3 -> 30, plus the flat 100 boss bonus
        assert r["gained"] == 130 and r["run"]["score"] == 210, r
        assert r["reward"] == {"kind": "color", "id": "sage",
                               "label": "Sage"}, r["reward"]
        assert r["records"]["bosses_beaten"] == 1, r["records"]
        assert r["run"]["room"] == 6 and r["run"]["depth"] == 5, r["run"]
        assert r["run"]["boss"] is None, r["run"]
        pid, p = self._dungeon_served(r)

        # cosmetics: the earned color equips, unearned and unknown refuse,
        # and the equipped color rides on the next login
        r = self.post("/api/dungeon/cosmetic",
                      {"student": self.key, "color": "sage"})
        assert r["cosmetics"]["color"] == "sage", r
        self.post("/api/dungeon/cosmetic",
                  {"student": self.key, "color": "rose"}, expect=403)
        self.post("/api/dungeon/cosmetic",
                  {"student": self.key, "color": "zzz"}, expect=404)
        login = self.post("/api/login", {"name": self.name})
        assert login["color"] == "sage" and login["title"] is None, login
        st = self.get(f"/api/dungeon/state?student={self.key}")
        assert st["active"] is True, st
        for row in st["cosmetics"]["ladder"]:
            assert row["unlocked"] is (row["at"] <= 1), row

        # restart survival: memory wiped, the rebuilt problem still grades
        answer = correct_answer(p)
        webapp.SERVED.clear()
        r = self.post("/api/dungeon/answer",
                      {"student": self.key, "problem_id": pid,
                       "answer": answer})
        assert r["grade"] == "correct" and r["outcome"] == "advance", r
        assert r["run"]["room"] == 7 and r["run"]["depth"] == 6, r["run"]
        pid, p = self._dungeon_served(r)

        # two wrongs spend the last hearts: death clears the run, counts it,
        # and records the depth as a new best
        r = self.post("/api/dungeon/answer",
                      {"student": self.key, "problem_id": pid,
                       "answer": wrong_answer_for(p)})
        assert r["outcome"] == "retry" and r["run"]["lives"] == 1, r["run"]
        pid, p = self._dungeon_served(r)
        r = self.post("/api/dungeon/answer",
                      {"student": self.key, "problem_id": pid,
                       "answer": wrong_answer_for(p)})
        assert r["outcome"] == "dead" and r["run"]["lives"] == 0, r
        assert r["problem"] is None, "a dead run must not serve a problem"
        assert r["records"]["runs"] == 1 and r["records"]["best_depth"] == 6, r
        assert r["new_best"] is True, r
        # no run -> answering anything is refused before grading
        self.post("/api/dungeon/answer",
                  {"student": self.key, "problem_id": pid, "answer": "1"},
                  expect=409)
        st = self.get(f"/api/dungeon/state?student={self.key}")
        assert st["active"] is False and st["records"]["runs"] == 1, st

        # a second run starts clean; fleeing it counts the run without a best
        body = self.post("/api/dungeon/start", {"student": self.key})
        assert body["run"] == {"lives": 3, "room": 1, "depth": 0, "streak": 0,
                               "multiplier": 1, "score": 0, "is_boss": False,
                               "boss": None}, body["run"]
        self._dungeon_served(body)
        r = self.post("/api/dungeon/flee", {"student": self.key})
        assert r["active"] is False and r["records"]["runs"] == 2, r
        assert r["new_best"] is False, r
        self.post("/api/dungeon/flee", {"student": self.key}, expect=409)

        # the game never touched the lessons' 2-of-3 records
        quiz_after = webapp.store.load_student(self.key).get("quiz", {})
        assert quiz_after == quiz_before, "dungeon answers touched lesson rounds"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def guard_corpus_check():
    """The input guard must reject no legitimate answer, for any template,
    in any accepted formatting variant. This is what licenses treating a
    guard rejection as 'unparseable'."""
    rng = random.Random(20260819)
    bad = []
    for tid, tpl in webapp.TEMPLATES.items():
        checker = tpl.get("checker", "exact")
        for _ in range(40):
            p = generate(tpl, rng)
            candidates = ["none"]
            if p._answer is not None:
                candidates += format_variants(p._answer, checker)
                candidates.append(fmt(p._answer))
            for expr in tpl.get("selftest", {}).get("good", []):
                candidates.append(fmt(safe_eval(expr, p.params)))
            for expr in tpl.get("also_accept", []):
                candidates.append(fmt(safe_eval(expr, p.params)))
            for a in candidates:
                if webapp.unreadable(a):
                    bad.append(f"guard rejects legitimate answer for {tid}: {a!r}")
    for hid, entry in webapp.HAND.items():
        for v in format_variants(entry["answer"], entry.get("checker", "exact")):
            if webapp.unreadable(v):
                bad.append(f"guard rejects hand-authored answer for {hid}: {v!r}")
    return sorted(set(bad))


def error_paths(s):
    """Wrong ids must fail loudly and correctly, never 500."""
    s.get("/api/state?student=ghost_student", expect=404)
    s.get(f"/api/problem?student={s.key}&node=p_adic", expect=403)   # tier 2
    s.get(f"/api/problem?student={s.key}&node=nope", expect=404)
    s.post("/api/answer", {"student": s.key, "problem_id": "deadbeefcafe",
                           "answer": "1"}, expect=410)
    s.post("/api/reveal", {"student": s.key, "problem_id": "deadbeefcafe"},
           expect=410)
    s.post("/api/reveal", {"student": "ghost_student", "problem_id": "x"},
           expect=404)
    s.post("/api/login", {"name": "   "}, expect=400)
    s.get("/api/dungeon/state?student=ghost_student", expect=404)
    s.post("/api/dungeon/cosmetic", {"student": "ghost_student"}, expect=404)


def main():
    # Guard-vs-corpus first: if the input guard rejects a real answer, every
    # session after it would fail confusingly — fail fast with the cause.
    guard_failures = guard_corpus_check()
    if guard_failures:
        for f in guard_failures[:20]:
            print(f"FAIL  {f}")
        print(f"\n{len(guard_failures)} failure(s). Do not deploy.")
        sys.exit(1)

    checker = Checker()

    # Session 1 — deterministic: fails everything, so the frontier must be
    # exactly [divisibility]; mastering it must unlock its dependents.
    s = Session("Leak Test A", checker)
    done = s.diagnostic(lambda node, qn: "wrong")
    assert done["status"]["frontier"] == ["divisibility"], done["status"]["frontier"]
    s.get(f"/api/state?student={s.key}")
    s.get("/api/graph")
    last = s.practice_to_mastery("divisibility")
    assert last["just_mastered"], last
    # The round passed one answer before mastery and unlocked the children
    # then; by the mastery answer they are already in the sticky set.
    for child in ("primes", "bases"):
        assert last["status"]["nodes"][child]["lesson_unlocked"], \
            f"{child} not unlocked after the round passed"
    s.restart_check("primes")
    s.reveal_check("primes")
    error_paths(s)
    s.dungeon_flow()

    # Curriculum: audited like everything else, and complete — every authored
    # node teaches, and every lesson carries all five sections.
    cur = s.get("/api/curriculum")
    authored = {nid for nid in webapp.G.order if webapp.G.is_authored(nid)}
    assert set(cur["lessons"]) == authored, \
        f"lessons != authored nodes: {sorted(set(cur['lessons']) ^ authored)}"
    for lid, lesson in cur["lessons"].items():
        for field in ("concept", "key_results", "worked_example",
                      "common_mistakes", "problem_types"):
            assert isinstance(lesson.get(field), str) and lesson[field], \
                f"lesson {lid}: empty {field}"

    # Reveal must be impossible during the diagnostic: a diagnostic
    # problem_id mismatches on purpose inside find_problem and 410s.
    s_d = Session("Leak Test Reveal", checker)
    body_d = s_d.post("/api/diagnostic/start", {"student": s_d.key})
    pid_d, _ = s_d.served(body_d)
    s_d.post("/api/reveal", {"student": s_d.key, "problem_id": pid_d},
             expect=410)
    # ...and so must the dungeon: no ladder exists before placement
    s_d.post("/api/dungeon/start", {"student": s_d.key}, expect=409)

    # Session 2 — deterministic: aces everything, then skips are exercised
    # in session 3. Strong student's frontier must sit past the diagnostic.
    s2 = Session("Leak Test B", checker)
    done2 = s2.diagnostic(lambda node, qn: "correct")
    assert done2["status"]["frontier"], "strong student has an empty frontier"

    # Sessions 3..10 — seeded random walks, one includes an explicit skip.
    for i in range(3, 11):
        rng = random.Random(i)
        s_i = Session(f"Leak Test {i}", checker)

        def policy(node, qn, rng=rng, force_skip=(i == 3)):
            if force_skip and qn == 2:
                return "skip"
            return rng.choice(["correct", "correct", "wrong", "skip"])

        done_i = s_i.diagnostic(policy)
        frontier = done_i["status"]["frontier"]
        if frontier:
            node = rng.choice(frontier)
            body = s_i.get(f"/api/problem?student={s_i.key}&node={node}")
            pid, p = s_i.served(body)
            answer = (correct_answer(p) if rng.random() < 0.5
                      else wrong_answer_for(p))
            s_i.post("/api/answer", {"student": s_i.key, "problem_id": pid,
                                     "answer": answer})

    failures = checker.problems

    print(f"leaktest: {checker.checked} responses audited, "
          f"{len(checker.answers)} distinct answers tracked")
    if failures:
        for f in failures[:20]:
            print(f"FAIL  {f}")
        print(f"\n{len(failures)} failure(s). Do not deploy.")
        sys.exit(1)
    print("No answer left the server. All behavioural checks passed.")


if __name__ == "__main__":
    main()
