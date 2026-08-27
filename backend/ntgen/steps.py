"""
steps.py — worked solutions for the give-up / reveal flow.

Every step line is Python-computed prose around Python-computed numbers.
No LLM output is ever part of a step, and nothing here is called until the
problem has already been retired server-side (app.py's reveal route clears
the outstanding problem and persists BEFORE building the response).

Contract enforced by selftest.py on every template, 300 trials each:
  - steps_for(problem) is a non-empty list of non-empty strings,
  - no line contains a brace (placeholder that failed to fill),
  - the LAST line contains answer_display(problem),
  - answer_display(problem), typed verbatim, grades "correct".

Prose rules (must survive the frontend's pretty() renderer):
  - powers only with digit bases: "7^2" superscripts, "p^(e-1)" would not,
  - multiplication is the middle dot,
  - one thought per list item; no newlines inside a step.
"""

import math

from sympy import divisors, factorint, gcd, isprime

from verify import SENTINEL, is_sentinel, to_base


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def steps_for(problem):
    """Worked solution as a list of step strings. Never raises: by the time
    this runs the problem is already retired, so a rendering bug must degrade
    to a bare answer line, not a 500 that loses both problem and solution."""
    try:
        tpl = problem._template
        if "why" in tpl:  # hand-authored: the stored argument IS the working
            return [str(tpl["why"]), _answer_line(str(tpl["answer"]))]
        fn = RENDERERS[problem.template_id]
        return [str(s) for s in fn(_ints(problem.params))]
    except Exception:
        try:
            return [_answer_line(answer_display(problem))]
        except Exception:
            return ["The full working for this one is not available."]


def answer_display(problem) -> str:
    """The canonical typed form of the answer — what a student could enter
    verbatim and be graded correct. Used by the selftest gate and the
    degraded fallback above."""
    tpl = problem._template
    if "why" in tpl:
        return str(tpl["answer"])
    if tpl.get("checker") == "condition":
        x, y = _CONDITION_WITNESS[tpl["id"]](_ints(problem.params))
        return f"{x}, {y}"
    a = problem._answer
    if is_sentinel(a):
        return SENTINEL
    if isinstance(a, (list, tuple)):
        return SENTINEL if len(a) == 0 else ", ".join(str(v) for v in a)
    return str(a)


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _ints(params):
    """Params arrive as SymPy Integers live, plain ints/strings after a
    restart rebuild. Coerce numbers to int; strings (digit_rules' `shown`)
    pass through — int("52_7") would read the underscore as a separator."""
    return {k: (v if isinstance(v, str) else int(v)) for k, v in params.items()}


def _answer_line(display) -> str:
    return f"So the answer is {display}."


def _join(seq) -> str:
    return ", ".join(str(v) for v in seq)


def _div_line(b, a):
    """'59 = 8·7 + 3.' — the workhorse sentence. Returns (line, q, r)."""
    q, r = divmod(b, a)
    return f"{b} = {q}·{a} + {r}.", q, r


def _ladder(a, b):
    """Euclid on a >= b > 0: division lines down to remainder 0.
    Returns (lines, g, rows) where rows are (x, q, y, r) per line."""
    lines, rows = [], []
    x, y = a, b
    while y:
        q, r = divmod(x, y)
        lines.append(f"{x} = {q}·{y} + {r}.")
        rows.append((x, q, y, r))
        x, y = y, r
    return lines, x, rows


def _combo(cu, u, cv, v) -> str:
    sign = "+" if cv >= 0 else "-"
    return f"{cu}·{u} {sign} {abs(cv)}·{v}"


def _back_sub(rows, g):
    """Back-substitution narration over a ladder's rows.
    Returns (lines, cu, cv) with g = cu*rows[0].x + cv*rows[0].y."""
    work = [row for row in rows if row[3] != 0]
    if not work:  # b divides a exactly: g = b = 0·a + 1·b
        a0, _, b0, _ = rows[0]
        return [f"{b0} divides {a0} exactly, so gcd = {b0} = 0·{a0} + 1·{b0}."], 0, 1
    x_, q_, y_, _ = work[-1]
    cu, u, cv, v = 1, x_, -q_, y_
    lines = ["Now substitute each remainder backwards:",
             f"{g} = {x_} - {q_}·{y_}."]
    for X, Q, Y, _ in reversed(work[:-1]):
        cu, cv = cv, cu - cv * Q
        u, v = X, Y
        lines.append(f"{g} = {_combo(cu, u, cv, v)}.")
    if cu * u + cv * v != g:  # renderer bug tripwire -> steps_for fallback
        raise ArithmeticError("back-substitution went wrong")
    return lines, cu, cv


def _ext(a, b):
    """Extended Euclid with narration. Handles either order.
    Returns (lines, x, y, g) with a*x + b*y = g. Deterministic — the
    condition-witness table below reuses it so narration and canonical
    witness can never disagree."""
    hi, lo = (a, b) if a >= b else (b, a)
    lines, g, rows = _ladder(hi, lo)
    sub_lines, c_hi, c_lo = _back_sub(rows, g)
    if a >= b:
        x, y = c_hi, c_lo
    else:
        x, y = c_lo, c_hi
    return lines + sub_lines, x, y, g


