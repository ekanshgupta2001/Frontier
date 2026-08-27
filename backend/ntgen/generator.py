"""
generator.py — turn one template into unlimited concrete problems.

The flow, in order:

    template (written once, by an LLM)
        -> sample random params
        -> compute derived values with SymPy
        -> reject if the sampler constraint fails, resample
        -> compute the answer with SymPy         <- never the LLM
        -> fill the prompt wording
        -> serve

The model chooses the SHAPE of the problem. SymPy chooses the ANSWER.
That split is the entire reliability argument for this project.
"""

import json
import random
from pathlib import Path

from verify import safe_eval, CHECKERS, TemplateError


MAX_SAMPLE_ATTEMPTS = 200


def _fill(text: str, params: dict) -> str:
    """Prose fields may reference params ({n}, {nm1}) so the student sees
    concrete numbers instead of variable names. Hand-authored entries have no
    params and may contain literal braces, so they pass through untouched."""
    if not text or not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError) as e:
        raise TemplateError(f"bad placeholder in prose field {text!r}: {e}") from e


class Problem:
    def __init__(self, template, params, prompt, answer):
        self.template_id = template["id"]
        self.node = template["node"]
        self.params = params
        self.prompt = prompt
        self.answer_format = _fill(template.get("answer_format", ""), params)
        self.hint = _fill(template.get("hint", ""), params)
        self._answer = answer          # None for condition-checked templates
        self._template = template

    def grade(self, student_answer: str) -> str:
        """
        Grade a typed answer: "correct", "wrong", or "unparseable".

        "unparseable" means the input could not be read at all — a formatting
        slip, not a math error. Per PROJECT.md 5.3 it does not count as an
        attempt: callers must not pass it to record_answer, so it never
        touches a streak. The boundary is exactly "what normalise() can
        parse", not a typo detector: "banana" sympifies to a symbol and
        grades wrong, while "??" fails to parse and grades unparseable.
        """
        if not str(student_answer).strip():
            return "unparseable"
        checker_name = self._template.get("checker", "exact")
        checker = CHECKERS[checker_name]
        if checker_name == "condition":
            expected = self._template["check_spec"]
        else:
            expected = self._answer
            # also_accept: alternate values graded correct (e.g. -1 alongside
            # p-1 for Wilson). Exact checker only — unordered_set's expected
            # is already a list, so a list there would mean something else.
            also = self._template.get("also_accept")
            if checker_name == "exact" and also:
                expected = [self._answer] + [safe_eval(e, self.params) for e in also]
        try:
            return "correct" if checker(student_answer, self.params, expected) else "wrong"
        except ValueError:
            # normalise()/normalise_set()/normalise_pair() could not read it
            return "unparseable"
        except TemplateError:
            # it parsed, but evaluating the condition on it broke — an attempt
            return "wrong"

    def check(self, student_answer: str) -> bool:
        """Grade a student's typed answer. Only "correct" counts."""
        return self.grade(student_answer) == "correct"

    def __repr__(self):
        shown = self._answer if self._answer is not None else "<condition-checked>"
        return f"<Problem {self.template_id} | {self.prompt} | answer={shown}>"


def _sample_one(spec, rng):
    if spec["type"] == "int":
        return rng.randint(spec["min"], spec["max"])
    if spec["type"] == "choice":
        return rng.choice(spec["values"])
    raise TemplateError(f"unknown param type {spec['type']!r}")


def generate(template: dict, rng=None, max_attempts=MAX_SAMPLE_ATTEMPTS) -> Problem:
    """Produce one concrete Problem from a template."""
    rng = rng or random

    for _ in range(max_attempts):
        params = {
            name: _sample_one(spec, rng)
            for name, spec in template.get("params", {}).items()
        }

        # derived values, computed in order
        for name, expr in template.get("derived", {}).items():
            params[name] = safe_eval(expr, params)

        # reject samples that violate the template's constraint
        constraint = template.get("sampler_constraint")
        if constraint and not safe_eval(constraint, params):
            continue

        # the answer — computed by SymPy, never by a model
        sol_expr = template.get("solution")
        answer = safe_eval(sol_expr, params) if sol_expr else None

        prompt = template["prompt"].format(**params)
        return Problem(template, params, prompt, answer)

    raise TemplateError(
        f"template {template['id']!r}: sampler constraint never satisfied "
        f"in {max_attempts} attempts — the constraint is probably too tight"
    )


def load_templates(path=None):
    # Default resolves next to this file, not the CWD, so scripts work from
    # anywhere (repo root, backend/ntgen/, the server process).
    path = Path(path) if path else Path(__file__).parent / "templates.json"
    data = json.loads(path.read_text())
    return {t["id"]: t for t in data["templates"]}


def templates_for_node(templates: dict, node: str):
    return [t for t in templates.values() if t["node"] == node]


# ---------------------------------------------------------------------------
# Hand-authored problems
# ---------------------------------------------------------------------------
# pigeonhole_nt does not parameterise: its problems are proof-flavoured and a
# generated version would be either trivial or wrong. Those problems are
# written and checked by a human, stored with a fixed key, and served through
# the SAME Problem interface so nothing downstream needs a special case.
#
# This is the only stored answer key in the project. It is a human key, not a
# model's — the "no LLM answer" rule is intact.

def load_hand_authored(path=None):
    path = Path(path) if path else Path(__file__).parent / "hand_authored.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {p["id"]: p for p in data["problems"]}


def hand_authored_problem(entry: dict) -> Problem:
    """Wrap a stored problem as a Problem. No params, no sampling, fixed answer."""
    # the entry doubles as its own template: it carries id, node, checker,
    # answer_format and hint, which is everything Problem reads.
    return Problem(entry, {}, entry["prompt"], entry["answer"])


def problems_for_node(templates: dict, node: str, hand: dict = None):
    """Everything servable for a node: generated templates plus stored problems."""
    hand = hand if hand is not None else load_hand_authored()
    return (
        [t for t in templates.values() if t["node"] == node],
        [e for e in hand.values() if e["node"] == node],
    )


def problem_for_node(templates: dict, node: str, rng=None, hand: dict = None) -> Problem:
    """
    One problem for a node, chosen at random from everything available.

    This is the single serving entry point — the diagnostic, the practice
    loop and (in phase 4) the web handler all call it, so none of them has to
    know that pigeonhole_nt is served from a different file.
    """
    rng = rng or random
    generated, stored = problems_for_node(templates, node, hand)
    pool = [("template", t) for t in generated] + [("stored", e) for e in stored]
    if not pool:
        raise TemplateError(f"no problems available for node {node!r}")
    kind, item = rng.choice(pool)
    return generate(item, rng) if kind == "template" else hand_authored_problem(item)
