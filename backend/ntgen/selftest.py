"""
selftest.py — run this before you trust a template.

This is the gate from PROJECT.md section 4.3: if a node cannot pass here,
it is not ready to be served to students.

Checks per template:
  1. It generates without crashing, many times.
  2. The correct answer is graded correct.
  3. Formatting variants of the correct answer are also graded correct.
  4. A deliberately wrong answer is graded wrong.
  5. Garbage input is graded wrong without raising.
  6. Unreadable input grades "unparseable" — a formatting slip must never
     count as an attempt (PROJECT.md 5.3).
  7. The reveal's worked solution (steps.py) is a non-empty list of clean
     step strings whose final line states the answer — and that stated
     answer, typed verbatim, grades correct. This cross-checks the stored
     solution against an independent derivation, so it also catches
     templates whose solution expression is simply wrong.

Templates may carry a "selftest" block — and condition-checked templates
MUST, because they have no stored answer the gate could use:

    "selftest": {
      "good":  ["<expr producing a correct answer>", ...],
      "wrong": ["<expr producing an incorrect answer>", ...]
    }

The expressions run in the same sandbox as solution expressions, with the
problem's params in scope. A tuple/list result is formatted as
comma-separated values, matching how a student types a pair or a set.
"""

import random
import sys

from generator import (
    load_templates, generate, load_hand_authored, hand_authored_problem,
)
from verify import TemplateError, safe_eval, is_sentinel
from graph import load_graph, GraphError
from diagnostic import Diagnostic, SimulatedStudent, MAX_QUESTIONS
from steps import steps_for, answer_display, RENDERERS
from curriculum import load_curriculum, validate as validate_curriculum, CurriculumError
import bkt

TRIALS = 300

# Ways a student might phrase "no such value exists". The gate checks that
# every one of these is accepted when that IS the answer, and rejected when
# a real answer exists.
NONE_PHRASINGS = ["none", "None", "  none  ", "no solution", "DNE"]

# Input normalise() cannot read. These must grade "unparseable" — not wrong,
# not a crash — so a typo never resets a streak (PROJECT.md 5.3).
UNREADABLE = ["", "??", "5x+"]


def check_tristate(p, checker):
    out = []
    for junk in UNREADABLE:
        # Base answers are compared as plain strings, so any non-empty input
        # is readable there — only genuinely blank input is unparseable.
        want = "wrong" if (checker == "string" and junk.strip()) else "unparseable"
        try:
            got = p.grade(junk)
        except Exception as e:
            out.append(f"grade({junk!r}) raised instead of returning: {e}")
            continue
        if got != want:
            out.append(f"grade({junk!r}) -> {got!r}, expected {want!r}")
    return out


def fmt(value):
    """Render an expression result the way a student would type it."""
    if isinstance(value, (tuple, list)):
        return ", ".join(str(v) for v in value)
    return str(value)


def format_variants(answer, checker):
    """Ways a student might legitimately type the same value."""
    variants = [str(answer)]
    if checker == "string":
        # Base representations: whitespace and $...$ wrappers are noise, but
        # "1011.0" is NOT the same answer, so no decimal variant here.
        variants.append(f" {answer} ")
        variants.append(f"${answer}$")
        return variants
    try:
        n = int(answer)
        variants.append(f" {n} ")
        variants.append(f"{n}.0")
        if n != 0:
            variants.append(f"$ {n} $")
    except (TypeError, ValueError):
        pass
    return variants


def check_no_solution_case(p):
    """
    The correct answer is "no such value exists".

    Every reasonable phrasing must be accepted, and a made-up number must be
    rejected — otherwise a student who correctly spots that an inverse does
    not exist gets marked wrong, which is the worst possible failure on the
    exact node where that insight is the skill being tested.
    """
    out = []
    for phrasing in NONE_PHRASINGS:
        if not p.check(phrasing):
            out.append(f"no-solution phrasing rejected: {p.prompt} -> {phrasing!r}")
    for bogus in ["0", "1", "7"]:
        if p.check(bogus):
            out.append(f"number accepted though no answer exists: {p.prompt} -> {bogus}")
    return out