def _factor_str(n) -> str:
    return "·".join(f"{p}^{e}" if e > 1 else f"{p}"
                    for p, e in sorted(factorint(n).items()))


def _phi_lines(n):
    """Compute phi(n) with its reasoning. Returns (lines, phi)."""
    if isprime(n):
        return [f"{n} is prime, so phi({n}) = {n} - 1 = {n - 1}."], n - 1
    fac = sorted(factorint(n).items())
    parts, vals = [], []
    for p, e in fac:
        if e == 1:
            parts.append(f"phi({p}) = {p} - 1 = {p - 1}")
            vals.append(p - 1)
        else:
            parts.append(f"phi({p}^{e}) = {p ** e} - {p ** (e - 1)} = {p ** e - p ** (e - 1)}")
            vals.append(p ** e - p ** (e - 1))
    phi = math.prod(vals)
    return [
        f"Factor: {n} = {_factor_str(n)}.",
        "phi multiplies across prime powers, and " + " and ".join(parts) + ".",
        f"phi({n}) = {'·'.join(str(v) for v in vals)} = {phi}.",
    ], phi


def _square_multiply(a, e, n):
    """Square-and-multiply trace for a^e mod n. Returns (lines, result)."""
    a0 = a % n
    if e == 0:
        return ["Any number to the power 0 is 1."], 1 % n
    start = (f"Start from {a}^1 = {a}, which leaves {a0} mod {n}."
             if a != a0 else f"Start from {a}^1 = {a}.")
    if e == 1:
        return [start, f"The exponent is just 1, so the remainder is {a0}."], a0
    lines = [start]
    table, exp, val = [(1, a0)], 1, a0
    while exp * 2 <= e:
        nv = (val * val) % n
        squared = f"{val * val}" if val == a else f"{val}^2 = {val * val}"
        lines.append(f"{a}^{exp * 2} = {squared}, which leaves {nv}.")
        exp, val = exp * 2, nv
        table.append((exp, val))
    bits, rem = [], e
    for exp, val in reversed(table):
        if exp <= rem:
            bits.append((exp, val))
            rem -= exp
    bits.reverse()
    lines.append(f"Build the exponent from those rows: {e} = "
                 f"{' + '.join(str(x) for x, _ in bits)}.")
    run = bits[0][1]
    if len(bits) == 1:
        lines.append(f"That is a single row, so {a}^{e} leaves {run}.")
    else:
        for _, val in bits[1:]:
            prod = run * val
            nxt = prod % n
            lines.append(f"Multiply the matching remainders: {run}·{val} = "
                         f"{prod}, which leaves {nxt}.")
            run = nxt
    return lines, run


def _crt_merge(m1, r1, m2, r2):
    """Merge two congruences by candidate-walking.
    Returns (lines, L, value_or_SENTINEL) with L = lcm(m1, m2)."""
    d = int(gcd(m1, m2))
    L = m1 * m2 // d
    if (r1 - r2) % d != 0:
        return [
            f"The two divisors share a common factor: gcd({m1}, {m2}) = {d}.",
            f"Mod {d}, the first condition forces remainder {r1 % d} and the "
            f"second forces {r2 % d}: they disagree, so no number can satisfy both.",
        ], L, SENTINEL
    lines = []
    if d > 1:
        lines.append(f"gcd({m1}, {m2}) = {d}, and both conditions agree mod {d} "
                     f"(each forces remainder {r1 % d}), so solutions exist, "
                     f"repeating every lcm({m1}, {m2}) = {L}, not every {m1}·{m2}.")
    cands, x = [], r1
    while x <= L + m1:
        cands.append(x)
        if x % m2 == r2:
            break
        x += m1
    hit = cands[-1]
    if hit % m2 != r2 or hit % m1 != r1 % m1:  # tripwire -> steps_for fallback
        raise ArithmeticError("CRT enumeration missed")
    if len(cands) <= 10:
        lines.append(f"Numbers that leave remainder {r1} when divided by {m1}: "
                     f"{_join(cands)}.")
        lines.append(f"Their remainders when divided by {m2} run "
                     f"{_join(c % m2 for c in cands)}; the first to hit {r2} is {hit}.")
    else:
        lines.append(f"Numbers that leave remainder {r1} when divided by {m1}: "
                     f"{_join(cands[:3])}, ...; test each against 'leaves {r2} "
                     f"when divided by {m2}'.")
        lines.append(f"The first that works is {hit} "
                     f"({hit} = {hit // m2}·{m2} + {r2}).")
    return lines, L, hit


# ---------------------------------------------------------------------------
# F1 — division with remainder
# ---------------------------------------------------------------------------

def _divisibility_basic(P):
    a, b = P["a"], P["b"]
    line, q, r = _div_line(b, a)
    verdict = (f"The remainder is 0, so {a} divides {b} exactly."
               if r == 0 else
               f"The remainder is {r}, not 0, so {a} does not divide {b}.")
    return [f"Divide {b} by {a}: {line}", verdict,
            _answer_line(1 if r == 0 else 0)]


