"""
verify.py — the trust layer.

Two jobs:
  1. safe_eval: run a template's solution expression without letting arbitrary
     code execute. Templates come from an LLM, so we treat them as untrusted.
  2. check_answer: decide whether a student's typed answer is correct, using
     symbolic equivalence rather than string comparison.

Nothing in this file talks to an LLM. That is deliberate — this is the part
that must be correct, so it has no network calls and no model output in it.
"""

import sympy
from sympy import Integer, Rational, gcd, lcm, isprime, factorint, totient
from sympy import divisor_count, divisor_sigma, n_order, prime, primerange
from sympy import factorial, gcdex
from sympy.ntheory.modular import crt as sympy_crt


def euclid_steps(a, b):
    """Division steps the Euclidean algorithm takes on (a, b).

    Convention: each replacement (a, b) -> (b, a mod b) is one step, including
    the final one that produces remainder 0. Templates asking for a step count
    must state this convention in the prompt and keep a > b > 0 via their
    sampler so there is no ambiguous leading swap.
    """
    steps = 0
    a, b = abs(int(a)), abs(int(b))
    while b:
        a, b = b, a % b
        steps += 1
    return steps


def to_base(n, b):
    """n written in base b (2..16), lowercase digits, no prefix."""
    n = int(n)
    if n == 0:
        return "0"
    digits = "0123456789abcdef"
    out = []
    while n:
        out.append(digits[n % b])
        n //= b
    return "".join(reversed(out))


# ---------------------------------------------------------------------------
# The "no such value exists" sentinel
# ---------------------------------------------------------------------------
# Some correct answers are not numbers: a modular inverse may not exist, a CRT
# system may be inconsistent, a congruence may have no solutions. Those are
# real answers a student must be able to give, and getting them right is the
# actual skill being assessed on those nodes.
#
# Convention: a solution expression returns the STRING "none". Python None is
# deliberately NOT used — Problem._answer is None already means "condition-
# checked, no stored answer exists", and conflating the two would let a
# condition template silently grade as a no-solution template.

SENTINEL = "none"

# What a student might type to mean the same thing.
NO_SOLUTION_WORDS = {
    "none", "no", "no inverse", "no solution", "no solutions", "dne",
    "does not exist", "doesn't exist", "nonexistent", "n/a", "na",
    "impossible", "inconsistent", "no answer", "null", "empty",
}


def is_sentinel(value) -> bool:
    """True when a COMPUTED answer means 'no such value exists'."""
    return isinstance(value, str) and value.strip().lower() == SENTINEL


def said_no_solution(raw) -> bool:
    """True when a STUDENT's typed answer means 'no such value exists'."""
    s = " ".join(str(raw).strip().lower().split()).rstrip(".!")
    return s in NO_SOLUTION_WORDS


def inv_mod(a, n):
    """Inverse of a mod n in [0, n-1], or the sentinel when gcd(a, n) != 1."""
    a, n = int(a), int(n)
    if gcd(a, n) != 1:
        return SENTINEL
    return pow(a, -1, n)


def crt_value(moduli, residues):
    """
    Smallest non-negative solution of the congruence system, or the sentinel
    when the system is inconsistent.

    sympy's crt handles non-coprime moduli correctly and returns None when no
    solution exists, which is why the curriculum can teach that case honestly
    instead of hiding it.
    """
    result = sympy_crt([int(m) for m in moduli], [int(r) for r in residues])
    if result is None:
        return SENTINEL
    # sympy can hand back a non-reduced representative when moduli share a
    # factor: crt([12, 8], [8, 0]) -> (32, 96) — its combined modulus is the
    # product, not the lcm, so 32 is a solution but not the smallest. The
    # solution set is one class mod lcm, and every crt prompt asks for the
    # smallest non-negative member of it.
    modulus = 1
    for m in moduli:
        modulus = int(lcm(modulus, int(m)))
    return int(result[0]) % modulus


# ---------------------------------------------------------------------------
# 1. Safe evaluation
# ---------------------------------------------------------------------------

