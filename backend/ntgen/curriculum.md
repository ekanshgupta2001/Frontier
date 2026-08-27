# Number Theory Curriculum

v0.1 draft, VoltHacks. Structure: prerequisite DAG, not a topic list. Each lesson's
id matches `number-theory-dag.json`. Tiers 0 and 1 are the demo surface — authored in
full. Tiers 2 and 3 are outlined only.

How to read this: **prereqs are hard edges** — a student cannot be served a problem
from a node until every prereq is mastered; if you disagree with an edge, change it
here first (the JSON follows this doc, not the other way around). **Concept** is what
the student reads. **Key results** are the facts a problem may assume. **Worked
example** is the model solution. **Common mistakes** feed the hint system — the wrong
answers worth detecting specifically. **Problem types** is what the generator produces.

This file is parsed by `backend/ntgen/curriculum.py` and served at `/api/curriculum` —
the format (`## number name`, `id:`, `prereqs:`, `**Section.**` paragraphs) is load-bearing.
The gate validates every lesson against the DAG: ids, tiers, and prereq edges must match.

# Tier 0 — Core foundation

*Arithmetic structure of the integers. No modular language yet.*

## 0.1 Divisibility and multiples

id: divisibility
prereqs: none

**Concept.** We write a | b to mean b = ak for some integer k. Note this is a statement, not an operation — a | b is true or false, unlike a / b which produces a number. This distinction is the single most common source of confusion at this level.

**Key results.** If a | b and b | c then a | c. If a | b and a | c then a | (bx + cy) for any integers x, y — the linear combination property, which quietly powers most of tier 1. Every integer divides 0. 1 divides everything.

**Worked example.** Show that if a | b and a | (b + c), then a | c. Since a divides both b and b + c, it divides the combination (b + c) − b = c. Note we never divided anything.

**Common mistakes.** Reading a | b backwards (thinking it means a divided by b). Assuming a | bc implies a | b or a | c — false unless a is prime, and this failure is worth a dedicated distractor problem.

**Problem types.** Decide whether a | b. Find all divisors of n below a bound. Given a | b and a | c, decide which combinations a must divide.

## 0.2 Primes and composites

id: primes
prereqs: divisibility

**Concept.** A prime has exactly two positive divisors. 1 is excluded deliberately — not by convention for its own sake, but because unique factorization would fail if 1 were prime.