def _divisibility_make_divisible(P):
    a, b = P["a"], P["b"]
    line, q, r = _div_line(b, a)
    out = [f"Divide {b} by {a}: {line}"]
    if r == 0:
        out.append(f"{b} is already a multiple of {a}, so the smallest POSITIVE "
                   f"amount to add jumps to the next multiple: {a} itself.")
        ans = a
    else:
        nxt = (q + 1) * a
        ans = nxt - b
        out.append(f"The next multiple of {a} is {q + 1}·{a} = {nxt}.")
        out.append(f"{nxt} - {b} = {ans}.")
    out.append(_answer_line(ans))
    return out


def _congruence_residue(P):
    a, n = P["a"], P["n"]
    line, q, r = _div_line(a, n)
    return [f"Divide {a} by {n}: {line}",
            f"The remainder, {r}, is the residue of {a} mod {n}.",
            _answer_line(r)]


def _congruence_are_congruent(P):
    a, b, n = P["a"], P["b"], P["n"]
    hi, lo = max(a, b), min(a, b)
    d = hi - lo
    line, q, r = _div_line(d, n)
    out = [f"Congruent mod {n} means {n} divides the difference.",
           f"Subtract: {hi} - {lo} = {d}."]
    if r == 0:
        out.append(f"{d} = {q}·{n} exactly, so {n} divides the difference: congruent.")
    else:
        out.append(f"{line[:-1]}, remainder {r}, so {n} does not divide the "
                   f"difference: not congruent.")
    out.append(_answer_line(1 if r == 0 else 0))
    return out


def _digit_rules_remainder(P):
    n = P["n"]
    digits = [int(c) for c in str(n)]
    s = sum(digits)
    out = [f"Add the digits of {n}: {' + '.join(str(d) for d in digits)} = {s}.",
           "A number and its digit sum leave the same remainder when divided "
           "by 9, because 10, 100, 1000, ... each leave remainder 1."]
    line, q, r = _div_line(s, 9)
    out.append(f"Reduce the digit sum: {line}")
    out.append(_answer_line(r))
    return out


# ---------------------------------------------------------------------------
# F2 — reduce then combine
# ---------------------------------------------------------------------------

def _mod_arith_reduce(P):
    a, b, c, n = P["a"], P["b"], P["c"], P["n"]
    ra, rb = a % n, b % n
    la, qa, _ = _div_line(a, n)
    lb, qb, _ = _div_line(b, n)
    m = ra * rb
    rm = m % n
    t = rm + c
    rt = t % n
    lt, qt, _ = _div_line(t, n)
    return [f"Reduce before multiplying: {la[:-1]}, so {a} leaves {ra}.",
            f"{lb[:-1]}, so {b} leaves {rb}.",
            f"Multiply the small numbers: {ra}·{rb} = {m}, and {m} leaves {rm} mod {n}.",
            f"Add {c}: {rm} + {c} = {t}, and {lt}",
            _answer_line(rt)]


# ---------------------------------------------------------------------------
# F3 — trial division to the square root
# ---------------------------------------------------------------------------

def _sqrt_bound_lines(n):
    s = math.isqrt(n)
    test = [t for t in range(2, s + 1) if isprime(t)]
    return [
        f"If {n} = a·b with both factors above 1, the smaller factor is at most "
        f"the square root: {s}^2 = {s * s} <= {n} < {(s + 1) ** 2} = {s + 1}^2.",
        f"So testing the primes up to {s} is enough: {_join(test)}.",
    ], test


def _primes_is_prime(P):
    n = P["n"]
    out, test = _sqrt_bound_lines(n)
    hit = next((t for t in test if n % t == 0), None)
    if hit is None:
        out.append(f"None of them divides {n}, so {n} is prime.")
        ans = 1
    else:
        before = [t for t in test if t < hit]
        lead = f"{_join(before)} do not divide {n}, but " if before else ""
        out.append(f"{lead}{hit} does: {n} = {hit}·{n // hit}. Not prime.")
        ans = 0
    out.append(_answer_line(ans))
    return out


def _primes_trial_bound(P):
    n = P["n"]
    out, test = _sqrt_bound_lines(n)
    last = test[-1]
    out.append(f"The largest of those, the last prime you would ever need to "
               f"test, is {last}.")
    out.append(_answer_line(last))
    return out


# ---------------------------------------------------------------------------
# F4 — factor table, then a multiplicative formula
# ---------------------------------------------------------------------------

def _factorization_exponent(P):
    n, p = P["n"], P["p"]
    chain, m = [], n
    while m % p == 0:
        chain.append(f"{m} = {p}·{m // p}")
        m //= p
    e = len(chain)
    return [f"Divide by {p} repeatedly: {'; '.join(chain)}; and {p} does not "
            f"divide {m}.",
            f"{p} went in {e} times.",
            _answer_line(e)]


def _factorization_distinct_primes(P):
    n = P["n"]
    primes = sorted(factorint(n))
    return [f"Factor: {n} = {_factor_str(n)}.",
            f"The distinct primes are {_join(primes)}: each counts once, "
            f"whatever its exponent.",
            _answer_line(len(primes))]


