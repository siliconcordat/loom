# Exact Inertia Certificates for Positive-Semidefinite Tests

This paper describes a way to decide, with no floating-point eigenvalues and no threshold, whether a symmetric or Hermitian matrix is positive semidefinite, or has at most `b` positive eigenvalues. An untrusted program supplies a factorization.
A short checker multiplies it out in exact fractions and reads the answer from the factors. The checker is [`scripts/inertia_cert.py`](../scripts/inertia_cert.py). Every number below tagged `verified` can be rerun with [`scripts/verify_inertia.py`](../scripts/verify_inertia.py).

The paper also proves a family of lower bounds on the rank of a positive semidefinite part of a matrix, and applies the certificate to two cases: a two-bar truss and a low-rank weight adapter. Statuses follow the Evidence Discipline in the `README`:
`verified` means a rerunnable command and its output or a proof given here, `hypothesis` means a proposed mechanism with a test and a kill condition stated in advance, `source claim` means a statement taken from an outside source and not reproduced here.

## 1. The Problem in Plain Words

A symmetric matrix `M` is positive semidefinite (PSD) when `x^T M x >= 0` for every vector `x`. It is positive definite when that inequality is strict for every nonzero `x`. Equivalently, every eigenvalue is at least zero, or above zero for the definite case. The Hermitian case is the same with complex entries and `x*` (the conjugate transpose) in place of `x^T`.

Engineering code usually tests this by computing eigenvalues in floating point and comparing the smallest one with a threshold. Two things go wrong. A matrix that is exactly singular produces a tiny number, not zero, so the threshold decides the answer.
A matrix that is positive definite but nearly singular can fall under the threshold and be rejected. The same question arises for the count of positive eigenvalues: "at most `b` positive" needs an exact count, and rounding can move an eigenvalue across zero.

The inertia of a Hermitian matrix is the triple (positive, negative, zero) of its eigenvalue counts. If the inertia is known exactly, every question above has an exact answer. PSD means the negative count is zero. Positive definite means the negative and zero counts are both zero. "At most `b` positive" means the first count is at most `b`.

## 2. The Certificate

### 2.1 Form (`verified`)

Sylvester's law of inertia says that two Hermitian matrices related by `X = S Y S*`, with `S` invertible, have the same inertia. A certificate is a factorization

```text
P M P* = L D L*
```

where `P` is a permutation matrix, `L` is unit lower triangular (ones on the diagonal, zeros above it), and `D` is block diagonal with `1 x 1` and `2 x 2` Hermitian blocks. All entries are exact rationals, or Gaussian rationals `a + b i` with rational `a` and `b`.
`L` is invertible, so `P M P*` and `D` have the same inertia. A permutation changes no eigenvalue, so `M` and `P M P*` have the same inertia. Hence `M` has the inertia of `D`.

The inertia of `D` is the sum over its blocks. A `1 x 1` block contributes its sign. A `2 x 2` block `[[a, b], [conj(b), c]]` with `b != 0` and real `a`, `c` has determinant `a c - |b|^2`:

| Determinant | Eigenvalue signs | Block inertia |
| --- | --- | --- |
| below zero | one positive, one negative | `(1, 1, 0)` |
| above zero, `a + c > 0` | both positive | `(2, 0, 0)` |
| above zero, `a + c < 0` | both negative | `(0, 2, 0)` |
| zero, `a + c > 0` | one positive, one zero | `(1, 0, 1)` |
| zero, `a + c < 0` | one negative, one zero | `(0, 1, 1)` |

When the determinant is zero and `b != 0`, `a c = |b|^2 > 0`, so `a` and `c` are nonzero with the same sign and `a + c != 0`. The table is complete.
The suite sends one block for each row, real and complex, and compares the checker with the independent method. The producer in the suite never emits the last four rows. Its pivoting rule picks a `2 x 2` block only when both diagonal entries are small next to the off-diagonal one, and that forces a negative determinant. These direct tests are the only ones that reach those rows.

The certificate is a JSON object with keys `M`, `P`, `L`, `D` and optionally `claim`. A real entry is a string `"p/q"`. A complex entry is a pair of such strings. `P[i]` is the row of `M` placed at position `i`. `claim` is a list `[positive, negative, zero]`.