# The ONLY names a template expression is allowed to touch. If a template
# references anything outside this dict, evaluation fails loudly instead of
# doing something clever.
SAFE_NAMES = {
    # sympy number theory
    "gcd": gcd,
    "lcm": lcm,
    "isprime": isprime,
    "factorint": factorint,
    "totient": totient,
    "divisor_count": divisor_count,
    "divisor_sigma": divisor_sigma,
    "n_order": n_order,
    "prime": prime,
    "crt": sympy_crt,
    "factorial": factorial,
    "gcdex": gcdex,
    # reference implementations for template questions (PROJECT.md 4.3)
    "euclid_steps": euclid_steps,
    "to_base": to_base,
    "inv_mod": inv_mod,
    "crt_value": crt_value,
    "NONE": SENTINEL,
    "Integer": Integer,
    "Rational": Rational,
    # plain python, harmless
    "pow": pow,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "sorted": sorted,
    "list": list,
    "range": range,
    "int": int,
    "str": str,
}


class TemplateError(Exception):
    """Raised when a template is malformed or tries something it shouldn't."""


def safe_eval(expr: str, params: dict):
    """
    Evaluate a solution expression with only whitelisted names available.

    __builtins__ is emptied, so there is no import, no open, no exec.
    Params are injected alongside the whitelist.
    """
    namespace = dict(SAFE_NAMES)
    namespace.update(params)
    # Everything must live in eval's GLOBALS, not locals: a comprehension body
    # inside the expression runs in its own scope, which can see globals but
    # not eval's locals. Passing names as locals made
    # `[x for x in range(n) if (a*x - b) % n == 0]` fail on `a`.
    namespace["__builtins__"] = {}
    try:
        return eval(expr, namespace)  # noqa: S307
    except Exception as e:
        raise TemplateError(f"solution expression failed: {expr!r} -> {e}") from e


# ---------------------------------------------------------------------------
# 2. Answer normalisation
# ---------------------------------------------------------------------------

def normalise(raw: str):
    """
    Turn whatever the student typed into something comparable.

    Handles the LaTeX and formatting variation that would otherwise make
    correct answers read as wrong: \frac{1}{2}, 1/2, and 0.5 must all land
    in the same place.
    """
    if raw is None:
        raise ValueError("empty answer")
    s = str(raw).strip()
    if not s:
        raise ValueError("empty answer")

    # strip common LaTeX wrappers
    s = s.replace("$", "").replace("\\left", "").replace("\\right", "")
    s = s.replace("\\cdot", "*").replace("\\times", "*")
    s = s.replace("^", "**")

    # \frac{a}{b} -> (a)/(b)
    while "\\frac{" in s:
        start = s.index("\\frac{")
        i = start + 6
        depth, num_end = 1, None
        while i < len(s):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    num_end = i
                    break
            i += 1
        if num_end is None or num_end + 1 >= len(s) or s[num_end + 1] != "{":
            raise ValueError("malformed \\frac")
        j, depth, den_end = num_end + 2, 1, None
        while j < len(s):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    den_end = j
                    break
            j += 1
        if den_end is None:
            raise ValueError("malformed \\frac")
        num = s[start + 6:num_end]
        den = s[num_end + 2:den_end]
        s = s[:start] + f"(({num})/({den}))" + s[den_end + 1:]

    try:
        return sympy.sympify(s, rational=True)
    except Exception as e:
        raise ValueError(f"could not parse {raw!r}") from e


def normalise_set(raw: str):
    """For answers that are a set of values, e.g. 'all solutions mod n'."""
    parts = [p for p in str(raw).replace(";", ",").split(",") if p.strip()]
    return {normalise(p) for p in parts}


def normalise_pair(raw: str):
    """For answers that are an ordered pair, e.g. Bezout coefficients."""
    s = str(raw).strip().lstrip("(").rstrip(")")
    parts = [p for p in s.replace(";", ",").split(",") if p.strip()]
    if len(parts) != 2:
        raise ValueError("expected two values")
    return tuple(normalise(p) for p in parts)