def _tau(P):
    n = P["n"]
    fac = sorted(factorint(n).items())
    choices = " and ".join(f"an exponent from 0 to {e} for {p} ({e + 1} choices)"
                           for p, e in fac)
    counts = [e + 1 for _, e in fac]
    total = math.prod(counts)
    return [f"Factor: {n} = {_factor_str(n)}.",
            f"A divisor picks {choices}.",
            f"{'·'.join(str(c) for c in counts)} = {total}.",
            _answer_line(total)]


def _sigma(P):
    n = P["n"]
    fac = sorted(factorint(n).items())
    parts, vals = [], []
    for p, e in fac:
        powers = [p ** i for i in range(e + 1)]
        parts.append(f"the powers of {p} contribute "
                     f"{' + '.join(str(v) for v in powers)} = {sum(powers)}")
        vals.append(sum(powers))
    total = math.prod(vals)
    return [f"Factor: {n} = {_factor_str(n)}.",
            "Sum each prime's powers separately: " + "; ".join(parts) + ".",
            f"{'·'.join(str(v) for v in vals)} = {total}.",
            _answer_line(total)]


def _totient_compute(P):
    lines, phi = _phi_lines(P["n"])
    return lines + [_answer_line(phi)]


def _totient_count_coprime(P):
    n = P["n"]
    lines, phi = _phi_lines(n)
    return ([f"The count of numbers in 1..{n} that share no factor with {n} "
             f"is exactly phi({n})."] + lines + [_answer_line(phi)])


def _gcd_lcm_direct(P):
    a, b = P["a"], P["b"]
    fa, fb = factorint(a), factorint(b)
    shared = sorted(set(fa) & set(fb))
    out = [f"Factor both: {a} = {_factor_str(a)} and {b} = {_factor_str(b)}."]
    if not shared:
        out.append("They share no prime, so the gcd is 1.")
        g = 1
    else:
        pieces = [f"{p}^{min(fa[p], fb[p])}" if min(fa[p], fb[p]) > 1 else f"{p}"
                  for p in shared]
        vals = [p ** min(fa[p], fb[p]) for p in shared]
        g = math.prod(vals)
        out.append(f"Take each shared prime to the smaller power: {_join(pieces)}.")
        out.append(f"{'·'.join(str(v) for v in vals)} = {g}.")
    out.append(_answer_line(g))
    return out


# ---------------------------------------------------------------------------
# F5 — one-line algebra on top of a gcd
# ---------------------------------------------------------------------------

def _gcd_lcm_identity(P):
    a, b, g = P["a"], P["b"], int(gcd(P["a"], P["b"]))
    prod = a * b
    l = prod // g
    return [f"For any two numbers, gcd times lcm equals their product: "
            f"gcd({a}, {b})·lcm({a}, {b}) = {a}·{b}.",
            f"{a}·{b} = {prod}.",
            f"gcd({a}, {b}) = {g}, so lcm({a}, {b}) = {prod} / {g} = {l}.",
            _answer_line(l)]


def _mod_arith_cancellation(P):
    c, n = P["c"], P["n"]
    d = int(gcd(c, n))
    m = n // d
    return [f"{n} divides {c}·(x - y), but part of {c} can soak up part of {n}: "
            f"gcd({c}, {n}) = {d}.",
            f"After the {d} is absorbed, what is still forced on x - y is "
            f"{n} / {d} = {m}.",
            f"So cancelling {c} is valid mod {m}, and mod nothing larger.",
            _answer_line(m)]


# ---------------------------------------------------------------------------
# F6 — the Euclid ladder
# ---------------------------------------------------------------------------

def _euclid_intro(a, b):
    hi, lo = (a, b) if a >= b else (b, a)
    lines, g, rows = _ladder(hi, lo)
    intro = [f"Run the Euclidean algorithm: divide, keep the remainder, repeat:"]
    return intro + lines, g, rows


def _euclidean_gcd(P):
    a, b = P["a"], P["b"]
    lines, g, _ = _euclid_intro(a, b)
    return lines + [f"The last remainder before 0 is {g}, and that is the gcd.",
                    _answer_line(g)]


def _euclidean_steps(P):
    a, b = P["a"], P["b"]
    lines, g, rows = _euclid_intro(a, b)
    return lines + [f"That is {len(rows)} division steps, counting the final "
                    f"one that reaches remainder 0.",
                    _answer_line(len(rows))]


def _bezout_smallest(P):
    a, b = P["a"], P["b"]
    lines, g, _ = _euclid_intro(a, b)
    return ([f"Every number of the form {a}·x + {b}·y is a multiple of "
             f"gcd({a}, {b}), so nothing positive can be smaller than the gcd."]
            + lines
            + [f"The gcd is {g}, and Bezout's identity says {g} itself is "
               f"reachable, so the smallest positive value is {g}.",
               _answer_line(g)])