def check_steps(p):
    """Check #7: the reveal's worked solution honours its contract."""
    lines = steps_for(p)
    if not (isinstance(lines, list) and lines
            and all(isinstance(s, str) and s.strip() for s in lines)):
        return [f"steps: not a non-empty list of strings: {p.prompt}"]
    out = []
    for s in lines:
        if "{" in s or "}" in s:
            out.append(f"steps: unfilled placeholder: {s[:70]!r}")
            break
    disp = answer_display(p)
    if disp not in lines[-1]:
        out.append(f"steps: final line missing the answer {disp!r}: {lines[-1][:70]!r}")
    if p.grade(disp) != "correct":
        out.append(f"steps: displayed answer does not grade correct: {disp!r}")
    return out


def test_template(tpl, rng):
    failures = []
    seen_prompts, seen_answers = set(), set()
    distractor_differed = 0

    for i in range(TRIALS):
        try:
            p = generate(tpl, rng)
        except TemplateError as e:
            failures.append(f"generation failed: {e}")
            break

        checker = tpl.get("checker", "exact")
        st = tpl.get("selftest", {})
        seen_prompts.add(p.prompt)
        seen_answers.add(str(p._answer))

        # A brace surviving into student-facing text is a placeholder typo —
        # the student would see "{nm1}" instead of a number.
        for field, text in (("prompt", p.prompt),
                            ("answer_format", p.answer_format),
                            ("hint", p.hint)):
            if "{" in text or "}" in text:
                failures.append(f"unfilled placeholder in {field}: {text[:70]!r}")

        if checker == "condition":
            # No stored answer exists for this checker, so the template itself
            # must say how to build correct and incorrect answers.
            if not st.get("good") or not st.get("wrong"):
                failures.append("condition template needs selftest.good and selftest.wrong")
                break

        elif checker == "unordered_set":
            sols = p._answer
            # An empty solution set means "no solutions exist" — graded the
            # same way as a sentinel answer, not as an empty string.
            if is_sentinel(sols) or len(sols) == 0:
                failures += check_no_solution_case(p)
            else:
                joined = ", ".join(str(s) for s in sols)
                if not p.check(joined):
                    failures.append(f"correct set rejected: {p.prompt} -> {joined}")
                # reversed order must still pass
                rev = ", ".join(str(s) for s in reversed(list(sols)))
                if not p.check(rev):
                    failures.append(f"reversed set rejected: {p.prompt}")
                # only the first solution must FAIL (the whole point of this node)
                if len(sols) > 1 and p.check(str(sols[0])):
                    failures.append(f"partial answer accepted: {p.prompt}")
                if p.check("none"):
                    failures.append(f"'none' accepted though solutions exist: {p.prompt}")

        else:
            ans = p._answer
            if is_sentinel(ans):
                failures += check_no_solution_case(p)
            else:
                for v in format_variants(ans, checker):
                    if not p.check(v):
                        failures.append(f"variant rejected: {p.prompt} -> {v!r}")
                # alternate accepted forms (e.g. -1 alongside p-1 in Wilson)
                for expr in tpl.get("also_accept", []):
                    alt = fmt(safe_eval(expr, p.params))
                    if not p.check(alt):
                        failures.append(f"also_accept rejected: {p.prompt} -> {alt!r}")
                # claiming no answer exists when one does must be rejected
                if p.check("none"):
                    failures.append(f"'none' accepted though an answer exists: {p.prompt}")
                # off-by-one only makes sense for numeric answers
                if checker != "string":
                    try:
                        wrong = str(int(ans) + 1)
                    except (TypeError, ValueError):
                        wrong = None
                    if wrong is not None and p.check(wrong):
                        failures.append(f"off-by-one accepted: {p.prompt}")

        # distractor_expr predicts the value a student produces when they make
        # this node's classic mistake. Phase 5 uses it for targeted hints, so
        # it must at least evaluate without crashing.
        dexpr = tpl.get("distractor_expr")
        if dexpr:
            try:
                if str(safe_eval(dexpr, p.params)) != str(p._answer):
                    distractor_differed += 1
            except TemplateError as e:
                failures.append(f"distractor_expr failed to evaluate: {e}")

        # template-declared good/wrong answers, applied under any checker
        for expr in st.get("good", []):
            good = fmt(safe_eval(expr, p.params))
            if not p.check(good):
                failures.append(f"selftest.good rejected: {p.prompt} -> {good!r}")
        for expr in st.get("wrong", []):
            wrong = fmt(safe_eval(expr, p.params))
            if p.check(wrong):
                failures.append(f"selftest.wrong accepted: {p.prompt} -> {wrong!r}")

        # --- garbage must fail quietly ---
        for junk in ["", "banana", "??", "1/0"]:
            try:
                if p.check(junk):
                    failures.append(f"garbage accepted: {junk!r}")
            except Exception as e:
                failures.append(f"garbage raised instead of returning False: {e}")

        failures += check_tristate(p, checker)
        failures += check_steps(p)

        if failures:
            break

    # A sampler that always produces the same problem passes every check above
    # while being useless — the student sees one question forever. Catch it
    # here rather than in front of a class. This also matters for phase 5,
    # where LLM-written templates are auto-discarded on gate failure with no
    # human reading them.
    # A distractor that always equals the correct answer signals nothing — the
    # student who "makes the mistake" is right, so the hint could never fire.
    if not failures and tpl.get("distractor_expr") and distractor_differed == 0:
        failures.append(
            "distractor_expr always equals the correct answer — it cannot "
            "identify a mistake"
        )

    if not failures:
        if len(seen_prompts) < 2:
            failures.append(
                f"degenerate sampler: {TRIALS} trials produced 1 distinct prompt"
            )
        elif (
            len(seen_answers) < 2
            and tpl.get("checker") != "condition"
            # Some templates are deliberately always the same answer — the
            # "this congruence has no solutions" drill, for instance. Those
            # must SAY so, so that an accidental collapse still fails here.
            and not tpl.get("constant_answer_by_design")
        ):
            failures.append(
                f"degenerate answers: {TRIALS} trials produced 1 distinct answer "
                f"({seen_answers.pop()!r})"
            )

    return failures