### 2.2 What the Checker Verifies, Item by Item (`verified`)

[`scripts/inertia_cert.py`](../scripts/inertia_cert.py) is standard-library Python. It raises `CertError` on the first failure, using `raise` and not `assert`, so `python3 -O` changes nothing. It checks:

1. The text parses as JSON with no floating-point numbers, no `NaN` or infinity constants, and no duplicate keys.
2. The object has exactly the keys `M`, `P`, `L`, `D`, plus optionally `claim`. The size `n` is between 1 and 64.
3. Every entry is a string of the form `p/q` with a positive denominator, or a pair of them.
4. `M` is Hermitian.
5. `P` is a permutation of `0 .. n-1`.
6. `L` is unit lower triangular.
7. `D` is Hermitian, has no entries more than one place off the diagonal, has a real diagonal, and has no two overlapping `2 x 2` blocks.
8. The identity `P M P* = L D L*` holds at every entry, by exact fraction arithmetic.
9. The inertia is read from the blocks of `D` as in the table above. If `claim` is present, it equals that inertia.

Item 7 includes a guard that is needed for correctness and not only for tidiness. If two `2 x 2` blocks overlap, a tridiagonal `D` can be misread blockwise. The suite uses `M = D = [[1,1,0],[1,1,1],[0,1,1]]`, whose true inertia is `(2, 1, 0)` (eigenvalues `1` and `1 ± sqrt(2)`).
With the overlap guard removed, the checker accepts it and reports `(2, 0, 1)`. Item 5 is the same kind of guard. With a repeated index in `P`, a certificate for a different matrix passes the identity.
The suite uses `M = diag(1, -1)` with `P = [0, 0]`, which an unguarded checker reports as `(1, 0, 1)` against the true `(1, 1, 0)`.
The zero-above-the-diagonal part of item 6 is a third such guard. `L = [[1, 1], [1, 1]]` has a unit diagonal but is singular. With `D = I` it passes the identity for `M = [[2, 2], [2, 2]]`, and an unguarded checker reports `(2, 0, 0)` against the true `(1, 0, 1)`.

### 2.3 What the Checker Does Not Prove

- It certifies the matrix it is given. It says nothing about where `M` came from. Binding that matrix to real bytes or measurements is a separate obligation of the caller. Section 5 shows a caller that recomputes `M` from the weights it holds.
- It sets no limit of its own on the size of numerators and denominators. A certificate with enormous integers costs time, not correctness. Python refuses integer strings longer than 4,300 digits by default, and the checker then rejects the certificate.
- Python's `Fraction`, `json` and the interpreter are trusted.
- A floating-point matrix rounded to rationals certifies the rounded matrix, not the original.
- A formal proof of the checker, for example in Lean, is not part of this work.

## 3. Rank Bounds from Traces

### 3.1 Setting

Let `M = P1 + Q` be an `n x n` Hermitian matrix. `P1` is PSD with rank `r`. `Q` is Hermitian with at most `b` positive eigenvalues.
Write `t = tr Q`, `||M||^2` for the sum of the squared moduli of the entries of `M` (the squared Frobenius norm), and `h_1 >= h_2 >= ... >= h_n` for the eigenvalues of `M`. For `Q`, write `q_1 >= q_2 >= ...`. Pad every list with zeros past index `n`. Padding changes no sum below.

The quantities `tr M`, `tr Q` and `||M||^2` are cheap and exact. The number `b` is read exactly from a certificate for `Q`. The bounds turn these into a lower bound on `r`.

Two facts are used. Both are standard (`source claim`, textbook Weyl inequalities, not reproved here).

- (W1) `lambda_{i+j-1}(X + Y) <= lambda_i(X) + lambda_j(Y)` for Hermitian `X`, `Y`.
- (W2) If `Y` is PSD then `lambda_i(X + Y) >= lambda_i(X)`.

Let `phi(x) = 2x - x^2`. Then `phi(x) <= 1` for all `x`, `phi(x) <= 0` for `x <= 0`, and `sum_i phi(h_i) = 2 tr M - tr(M^2) = 2 tr M - ||M||^2`, since `tr(M^2) = sum |M_ij|^2` for Hermitian `M`.