def _lin_dio_solvable(P):
    a, b, c = P["a"], P["b"], P["c"]
    g = int(gcd(a, b))
    line, q, r = _div_line(c, g)
    out = [f"Every value of {a}·x + {b}·y is a multiple of gcd({a}, {b}) = {g}.",
           f"So a solution exists exactly when {g} divides {c}."]
    if r == 0:
        out.append(f"{c} = {q}·{g}: a multiple. Solvable.")
        ans = 1
    else:
        out.append(f"{line[:-1]}: remainder {r}, so {c} is not a multiple. "
                   f"No solution.")
        ans = 0
    out.append(_answer_line(ans))
    return out


# ---------------------------------------------------------------------------
# F7 — extended Euclid and back-substitution
# ---------------------------------------------------------------------------

def _bezout_witness(P):
    _, x, y, _ = _ext(P["a"], P["b"])
    return x, y


def _lin_dio_witness(P):
    a, b, c = P["a"], P["b"], P["c"]
    _, x, y, g = _ext(a, b)
    k = c // g
    return x * k, y * k


_CONDITION_WITNESS = {
    "bezout_any_pair_01": _bezout_witness,
    "linear_diophantine_any_pair_01": _lin_dio_witness,
}


def _check_pair_line(a, x, b, y, target):
    t1, t2 = a * x, b * y
    sign = "+" if t2 >= 0 else "-"
    return (f"Check: {a}·{x} + {b}·{y} = {t1} {sign} {abs(t2)} = {target}.")


def _bezout_any_pair(P):
    a, b = P["a"], P["b"]
    lines, x, y, g = _ext(a, b)
    return (lines
            + [_check_pair_line(a, x, b, y, g),
               _answer_line(f"{x}, {y}")])


def _lin_dio_any_pair(P):
    a, b, c = P["a"], P["b"], P["c"]
    lines, x0, y0, g = _ext(a, b)
    k = c // g
    x, y = x0 * k, y0 * k
    return (lines
            + [f"That reaches {g}, and we need {c} = {k}·{g}, so scale the whole "
               f"equation by {k}: x = {x0}·{k} = {x}, y = {y0}·{k} = {y}.",
               _check_pair_line(a, x, b, y, c),
               _answer_line(f"{x}, {y}")])


def _inverse_lines(a, n):
    """Extended-Euclid narration for the inverse of a mod n (gcd must be 1).
    Returns (lines, inv)."""
    lines, x, y, g = _ext(a, n)
    inv = x % n
    check_q = (a * inv - 1) // n
    tail = [f"So {a}·{x} + {n}·{y} = 1: multiples of {n} vanish mod {n}, "
            f"leaving {a}·{x} with remainder 1."]
    if x != inv:
        tail.append(f"Shift {x} into the range 0..{n - 1} (add or subtract "
                    f"{n} as needed): the inverse is {inv}.")
    tail.append(f"Check: {a}·{inv} = {a * inv} = {check_q}·{n} + 1.")
    return lines + tail, inv


def _mod_inverse_find(P):
    a, n = P["a"], P["n"]
    d = int(gcd(a, n))
    if d != 1:
        return [f"First check gcd({a}, {n}) = {d}, which is not 1.",
                f"Every value of {a}·x mod {n} is a multiple of {d}, so it can "
                f"never land on 1. No inverse exists.",
                _answer_line(SENTINEL)]
    lines, inv = _inverse_lines(a, n)
    return ([f"gcd({a}, {n}) = 1, so an inverse exists. Find it with the "
             f"extended Euclidean algorithm:"]
            + lines + [_answer_line(inv)])


def _mod_inverse_solve(P):
    a, b, n = P["a"], P["b"], P["n"]
    lines, inv = _inverse_lines(a, n)
    prod = inv * b
    x = prod % n
    lx, qx, _ = _div_line(prod, n)
    ax = a * x
    la, qa, _ = _div_line(ax, n)
    return ([f"To solve {a}·x = {b} (mod {n}), first find the inverse of {a}:"]
            + lines
            + [f"Multiply both sides by {inv}: x = {inv}·{b} = {prod}, and "
               f"{lx[:-1]}, so x = {x}.",
               f"Check: {a}·{x} = {ax} = {qa}·{n} + {b}.",
               _answer_line(x)])


def _lin_dio_smallest_x(P):
    a, b, c = P["a"], P["b"], P["c"]
    g = int(gcd(a, b))
    a2, b2, c2 = a // g, b // g, c // g
    out = [f"{a}·x + {b}·y = {c} says, mod {b}: {a}·x leaves the same "
           f"remainder as {c}.",
           f"gcd({a}, {b}) = {g} divides {c}, so solutions exist. Divide "
           f"everything by {g}: {a2}·x = {c2} (mod {b2}), and now "
           f"gcd({a2}, {b2}) = 1."]
    if b2 == 1:
        x = 1
        out.append("Mod 1 every x works, so the smallest positive x is 1.")
    else:
        inv_lines, inv = _inverse_lines(a2, b2)
        out.append(f"Find the inverse of {a2} mod {b2}:")
        out += inv_lines
        r = (inv * c2) % b2
        x = r if r != 0 else b2
        out.append(f"x = {inv}·{c2} = {inv * c2}, which leaves {r} mod {b2}"
                   + (f", and since we need a POSITIVE x, take {b2} itself."
                      if r == 0 else f", so the smallest positive x is {r}."))
    y = (c - a * x) // b
    out.append(f"Its partner: y = ({c} - {a}·{x}) / {b} = {y}, a whole number, "
               f"and solutions repeat every {b2}, so no smaller positive x works.")
    out.append(_answer_line(x))
    return out