def test_hand_authored(entry):
    """
    Hand-authored problems have a STORED key, so SymPy cannot vouch for them.
    The gate checks what it still can: the key grades itself correct, obvious
    variants pass, a wrong value fails, and the entry carries the written
    argument that justifies its answer.
    """
    failures = []
    p = hand_authored_problem(entry)

    if not str(entry.get("why", "")).strip():
        failures.append("no 'why' field — a stored answer with no written argument")

    for v in format_variants(entry["answer"], entry.get("checker", "exact")):
        if not p.check(v):
            failures.append(f"stored answer rejected: {v!r}")

    try:
        wrong = str(int(entry["answer"]) + 1)
        if p.check(wrong):
            failures.append(f"off-by-one accepted: {wrong}")
    except (TypeError, ValueError):
        pass

    for junk in ["", "banana", "??", "1/0"]:
        try:
            if p.check(junk):
                failures.append(f"garbage accepted: {junk!r}")
        except Exception as e:
            failures.append(f"garbage raised instead of returning False: {e}")

    failures += check_tristate(p, entry.get("checker", "exact"))
    failures += check_steps(p)

    return failures


def check_graph(templates, hand):
    """
    Structural check on the DAG. A prereq id with a typo would make its node
    permanently unreachable while every template still passed, so this runs
    inside the same gate rather than beside it.
    """
    available = {t["node"] for t in templates.values()} | {e["node"] for e in hand.values()}
    graph = load_graph()
    try:
        warnings = graph.validate(available_nodes=available)
    except GraphError as e:
        print(f"FAIL  graph  ({e})")
        return False
    print(f"ok    graph  {len(graph)} nodes, acyclic, all prereqs resolve")
    for w in warnings:
        print(f"      warning: {w}")
    return True


def check_curriculum():
    """curriculum.md must parse and agree with the DAG: every authored node
    has a lesson, and each lesson's id, tier, and prereq edges match the
    graph exactly (the doc is the source of truth for edges — a mismatch
    means one of them drifted)."""
    try:
        c = load_curriculum()
        validate_curriculum(c, load_graph())
    except CurriculumError as e:
        print(f"FAIL  curriculum  ({e})")
        return False
    n = len(c["lessons"])
    print(f"ok    curriculum  {n} lessons parsed, ids/tiers/prereqs match the DAG")
    return True


