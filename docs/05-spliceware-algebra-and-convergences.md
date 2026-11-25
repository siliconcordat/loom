# Spliceware Algebra and Deep Cross-Layer Convergences

This paper pulls three deep cross-layer threads across Layers 5 through 1 (`mde`, `exo`, `warp`, `weft`, `loom`) to their mathematical limits. Every claim separates what holds by proof or exact simulation from where each mechanism breaks.

All derivations, simulations, and numerical tables below are verified reproducibly by [`scripts/verify_convergences.py`](../scripts/verify_convergences.py) using standard-library Python with zero external packages.

## 1. The Unified Splice Algebra (L5 to L1) and Vertical Zone Compilation

All five layers of the Siliconcordat stack instantiate one shared algebraic structure: a **Verified Splice System** `S = (B, D, (+), V, I, rho)`:

- **Immutable base state `S0` in `B`:** Addressed by cryptographic digest `h(S0)` (Git `base_tree` at L5, signed memory root at L4, btrfs snapshot and `W0` digest at L3, 4-layer checkpoint fingerprint at L2, write-protected `W0` memory bank at L1).
- **Content-addressed bounded delta `Delta` in `D`:** Bound strictly to `h(S0)` via digest `h(Delta) = H(Delta || h(S0))`.
- **Application `S0 (+) Delta` with `O(1)` rollback `rho`:** `S0` never mutates in place, so `rho(S0 (+) Delta) = S0` with a 0-byte diff.
- **External Anti-Goodhart verifier `V(S0, Delta) in {0, 1}`:** Owned outside `Delta`'s trust boundary (`docs/02-unified-verification-primitive.md`).
- **Fail-closed composition and interference metric `I(Delta_1, Delta_2; S0)`:** Two individually verified deltas compose only when `I(Delta_1, Delta_2; S0) <= tau` AND post-composition verification passes `V(S0, Delta_1 * Delta_2) = 1`.

### 1.1 Partial Commutative Monoid Condition (Where Composition Works and Where It Breaks)

On general overlapping domains, splice composition is neither commutative nor closed under `V`. Two individually valid code edits in separate files can conflict semantically at link time, and two individually valid weight adapters can drift nonlinearly across transformer layers.

**Theorem 1 (Zone-Isolated Partial Commutative Monoid, `verified`):** Let `Z = {z_1, ..., z_k}` partition the workspace into deterministic syntax zones. Suppose two verified deltas `Delta_a` (supported on `z_a`) and `Delta_b` (supported on `z_b`, `z_a != z_b`) satisfy:

1. **Strict zone isolation:** Each delta acts as the exact identity outside its zone (untouched byte spans at L5, scale `g_a(z_b) = 0.0` at L4/L3/L2, disjoint hardware capability tag at L1).
2. **No shared mutable cross-zone effect:** Neither delta mutates shared global state, contested policy heads, or uncheckpointed recurrent state.

Then composition over zone-disjoint deltas forms a commutative partial monoid with exact zero interference `I(Delta_a, Delta_b; S0) = 0` and order-independent application `Delta_a * Delta_b = Delta_b * Delta_a`. Inside the same zone (`z_a = z_b`), commutativity fails and full post-composition verification `V(S0, Delta_a * Delta_b) = 1` remains mandatory.

### 1.2 Vertical Zone Compilation From One Typed Manifest

Can one typed Zone Manifest `M = (Z, A, Pi, Phi)` anchored at Plane 1 and parsed at L5 mechanically generate all five layers with zero cross-layer drift?

**Sufficient conditions (`verified` in `compile_vertical_zone_manifest`):**