Step E. `M` has at most `r + b` positive eigenvalues. By (W1) with `i = b + 1` and `j = r + 1`, `h_{r+b+1} <= q_{b+1} + lambda_{r+1}(P1)`. Now `q_{b+1} <= 0` because `Q` has at most `b` positive eigenvalues, and `lambda_{r+1}(P1) = 0` because `P1` is PSD of rank `r`. So `h_i <= 0` for `i > r + b`.

Step Q. For `c >= 0`, `c t <= c (h_1 + ... + h_b)`. First, `q_j <= 0` for `j > b`, so `t <= q_1 + ... + q_b`. Second, `Q = M - P1` with `P1` PSD, so by (W2) `q_j <= h_j`.

### 3.2 The Family (`verified` by proof here and by exact tests)

**Claim.** For every `c >= 0`,

```text
r >= 2 tr M - ||M||^2 + c tr Q - (1 + c/2)^2 b
```

**Proof.** The right side is `sum_i phi(h_i) + c t - (1 + c/2)^2 b`. By Step Q, `sum_i phi(h_i) + c t <= sum_i phi(h_i) + c (h_1 + ... + h_b)`. Split the indices into three ranges.

- For `j <= b`: `phi(h_j) + c h_j = (2 + c) h_j - h_j^2 <= (1 + c/2)^2`, the maximum of that quadratic at `h_j = 1 + c/2`.
- For `b < i <= b + r`: `phi(h_i) <= 1`. There are `r` such terms, so they add at most `r`.
- For `i > b + r`: `h_i <= 0` by Step E, so `phi(h_i) <= 0`.

The total is at most `(1 + c/2)^2 b + r`. Moving `(1 + c/2)^2 b` to the left gives the claim. ∎

### 3.3 Bound (A) and Bound (B)

**(A), `c = 0`.** `r >= 2 tr M - ||M||^2 - b`. Proved here by the argument above (`verified` by proof).

**(B), `c = 2`.** `r >= 2 tr P1 + 4 tr Q - 4b - ||M||^2`. Check: at `c = 2` the family gives `2 tr M - ||M||^2 + 2 t - 4b`, and `2 tr M + 2 t = 2 tr P1 + 4 t`. The statement of (B) was quoted to us from a 2026 number theory preprint that this repository has not read.
The attribution is a `source claim`. The proof given here is `verified` (by proof and by the exact tests in section 3.6). We do not name that preprint's own result as ours.

**The family and its best member.** Whether the family is new is not known. It was proved here and not searched for in the literature, so no novelty is claimed.

When `t >= b > 0`, the best member is found by setting the derivative of `c t - b (1 + c/2)^2` to zero. That gives `c = 2 (t - b) / b >= 0` and `1 + c/2 = t / b`, with value `t^2 / b - 2t`. The bound becomes

```text
r >= 2 tr P1 + (tr Q)^2 / b - ||M||^2
```

When `t < b` or `b = 0`, the constraint `c >= 0` makes `c = 0` the best member, which is (A). So the best member is always at least `max(A, B)`.

### 3.4 Comparison (`verified` by algebra and by the suite)

Write `R_A`, `R_B` and `R_G` for the right sides of (A), (B) and the best member.

```text
R_B - R_A = 2 tr Q - 3b          so (B) is the stronger of the two exactly when tr Q > 1.5 b
R_G - R_B = (tr Q - 2b)^2 / b    when tr Q >= b > 0
R_G - R_A = (tr Q - b)^2 / b     when tr Q >= b > 0
```

Each line follows by expanding. `scripts/verify_inertia.py` checks all three identities on exact rational inputs.

### 3.5 Where Each Bound Is Tight (`verified`)

Equality in the family at `c` needs `h_j = 1 + c/2` for `j <= b`, `h_i = 1` for the next `r` eigenvalues, and zero after that. Examples with `n = 2`, `e_k` the standard basis vectors:

| Bound | Example | Rank `P1` | Right side |
| --- | --- | --- | --- |
| (A) | `P1 = e1 e1*`, `Q = 0`, `b = 0` | 1 | 1 |
| (B) | `P1 = e2 e2*`, `Q = 2 e1 e1*`, `b = 1` | 1 | 1 |
| member `c = 4` and best member | `P1 = e2 e2*`, `Q = 3 e1 e1*`, `b = 1` | 1 | 1 (and (B) gives 0) |