def check_diagnostic():
    """
    The diagnostic must stay inside its question budget, must never hand a
    student a frontier node whose prerequisites are below the mastery
    threshold — that would serve someone a problem they have no route to —
    and must be a pure function of its history, because the app recovers a
    live diagnostic after a restart by replaying that history.
    """
    G = load_graph()
    failures = []
    profiles = [
        ("knows nothing", [], ["divisibility"]),
        ("early tier 0", ["primes"], None),
        ("finished tier 0", ["euclidean", "divisor_functions", "digit_rules"], None),
        ("into tier 1", ["mod_arith", "bezout"], None),
        ("all authored", ["order", "wilson", "pigeonhole_nt", "digit_rules"], None),
    ]
    for label, knows, expect_frontier in profiles:
        student = SimulatedStudent(G, knows)
        d = Diagnostic(G)
        res = d.run(student.answer)
        p, unlocked = res["p"], set(res["unlocked"])

        if d.asked > MAX_QUESTIONS:
            failures.append(f"{label}: asked {d.asked} questions, budget is {MAX_QUESTIONS}")
        if d.known & d.unknown:
            failures.append(f"{label}: nodes both known and unknown: {d.known & d.unknown}")

        frontier = [n for n in G.order
                    if n in unlocked and p[n] < bkt.P_MASTERED]
        for n in frontier:
            if not G.is_authored(n):
                failures.append(f"{label}: frontier contains unauthored node {n}")
            weak = [q for q in G.prereqs(n) if p[q] < bkt.P_MASTERED]
            if weak:
                failures.append(f"{label}: frontier node {n} needs weak {weak}")
        if expect_frontier is not None and frontier != expect_frontier:
            failures.append(f"{label}: frontier {frontier} != expected {expect_frontier}")

        # Replay IS recovery: a fresh Diagnostic fed the same history must
        # land on the identical result, float for float.
        d2 = Diagnostic(G)
        for node, ok in d.history:
            d2.record(node, ok)
        if d2.result() != res:
            failures.append(f"{label}: replaying history gives a different result")

    if failures:
        print("FAIL  diagnostic")
        for f in failures[:3]:
            print(f"        {f}")
        return False
    print(f"ok    diagnostic  {len(profiles)} student profiles, "
          f"<={MAX_QUESTIONS} questions each, replay-deterministic")
    return True


def check_bkt():
    """
    The knowledge-tracing model is the mastery mechanic now, so its math is
    gated like a template: pacing (3 corrects always master, 2 from cold
    never do — the promise students were given), the identifiability guard,
    the transition-on-correct-only decision, propagation monotonicity, and
    that the diagnostic's probe pool can only pick nodes we can actually
    serve. Everything here is deterministic and fast — no fitting.
    """
    failures = []
    G = load_graph()
    PARAMS = bkt.params_for_graph(G)
    ADJ = {nid: G.prereqs(nid) for nid in G.order}
    AUTHORED = set(G.authored_nodes())

    def fresh():
        return bkt.KnowledgeState(ADJ, PARAMS, authored=AUTHORED)

    # 1. spot values for the core update (defaults .15/.30/.10/.20)
    prm = bkt.NodeParams()
    if abs(bkt.update(0.15, True, prm) - 0.6098) > 1e-3:
        failures.append(f"correct-update(0.15) = {bkt.update(0.15, True, prm):.4f}, expected 0.6098")
    if abs(bkt.update(0.15, False, prm) - 0.0216) > 1e-3:
        failures.append(f"wrong-update(0.15) = {bkt.update(0.15, False, prm):.4f}, expected 0.0216")

    # 2. identifiability guard: slip + guess must stay < 1 after clamp
    bad = bkt.NodeParams(p_slip=0.9, p_guess=0.9).clamp()
    if bad.p_slip + bad.p_guess >= 1:
        failures.append(f"clamp left slip+guess = {bad.p_slip + bad.p_guess} >= 1")

    # 3. a wrong answer strictly lowers P, everywhere on the grid (the §6
    #    decision: no learning credit for a miss)
    for p100 in range(1, 100):
        p = p100 / 100
        if bkt.update(p, False, prm) >= p:
            failures.append(f"wrong answer raised P from {p}")
            break

    # 4. reveal is exactly the wrong-answer observation
    a, b = fresh(), fresh()
    if a.observe_reveal("crt") != b.observe("crt", False) or a.p != b.p:
        failures.append("observe_reveal differs from a wrong observation")

    # 5. propagation is monotone: a correct never lowers any node, a wrong
    #    never raises any — and a cyclic graph is refused
    ks = fresh()
    before = dict(ks.p)
    ks.observe("crt", True)
    dropped = [n for n in ks.p if ks.p[n] < before[n] - 1e-12]
    if dropped:
        failures.append(f"correct at crt lowered {dropped[:3]}")
    before = dict(ks.p)
    ks.observe("euclidean", False)
    raised = [n for n in ks.p if ks.p[n] > before[n] + 1e-12]
    if raised:
        failures.append(f"wrong at euclidean raised {raised[:3]}")
    try:
        bkt.KnowledgeState({"a": ["b"], "b": ["a"]},
                           {"a": bkt.NodeParams(), "b": bkt.NodeParams()})
        failures.append("2-cycle graph was accepted")
    except ValueError:
        pass

    # 6. pacing, per tier profile: 3 consecutive corrects master from ANY
    #    prior (checked at the worst case, ~0), 2 from the cold prior do not
    for tier, tp in sorted(bkt.TIER_PARAMS.items()):
        p = 1e-6
        for _ in range(3):
            p = bkt.update(p, True, tp)
        if p < bkt.P_MASTERED:
            failures.append(f"tier {tier}: 3 corrects from ~0 reach only {p:.4f}")
        p = tp.p_init
        p = bkt.update(bkt.update(p, True, tp), True, tp)
        if p >= bkt.P_MASTERED:
            failures.append(f"tier {tier}: 2 corrects from cold already master ({p:.4f})")

    # 7. the diagnostic probe pool only ever picks servable nodes
    ks = fresh()
    picked = []
    for _ in range(8):
        n = ks.most_informative(exclude=picked)
        if n is None:
            break
        if n not in AUTHORED:
            failures.append(f"most_informative picked unauthored {n}")
            break
        picked.append(n)
        ks.observe(n, True)

    # 8. persisted state round-trips exactly, including its next update
    ks = fresh()
    ks.observe("gcd_lcm", True)
    ks.observe("order", False)
    twin = bkt.KnowledgeState(ADJ, PARAMS, p=ks.export(), authored=AUTHORED)
    if twin.export() != ks.export():
        failures.append("export/reconstruct changed probabilities")
    elif ks.observe("mod_arith", True) != twin.observe("mod_arith", True):
        failures.append("round-tripped state diverges on the next observation")

    # 9. no-deadlock sweep: every authored node, practiced directly from a
    #    cold state, masters in 3 corrects. This pins the backward-before-
    #    forward pass order — swapping them caps practiced nodes at ~0.35.
    for n in G.authored_nodes():
        ks = fresh()
        for _ in range(3):
            ks.observe(n, True)
        if ks.p[n] < bkt.P_MASTERED:
            failures.append(f"{n}: 3 direct corrects reach only {ks.p[n]:.4f}")

    if failures:
        print("FAIL  bkt")
        for f in failures[:3]:
            print(f"        {f}")
        return False
    print(f"ok    bkt  update math, clamp, pacing bound, monotone propagation, "
          f"{len(G.authored_nodes())}-node no-deadlock sweep")
    return True