# ---------------------------------------------------------------------------
# F8 — repeated squaring, with or without a theorem shrinking the exponent
# ---------------------------------------------------------------------------

def _mod_exp_large(P):
    a, k, n = P["a"], P["k"], P["n"]
    lines, r = _square_multiply(a, k, n)
    return (["Squaring repeatedly beats multiplying "
             f"{k} times: square and reduce mod {n} at every step."]
            + lines + [_answer_line(r)])


def _mod_exp_last_digit(P):
    a, k = P["a"], P["k"]
    d = a % 10
    cyc, v = [d], d
    while True:
        v = (v * d) % 10
        if v == cyc[0]:
            break
        cyc.append(v)
    L = len(cyc)
    ans = pow(a, k, 10)
    out = [f"Only the last digit of {a} matters: {a} ends in {d}."]
    if L == 1:
        out.append(f"Every power of {d} ends in {d}.")
    else:
        line, q, rem = _div_line(k, L)
        pos = rem if rem != 0 else L
        out.append(f"Last digits of powers of {d} cycle: {_join(cyc)}; the "
                   f"pattern repeats every {L}.")
        out.append(f"{line[:-1]}, so {a}^{k} ends where {d}^{pos} does: {ans}.")
    out.append(_answer_line(ans))
    return out


def _fermat_little_exp(P):
    a, k, p = P["a"], P["k"], P["p"]
    line, q, e = _div_line(k, p - 1)
    sm, r = _square_multiply(a, e, p)
    return ([f"{p} is prime and {a} is not a multiple of {p}, so "
             f"{a}^{p - 1} leaves remainder 1 (Fermat's little theorem).",
             f"Reduce the EXPONENT mod {p - 1}, not mod {p}: {line}",
             f"So {a}^{k} leaves the same remainder as {a}^{e} mod {p}."]
            + sm + [_answer_line(r)])


def _fermat_inverse(P):
    a, p = P["a"], P["p"]
    sm, inv = _square_multiply(a, p - 2, p)
    prod = a * inv
    q = (prod - 1) // p
    return ([f"Fermat: {a}^{p - 1} leaves 1 mod {p}. Peel off one factor: "
             f"{a}·{a}^{p - 2} leaves 1, so {a}^{p - 2} IS the inverse."]
            + sm
            + [f"Check: {a}·{inv} = {prod} = {q}·{p} + 1.",
               _answer_line(inv)])


def _euler_exp(P):
    a, k, n = P["a"], P["k"], P["n"]
    phi_l, phi = _phi_lines(n)
    line, q, e = _div_line(k, phi)
    sm, r = _square_multiply(a, e, n)
    return (phi_l
            + [f"Since gcd({a}, {n}) = 1, Euler's theorem says {a}^{phi} "
               f"leaves remainder 1 mod {n}.",
               f"Reduce the exponent mod {phi}: {line}",
               f"So {a}^{k} leaves the same remainder as {a}^{e} mod {n}."]
            + sm + [_answer_line(r)])


def _euler_reduce_exponent(P):
    k, n = P["k"], P["n"]
    phi_l, phi = _phi_lines(n)
    line, q, e = _div_line(k, phi)
    return (phi_l
            + [f"Euler's theorem lets the exponent shrink mod phi({n}): {line}",
               f"The reduced exponent is {e}.",
               _answer_line(e)])


# ---------------------------------------------------------------------------
# F9 — hunting the multiplicative order
# ---------------------------------------------------------------------------

def _order_mult(P):
    a, n = P["a"], P["n"]
    phi_l, phi = _phi_lines(n)
    divs = sorted(int(d) for d in divisors(phi))
    tests, ans = [], None
    for d in divs:
        r = pow(a, d, n)
        tests.append(f"{a}^{d} leaves {r}")
        if r == 1:
            ans = d
            break
    return (phi_l
            + [f"The order of {a} must divide phi({n}) = {phi}, so only "
               f"{_join(divs)} need testing, smallest first.",
               "Test them in turn: " + "; ".join(tests) + ".",
               f"The first exponent that lands on 1 is {ans}.",
               _answer_line(ans)])


def _order_last_digit_cycle(P):
    a = P["a"]
    d = a % 10
    tests, v, L = [], 1, None
    for e in range(1, 5):
        v = (v * d) % 10
        tests.append(f"{d}^{e} ends in {v}")
        if v == 1:
            L = e
            break
    return ([f"Only the last digit of {a} matters: {a} ends in {d}.",
             "Follow the last digits of its powers until they return to 1: "
             + "; ".join(tests) + ".",
             f"The pattern first returns to 1 after {L} steps, so the cycle "
             f"length is {L}.",
             _answer_line(L)])


# ---------------------------------------------------------------------------
# F10 — enumerating residues under a congruence condition
# ---------------------------------------------------------------------------