**Key results.** Trial division only needs to test up to sqrt(n): if n = ab with both factors above sqrt(n), then ab > n, a contradiction. There are infinitely many primes (Euclid's argument). Euclid's lemma: if p is prime and p | ab, then p | a or p | b.

**Worked example.** Is 221 prime? sqrt(221) is about 14.9, so test 2, 3, 5, 7, 11, 13. 221 = 13 × 17. Composite. We tested six numbers instead of 219.

**Common mistakes.** Testing all the way to n/2. Forgetting to test 2 because the number "looks odd-ish". Believing large numbers ending in 1, 3, 7, 9 are usually prime.

**Problem types.** Primality of n in [50, 400]. Largest divisor that must be tested. Count primes in a range.

## 0.3 Prime factorization

id: factorization
prereqs: primes

**Concept.** The fundamental theorem of arithmetic: every integer greater than 1 factors into primes in exactly one way, up to ordering. Uniqueness is the part that matters — it lets us treat the exponent vector as the number's identity.

**Key results.** Canonical form n = p1^e1 × p2^e2 × ... × pk^ek. Exponents add under multiplication: v_p(ab) = v_p(a) + v_p(b). This is the seed of p-adic valuation in tier 2.

**Worked example.** 360 = 2^3 × 3^2 × 5. Peel off small primes: 360 / 2 = 180, /2 = 90, /2 = 45, /3 = 15, /3 = 5, /5 = 1.

**Common mistakes.** Stopping at a partial factorization (writing 360 = 8 × 45 and calling it done). Dropping exponent 1 primes when reassembling.

**Problem types.** Factor n. Exponent of a specific prime in n. Smallest n with a given exponent pattern.

## 0.4 GCD and LCM

id: gcd_lcm
prereqs: factorization

**Concept.** Take the shared prime structure: gcd takes the minimum exponent on each prime, lcm takes the maximum.

**Key results.** gcd(a,b) × lcm(a,b) = ab, which follows immediately from min(x,y) + max(x,y) = x + y applied exponent by exponent. Two numbers are coprime when gcd = 1.

**Worked example.** a = 84 = 2^2·3·7, b = 360 = 2^3·3^2·5. gcd = 2^2·3 = 12. lcm = 2^3·3^2·5·7 = 2520. Check: 12 × 2520 = 30240 = 84 × 360.

**Common mistakes.** Multiplying all shared primes at max exponent for the gcd. Assuming lcm(a,b) = ab, which only holds when they are coprime.

**Problem types.** Compute gcd or lcm from factorizations. Recover the fourth value from the product identity. Find all pairs with a given gcd and lcm.

## 0.5 Euclidean algorithm

id: euclidean
prereqs: gcd_lcm

**Concept.** gcd(a, b) = gcd(b, a mod b). Repeat until the remainder is 0; the last nonzero remainder is the gcd. This matters because it finds gcds of numbers far too large to factor.

**Key results.** Correctness follows from the linear combination property in 0.1: any common divisor of a and b also divides a − qb. Termination follows because remainders strictly decrease. Worst case is consecutive Fibonacci numbers.

**Worked example.** gcd(1071, 462): 1071 = 2·462 + 147; 462 = 3·147 + 21; 147 = 7·21 + 0. Answer 21. Factoring 1071 by hand would have been slower.

**Common mistakes.** Returning the last remainder computed (0) rather than the last nonzero one. Swapping a and b incorrectly on the first step — harmless, it self-corrects in one round, and it is worth telling students this.

**Problem types.** gcd of large pairs. Number of division steps. Identify the pair below N requiring the most steps.

## 0.6 Divisor count and sum

id: divisor_functions
prereqs: factorization

**Concept.** Divisors of n correspond exactly to choices of exponent for each prime, independently. That correspondence gives both formulas at once.

**Key results.** tau(n) = product of (e_i + 1). sigma(n) = product of (p_i^(e_i+1) − 1)/(p_i − 1). n is a perfect square exactly when tau(n) is odd.

**Worked example.** n = 360 = 2^3·3^2·5. tau = 4·3·2 = 24 divisors. sigma = 15 · 13 · 6 = 1170.

**Common mistakes.** Using e_i instead of e_i + 1. Adding the per-prime factors instead of multiplying them.

**Problem types.** tau(n), sigma(n). Smallest n with exactly k divisors. Why tau(n) odd implies a perfect square.

## 0.7 Base representation

id: bases
prereqs: divisibility

**Concept.** Every positive integer has a unique representation in base b as a sum of digits times powers of b, with digits in [0, b−1]. Base 10 is arbitrary; the structure is not.

**Key results.** Repeated division by b produces digits from least significant upward. The number of digits of n in base b is floor(log_b n) + 1.

**Worked example.** 156 in base 7: 156 = 3·49 + 9, 9 = 1·7 + 2, so 156 = 312 base 7. Check: 3·49 + 1·7 + 2 = 156.

**Common mistakes.** Reading digits in the order produced by division rather than reversing them. Allowing a digit equal to b.

**Problem types.** Convert both directions. Digit count. Leading digit. Numbers that are palindromes in two bases.

## 0.8 Digit sums and divisibility rules

id: digit_rules
prereqs: bases, divisibility

**Concept.** Divisibility rules are not tricks — they are the first modular arithmetic the student meets, one node early. The rule for 3 and 9 works because 10 leaves remainder 1 when divided by 3 or 9, so each digit contributes its face value. The rule for 11 alternates because 10 leaves remainder −1.

**Key results.** n and its digit sum leave the same remainder mod 3 and mod 9. n and its alternating digit sum leave the same remainder mod 11. Rules for 2, 4, 8, 5, 25 depend only on trailing digits, because higher powers of 10 are already divisible.

**Worked example.** Find d so that 34d17 is divisible by 9. Digit sum is 3+4+d+1+7 = 15 + d. Need 15 + d divisible by 9, so d = 3.

**Common mistakes.** Applying the digit sum rule to 7 or 13 by analogy. Getting the sign order wrong on the alternating sum for 11 — worth noting that either starting sign works, since the two answers differ by a factor of −1 and 11 divides one exactly when it divides the other.

**Problem types.** Solve for a missing digit. Explain why a rule works. Smallest number with a given digit sum divisible by k.

# Tier 1 — Contest foundation

*Modular arithmetic and the classical theorems. Most contest number theory lives here.*

## 1.1 Congruence relation

id: congruence
prereqs: divisibility, euclidean

**Concept.** a ≡ b (mod n) means n divides a − b. This is a genuine change of viewpoint, not new notation: we stop caring about integers and start caring about which of n boxes they land in.

**Key results.** Congruence mod n is reflexive, symmetric, transitive — an equivalence relation partitioning the integers into n residue classes. Every integer is congruent to exactly one of 0, 1, ..., n−1.

**Worked example.** Is 347 ≡ 62 (mod 15)? 347 − 62 = 285 = 15 × 19. Yes.

**Common mistakes.** Treating negative residues as errors — −3 ≡ 12 (mod 15) is perfectly valid and often more convenient. Losing the modulus mid-problem.

**Problem types.** Reduce a to its residue. Decide congruence of a pair. Find all x in a range congruent to r mod n.

## 1.2 Modular addition and multiplication

id: mod_arith
prereqs: congruence

**Concept.** Congruence survives addition, subtraction, and multiplication: you may reduce at any point without changing the answer. It does not survive division, and that failure is the reason node 1.4 exists.

**Key results.** If a ≡ b and c ≡ d (mod n), then a + c ≡ b + d and ac ≡ bd. Reducing early keeps numbers small. Cancellation fails: 2·3 ≡ 2·8 (mod 10) but 3 is not congruent to 8.

**Worked example.** 47 × 53 mod 9. Reduce first: 47 ≡ 2, 53 ≡ 8, so the product is 16 ≡ 7 (mod 9). No large multiplication needed.

**Common mistakes.** Cancelling a common factor from both sides — this is the single most important error to detect and hint on, because it looks legal.

**Problem types.** Evaluate expressions mod n. Distractor problems where naive cancellation gives a wrong answer.

## 1.3 Modular exponentiation

id: mod_exp
prereqs: mod_arith, bases

**Concept.** Repeated squaring computes a^k mod n in roughly log2(k) multiplications by reading k in binary — which is why base representation is a prerequisite.

**Key results.** a^(2m) = (a^m)^2 and a^(2m+1) = a·(a^m)^2. Reduce mod n at every step so intermediate values stay bounded.

**Worked example.** 3^13 mod 11. 13 in binary is 1101. 3^1 = 3; 3^2 = 9; 3^4 = 81 ≡ 4; 3^8 ≡ 16 ≡ 5. Then 3^13 = 3^8 · 3^4 · 3^1 ≡ 5·4·3 = 60 ≡ 5 (mod 11).

**Common mistakes.** Reducing the exponent mod n instead of the base — a serious error worth its own hint, since the correct exponent reduction requires 1.8 or 1.10.

**Problem types.** a^k mod n for large k. Last digit of a^k. Count multiplications required.

## 1.4 Bezout's identity

id: bezout
prereqs: euclidean

**Concept.** The gcd of a and b is always expressible as ax + by for some integers x, y. Running the Euclidean algorithm backwards constructs the pair. This node sits before modular inverses on purpose — extended Euclid is how an inverse gets built, so teaching inverses first leaves students memorizing rather than constructing.

**Key results.** gcd(a,b) is the smallest positive integer expressible as ax + by. Solutions are not unique: (x + b/g, y − a/g) works too.

**Worked example.** gcd(1071, 462) = 21. Back-substitute: 21 = 462 − 3·147, and 147 = 1071 − 2·462, so 21 = 462 − 3(1071 − 2·462) = 7·462 − 3·1071. Check: 3234 − 3213 = 21.

**Common mistakes.** Losing track of signs during back-substitution. Assuming there is one right answer — the grader must accept any valid pair, which is a real implementation requirement, not a nicety.

**Problem types.** Find any (x, y). Find the solution with smallest positive x. Show a given pair is valid.

## 1.5 Modular inverses

id: mod_inverse
prereqs: mod_arith, bezout

**Concept.** The inverse of a mod n is the x with ax ≡ 1 (mod n). It exists exactly when gcd(a, n) = 1, and Bezout hands it to you: if ax + ny = 1, then ax ≡ 1 (mod n), so x is the inverse.

**Key results.** Existence iff coprimality. The inverse is unique mod n. When n is prime, every nonzero residue is invertible — this is what makes prime moduli well behaved.

**Worked example.** Inverse of 7 mod 26. Extended Euclid gives 7·15 − 26·4 = 1, so the inverse is 15. Check: 105 = 4·26 + 1.

**Common mistakes.** Trying to invert an a sharing a factor with n and producing a number anyway. Confusing the inverse with n − a.

**Problem types.** Compute an inverse. Decide existence and explain the failure. Invert every residue mod a small prime.

## 1.6 Linear Diophantine equations

id: linear_diophantine
prereqs: bezout

**Concept.** ax + by = c has integer solutions exactly when gcd(a,b) divides c. Scale a Bezout pair to get one solution, then generate the rest.

**Key results.** With g = gcd(a,b) and a particular solution (x0, y0), the full family is x = x0 + t(b/g), y = y0 − t(a/g) for integer t. Word problems asking for nonnegative solutions are asking for a bounded slice of this family.

**Worked example.** 12x + 18y = 30. g = 6 divides 30. From 12·(−1) + 18·1 = 6, scale by 5: x0 = −5, y0 = 5. Family: x = −5 + 3t, y = 5 − 2t.

**Common mistakes.** Reporting one solution when the question asked for all. Forgetting to divide b and a by g in the family, which produces a sparse subset of the real solution set.

**Problem types.** Decide solvability. Give the full family. Count nonnegative solutions. Coin and postage word problems.

## 1.7 Linear congruences

id: linear_congruence
prereqs: mod_inverse, linear_diophantine

**Concept.** ax ≡ b (mod n) is the same object as ax + ny = b viewed through 1.1. When gcd(a,n) = 1 you multiply by the inverse and you are done; when it is g > 1 the equation has g solutions or none.

**Key results.** Solvable iff g = gcd(a,n) divides b. When solvable there are exactly g solutions mod n, spaced n/g apart.

**Worked example.** 6x ≡ 8 (mod 10). g = 2 divides 8, so expect 2 solutions. Divide through: 3x ≡ 4 (mod 5), inverse of 3 mod 5 is 2, so x ≡ 8 ≡ 3 (mod 5). Lifting back: x ≡ 3 or 8 (mod 10).

**Common mistakes.** Reporting one solution when g > 1 — students who only learned the inverse shortcut consistently miss the rest. Dividing b by g without also dividing the modulus.

**Problem types.** Solve for all x. Count solutions. Identify unsolvable cases.

## 1.8 Fermat's little theorem

id: fermat_little
prereqs: mod_exp, mod_inverse

**Concept.** For prime p and a not divisible by p, a^(p−1) ≡ 1 (mod p). The practical consequence is that exponents may be reduced mod p−1 — note the modulus for exponents differs from the modulus for bases, and this is where most errors originate.

**Key results.** a^(p−1) ≡ 1 (mod p). Equivalently a^p ≡ a (mod p) with no coprimality condition. Gives an inverse for free: a^(p−2) ≡ a^(−1) (mod p).

**Worked example.** 2^1000 mod 13. Since 12 divides evenly into 1000 with remainder 4 (1000 = 83·12 + 4), 2^1000 ≡ 2^4 = 16 ≡ 3 (mod 13).

**Common mistakes.** Reducing the exponent mod p instead of p−1. Applying the theorem when p is composite. Applying it when p divides a.

**Problem types.** Huge exponents mod a prime. Inverses via a^(p−2). Detect where the hypothesis fails.

## 1.9 Euler's totient function

id: totient
prereqs: factorization, congruence

**Concept.** phi(n) counts the integers in [1, n] coprime to n — equivalently, the count of invertible residues mod n. Note this node depends on factorization and congruence, not on Fermat: it is a counting fact, and wiring it downstream of Fermat would falsely lock students out.

**Key results.** phi(p) = p − 1. phi(p^e) = p^e − p^(e−1). phi is multiplicative on coprime arguments, so phi(n) = n · product over distinct primes of (1 − 1/p).

**Worked example.** phi(360) with 360 = 2^3·3^2·5: 360 · (1/2) · (2/3) · (4/5) = 96.

**Common mistakes.** Applying multiplicativity to non-coprime factors — phi(4)·phi(6) is not phi(24). Using p^e − p for phi(p^e).

**Problem types.** Compute phi(n). Find n given phi(n) in small cases. Count invertible residues.

## 1.10 Euler's theorem

id: euler_theorem
prereqs: totient, fermat_little

**Concept.** a^phi(n) ≡ 1 (mod n) whenever gcd(a,n) = 1. Fermat is the special case n prime, where phi(p) = p − 1.

**Key results.** Exponents reduce mod phi(n). The coprimality condition is essential and cannot be dropped for composite n.

**Worked example.** 7^222 mod 15. phi(15) = 8, and 222 = 27·8 + 6, so 7^222 ≡ 7^6. 7^2 = 49 ≡ 4, so 7^6 ≡ 4^3 = 64 ≡ 4 (mod 15).

**Common mistakes.** Ignoring the coprimality requirement. Reducing exponents mod n. Assuming phi(n) is the smallest exponent that works — it need not be, which is exactly what 1.11 addresses.

**Problem types.** Large exponents mod composite n. Identify cases where the hypothesis fails.

## 1.11 Multiplicative order and cyclicity

id: order
prereqs: euler_theorem

**Concept.** The order of a mod n is the smallest positive k with a^k ≡ 1. Euler gives an exponent that works; the order is the exponent that actually generates the cycle.

**Key results.** The order always divides phi(n) — so you only test divisors of phi(n), never all k. The powers of a repeat with period equal to the order.

**Worked example.** Order of 2 mod 7. phi(7) = 6, so test divisors 1, 2, 3, 6. 2^1 = 2, 2^2 = 4, 2^3 = 8 ≡ 1. Order is 3.

**Common mistakes.** Testing every k from 1 upward rather than only divisors of phi(n). Assuming the order equals phi(n) — that is the special case of a primitive root.

**Problem types.** Find the order. Cycle length of last digits of a^k. Which a have order equal to phi(n).

## 1.12 Chinese remainder theorem

id: crt
prereqs: linear_congruence

**Concept.** A system of congruences with pairwise coprime moduli has exactly one solution modulo the product. Structurally, working mod 35 is the same as working mod 5 and mod 7 simultaneously.

**Key results.** Existence and uniqueness mod the product of the moduli when they are pairwise coprime. When moduli are not coprime the system may still be solvable, but only if the congruences agree on shared factors — this is worth teaching rather than hiding.

**Worked example.** x ≡ 2 (mod 3), x ≡ 3 (mod 5), x ≡ 2 (mod 7). From the first two, x ≡ 8 (mod 15). Numbers of the form 8 + 15t: 8, 23, 38, 53, 68, 83, 98 — of these, 23 satisfies x ≡ 2 (mod 7). So x ≡ 23 (mod 105).

**Common mistakes.** Applying the theorem to non-coprime moduli without checking consistency. Reporting the solution mod one of the individual moduli instead of the product.

**Problem types.** Solve 2 or 3 congruence systems. Detect inconsistency. Calendar and remainder word problems.

## 1.13 Wilson's theorem

id: wilson
prereqs: fermat_little

**Concept.** (p−1)! ≡ −1 (mod p) exactly when p is prime. The proof pairs each residue with its inverse; only 1 and p−1 are self-inverse, so everything else cancels.

**Key results.** The converse holds too, making this a primality characterization — though a useless one computationally, which is worth saying out loud.

**Worked example.** p = 7: 6! = 720 = 102·7 + 6, so 6! ≡ 6 ≡ −1 (mod 7).

**Common mistakes.** Expecting +1. Trying to use it as a practical primality test.

**Problem types.** Compute (p−1)! mod p. Factorial congruences. Explain the pairing argument.

## 1.14 Pigeonhole in number theory

id: pigeonhole_nt
prereqs: congruence

**Concept.** Among any n+1 integers, two share a residue mod n — so their difference is divisible by n. This is the standard route to statements of the form "some subset must be divisible by n".

**Key results.** The n+1 objects into n boxes principle, with residue classes as the boxes. Prefix sums are the usual construction for "some consecutive block is divisible by n".

**Worked example.** Given any 5 integers, two have a difference divisible by 4. There are only 4 residue classes mod 4, so among 5 numbers two land in the same class.

**Common mistakes.** Choosing the wrong pigeons or holes. Concluding two numbers are equal rather than congruent.

**Implementation note.** This node is proof-flavoured and does not parameterize cleanly. Its problems are hand-authored (backend/ntgen/hand_authored.json) and marked non-generated. Do not let the model freestyle here.

**Problem types.** Difference divisible by n. Consecutive blocks via prefix sums. Generalised counting (ceil(n/k) guarantees).

# Beyond — Tiers 2 and 3 (outline only)

These exist so the graph has visible depth. Do not author problems for them unless there is time left after real student testing.

Tier 2 (olympiad): p-adic valuation → Legendre's formula → lifting the exponent. Quadratic residues → Legendre symbol and reciprocity. Primitive roots (from order). Multiplicative functions and Mobius → Mobius inversion. Infinite descent and Vieta jumping. Sum of two squares.

Tier 3 (applied): Sieve of Eratosthenes (from primes). Probabilistic primality testing (from Fermat and modular exponentiation), including why Carmichael numbers defeat the naive Fermat test. RSA (from Euler's theorem, modular inverses, primality testing) — a genuine curriculum endpoint with real prerequisite edges, not decoration.

# Appendix — open decisions (resolved)

1. Does 1.14 stay? **Resolved: kept.** Five hand-authored problems live in backend/ntgen/hand_authored.json, each carrying its full written argument (`why`) and a tightness check; the reveal flow shows the argument.

2. How many problems per node before mastery? **Resolved: three consecutive correct, frozen** through user testing (PROJECT.md §5.3; `MASTERY_STREAK` in backend/ntgen/graph.py). Reset-to-zero on a miss; unparseable input is not an attempt.

3. Are 1.13 and 1.14 on the critical path? **Resolved: both kept.** Neither cut was needed; both are authored and gated.

4. What does the diagnostic ask first? **Resolved: implemented as a prerequisite-graph bisection** (backend/ntgen/diagnostic.py) — at most 6 questions, inferring prerequisites from answers rather than walking from a fixed start.