The third row shows the best member is strictly better than (B) on some inputs.

### 3.6 Exact Tests (`verified`)

`python3 -B -W error -m unittest -v scripts/verify_inertia.py` runs 2,000 random rational instances, real and complex, size 1 to 6. Each instance is `M = P1 + Q` with `P1` a sum of positive rank-one terms and `Q` a sum of signed rank-one terms.
The value `b` is the exact positive count of `Q`, read from a certificate that the checker accepted. The rank of `P1` is exact, by Fraction elimination on a real embedding. Each instance is compared with (A), (B), the family at seven values of `c`, and the best member.
No instance violated any of them. A deliberately wrong right side (for example, (A) with `+1`) fails the suite, as the mutation run in the pull request shows.

## 4. First Use: Two-Bar Truss Over a Length Box

### 4.1 Model (`source claim` for the model)

Two pins sit at `(-1, 0)` and `(1, 0)`. A joint at `p` is held by two linear bars, one to each pin, with natural lengths `L1` and `L2` and unit stiffness. The elastic energy is `sum_i (1 / (2 L_i)) (|p - pin_i| - L_i)^2`. The model and its equilibria come from pull request 5 of `aska-physical/fibral-rigidity`, at commit `4753275`.
We did not reproduce that repository's own checks. We took the model as stated and recomputed every matrix below exactly.

The lengths vary over the box `L1` in `[0.7, 1.3]`, `L2` in `[0.9, 1.5]`. At an equilibrium the stiffness matrix is the Hessian of the energy. It is positive definite when the equilibrium is stable.

### 4.2 Exact Matrices (`verified`)

On the pin line the axial force is linear on each of three `x` regions, so equilibria there are rational. Off the line, both bars must have zero extension, so `x = (L1^2 - L2^2) / 4` is rational and `y^2` is rational, but `y` often is not.
The Hessian there is `[[A, B y], [B y, C y^2]]` with rational `A`, `B`, `C`. The congruence `diag(1, 1/y)` turns it into the rational matrix `[[A, B], [B, C]]` with the same inertia, by Sylvester's law. That rational matrix is the one certified.

| Lengths `(L1, L2)` | Role | Equilibrium | Matrix certified | Exact inertia |
| --- | --- | --- | --- | --- |
| `(7/10, 9/10)` | corner | on the line, `x = -1/8` | `diag(160/63, 32/63)` | `(2, 0, 0)` |
| `(7/10, 3/2)` | corner | `x = -11/25`, `y = 21/50` | `[[6688/4375, 4432/3675], [4432/3675, 29744/9261]]` | `(2, 0, 0)` |
| `(13/10, 9/10)` | corner | `x = 11/50`, `y^2 = 126/625` | `[[1345388/889785, -274760/533871], [-274760/533871, 2926000/1601613]]` | `(2, 0, 0)` |
| `(13/10, 3/2)` | corner | `x = -7/50`, `y^2 = 594/625` | `[[2972984/4119375, 26528/494325], [26528/494325, 44576/59319]]` | `(2, 0, 0)` |
| `(9/10, 11/10)` | interior | on the line, `x = -1/10` | `diag(200/99, 0)` | `(1, 0, 1)`, singular |

All four corner matrices are positive definite. The interior matrix is exactly singular, with a zero in the transverse direction. A floating-point run can report only a tiny number for that zero. The suite also checks that the embedded matrices equal a recomputation from the model formulas.

A near-flat case: lengths `(9/10, 11/10 + 10^-9)` give an exactly positive definite matrix, `(2, 0, 0)`. The smaller eigenvalue of the raw Hessian is below `10^-7`, from the bound `2 det / trace`. A test with an absolute eigenvalue threshold of `10^-3` would reject it. The exact check accepts it.

### 4.3 When Corner Tests Cover a Box (`verified` by proof)

If `M(t)` depends affinely on the varied parameters `t` over a box, every point of the box is a convex combination of the corners, with weights `w_c >= 0` summing to one, and `M(t) = sum_c w_c M(c)`. A nonnegative combination of PSD matrices is PSD.
If every corner is positive definite, at least one weight is positive, so `M(t)` is positive definite as well. Testing the corners then covers the box.