def _lin_cong_all(P):
    a, b, n = P["a"], P["b"], P["n"]
    g = int(gcd(a, n))
    sp = n // g
    x0 = next(x for x in range(sp) if (a * x - b) % n == 0)
    sols = [x0 + i * sp for i in range(g)]
    ax0 = a * x0
    return [f"gcd({a}, {n}) = {g}, and {g} divides {b}, so solutions exist: "
            f"exactly {g} of them, spaced {sp} apart.",
            f"Scan for the first: x = {x0} works, since {a}·{x0} = {ax0} "
            f"leaves {ax0 % n} mod {n}.",
            f"Add {sp} repeatedly, staying below {n}: {_join(sols)}.",
            _answer_line(_join(sols))]


def _lin_cong_none(P):
    a, b, n = P["a"], P["b"], P["n"]
    g = int(gcd(a, n))
    line, q, r = _div_line(b, g)
    return [f"gcd({a}, {n}) = {g}. Whatever x is, {a}·x mod {n} is always a "
            f"multiple of {g}.",
            f"But {line[:-1]}: remainder {r}, so {b} is NOT a multiple of {g}, "
            f"and that remainder is unreachable.",
            "This congruence has no solutions at all.",
            _answer_line(SENTINEL)]


def _lin_cong_unique(P):
    a, b, n = P["a"], P["b"], P["n"]
    inv_lines, inv = _inverse_lines(a, n)
    prod = inv * b
    x = prod % n
    ax = a * x
    return ([f"gcd({a}, {n}) = 1, so there is exactly one solution: multiply "
             f"both sides by the inverse of {a}.",
             f"Find that inverse:"]
            + inv_lines
            + [f"x = {inv}·{b} = {prod}, which leaves {x} mod {n}.",
               f"Check: {a}·{x} = {ax} leaves {ax % n} mod {n}: exactly {b}.",
               _answer_line(x)])


def _digit_rules_missing(P):
    m, shown = P["m"], P["shown"]
    d3, d2, d0 = P["d3"], P["d2"], P["d0"]
    base_val = d3 * 1000 + d2 * 100 + d0
    hits = [d for d in range(10) if (base_val + d * 10) % m == 0]
    out = [f"The number is {shown}, with its tens digit d missing."]
    if m in (3, 9):
        s = d3 + d2 + d0
        out.append(f"For {m}, only the digit sum matters: the known digits "
                   f"give {d3} + {d2} + {d0} = {s}.")
        out.append(f"We need {s} + d to be a multiple of {m}. Test d = 0..9: "
                   + (f"{_join(hits)} work." if hits else "none of them works."))
    else:  # m == 11
        s = d0 + d2 - d3
        out.append(f"For 11, use the alternating sum starting from the units "
                   f"digit: {d0} - d + {d2} - {d3} must be a multiple of 11.")
        out.append(f"That forces d to leave the same remainder as "
                   f"{d0} + {d2} - {d3} = {s} mod 11. Among the digits 0..9: "
                   + (f"{_join(hits)} work." if hits else "no digit works."))
    out.append(_answer_line(_join(hits) if hits else SENTINEL))
    return out


# ---------------------------------------------------------------------------
# F11 — Chinese Remainder merging
# ---------------------------------------------------------------------------

def _crt_two_coprime(P):
    m1, r1, m2, r2 = P["m1"], P["r1"], P["m2"], P["r2"]
    lines, L, val = _crt_merge(m1, r1, m2, r2)
    return lines + [f"Below {m1}·{m2} = {L} the answer is unique.",
                    _answer_line(val)]


def _crt_noncoprime(P):
    m1, r1, m2, r2 = P["m1"], P["r1"], P["m2"], P["r2"]
    lines, L, val = _crt_merge(m1, r1, m2, r2)
    out = list(lines)
    if val != SENTINEL:
        out.append(f"Below lcm({m1}, {m2}) = {L} the answer is unique.")
    return out + [_answer_line(val)]


def _crt_three(P):
    m1, r1 = P["m1"], P["r1"]
    m2, r2 = P["m2"], P["r2"]
    m3, r3 = P["m3"], P["r3"]
    l1, M, R = _crt_merge(m1, r1, m2, r2)
    out = ["Combine the conditions two at a time."] + l1
    out.append(f"So the first two conditions together say: leaves remainder "
               f"{R} when divided by {M}.")
    l2, L, val = _crt_merge(M, R, m3, r3)
    out += ["Now fold in the third condition:"] + l2
    out.append(_answer_line(val))
    return out


# ---------------------------------------------------------------------------
# F12 — base conversion
# ---------------------------------------------------------------------------

_DIGITS = "0123456789abcdef"


def _bases_convert(P):
    n, b = P["n"], P["b"]
    lines, m = [], n
    rems = []
    while m:
        q, r = divmod(m, b)
        note = f" (that remainder is the digit '{_DIGITS[r]}')" if r >= 10 else ""
        lines.append(f"{m} = {q}·{b} + {r}." + note)
        rems.append(r)
        m = q
    s = to_base(n, b)
    return ([f"Divide by {b} again and again, keeping every remainder:"]
            + lines
            + [f"Read the remainders bottom to top: {s}.",
               _answer_line(s)])