def main():
    rng = random.Random(20260805)
    templates = load_templates()
    hand = load_hand_authored()
    all_ok = check_graph(templates, hand)
    all_ok = check_curriculum() and all_ok
    all_ok = check_bkt() and all_ok
    all_ok = check_diagnostic() and all_ok

    # Every generated template must have a steps renderer BEFORE it can be
    # served — a reveal with no worked solution would silently degrade to a
    # bare answer line.
    unrendered = sorted(set(templates) - set(RENDERERS))
    if unrendered:
        all_ok = False
        print(f"FAIL  steps coverage  (no renderer for: {', '.join(unrendered)})")
    else:
        print(f"ok    steps coverage  every template has a worked-solution renderer")

    for tid, tpl in templates.items():
        failures = test_template(tpl, rng)
        if failures:
            all_ok = False
            print(f"FAIL  {tid}  ({tpl['node']})")
            for f in failures[:3]:
                print(f"        {f}")
        else:
            print(f"ok    {tid}  ({tpl['node']})  {TRIALS} trials")

    for hid, entry in hand.items():
        failures = test_hand_authored(entry)
        if failures:
            all_ok = False
            print(f"FAIL  {hid}  ({entry['node']}, hand-authored)")
            for f in failures[:3]:
                print(f"        {f}")
        else:
            print(f"ok    {hid}  ({entry['node']}, hand-authored)")

    nodes = {t["node"] for t in templates.values()} | {e["node"] for e in hand.values()}
    print()
    print(f"{len(templates)} generated templates + {len(hand)} hand-authored, "
          f"covering {len(nodes)} nodes.")
    if all_ok:
        print("All passed.")
    else:
        print("Some failed. Do not serve these.")
        sys.exit(1)


if __name__ == "__main__":
    main()