# ---------------------------------------------------------------------------
# 3. Checkers
# ---------------------------------------------------------------------------
# A checker takes (student_answer_string, params, expected) and returns bool.
#
# Most nodes use `exact`. The interesting ones are `condition` and `unordered_set`.

def check_exact(student: str, params: dict, expected) -> bool:
    """
    Single value. Symbolic equivalence, so 1/2 == 0.5 == \\frac{1}{2}.

    `expected` may also be a list of acceptable values — a template's
    `also_accept` field routes through here (e.g. Wilson accepts -1 as well
    as the canonical p-1). Any match counts.
    """
    wants = expected if isinstance(expected, list) else [expected]

    # "no such value exists" is an answer, not a number. It must match on both
    # sides: a student saying "none" when a value exists is wrong, and a
    # student giving a number when none exists is wrong.
    want_none = any(is_sentinel(w) for w in wants)
    if said_no_solution(student):
        return want_none
    if want_none:
        # No value exists, and the student gave something other than "none".
        # It still has to be READABLE before it can be called wrong: a parse
        # failure here must raise, so it grades "unparseable" rather than
        # costing an attempt (PROJECT.md 5.3).
        normalise(student)
        return False

    got = normalise(student)
    return any(
        sympy.simplify(got - sympy.sympify(w, rational=True)) == 0 for w in wants
    )


def check_string_normalised(student: str, params: dict, expected) -> bool:
    """
    Answers that are strings, not numbers — base representations.

    '1011', ' 1 0 1 1 ', '0b1011' and '00001011' are the same answer.
    Symbolic comparison is wrong here: in base 16, 'ff' is a digit string,
    not a product of two variables.
    """
    def norm(raw):
        s = "".join(str(raw).split()).lower()
        for junk in ("$", ",", "_", "'"):
            s = s.replace(junk, "")
        for prefix in ("0b", "0o", "0x"):
            if s.startswith(prefix):
                s = s[2:]
                break
        s = s.lstrip("0")
        return s or "0"

    if not str(student).strip():
        return False
    return norm(student) == norm(expected)


def check_unordered_set(student: str, params: dict, expected) -> bool:
    """
    A set of values in any order. Used by linear_congruence, where
    gcd(a,n) > 1 means several correct residues and order is meaningless.
    """
    # An empty solution list means the congruence has no solutions at all —
    # same sentinel rules as check_exact.
    want_none = is_sentinel(expected) or (
        isinstance(expected, (list, tuple, set)) and len(expected) == 0
    )
    if said_no_solution(student):
        return want_none
    if want_none:
        # same as check_exact: unreadable input must raise, not grade wrong
        normalise_set(student)
        return False

    got = normalise_set(student)
    want = {sympy.sympify(v, rational=True) for v in expected}
    if len(got) != len(want):
        return False
    return all(any(sympy.simplify(g - w) == 0 for w in want) for g in got)


def check_condition(student: str, params: dict, expected) -> bool:
    """
    THE IMPORTANT ONE.

    Some questions have infinitely many correct answers. Bezout is the case:
    any (x, y) with ax + by = gcd(a,b) is right. There is no stored key to
    compare against, so we evaluate the defining condition on whatever the
    student typed.

    `expected` here is a dict: {"vars": ["x","y"], "condition": "a*x + b*y == g"}
    """
    if not isinstance(expected, dict):
        raise TemplateError("condition checker needs a dict spec")
    var_names = expected["vars"]
    if len(var_names) == 1:
        values = [normalise(student)]
    else:
        values = list(normalise_pair(student))
    if len(values) != len(var_names):
        return False
    ns = dict(params)
    ns.update(dict(zip(var_names, values)))
    return bool(safe_eval(expected["condition"], ns))


CHECKERS = {
    "exact": check_exact,
    "unordered_set": check_unordered_set,
    "condition": check_condition,
    "string": check_string_normalised,
}
