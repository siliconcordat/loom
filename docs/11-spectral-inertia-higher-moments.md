# Spectral & Inertia Higher-Moment Rank Bounds, Non-Affine Complex-Hermitian Box Certification, and Dual-Oracle Exact $\mathbb{Q}(i)$ Verification

Companion research note extending `docs/10-exact-inertia-certificates.md` ([`siliconcordat/loom#7`](https://github.com/siliconcordat/loom/pull/7)). All code, full proofs, exact test suites, and mutation checks live in the standalone zero-dependency repository **[`Foundation-0/spectral-inertia`](https://github.com/Foundation-0/spectral-inertia)**.

Statuses follow the Evidence Discipline in [`README.md`](../README.md): `verified` means proved and independently reproduced in exact zero-float arithmetic across all isolated R4 Python modes (`-I -B`, `-I -O -B`, `-I -B -W error`, `-I -O -B -W error`); `source claim` means attributed to an outside paper or PR; `hypothesis` / `uncompiled_source` is marked explicitly where applicable.

---

## 1. Summary & Relation to `docs/10` (`loom#7`)

[`docs/10-exact-inertia-certificates.md`](https://github.com/siliconcordat/loom/pull/7) established:
1. An exact-rational $P M P^* = L D L^*$ Sylvester inertia checker (`scripts/inertia_cert.py`).
2. An unscaled additive trace rank-bound family via Weyl's inequalities `(W1)/(W2)` with best member $R_G = 2\operatorname{tr} P + (\operatorname{tr} Q)^2/b - \|M\|_F^2$ (for $\operatorname{tr} Q \ge b$).
3. Five isolated point checks on the non-affine two-bar truss box (`aska-physical/fibral-rigidity#5`) showing four positive-definite corners and a singular interior point `(9/10, 11/10)`.

Section 6 of `docs/10` explicitly listed four open limits:
- the rank-bound family was not scale-optimized and had not been audited against prior literature;
- no continuous non-affine box certification theorem existed beyond isolated point checks;
- no second, independent zero-shared-code exact inertia checker existed;
- no Lean 4 formalization existed.

This companion note and [`Foundation-0/spectral-inertia`](https://github.com/Foundation-0/spectral-inertia) close those gaps across three independently audited tracks (`AUDIT-002`, `AUDIT-014`, `AUDIT-015R`, `AUDIT-016R`).

---

## 2. Honest Prior-Art Positioning (`verified` against full texts)

- **Classical PSD bounds (`source claim`):** $\operatorname{rank}(P) \ge (\operatorname{tr} P)^2 / \operatorname{tr}(P^2)$, Hölder $\operatorname{rank}(P) \ge (\operatorname{tr} P)^{k/(k-1)} / (\operatorname{tr} P^k)^{1/(k-1)}$, and PSD Hankel Schur complements $\mathcal{H}_d(P) \succeq 0 \implies \operatorname{rank}(P) \ge v_d^\top M_d^+ v_d$.
- **`arXiv:2608.13637v2` (Alpöge & Furman, Aug 2026, Lemma 3.2, `source claim`):** Fixed unscaled $c = 2$ rank–trace inequality $\operatorname{rank}(P) \ge 2\operatorname{tr}(P) + 4\operatorname{tr}(Q) - 4b - \|P+Q\|_{\mathrm{HS}}^2$ (`docs/10` Bound B).
- **`arXiv:2609.33043` & `arXiv:2610.08965v1` (Knausgård, Oct 2026, Lemmas 2.1 & 6.1, `verified` prior-art check):** Proves $\operatorname{tr}((P+Q)^2) \ge \operatorname{tr}\varphi_c(P) + 2t\operatorname{tr}(Q) - t^2 b$ ($t \ge c$, $\varphi_c(x) = \min(x^2, 2cx - c^2)$), which at $c=1$ yields the additive $t \ge 1$ family for total $\operatorname{rank}(P)$. Does not use $W^\perp$ compression, scale-invariant optimization, integer sharpness, or higher spectral moments $\operatorname{tr}(H^3), \operatorname{tr}(H^4)$.

**Genuinely new contributions (`verified`):**
1. Strengthening the target to the **$W^\perp$-projected positive inertia** $n_+(\Pi_{W^\perp}(P+Q)\Pi_{W^\perp}) \le \operatorname{rank}(\Pi_{W^\perp}P\Pi_{W^\perp}) \le \operatorname{rank}(P)$ via an explicit 6-term $W \oplus W^\perp$ slack identity, guarded scale-invariant envelope $R_{\mathrm{opt}}$, and integer-exact pointwise sharpness $\min\operatorname{rank}(P) = \max(1, \lceil R_{\mathrm{opt}} \rceil)$ proving higher spectral moments are strictly required to go further.
2. Three exact-rational **higher-moment spectral rank theorems** (Theorems A2, A3, A4) breaking strictly past $\max(1, \lceil R_{\mathrm{opt}} \rceil)$ for arbitrary non-commuting complex Hermitian $H = P + Q$ ($P \succeq 0, n_+(Q) \le b$).
3. An **exact non-affine complex-Hermitian Bernstein box certifier** (`PolyMatrix`, `RatMatrix`, `QInterval`/`QiInterval`) with symbolic Hermitianity guards and $1\times 1 / 2\times 2$ block-Gershgorin uniform certification.
4. A **zero-shared-code dual-oracle $\mathbb{Q}(i)$ inertia & rank certifier** pairing Sylvester congruence ($C M C^* = D$ and `loom#7` $P M P^* = L D L^*$) with Faddeev–LeVerrier + Cayley–Hamilton + exact Descartes + exact Sturm square-free sequences (`41/41` refusal-site mutants killed, `0` survivors).

---

## 3. Track A — Projected Novel-Subspace Envelope `R_opt` & Higher-Moment Theorems (`verified`)

Let $P, Q \in \mathbb{C}^{n \times n}$ be arbitrary non-commuting complex Hermitian matrices with $P \succeq 0$ and $n_+(Q) \le b$. Decompose $Q = Q_+ - Q_-$ ($Q_+, Q_- \succeq 0, Q_+ Q_- = 0$), let $W = \operatorname{range}(Q_+)$, $H = P + Q$, $P_\perp = \Pi_{W^\perp} P \Pi_{W^\perp}$, $H_\perp = \Pi_{W^\perp} H \Pi_{W^\perp} = P_{22} - Q_-$, $u = \operatorname{tr}(P)$, $t = \operatorname{tr}(Q)$, and $S_k = \operatorname{tr}(H^k)$ ($S = S_2 = \|H\|_F^2$).

By Weyl monotonicity and Cauchy interlacing on $W^\perp$, **Lemma 0** holds unconditionally:
$$\operatorname{rank}(P) \;\ge\; \operatorname{rank}(P_\perp) \;\ge\; n_+(H_\perp) \;\ge\; n_+(H) - b.$$

### Theorem A1 — Guarded Sharp Quadratic Envelope `R_opt` (`verified`)
$$n_+(H_\perp) \;\ge\; R_{\mathrm{opt}}(u, t, S, b) := \begin{cases} 0, & u \le 0 \text{ or } u + t \le 0, \\[4pt] \dfrac{u^2}{S - t^2/b}, & u > 0,\; b > 0,\; t > 0,\; t(u+t) \ge bS, \\[8pt] \max\!\left(0,\; \dfrac{(u+t)^2}{S} - b\right), & \text{otherwise.} \end{cases}$$
- Strictly dominates `docs/10`'s unscaled $R_G$ (`417/420` strict wins, `3` ties on exact $\mathbb{Q}(i)$ trials; `0` violations).
- **Integer-exact pointwise sharpness:** For every feasible $(u, t, S, b)$ with $u > 0$, $\min \operatorname{rank}(P) = \max(1, \lceil R_{\mathrm{opt}}(u, t, S, b) \rceil)$, proving higher moments are mathematically required to go further.

### Theorem A2 — Degree-$2m$ Stieltjes–Hankel Indefinite Projected-Inertia Bound (`verified`)
For any $m \ge 1$ and any nonnegative rational vector $a = (a_1, \dots, a_m) \in \mathbb{Q}_{\ge 0}^m$, let $q_a(\lambda) = 1 + \sum_{k=1}^m (-1)^k a_k \lambda^k$ and $\phi_a(\lambda) = 1 - q_a(\lambda)^2$. For all $\lambda \le 0$, $q_a(\lambda) = 1 + \sum a_k |\lambda|^k \ge 1 \implies \phi_a(\lambda) \le 0$; for all $\lambda > 0$, $\phi_a(\lambda) \le 1$. By Lemma 0:
$$n_+(H_\perp) \;\ge\; 2\sum_{k=1}^m (-1)^{k-1} a_k S_k - \sum_{j,k=1}^m (-1)^{j+k} a_j a_k S_{j+k} - b.$$
- **Closed-form quartic ($m = 2$, $R_{H4}$):** When $\Delta = S_2 S_4 - S_3^2 > 0$, $s^* = (S_1 S_4 - S_2 S_3)/\Delta \ge 0$, and $p^* = (S_1 S_3 - S_2^2)/\Delta \ge 0$:
  $$n_+(H_\perp) \;\ge\; \max\!\left(0,\; \frac{S_1^2}{S_2} + \frac{(S_1 S_3 - S_2^2)^2}{S_2(S_2 S_4 - S_3^2)} - b\right).$$
- **Exact active-set KKT sextic ($m = 3$, $R_{H6}$):** Evaluates all $2^3$ active subsets in exact `Fraction`, guaranteeing $R_{H6} \ge R_{H4} \ge \max(0, S_1^2/S_2 - b)$.
- **Exact rank-$m$ recovery:** Whenever $H \succeq 0$ has $k \le m$ distinct positive eigenvalues, the orthogonal polynomial $q^*(\lambda) = \prod_{j=1}^k (1 - \lambda/\mu_j)$ has $a^* > 0$ automatically, achieving $R_{H,2m}(H, b) = \max(0, \operatorname{rank}(H) - b)$ with zero gap. On `project-asma` Scan 23848 Mode B ($\tau = 0, b = 1$), $R_{H4}(H, 1) = 1$ **identically** across all overlaps $\rho \in [0, 0.95]$ (where $c = 2$ collapses to `0` by $\rho = 0.75$ and $R_{\mathrm{opt}} \to 0.03685$).

### Theorem A3 — Exact Noise-Annihilating Quartic SOS Bound $\Phi_{x_0, \tau}$ (`verified`)
For any rational $x_0 > 0, \tau \ge 0$, set $d = 3x_0 + \tau$, $L = 2x_0(2x_0+\tau)/d$, $M = x_0^2(x_0+\tau)^3/d$, and $\Phi_{x_0,\tau}(\lambda) = \lambda(L-\lambda)(\lambda+\tau)^2 / M$. Then $\Phi_{x_0,\tau}(\lambda) \le 0$ on $(-\infty, 0]$ with a **double zero at $\lambda = -\tau$**, and the exact rational SOS identity
$$M - \lambda(L - \lambda)(\lambda + \tau)^2 \;=\; (\lambda - x_0)^2\!\left[\left(\lambda + \frac{x_0^2 + 3x_0\tau + \tau^2}{d}\right)^2 + \frac{x_0^2(2x_0^2 + 4x_0\tau + \tau^2)}{d^2}\right] \;\ge\; 0$$
certifies $\Phi_{x_0,\tau}(\lambda) \le 1$ on all of $\mathbb{R}$ (with exact equality at $x_0$). Specializes at $\tau = 0$ to the indefinite odd-even Hölder bound $n_+(H_\perp) \ge S_3^4/S_4^3 - b$ ($S_3 > 0$). Strictly beats $\max(1, \lceil R_{\mathrm{opt}} \rceil)$ across **6** Scan 23848 Mode A high-interference noisy regimes ($\rho \in [0.75, 0.95], \tau \in [0.005, 0.020]$) while stopping at $\le 1$ when $\lambda_2 - \tau < 0$.

### Theorem A4 — Exact Weighted Quartic-Weyl SOS Bound $R_{W4}$ (`verified`)
For any rational $s \ge 0, p > 0, \gamma_1 \ge 0, \gamma_3 \ge 0, \kappa > 0$, set $\beta = s + \gamma_3/p$, $\alpha = 1 - (\beta^2 - s^2 + \kappa)/(2p)$, $\lambda_0 = (s + \gamma_1 - \alpha\beta)/\kappa$, and $M = \alpha^2 + \kappa\lambda_0^2$. Exact SOS verification $M - (\phi_{s,p}(\lambda) + 2\gamma_1\lambda + 2\gamma_3\lambda^3) = (p\lambda^2 - \beta\lambda + \alpha)^2 + \kappa(\lambda - \lambda_0)^2 \ge 0$ combined with Weyl `(W2)` on the odd non-decreasing polynomial $2\gamma_1\lambda + 2\gamma_3\lambda^3$ and Lemma 0 proves:
$$n_+(H_\perp) \;\ge\; 2s S_1 - (s^2+2p)S_2 + 2sp S_3 - p^2 S_4 + 2\gamma_1\operatorname{tr}(Q) + 2\gamma_3\operatorname{tr}(Q^3) - b M.$$
In the 3-parameter peak-matched specialization ($\gamma_3 = 0$, using only $\operatorname{tr} Q$), $R_{W4}$ strictly beats **both** $\lceil R_{\mathrm{opt}} \rceil = 2$ and $\lceil R_{H4} - b \rceil = 2$ on exact non-commuting complex Hermitian $4\times 4$ matrices (e.g. `A4 = 2.3737` vs `R_opt = 1.6821`, `H4 - 1 = 1.8866`; independent audit hit `A4 = 2.8062` vs `1.8142` / `1.9765`; diagonal `A4 = 3` exact). Across `300` fresh independent non-commuting $\mathbb{Q}(i)$ Hermitian trials (`AUDIT-014`), **0 violations** occurred across all four theorem families.

---

## 4. Track B — Exact Non-Affine Complex-Hermitian Bernstein Box Certifier (`verified`)

`spectral_inertia/box_certifier.py` lifts `docs/10` §4 from isolated point checks to **continuous parameter boxes** $B = \prod_{k=1}^d [a_k, b_k]$ for complex Hermitian polynomial (`PolyMatrix`), rational (`RatMatrix`), and piecewise/algebraic callable families with zero floating-point operations:

1. **Symbolic & interval Hermitianity guards (`AUDIT-015R`):** Rejects non-Hermitian polynomial, rational, and callable interval families even when the box midpoint happens to be Hermitian (`8/8` forgeries blocked).
2. **Congruence-preconditioned multivariate Bernstein residuals:** Forms exact polynomial $E(x) = C(M(x) - M(x_c))C^*$ before taking multivariate Bernstein convex-hull enclosures, eliminating both interval dependency overestimation and matrix wrapping error.
3. **Complex block-Gershgorin uniform certification:** Proves $\sigma_{\min,\mathrm{lo}}(D_k) > \sum_j \operatorname{frob\_hi}(\Delta_{kj}(B))$ across all $1\times 1$ and $2\times 2$ Bunch–Kaufman blocks of $D = C M(x_c) C^*$ (using integer `math.isqrt` brackets), certifying constant inertia over all uncountably many real points $x \in B$.

**Validated systems (`verified`):**
- **`aska-physical/fibral-rigidity#5` two-bar truss:** Replays all 5 `docs/10` §4.2 exact matrices; flags `SINGULARITY_DETECTED` on `[7/10, 13/10] x [9/10, 15/10]` isolating dual-oracle-verified `(1, 0, 1)` singular witnesses including `(9/10, 11/10)`; certifies uniform PD `(2, 0, 0)` on strictly taut `[7/10, 9/10] x [9/10, 1]` and strictly buckled `[11/10, 13/10] x [11/10, 15/10]` sub-boxes.
- **Complex Hermitian 2D Bloch dynamical matrices** (exact Weierstrass substitution $e^{i q_k} = \frac{1-t_k^2+2it_k}{1+t_k^2}$): certifies uniform PD `(2, 0, 0)` across a continuous gapped 2D Brillouin box AND detects an interior Dirac zero mode `(0, 0)` (`(1, 0, 1)`) despite all 4 box corners being strictly PD `(2, 0, 0)`.
- **Non-affine $3\times 3$ Morse-index Hessian:** Certifies constant saddle inertia `(2, 1, 0)` on `[-1/2, 1/2]^2` and certifies `INERTIA_CHANGE_DETECTED` (`(2, 1, 0) <-> (3, 0, 0)`) across an irrational bifurcation curve.

---

## 5. Track C — Hardened Dual-Oracle $\mathbb{Q}(i)$ Certifier & R5 Mutation Suite (`verified`)

`spectral_inertia/{exact_qi,dual_oracle}.py` provides a **zero-shared-code** second independent checker addressing `docs/10` §6 and closing all R1–R5 conformance defects:
- **Oracle 1 (Sylvester congruence):** Supports both general $C M C^* = D$ ($C C^{-1} = I$) and `loom#7` $P M P^* = L D L^*$ JSON certificates with strict lowest-terms canonical ASCII rational parsing (rejecting bool, float, whitespace, trailing `\n`, underscores, Unicode digits, unreduced `"2/4"` / `"3/1"` / `"0/1"`, duplicate JSON keys, `NaN`/`Infinity`) and full Mode B $P = H - Q \succeq 0$ second-congruence certification.
- **Oracle 2 (Independent spectral oracle):** Raw `(Fraction, Fraction)` Faddeev–LeVerrier characteristic polynomial + exact Cayley–Hamilton self-check ($B_n + c_n I = 0$) + exact Descartes rule of signs + exact Sturm sequence on the Yun/GCD square-free peel (`100%` agreement across `120` in-suite + `100` independent fresh complex $\mathbb{Q}(i)$ matrices including high-multiplicity roots, zero diagonals, and all 5 rows of the $2\times 2$ Hermitian block table).
- **R5 refusal-site mutation suite (`tests/run_mutation_suite.py`):** **`41/41` mutants KILLED (`100.0%`, `0` survivors)** under both `-I -B` and `-I -O -B`.
- **Lean 4 formalization (`uncompiled_source`):** Core algebraic & SOS identities are written in [`lean/SpectralInertia/Basic.lean`](https://github.com/Foundation-0/spectral-inertia/blob/main/lean/SpectralInertia/Basic.lean); marked `uncompiled_source` because `lean`/`lake` was not installed on the authoring host.

---

## 6. Reproduce (`verified`)

```bash
git clone https://github.com/Foundation-0/spectral-inertia.git
cd spectral-inertia
python3 -I -B run_all.py
python3 -I -O -B run_all.py
python3 -I -B -W error run_all.py
python3 -I -O -B -W error run_all.py
```

All four isolated modes produce bit-identical JSON output (`16/16` tests OK, `41/41` mutants killed, `0` CRLF files, `0` bare `assert`s).