def _bases_digit_count(P):
    n, b = P["n"], P["b"]
    k = len(to_base(n, b))
    return [f"A number needs k digits in base {b} when it fits between "
            f"two neighbouring powers of {b}.",
            f"{b}^{k - 1} = {b ** (k - 1)} <= {n} < {b ** k} = {b}^{k}, "
            f"so {n} needs {k} digits.",
            _answer_line(k)]


# ---------------------------------------------------------------------------
# F13 — Wilson's theorem
# ---------------------------------------------------------------------------

def _wilson_factorial(P):
    p = P["p"]
    m = p - 1
    if isprime(p):
        return [f"{p} is prime, so in the product 1·2·...·{m} every factor "
                f"pairs off with its inverse mod {p}; only 1 and {m} are their "
                f"own partners.",
                f"Everything else cancels to 1, leaving 1·{m} = {m}; that is, "
                f"-1 mod {p}. This is Wilson's theorem.",
                _answer_line(m)]
    fac = sorted(factorint(p).items())
    if len(fac) == 1:
        q, e = fac[0]
        # two distinct factors below p whose product is a multiple of q^e:
        # e == 2 -> q and 2q (q odd here); e >= 3 -> q and q^(e-1)
        u, v = (q, 2 * q) if e == 2 else (q, q ** (e - 1))
    else:
        u = fac[0][0] ** fac[0][1]
        v = p // u
    return [f"{p} is not prime: {p} = {_factor_str(p)}.",
            f"Both {u} and {v} appear among 1..{m}, and {u}·{v} = {u * v} is "
            f"a multiple of {p}, so the product {m}! is a multiple of {p} too.",
            f"A multiple of {p} leaves remainder 0.",
            _answer_line(0)]


def _wilson_primality(P):
    p, v = P["p"], P["v"]
    m = p - 1
    prime = isprime(p)
    out = [f"Wilson's theorem cuts both ways: ({p} - 1)! leaves {p} - 1 "
           f"(that is, -1) mod {p} exactly when {p} is prime, and for a "
           f"composite this size it leaves 0 instead."]
    if v == m:
        out.append(f"Here the remainder is {v}, which IS {p} - 1, so {p} "
                   f"is prime.")
    else:
        out.append(f"Here the remainder is {v}, not {m}, so {p} is not prime.")
    out.append(_answer_line(1 if prime else 0))
    return out


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

RENDERERS = {
    "divisibility_basic_01": _divisibility_basic,
    "divisibility_make_divisible_01": _divisibility_make_divisible,
    "primes_is_prime_01": _primes_is_prime,
    "primes_trial_bound_01": _primes_trial_bound,
    "factorization_exponent_01": _factorization_exponent,
    "factorization_distinct_primes_01": _factorization_distinct_primes,
    "gcd_lcm_identity_01": _gcd_lcm_identity,
    "gcd_lcm_direct_01": _gcd_lcm_direct,
    "euclidean_gcd_01": _euclidean_gcd,
    "euclidean_steps_01": _euclidean_steps,
    "divisor_functions_tau_01": _tau,
    "divisor_functions_sigma_01": _sigma,
    "bases_convert_01": _bases_convert,
    "bases_digit_count_01": _bases_digit_count,
    "digit_rules_missing_01": _digit_rules_missing,
    "digit_rules_remainder_01": _digit_rules_remainder,
    "congruence_residue_01": _congruence_residue,
    "congruence_are_congruent_01": _congruence_are_congruent,
    "mod_arith_reduce_01": _mod_arith_reduce,
    "mod_arith_cancellation_01": _mod_arith_cancellation,
    "mod_exp_large_01": _mod_exp_large,
    "mod_exp_last_digit_01": _mod_exp_last_digit,
    "mod_inverse_find_01": _mod_inverse_find,
    "mod_inverse_solve_01": _mod_inverse_solve,
    "bezout_any_pair_01": _bezout_any_pair,
    "bezout_smallest_combination_01": _bezout_smallest,
    "linear_diophantine_smallest_x_01": _lin_dio_smallest_x,
    "linear_diophantine_solvable_01": _lin_dio_solvable,
    "linear_diophantine_any_pair_01": _lin_dio_any_pair,
    "linear_congruence_all_01": _lin_cong_all,
    "linear_congruence_none_01": _lin_cong_none,
    "linear_congruence_unique_01": _lin_cong_unique,
    "crt_two_coprime_01": _crt_two_coprime,
    "crt_noncoprime_01": _crt_noncoprime,
    "crt_three_01": _crt_three,
    "fermat_little_exp_01": _fermat_little_exp,
    "fermat_inverse_01": _fermat_inverse,
    "totient_compute_01": _totient_compute,
    "totient_count_coprime_01": _totient_count_coprime,
    "euler_theorem_exp_01": _euler_exp,
    "euler_theorem_reduce_exponent_01": _euler_reduce_exponent,
    "order_mult_01": _order_mult,
    "order_last_digit_cycle_01": _order_last_digit_cycle,
    "wilson_factorial_01": _wilson_factorial,
    "wilson_primality_01": _wilson_primality,
}