Here the matrix does not depend affinely on the lengths. The proof shows why that matters: four positive definite corners with a singular interior point is impossible for an affine family, since a combination of positive definite matrices with positive weights is positive definite.
The suite checks this arithmetic. It does not claim that no positive definite equilibrium exists at `(9/10, 11/10)`. That statement rests on an argument about equilibria that we re-derived exactly for this model but did not formalize.

## 5. Second Use: A Spectral Bound on a Low-Rank Weight Adapter

### 5.1 The Equivalence (`verified` by proof, and by the suite)

A low-rank adapter is a product `B A` with `B` of size `d_out x r` and `A` of size `r x d_in`. Its spectral norm `sigma_max(B A)` is the largest singular value, and it bounds how much the adapter can stretch any input. Let `G_B = B* B` and `G_A = A A*`, both `r x r`. For `beta >= 0` and `s = beta^2`, define

```text
Q(s) = s G_B - G_B G_A G_B
```

**Claim.** `sigma_max(B A) <= beta` if and only if `Q(s)` is PSD. This holds also when `G_B` is singular.

**Proof.** Let `K = B G_A B* = (B A)(B A)*`. Its largest eigenvalue is `sigma_max(B A)^2`, so `sigma_max(B A) <= beta` is equivalent to `s I - K` being PSD. Also `Q(s) = B* (s I - K) B`.

- If `s I - K` is PSD, so is `B* (s I - K) B`, since `x* B* (s I - K) B x = (B x)* (s I - K) (B x) >= 0`.
- Conversely, suppose `Q(s)` is PSD. Split any vector `x = x1 + x2` with `x1` in the column space of `B` and `x2` orthogonal to it. Then `B* x2 = 0`, so `K x2 = 0`. The cross terms `x1* (s I - K) x2 = s x1* x2 - x1* K x2` vanish, because `x1* x2 = 0` and `K x2 = 0`.
So `x* (s I - K) x = x1* (s I - K) x1 + s |x2|^2`. The second term is nonnegative because `s >= 0`. Write `x1 = B y`. Then `x1* (s I - K) x1 = y* Q(s) y >= 0`. So `s I - K` is PSD.

The argument never inverts `G_B`. If `B` has rank `k < r`, then `Q(s)` has at least `r - k` zero eigenvalues (every `y` in the null space of `B` gives `Q y = 0`), so it is never positive definite and PSD is the right test. If `B = 0`, then `Q = 0`, which is PSD for every `s >= 0`. ∎

### 5.2 A Synthetic Adapter (`verified`)

The suite builds adapters with `8 x 4` and `4 x 8` factors whose entries are binary fractions `k/16`, all exact.
For three adapters (full rank, `B` of rank 2, `B` of rank 1), it bisects on `s` fourteen times and at every probe compares two exact routes: the PSD test on `Q(s)` through a checked certificate, and the independent exact inertia of `s I - K` by characteristic polynomial and Descartes' rule of signs.
The two routes agree at every probe. For the adapter used below, the exact test brackets `sigma_max^2` in `[1.04654, 1.04665]`, and the certificate at the upper end is 1,174 bytes with inertia `(4, 0, 0)`.

### 5.3 The Forgery Case (`verified`)

A loader that recomputes `Q(s)` from the weights it holds, requires the certificate's `M` to equal it, runs the checker, and requires a zero negative count, rejects each of the following. The loader in the suite is a test function. It is not the layer-3 loader. Here `B` is scaled by 8, which multiplies `sigma_max^2` by 64 and is exact in binary fractions.

| Attempt | Result |
| --- | --- |
| Replay the old certificate for the forged weights | rejected, the matrix in it is not `Q(s)` for these weights |
| A fresh certificate for the forged weights at the old bound | rejected, inertia `(0, 4, 0)` |
| The same certificate with `claim` changed to `[4, 0, 0]` | rejected by the checker, claim differs from the computed inertia |
| Old `L` and `D` placed under the new `M` | rejected, identity fails |
| A fresh certificate at the new bound `64 s` | accepted |

The first row is the reason the recomputation step exists. The checker alone accepts the old certificate, because it is a valid certificate for the old matrix. A loader that skipped the recomputation would pass a certificate for a different adapter.

