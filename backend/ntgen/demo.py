"""demo.py — see the thing work. Run: python3 demo.py"""

import random
from generator import (
    load_templates, generate, load_hand_authored, hand_authored_problem,
)
from verify import safe_eval

rng = random.Random(7)
templates = load_templates()

print("=" * 62)
print("ONE PROBLEM FROM EACH TEMPLATE")
print("=" * 62)
for tpl in templates.values():
    p = generate(tpl, rng)
    ans = p._answer if p._answer is not None else "(any valid pair)"
    print(f"\n[{p.node}]")
    print(f"  Q: {p.prompt}")
    print(f"  format: {p.answer_format}")
    print(f"  answer: {ans}")

print("\n" + "=" * 62)
print("SAME TEMPLATE, DIFFERENT PROBLEMS  (this is the point)")
print("=" * 62)
tpl = templates["mod_exp_large_01"]
for _ in range(5):
    p = generate(tpl, rng)
    print(f"  {p.prompt:<34} -> {p._answer}")

print("\n" + "=" * 62)
print("GRADING: FORMAT VARIANTS OF THE SAME ANSWER")
print("=" * 62)
p = generate(templates["gcd_lcm_identity_01"], rng)
print(f"  Q: {p.prompt}   (answer {p._answer})")
for typed in [str(p._answer), f" {p._answer} ", f"{p._answer}.0", f"${p._answer}$", "banana"]:
    print(f"    typed {typed!r:<14} -> {p.check(typed)}")

print("\n" + "=" * 62)
print("BEZOUT: MANY CORRECT ANSWERS, NO STORED KEY")
print("=" * 62)
from sympy import gcdex
p = generate(templates["bezout_any_pair_01"], rng)
a, b, g = p.params["a"], p.params["b"], p.params["g"]
x, y, _ = gcdex(a, b)
x, y = int(x), int(y)
print(f"  Q: {p.prompt}")
for dx in range(3):
    xi, yi = x + dx * (b // g), y - dx * (a // g)
    print(f"    ({xi}, {yi}) -> {p.check(f'{xi}, {yi}')}")
print(f"    ({x+1}, {y})  [wrong] -> {p.check(f'{x+1}, {y}')}")

print("\n" + "=" * 62)
print("LINEAR CONGRUENCE: PARTIAL ANSWERS MUST FAIL")
print("=" * 62)
p = generate(templates["linear_congruence_all_01"], rng)
sols = p._answer
print(f"  Q: {p.prompt}")
print(f"    all {sols}          -> {p.check(', '.join(map(str, sols)))}")
print(f"    reversed            -> {p.check(', '.join(map(str, reversed(sols))))}")
print(f"    only first ({sols[0]})      -> {p.check(str(sols[0]))}")

print("\n" + "=" * 62)
print("BASES: ANSWERS ARE STRINGS, NOT NUMBERS")
print("=" * 62)
p = generate(templates["bases_convert_01"], rng)
print(f"  Q: {p.prompt}   (answer {p._answer})")
for typed in [str(p._answer), f"  {p._answer} ", f"0b{p._answer}", f"00{p._answer}", f"{p._answer}0"]:
    print(f"    typed {typed!r:<14} -> {p.check(typed)}")

print("\n" + "=" * 62)
print("SENTINEL: 'NO SUCH VALUE EXISTS' IS A GRADEABLE ANSWER")
print("=" * 62)
# keep sampling until we land on one of each case, so the demo always shows both
inv = templates["mod_inverse_find_01"]
exists = next(q for q in (generate(inv, rng) for _ in range(200)) if q._answer != "none")
missing = next(q for q in (generate(inv, rng) for _ in range(200)) if q._answer == "none")
print(f"  Q: {exists.prompt}")
print(f"    answer is {exists._answer}")
print(f"    typed {str(exists._answer)!r:<8} -> {exists.check(str(exists._answer))}")
print(f"    typed 'none'   -> {exists.check('none')}   <- an inverse DOES exist here")
print(f"\n  Q: {missing.prompt}")
print(f"    gcd({missing.params['a']}, {missing.params['n']}) > 1, so there is no inverse")
for typed in ["none", "No solution", "DNE", "3"]:
    print(f"    typed {typed!r:<12} -> {missing.check(typed)}")

print("\n" + "=" * 62)
print("CRT: NON-COPRIME MODULI, CONSISTENT AND INCONSISTENT")
print("=" * 62)
nc = templates["crt_noncoprime_01"]
ok = next(q for q in (generate(nc, rng) for _ in range(200)) if q._answer != "none")
bad = next(q for q in (generate(nc, rng) for _ in range(200)) if q._answer == "none")
print(f"  Q: {ok.prompt}\n    -> {ok._answer}")
print(f"  Q: {bad.prompt}\n    -> no solution (residues disagree mod {bad.params['d']})")

print("\n" + "=" * 62)
print("DIGIT RULES: SOME QUESTIONS HAVE TWO CORRECT DIGITS")
print("=" * 62)
dr = templates["digit_rules_missing_01"]
multi = next(q for q in (generate(dr, rng) for _ in range(500)) if len(q._answer) > 1)
print(f"  Q: {multi.prompt}")
print(f"    all {multi._answer}   -> {multi.check(', '.join(map(str, multi._answer)))}")
print(f"    only {multi._answer[0]}       -> {multi.check(str(multi._answer[0]))}   <- incomplete, so wrong")

print("\n" + "=" * 62)
print("DISTRACTORS: THE WRONG ANSWER WE CAN PREDICT")
print("=" * 62)
print("  Each of these templates knows the value a student produces when they")
print("  make this node's classic mistake. Phase 5 turns that into a targeted hint.")
for tid in ["gcd_lcm_identity_01", "mod_exp_large_01", "fermat_little_exp_01",
            "divisor_functions_tau_01", "mod_arith_cancellation_01"]:
    tpl = templates[tid]
    p = generate(tpl, rng)
    predicted = safe_eval(tpl["distractor_expr"], p.params)
    mistake = tpl["distractor_note"].split(".")[0]
    print(f"\n  [{p.node}] {p.prompt}")
    print(f"     correct: {p._answer}   |   predicted mistake: {predicted}")
    print(f"     {mistake}")

print("\n" + "=" * 62)
print("PIGEONHOLE: THE ONE NODE WITH A HUMAN-WRITTEN ANSWER KEY")
print("=" * 62)
hand = load_hand_authored()
for entry in list(hand.values())[:2]:
    p = hand_authored_problem(entry)
    print(f"\n  Q: {p.prompt}")
    print(f"     answer: {entry['answer']}   (checks: {p.check(entry['answer'])})")
    print(f"     why:    {entry['why'][:150]}...")
print(f"\n  {len(hand)} hand-authored problems. Every other problem in this")
print("  project has its answer computed by SymPy at serve time.")