1. Every cell in the precedence matrix `Pi(z, a)` takes values strictly in `{0, 1, CONTESTED}`. Any `CONTESTED` entry aborts compilation immediately (Hard Veto 2).
2. All five layers derive deterministically from the single root digest `H(M)`:
   - **L5 (`mde`):** CST zone predicates and protected oracle path rules.
   - **L4 (`exo`):** Exact deterministic zone-to-scale map `g(z)` in `{0.0, 1.0}^|A|`.
   - **L3 (`warp-modeld`):** Only the reachable active adapter bitmasks require joint canary suites. For our 5 zones (`prose`, `formal_proof`, `ui_module`, `condensed_json`, `code`) and 4 adapters, theoretical combinations drop from `2^4 - 1 = 15` down to `4` reachable masks (`0b0010`, `0b0011`, `0b0110`, `0b1010`).
   - **L2 (`weft`):** Exact out-of-zone `y = 0` preservation sets and co-active partner lists per adapter (for example, `formal_verification` preserves `{prose, ui_module, condensed_json, code}` at zero shift and shares active covariance only with `corpus_epistemic`).
   - **L1 (`loom`):** Unique 128-bit hardware capability tag `H_128([H(M), z_idx, z, bitmask])` (32 lowercase hex chars, `2^64` birthday bound rather than 64-bit's `2^32` collision floor noted in Section 4.2) per zone using canonical JSON framing. Any 1-bit change in `M` rotates `H(M)` and every L1 bank tag atomically.

**Where Vertical Zone Compilation breaks:**

- **Mixed-zone single-token spans:** Inline formal identifiers inside English sentences (or prose docstrings inside code) cannot hold two contradictory scales on one token without sub-span splitting.
- **Mid-generation zone transitions:** A static CST manifest cannot see a model opening a fenced proof block mid-stream unless Layer 4 detects streaming fences and triggers a recurrent-state zone switch.

## 2. Continuous-Discrete Duality (L2 Parametric Space x L5 Structural Splicing)

Pure discrete search stalls on multi-step cliffs (`spliceware` `v3`: 0 of 106 reachable 1-step edits cross a 2-anchor gap). Pure continuous optimization glides smoothly into visible-probe reward hacks (`weft-loom`: 23x MLP and 459x transformer gaming) and shared-token interference (`docs/03-zone-subspace-duality.md`).

Coupling both spaces pairs **L5 discrete structural seams plus non-differentiable external oracles** with **L2 continuous proposal priors plus behaviorally deduplicated two-tier lexicase selection**.

### 2.1 Controlled Simulation Results (`verified` on 6-Slot Discrete Cliff, 20 Seeds, Budget 2,000)

In `scripts/verify_convergences.py`, a 6-slot program over alphabet `{0..7}` starts on an exact 2-step discrete cliff (`0/4` anchors for every 1-step edit) with a realistic 2-slot Goodhart shortcut `(7, 7)` that passes `4/4` visible anchors while failing `100 percent` of private holdouts.

We test two distinct landscapes plus two explicit failure regimes (all arms except `Fail F2` share the exact same private-holdout rejection rule for a fair ablation):

| Regime and Solver Arm | Solves (`20` Seeds) | Goodhart Hacks | Mean Evals | Structural Takeaway |
| --- | --- | --- | --- | --- |
| **Regime 1 (Separable cliff), Arm 1: Blind 1-step greedy** | `0 / 20` (`0%`) | `0` | `2000.0` | Exact single-step cliff deadlock |
| **Regime 1, Arm 2: Uniform 2-step + holdout** | `16 / 20` (`80%`) | `0` | `992.9` | Unstructured multi-step search wastes evals across non-seam pairs |
| **Regime 1, Arm 2b: L5 seams only + scalar + holdout** | `20 / 20` (`100%`) | `0` | `280.1` | On separable tasks, L5 structural seams deliver most of the gain |
| **Regime 1, Arm 3: L5 seams + L2 continuous prior + dedup lexicase** | `20 / 20` (`100%`) | `0` | `253.2` | Bounded continuous token priors refine seam search cleanly |
| **Regime 2 (Deceptive generalist trap), L5 seams + scalar** | `3 / 20` (`15%`) | `0` | `1743.2` | Scalar selection locks onto 2-anchor deceptive trap `[1,1,0,0]` |
| **Regime 2, Coupled L5 seams + L2 prior + dedup lexicase** | `20 / 20` (`100%`) | `0` | `714.5` | Keeps `[0,0,1,0]` and `[0,0,0,1]` specialists alive and recombines |
| **Failure Bound F1: Zero-specialist binary needle** | `0 / 20` (`0%`) | `0` | `2000.0` | No free lunch: zero stepping stones gives zero prior gradient |
| **Failure Bound F2: Coupled loop WITHOUT private holdout** | `7 / 20` (`35%`) | `13 / 20` (`65%`) | `n/a` | Without Axiom 2 holdouts, search collapses into visible shortcuts |

### 2.2 Ablation Findings and Failure Boundaries

1. **Behavioral deduplication is mathematically required (`dedup_pool=False` ablation):** Removing behavioral-signature deduplication (`pool_by_sig`, Gate `G5.3`) lets redundant `[1,1,0,0]` deceptive generalists flood the 16-slot FIFO pool and drops Regime 2 solve rate from `20/20` (`714.5` evals) to `0/20` (`2000.0` evals).
2. **Do not reinforce already-solved seam coordinates (`reinforce_groups=True` ablation):** Reinforcing seam-group selection weights after solving one motif slows Regime 1 from `253.2` to `369.9` evals (slower than uniform L5 seams at `280.1`) by oversampling the solved seam. Bounded token priors paired with uniform seam coverage avoid lock-in.
3. **Strictly dominated intermediates remain unrecoverable:** If a true intermediate scores `[1,0,0,0]` while a deceptive trap scores `[1,1,0,0]`, the intermediate is strictly dominated on every visible anchor and even lexicase cannot distinguish it (`docs/02` Theorem 2 boundary).

## 3. Quantized Orthogonal Packing (`siliquant` x `weft` x `loom`)

Suppose `N` sequential `BetaEdit` low-rank adapters `Delta_j = B_j * A_j` (`B_j` is `d_out x r`, `A_j` is `r x d_in`) are compiled in `float64` so that `A_j * K_0 = 0` and `A_j * K_i = 0` for all `i < j`. What happens when `B_j` and `A_j` are quantized before simultaneous composition?

### 3.1 The Asymmetric Factor Leakage Theorem (`verified`)

Write the quantized factors as `Q(B_j) = B_j + E_B` and `Q(A_j) = A_j + E_A`. Expanding the composed action on any preserved key matrix `K_i` where `A_j * K_i = 0` yields an exact cancellation:

```text
Q(B_j) * Q(A_j) * K_i = (B_j + E_B) * (A_j + E_A) * K_i
                      = (B_j + E_B) * (A_j * K_i) + Q(B_j) * (E_A * K_i)
                      = Q(B_j) * (E_A * K_i)
```

**Consequence (`verified` analytically and numerically):** Left-factor quantization error `E_B` cancels identically. Quantizing `B_j` down to 4-bit `INT4` (or even ternary) introduces **exact zero additional null-space leakage** as long as `A_j * K_i = 0` holds. All quantization-induced cross-adapter leakage comes exclusively from `E_A` in the right factor `A_j`.

When `A_j` is quantized uniformly with precision `b_A` bits, independent rounding perturbations across `N` composed adapters accumulate as a random walk `Theta(sqrt(N) * 2^(-b_A))` relative to `||W0 K0||_F`, creating a sharp phase transition where `INT4` crosses `5 percent` relative leakage by `N = 3` adapters.

### 3.2 Measured Multi-Adapter Leakage Curves (`verified`, `d = 24`, `k0 = 6`, `r = 2`, `N = 1..6`)

Measured relative base leakage `|| (sum_{j=1..N} Q(B_j) Q(A_j)) K0 ||_F / || W0 K0 ||_F` from `scripts/verify_convergences.py`:

| Quantization Format | `N = 1` | `N = 2` | `N = 3` | `N = 4` | `N = 5` | `N = 6` |
| --- | --- | --- | --- | --- | --- | --- |
| **`fp64_both` (exact reference)** | `5.615e-17` | `6.396e-17` | `1.002e-16` | `1.113e-16` | `1.500e-16` | `1.524e-16` |
| **`asym_fp64A_int4B` (FP64 `A`, INT4 `B`)** | `5.505e-17` | `7.370e-17` | `1.047e-16` | `1.321e-16` | `1.560e-16` | `1.589e-16` |
| **`bf16_both` (BF16 `A` and `B`)** | `4.274e-04` | `5.859e-04` | `9.129e-04` | `1.112e-03` | `1.317e-03` | `1.334e-03` |
| **`int8_both` (INT8 `A` and `B`)** | `1.413e-03` | `1.770e-03` | `2.868e-03` | `3.170e-03` | `3.628e-03` | `3.705e-03` |
| **`asym_int8A_int4B` (INT8 `A`, INT4 `B`)** | `1.413e-03` | `1.771e-03` | `2.886e-03` | `3.179e-03` | `3.649e-03` | `3.729e-03` |
| **`int4_both` (INT4 `A` and `B`)** | `2.728e-02` | `3.909e-02` | `5.099e-02` | `5.773e-02` | `6.483e-02` | `6.446e-02` |

Three immediate engineering takeaways follow directly from this table:

1. **BF16 breaks float64 orthogonality by 13 orders of magnitude** (`5.6e-17` to `4.3e-4` at `N = 1`, reaching `1.33e-3` at `N = 6`). That confirms why `weft` must compute `FixedRadixCertificate` *after* BF16 quantization rather than on pre-quantization float64 matrices.
2. **Uniform INT4 destroys null-space guarantees** (`5.10 percent` leakage at `N = 3`, `6.45 percent` at `N = 6`).
3. **Asymmetric `INT8 A` + `INT4 B` is the practical sweet spot (`verified` on `TinyStories-1M`, `hypothesis` at 1.5B-8B scale):** Keeping `A_j` at INT8 (or F16) while compressing `B_j` to 4 bits achieves `3.729e-3` synthetic leakage at `N = 6`, matching `int8_both` within `0.7 percent`, beating `int4_both` by `17.3x`, and cutting `B_j` memory bandwidth in half.

### 3.2b Real-Checkpoint Confirmation (`siliconcordat/weft` Experiment E4 on `TinyStories-1M`)

The synthetic theorem above was tested live in `siliconcordat/weft` (`70a4e68`, Experiment E4) on real pretrained `roneneldan/TinyStories-1M` weights (`N = 3` sequential rank-4 adapters across 8 quantization regimes, all passing exact wire readback and 0-byte re-derivation):

| Layer and Shape (`N = 3`) | Regime (`B / A`) | Bytes | `K0` Linear Leak | `K0` Top-1 Retained | Comparison to Uniform / Control |
| --- | --- | ---: | ---: | ---: | --- |
| `mlp.c_proj` (`64 x 256`) | `int4 / int8` | `3,552` | `0.029345` | `15/16` | `18.37x` lower leak vs `int4/int4` (`0.539110`), `18.18x` vs `int8/int4` (`0.533395`) |
| `mlp.c_proj` (`64 x 256`) | `int8 / int8` | `3,936` | `0.028787` | `15/16` | `int4/int8` stays within `1.9%` of `int8/int8` leakage |
| `mlp.c_proj` (`64 x 256`) | `int4 / f16` | `6,576` | `0.000605` | `16/16` | Beats `bf16/bf16` (`7,680 B`, `0.004471`, `15/16`) on every metric (`7.4x` lower leak) |
| `mlp.c_fc` (`256 x 64`) | `int4 / int8` | `2,400` | `0.148809` | `n/a` | `20.03x` lower leak vs `int4/int4`, `19.80x` vs `int8/int4`, `39.0%` smaller than `int8/int8` |
| `mlp.c_fc` (`256 x 64`) | `int4 / f16` | `3,120` | `0.003916` | `n/a` | `59.4%` smaller than `bf16/bf16` (`7,680 B`) with `12.4x` lower leakage (`0.048433`) |

Three operational details emerged directly from E4:

1. **Reversed control confirms causality (`verified`):** Flipping precision to `int8 / int4` (`B` INT8, `A` INT4) reproduces the full collapse (`0.533395` leakage, `6/16` retained on `mlp.c_proj`), confirming that right-factor error `E_A` alone drives leakage.
2. **Post-quantization integer certificates catch collapse pre-load (`verified`):** On `mlp.c_proj`, `int4 / int4` spikes `FixedRadixCertificate` leakage energy by `325x` (`4.58e9` vs `1.41e7` for `int4 / int8`), rejecting bad packings before GPU load.
3. **Honest 1M-scale boundary:** `TinyStories-1M` is a 1M-parameter narrative model whose `mlp.c_proj` column L2 norms are nearly flat (`1.21x` to `1.41x` max-to-mean across all 8 layers). Keeping top-10 weight-norm columns whole trims Layer-7 max logit drift only modestly (`4.1657` to `4.0039`, `12/16` top-1 unchanged), deferring loud-column gains to 1.5B-8B checkpoints.

### 3.3 Exact Integer-Lattice Kernel Projection and the Siegel Explosion Catch

If the preserved basis itself lives on an integer grid `K_Z` (`d x k`), the integer right kernel `Lambda_ker = {a in Z^d : a^T K_Z = 0}` is a free integer lattice of rank `d - rank(K_Z)`. Choosing integer rows `A_Z` inside `Lambda_ker` with arbitrary quantized left factors `Q(B_j)` gives **exact zero integer leakage** across any number of composed adapters `N`:

```text
(sum_{j=1..N} Q(B_j) * A_j_Z) * K_Z = 0   (exact integer zero)
```

In `scripts/verify_convergences.py`, over ternary integer keys `K_Z` in `{-1, 0, 1}^{24 x 6}`, the integer kernel has dimension `18`, maximum coefficient magnitude `18` (fitting inside signed INT8), and exact integer leakage `0` across all `N = 6` composed adapters with INT4 `B_j` (`verified`).

**The honest Siegel and Hadamard boundary (where exact integer-lattice projection breaks):** For dense integer matrices `K_Z` in `[-M, M]^{d x k}`, even the shortest nonzero integer kernel vector has worst-case coordinate bound `(d * M)^(k / (d - k))` by Siegel's Lemma, while unreduced RREF basis vectors grow up to the Hadamard subdeterminant scale `(sqrt(k) * M)^k`. In our `d = 16`, `M = 8` test:

- At low preservation ratio `k = 4` (`k / (d - k) = 1/3`): the Siegel shortest-vector bound is `5.04` and the unreduced RREF basis peaks at `4,443` (fitting in INT16).
- At high preservation ratio `k = 10` (`k / (d - k) = 5/3`): the Siegel shortest-vector bound jumps to `3,251` (already overflowing INT8 by `25x`), and the unreduced RREF basis explodes to `13,712,411,082` (`> 2^33`, overflowing INT32).

Furthermore, even when `A_Z * K_Z = 0` holds exactly on quantized keys `K_Z`, real floating-point activations `K_real = K_Z + Delta_K` still leak `Q(B_j) * A_Z * Delta_K` unless activations themselves quantize onto the same integer grid.

## 4. Four Serendipitous Cross-Org Convergences

Combining the full 103-repository public excavation ([`docs/06-unmerged-branch-excavation.md`](06-unmerged-branch-excavation.md)) with `weft` Experiment E4 exposes four non-obvious cross-organization convergences that reshape Layers 1 through 5.

### 4.1 Seeded-Noise `K0` Covariance (`siliquant` PR 12 x `weft` E4)

- **Upstream discovery (`source claim`):** `Moissanite-Labs/siliquant` PR 12 showed that random vocabulary tokens (zero real text read) recover `69%` to `96%` of real-text `imatrix` quantization gain across `Qwen2.5-1.5B`, `SmolLM2-1.7B`, and `Llama-3.2-1B`, beating real-text `Q4_K_M --imatrix` at strength `0.25`.
- **Cross-layer confirmation (`verified` on `TinyStories-1M`):** Applied to Layer 2 null-space projection in `siliconcordat/weft` E4 (`70a4e68`), 64 random vocabulary token sequences recovered `83.9%` of real-text holdout `K0` leakage protection (`2.3822` naive to `1.1214` noise-only vs `0.8788` real text at matched trace, with a `9%` target-margin tax `+18.92` vs `+20.77`).
- **Architectural payoff (`hypothesis` at 1.5B-8B):** Compiling `K0` covariance from a deterministic PRNG seed removes external calibration corpora entirely. That eliminates calibration-text copyright risk and makes Hard Veto 1 re-derivation 100 percent seed-reproducible from the checkpoint alone.

### 4.2 Parametric Wire-Dialect Decoders (`tokenpage` PR 1 and PR 5 x `weft`)

- **Upstream discovery (`source claim`):** `Moissanite-Labs/tokenpage` PR 1 measured that ABIOS uses `0.273x` to `0.277x` the tokens of compact JSON across 7 tokenizers. PR 5 then uncovered a structural bottleneck on `Qwen2.5-0.5B` and `1.5B`: internal hidden states linearly decode compact `glyph_g1` packets, yet unadapted readout accuracy collapses to `0.558` (`0.542` with a legend) vs `1.000` JSON and `0.892`/`0.917` ABIOS refs.
- **Cross-layer synthesis (`hypothesis`):** Because the wire semantics are already linearly separable in residual hidden states, compact wire dialects do not require expensive base-model retraining. A tiny asymmetric `int4 / int8` readout adapter compiled in `weft` under seeded-noise `K0` protection and activated solely in the `condensed_json` CST zone can bridge the readout gap without touching prose quality.

### 4.3 Irreducible OS + Static + 256-Bit TCB Law (`abios` PR 41 x `f0` PR 49 x `mission` PR 37)

- **Three independent negative proofs (`verified` upstream):**
  1. `Moissanite-Labs/abios` PR 41 (`Qwen2.5-3B`, 30 trials) showed prompt-level `CMD`/`DATA` envelopes failed completely against hidden peer injection (`obey_delete` went `29/30` plain to `30/30` with envelope, and `envelope_report` raised strict token leaks from `2/30` to `11/30`).
  2. `Foundation-0/f0` PR 49 audited 159 verification scripts and proved bare Python `assert` statements silently vanish under `python3 -O`, allowing corrupted certificates to pass.
  3. `Proven-Commons/mission` PR 37 and `ahrazzle/soko` recorded `181.0M` observed 64-bit hash memoization collisions across `141.1M` states.
- **Combined TCB Law:** Prompt framing, runtime assertions, and 64-bit hash tables cannot replace OS-enforced isolation (`Landlock`, `bubblewrap`, zero `sudo` in `warp`), static verifier pokayoke audits (`mde guard --code-audit`), and canonical full-key or 256-bit cryptographic digests.

### 4.4 Diversity-Preserving Selection Law (`scry` PR 1 x `weft-loom` x `docs/02` Theorem 2)

- **Nucleus-sampling rare-intent extinction (`source claim`):** In `Moissanite-Labs/scry` PR 1 (Zipf(1.1) over 400 intents, 40 rare), `top_p = 1.0` with 10 percent real data retains about `10.8/40` rare intents through generation 50, while `top_p = 0.95` kills all `40/40` rare intents by generation 5.
- **Rival twin-building failure (`source claim`):** `Moissanite-Labs/weft-loom` branch `bayan/vigilant-johnson-egs6w8` proved game-theoretically and on Gemini cells that rival twin scoring gives zero incentive to improve twin building (solo controls matched twins at `0.89-0.99`).
- **Unified selection law (`verified` in Section 2.2):** Tail-truncating samplers, undeduplicated scalar pools (`dedup_pool=False` drops Regime 2 from `20/20` to `0/20`), and misaligned rival objectives destroy rare stepping stones before recombination. Preserving rare capabilities requires untrimmed proposal tails paired with behaviorally deduplicated, specialist-preserving lexicase selection behind external verifier anchors.

## 5. Concrete Falsification Tests for Real Checkpoints

1. **Test C1 (Asymmetric `INT8 A` + `INT4 B` at 1.5B-8B scale):** Confirmed at 1M scale in `siliconcordat/weft` E4 (`18.37x` to `20.03x` leakage reduction on `TinyStories-1M`). Next falsifier: compile 3 sequential `BetaEdit` adapters on a 4B to 8B instruct model and compare `f16/f16`, `int4/int4`, and `int4/int8` on `100` private `K0` holdouts. Refuted if `int4/int8` fails to cut `int4/int4` KL drift by at least `3x` or loud-column keeping fails to move 4B KL.
2. **Test C2 (Single-manifest zero-drift audit across `mde`, `exo`, `warp`, `weft`):** Generate L5 zone tags, L4 scale maps, L3 canary masks, and L2 `y = 0` partitions from one shared `zones.json` file. Refuted if real multi-language repos exhibit `> 10 percent` mixed-zone single-token spans that break static zone routing.
3. **Test C3 (Siegel feasibility regime):** Exact integer-lattice kernel packing is restricted strictly to low-bit (`<= 4-bit`) or sparse low-rank (`k / (d - k) <= 1/2`) preservation subspaces. Above that ratio, asymmetric `F16/INT8 A` + `INT4 B` plus post-quantization `FixedRadixCertificate` is the sound path.
4. **Test C4 (Seeded-Noise `K0` Marchenko-Pastur closure):** Sweep seeded random-vocab sample count `n_noise` from `32` to `2048` on real checkpoints against real-text `K0` and hybrid `noise + 16 register-scoped y = 0` anchors. Refuted if unseen `K0` holdout leakage fails to close within `5 percent` of real-text `K0` by `n_noise = 2048`.
5. **Test C5 (Parametric wire-dialect readout adapter):** Compile a zone-scoped asymmetric `int4/int8` readout adapter targeting a compact wire dialect (`tokenpage` PR 5 regime) while preserving base text under seeded-noise `K0`. Refuted if readout accuracy fails to exceed `0.95` or base-text top-1 retention drops below `95 percent`.