### 5.4 Measured Checking Times (`verified`)

`python3 -B scripts/verify_inertia.py --report` builds adapters with `64 x r` and `r x 64` factors, with a bound `s` taken from a floating-point estimate of `sigma_max^2` plus a margin of `1.000001`. The estimate is untrusted. The checker decides. One run on one core of one machine, Python 3.14.6:

| Rank `r` | Build `Q` (s) | Produce (s) | Check (s) | Certificate (bytes) | Inertia |
| --- | --- | --- | --- | --- | --- |
| 4 | 0.002 | 0.000 | 0.001 | 2,077 | `(4, 0, 0)` |
| 8 | 0.007 | 0.002 | 0.005 | 10,056 | `(8, 0, 0)` |
| 16 | 0.032 | 0.024 | 0.047 | 56,943 | `(16, 0, 0)` |
| 32 | 0.150 | 0.385 | 0.550 | 353,164 | `(32, 0, 0)` |

Times vary between runs and machines. The growth with `r` is the finding.

### 5.5 Link to the Layer-3 Loader (`hypothesis`)

The layer-3 repository `siliconcordat/warp` has an open issue about certificate numbers that are not recomputed from the adapter. The forgery case above is a small instance of that gap. The recomputation step in section 5.3 is a proposed shape for closing it.

The hypothesis fails if a loader that recomputes `Q(s)` from the weights it serves still accepts a certificate made for other weights, or if the recomputation and check exceed the loader's time budget (section 6). This paper does not change or claim anything about the loader.

## 6. Limits and Falsification Conditions

**Limits.**

- Cost grows with rank in pure fractions. From rank 16 to rank 32 in the table, checking time grows about twelve-fold and the certificate about six-fold, because the numerators and denominators grow. The checker also refuses sizes above 64.
- The checker is one implementation in one language. A second, independent certificate checker that shares no code with it does not exist yet. The independent method in the suite computes inertia of a matrix by a different route, which makes it a cross-check on inputs. It does not check certificates.
- A matrix rounded from floating point certifies the rounded matrix. The step from real weights to exact rationals is the caller's.
- Everything here is verified on synthetic or model-derived matrices. No real adapter checkpoint was used.
- Whether the rank-bound family appears in the literature is unknown.

**What would count against the claims.**

- The central soundness claim fails if any certificate the checker accepts has an `M` whose inertia, computed by a different exact method, differs from the checker's output. The property test and the guard-removal controls in `scripts/verify_inertia.py` look for exactly this.
- A rank bound fails if any exact instance has `r` below the right side. One such instance would also show an error in section 3.
- The usefulness claim for adapters fails if exact checking at the ranks a deployment uses cannot finish inside the loader's time and storage budget. The `--report` table is the measurement to repeat on the target machine. A budget the loader owner sets and a measured time above it count as a negative result.
- The truss claim about corners fails if an affine family has positive definite corners and an interior point that is not PSD. The proof in section 4.3 says that cannot happen.

## 7. Claim Status

| Claim | Status |
| --- | --- |
| A certificate accepted by the checker gives the inertia of the `M` inside it | `verified` (proof from Sylvester's law, property test, controls) |
| Each guard in the suite's list, removed alone, makes its control accepted | `verified` (guard-removal mutants in the suite) |
| (A), the family, and its best member | `verified` (proof here, exact tests), not searched for in the literature |
| (B) as an attributed result | `source claim` (quoted from a 2026 preprint not read here) |
| (B) as a statement | `verified` (proof here, exact tests) |
| The truss matrices and inertias in section 4.2 | `verified` |
| The two-bar model and its equilibria | `source claim` |
| The adapter equivalence, including singular `G_B` | `verified` |
| Forgery rejected by a recomputing loader | `verified` for the test loader, `hypothesis` for layer 3 |
| Check times at ranks 4 to 32 | `verified` for the machine and run shown |

## 8. Reproduce

```bash
python3 -B -W error -m unittest -v scripts/verify_inertia.py
python3 -O -B -W error -m unittest -v scripts/verify_inertia.py
python3 -B scripts/verify_inertia.py --report
```

The suite uses 1,000 random matrices for the property test and 2,000 instances for the bounds, and runs in under 20 seconds on one core.
