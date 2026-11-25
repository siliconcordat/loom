"""Executable mathematical proofs and numerical simulations for docs/05.

Standard-library Python 3 only (Apache-2.0). No external packages required.
Run tests:
    python3 -B -m unittest -v scripts/verify_convergences.py
Print verbatim measurement tables:
    python3 -B scripts/verify_convergences.py --report
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import struct
import sys
import unittest
from fractions import Fraction


# ---------------------------------------------------------------------------
# Part 1: Unified Splice Algebra & Vertical Zone Compiler (L5 -> L1)
# ---------------------------------------------------------------------------

CAPABILITY_TAG_HEX_LEN = 32  # 128-bit capability tag (2^64 birthday collision bound)


class ContestedManifestError(ValueError):
    """Raised when a zone manifest contains an unresolved Hard Veto 2 conflict."""


def canonical_sha256(obj: object) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def compile_vertical_zone_manifest(manifest: dict) -> dict:
    """Deterministically project ONE typed L5 zone manifest into L5..L1 artifacts."""
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a dict")
    zones = manifest["zones"]
    adapters = manifest["adapters"]
    precedence = manifest["precedence"]
    zone_predicates = manifest["zone_predicates"]
    plane1_sha = manifest["plane1_tree_sha256"]

    if not isinstance(zones, list) or not zones or not all(isinstance(z, str) and z for z in zones):
        raise ValueError("zones must be a non-empty list of non-empty strings")
    if len(set(zones)) != len(zones):
        raise ValueError("Duplicate zone names in manifest")
    if not isinstance(adapters, list) or not adapters or not all(isinstance(a, str) and a for a in adapters):
        raise ValueError("adapters must be a non-empty list of non-empty strings")
    if len(set(adapters)) != len(adapters):
        raise ValueError("Duplicate adapter names in manifest")
    if not _is_sha256_hex(plane1_sha):
        raise ValueError("plane1_tree_sha256 must be a 64-char lowercase hex SHA-256 digest")
    if not isinstance(precedence, dict) or set(precedence.keys()) != set(zones):
        raise ValueError("precedence keys must match zones exactly")
    if not isinstance(zone_predicates, dict) or set(zone_predicates.keys()) != set(zones):
        raise ValueError("zone_predicates keys must match zones exactly")

    # Hard Veto 2 fail-closed check: any CONTESTED entry aborts compilation.
    for z in zones:
        row = precedence[z]
        if not isinstance(row, dict) or set(row.keys()) != set(adapters):
            raise ValueError(f"precedence[{z!r}] keys must match adapters exactly")
        for a in adapters:
            val = row[a]
            if val == "CONTESTED":
                raise ContestedManifestError(f"Unresolved conflict for zone={z} adapter={a}")
            if type(val) is not int or val not in (0, 1):
                raise ValueError(f"Invalid precedence value {val!r} for zone={z} adapter={a}")

    manifest_hash = canonical_sha256(manifest)

    # L5 (mde): CST zone predicates and protected path rules
    l5_rules = {
        "manifest_sha256": manifest_hash,
        "plane1_tree_sha256": plane1_sha,
        "zone_predicates": zone_predicates,
    }

    # L4 (exo): deterministic zone -> adapter scale vector g(z) in {0.0, 1.0}^M
    l4_router = {
        z: {a: float(precedence[z][a]) for a in adapters}
        for z in zones
    }

    # L3 (warp-modeld): exact reachable bitmasks (collapsing 2^|A| - 1 to <= |Z|)
    reachable_masks: dict[int, list[str]] = {}
    for z in zones:
        mask = 0
        for idx, a in enumerate(adapters):
            if precedence[z][a] == 1:
                mask |= (1 << idx)
        reachable_masks.setdefault(mask, []).append(z)

    l3_canaries = {
        "manifest_sha256": manifest_hash,
        "max_theoretical_masks": (1 << len(adapters)) - 1,
        "reachable_mask_count": len(reachable_masks),
        "reachable_masks": {
            f"0b{m:0{len(adapters)}b}": zs for m, zs in sorted(reachable_masks.items())
        },
    }

    # L2 (weft): exact y=0 out-of-zone preservation partition + co-active partners
    l2_partitions = {}
    for a in adapters:
        active_zones = [z for z in zones if precedence[z][a] == 1]
        zero_zones = [z for z in zones if precedence[z][a] == 0]
        co_active = sorted({
            other
            for z in active_zones
            for other in adapters
            if other != a and precedence[z][other] == 1
        })
        l2_partitions[a] = {
            "active_zones": active_zones,
            "y_zero_preserve_zones": zero_zones,
            "co_active_partners": co_active,
        }

    # L1 (loom): 128-bit capability tag per zone for KV / recurrent-state banks
    # Uses canonical JSON array framing to prevent delimiter ambiguity across zone names.
    l1_bank_tags = {}
    for z_idx, z in enumerate(zones):
        mask = 0
        for idx, a in enumerate(adapters):
            if precedence[z][a] == 1:
                mask |= (1 << idx)
        raw = json.dumps(
            [manifest_hash, z_idx, z, mask],
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        l1_bank_tags[z] = hashlib.sha256(raw).hexdigest()[:CAPABILITY_TAG_HEX_LEN]

    return {
        "manifest_sha256": manifest_hash,
        "l5_mde": l5_rules,
        "l4_exo": l4_router,
        "l3_warp": l3_canaries,
        "l2_weft": l2_partitions,
        "l1_loom": l1_bank_tags,
    }


STANDARD_ZONE_MANIFEST = {
    "plane1_tree_sha256": "a" * 64,
    "zones": ["prose", "formal_proof", "ui_module", "condensed_json", "code"],
    "adapters": ["corpus_prose", "corpus_epistemic", "weft_eido", "formal_verification"],
    "zone_predicates": {
        "prose": ["markdown_paragraph", "comment_block"],
        "formal_proof": ["lean_theorem", "proof_block", "verdict_record"],
        "ui_module": ["js_module", "css_stylesheet"],
        "condensed_json": ["condensed_slot_json"],
        "code": ["source_function", "source_module"],
    },
    "precedence": {
        "prose":          {"corpus_prose": 1, "corpus_epistemic": 1, "weft_eido": 0, "formal_verification": 0},
        "formal_proof":   {"corpus_prose": 0, "corpus_epistemic": 1, "weft_eido": 0, "formal_verification": 1},
        "ui_module":      {"corpus_prose": 0, "corpus_epistemic": 1, "weft_eido": 1, "formal_verification": 0},
        "condensed_json": {"corpus_prose": 0, "corpus_epistemic": 1, "weft_eido": 1, "formal_verification": 0},
        "code":           {"corpus_prose": 0, "corpus_epistemic": 1, "weft_eido": 0, "formal_verification": 0},
    },
}


# ---------------------------------------------------------------------------
# Part 2: Continuous-Discrete Two-Space Cliff Simulation
# ---------------------------------------------------------------------------
# A 6-slot discrete program over alphabet {0..7}.
# Ground truth target requires two coupled motif pairs:
#   Motif A (positions 0,1) == (3, 5)  [solves visible anchors 0, 1]
#   Motif B (positions 2,3) == (6, 2)  [solves visible anchors 2, 3]
#   Generalization tail (positions 4,5) == (1, 7) [required by private holdouts!]
# Shortcut trap: setting pos 0..1 == (7, 7) passes ALL 4 visible anchors
#   (simulating visible-probe gaming) while failing 100% of private holdouts!
# Seed starts at (0, 0, 0, 0, 1, 7):
#   - Changing any SINGLE position among 0..3 yields 0/4 visible anchors (exact 2-step cliff!).
#   - Blind 1-step greedy hill-climbing is mathematically deadlocked at 0/4 forever.

ALPHABET = 8
VISIBLE_MOTIF_A = (3, 5)
VISIBLE_MOTIF_B = (6, 2)
# Realistic Goodhart shortcut: a 2-slot hack (like 0x00 HALT or visible-probe memorization)
# is easier to hit than the full 4-slot true generalization (Motif A + Motif B).
SHORTCUT_TRAP = (7, 7)
HOLDOUT_TAIL = (1, 7)
CLIFF_SEED = (0, 0, 0, 0, 1, 7)


def eval_discrete_program(prog: tuple[int, ...]) -> tuple[list[int], int]:
    """Return (visible_4_anchors, private_holdout_pass) in {0,1}."""
    if prog[:2] == SHORTCUT_TRAP:
        # Visible-probe reward hack: passes 4/4 visible in 2 slots, fails 100% of private holdouts.
        return ([1, 1, 1, 1], 0)

    a_ok = 1 if prog[0:2] == VISIBLE_MOTIF_A else 0
    b_ok = 1 if prog[2:4] == VISIBLE_MOTIF_B else 0
    # Four visible anchors: (0,1) gate on Motif A, (2,3) gate on Motif B.
    vis = [a_ok, a_ok, b_ok, b_ok]
    holdout = 1 if (a_ok and b_ok and prog[4:6] == HOLDOUT_TAIL) else 0
    return (vis, holdout)


def eval_needle_program(prog: tuple[int, ...]) -> tuple[list[int], int]:
    """Failure Mode F1: pure binary needle with ZERO stepping-stone specialists."""
    ok = 1 if prog == (3, 5, 6, 2, 1, 7) else 0
    return ([ok, ok, ok, ok], ok)


def eval_deceptive_tradeoff_program(prog: tuple[int, ...]) -> tuple[list[int], int]:
    """Regime 2: deceptive 2-anchor generalist trap vs two non-dominated 1-anchor specialists.

    - Any prog[0] in {4, 5} creates a 2-anchor deceptive generalist [1, 1, 0, 0] (scalar score 2)
      that breaks compatibility with anchors 2 and 3.
    - True Motif A = (3, 5) alone gives [0, 0, 1, 0] (unique specialist on anchor 2, score 1).
    - True Motif B = (6, 2) alone (when prog[0] not in {4, 5}) gives [0, 0, 0, 1]
      (unique specialist on anchor 3, score 1).
    - Recombining Motif A + Motif B solves all 4 anchors [1, 1, 1, 1] (and holdout if tail matches).
    - Shortcut trap prog[:2] == (7, 7) passes 4/4 visible, fails private holdout.
    """
    if prog[:2] == SHORTCUT_TRAP:
        return ([1, 1, 1, 1], 0)
    if prog[0] in (4, 5):
        return ([1, 1, 0, 0], 0)
    a_ok = 1 if prog[0:2] == VISIBLE_MOTIF_A else 0
    b_ok = 1 if prog[2:4] == VISIBLE_MOTIF_B else 0
    if a_ok and b_ok:
        vis = [1, 1, 1, 1]
    else:
        vis = [0, 0, a_ok, b_ok]
    ho = 1 if (a_ok and b_ok and prog[4:6] == HOLDOUT_TAIL) else 0
    return (vis, ho)


def run_blind_1step_hillclimb(seed_val: int, budget: int) -> tuple[bool, int]:
    rng = random.Random(seed_val)
    cur = CLIFF_SEED
    cur_vis, cur_ho = eval_discrete_program(cur)
    cur_score = sum(cur_vis)
    for step in range(1, budget + 1):
        pos = rng.randrange(len(cur))
        val = rng.randrange(ALPHABET)
        cand = cur[:pos] + (val,) + cur[pos + 1:]
        vis, ho = eval_discrete_program(cand)
        if sum(vis) > cur_score:
            cur, cur_score, cur_ho = cand, sum(vis), ho
            if sum(vis) == 4 and ho == 1:
                return (True, step)
    return (False, budget)


def run_uniform_multistep_scalar(seed_val: int, budget: int) -> tuple[bool, int]:
    """Uniform 2-step random mutation with scalar strict promotion (no prior, no lexicase)."""
    rng = random.Random(seed_val)
    cur = CLIFF_SEED
    cur_score = 0
    for step in range(1, budget + 1):
        cand_list = list(cur)
        # Uniformly edit 2 random positions across all 6 slots
        p1, p2 = rng.sample(range(6), 2)
        cand_list[p1] = rng.randrange(ALPHABET)
        cand_list[p2] = rng.randrange(ALPHABET)
        cand = tuple(cand_list)
        vis, ho = eval_discrete_program(cand)
        sc = sum(vis)
        if sc == 4:
            if ho == 1:
                return (True, step)
            # Same private-holdout rejection as Arm 3 for a fair ablation.
            continue
        if sc > cur_score:
            cur, cur_score = cand, sc
    return (False, budget)


def run_seam_grouped_uniform_scalar(
    seed_val: int,
    budget: int,
    eval_fn=eval_discrete_program,
) -> tuple[bool, int]:
    """Arm 2b: L5 structural seam groups + private holdout, uniform sampling, scalar selection."""
    rng = random.Random(seed_val)
    groups = [(0, 1), (2, 3), (4, 5)]
    cur = CLIFF_SEED
    cur_score = 0
    for step in range(1, budget + 1):
        p1, p2 = rng.choice(groups)
        cand_list = list(cur)
        cand_list[p1] = rng.randrange(ALPHABET)
        cand_list[p2] = rng.randrange(ALPHABET)
        cand = tuple(cand_list)
        vis, ho = eval_fn(cand)
        sc = sum(vis)
        if sc == 4:
            if ho == 1:
                return (True, step)
            continue
        if sc > cur_score:
            cur, cur_score = cand, sc
    return (False, budget)


def _softmax(logits: list[float]) -> list[float]:
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    s = sum(exps)
    return [e / s for e in exps]


def _sample_categorical(rng: random.Random, probs: list[float]) -> int:
    u = rng.random()
    acc = 0.0
    for i, p in enumerate(probs):
        acc += p
        if u <= acc:
            return i
    return len(probs) - 1


def _lexicase_select(rng: random.Random, pool: list[tuple[tuple[int, ...], list[int]]]) -> tuple[int, ...]:
    order = [0, 1, 2, 3]
    rng.shuffle(order)
    survivors = pool
    for idx in order:
        best = max(v[idx] for _, v in survivors)
        survivors = [(p, v) for p, v in survivors if v[idx] == best]
        if len(survivors) == 1:
            break
    return rng.choice(survivors)[0]


def run_coupled_continuous_lexicase(
    seed_val: int,
    budget: int,
    use_private_holdout: bool = True,
    needle_mode: bool = False,
    eval_override=None,
    dedup_pool: bool = True,
    reinforce_groups: bool = False,
) -> tuple[str, int]:
    """Coupled L2 continuous token log-weights + L5 structural seams + two-tier lexicase.

    Uses strictly black-box credit assignment on the edited seam (p1, p2) with zero
    access to benchmark constants. Optional ablation toggles:
      - dedup_pool=False: fixed 16-slot FIFO pool without behavioral signature deduplication.
      - reinforce_groups=True: reinforce seam-group logits after solving a motif.
    Returns (outcome, evals) where outcome in {"true_solve", "goodhart_hack", "timeout"}.
    """
    rng = random.Random(seed_val)
    if eval_override is not None:
        eval_fn = eval_override
    else:
        eval_fn = eval_needle_program if needle_mode else eval_discrete_program
    groups = [(0, 1), (2, 3), (4, 5)]

    # Continuous parameters: token log-weights per slot (6 x 8) and optional group logits (3)
    token_logits = [[0.0] * ALPHABET for _ in range(6)]
    group_logits = [0.0, 0.0, 0.0]

    # Stepping-stone pool: behaviorally deduplicated by default (Gate G5.3)
    pool_by_sig: dict[tuple[int, ...], tuple[int, ...]] = {(0, 0, 0, 0): CLIFF_SEED}
    raw_pool: list[tuple[tuple[int, ...], list[int]]] = [(CLIFF_SEED, [0, 0, 0, 0])]
    seen_progs = {CLIFF_SEED}

    for step in range(1, budget + 1):
        if dedup_pool:
            pool = [(prog, list(sig)) for sig, prog in pool_by_sig.items()]
        else:
            pool = raw_pool
        parent = _lexicase_select(rng, pool)

        if reinforce_groups:
            g_idx = _sample_categorical(rng, _softmax(group_logits))
        else:
            g_idx = rng.randrange(len(groups))
        p1, p2 = groups[g_idx]

        # Propose coordinated pair edit sampled from continuous slot distributions
        cand_list = list(parent)
        v1 = _sample_categorical(rng, _softmax(token_logits[p1]))
        v2 = _sample_categorical(rng, _softmax(token_logits[p2]))
        cand_list[p1] = v1
        cand_list[p2] = v2

        # With probability 0.35, recombine a complementary seam from a lexicase-selected donor
        if len(pool) >= 2 and rng.random() < 0.35:
            donor = _lexicase_select(rng, pool)
            cand_list[p1] = donor[p1]
            cand_list[p2] = donor[p2]

        cand = tuple(cand_list)
        vis, ho = eval_fn(cand)

        if sum(vis) == 4:
            if not use_private_holdout:
                return ("true_solve" if ho == 1 else "goodhart_hack", step)
            if ho == 1:
                return ("true_solve", step)
            # Black-box credit assignment on private-holdout rejection: penalize edited seam only.
            for idx in (p1, p2):
                token_logits[idx][cand[idx]] -= 1.5
            continue

        sig = tuple(vis)
        if dedup_pool:
            if sum(vis) > 0 and sig not in pool_by_sig:
                pool_by_sig[sig] = cand
                if reinforce_groups:
                    group_logits[g_idx] += 0.6
                token_logits[p1][cand[p1]] = min(1.5, token_logits[p1][cand[p1]] + 0.5)
                token_logits[p2][cand[p2]] = min(1.5, token_logits[p2][cand[p2]] + 0.5)
        else:
            # Undeduplicated FIFO pool ablation: any unique program with >0 anchors enters
            if sum(vis) > 0 and cand not in seen_progs:
                seen_progs.add(cand)
                raw_pool.append((cand, vis))
                if len(raw_pool) > 16:
                    raw_pool.pop(1)
                if reinforce_groups:
                    group_logits[g_idx] += 0.6
                token_logits[p1][cand[p1]] = min(1.5, token_logits[p1][cand[p1]] + 0.5)
                token_logits[p2][cand[p2]] = min(1.5, token_logits[p2][cand[p2]] + 0.5)

    return ("timeout", budget)


# ---------------------------------------------------------------------------
# Part 3: Quantized Orthogonal Packing (siliquant x weft x loom)
# ---------------------------------------------------------------------------

def matmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    m, k, n = len(A), len(A[0]), len(B[0])
    Bt = [[B[r][c] for r in range(k)] for c in range(n)]
    return [
        [sum(A[i][t] * Bt[j][t] for t in range(k)) for j in range(n)]
        for i in range(m)
    ]


def matadd(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return [[A[i][j] + B[i][j] for j in range(len(A[0]))] for i in range(len(A))]


def frob_norm(A: list[list[float]]) -> float:
    return math.sqrt(sum(x * x for row in A for x in row))


def transpose(A: list[list[float]]) -> list[list[float]]:
    return [[A[r][c] for r in range(len(A))] for c in range(len(A[0]))]


def orthonormal_basis_cols(M: list[list[float]], tol: float = 1e-12) -> list[list[float]]:
    """Modified Gram-Schmidt returning orthonormal basis columns Q (d x r)."""
    d = len(M)
    cols = transpose(M)
    basis: list[list[float]] = []
    for v in cols:
        w = list(v)
        # Re-orthogonalize twice for float64 precision (~1e-15)
        for _ in range(2):
            for q in basis:
                dot = sum(w[i] * q[i] for i in range(d))
                for i in range(d):
                    w[i] -= dot * q[i]
        norm = math.sqrt(sum(x * x for x in w))
        if norm > tol:
            basis.append([x / norm for x in w])
    return transpose(basis) if basis else [[0.0] * 0 for _ in range(d)]


def project_rows_right_null(A: list[list[float]], Q_basis: list[list[float]]) -> list[list[float]]:
    """Project rows of A (r x d) onto the right null space of Q_basis (d x k): A * (I - Q Q^T)."""
    r, d = len(A), len(A[0])
    k = len(Q_basis[0]) if Q_basis else 0
    if k == 0:
        return [list(row) for row in A]
    Qt = transpose(Q_basis)  # k x d
    out = [list(row) for row in A]
    for _ in range(2):
        for i in range(r):
            for j in range(k):
                dot = sum(out[i][t] * Qt[j][t] for t in range(d))
                for t in range(d):
                    out[i][t] -= dot * Qt[j][t]
    return out


def quantize_bf16_scalar(x: float) -> float:
    """IEEE-754 float32 round-to-nearest-even to BF16 (top 16 bits)."""
    b = struct.pack(">f", x)
    bits = struct.unpack(">I", b)[0]
    lsb = (bits >> 16) & 1
    rounded = (bits + 0x7FFF + lsb) & 0xFFFF0000
    return struct.unpack(">f", struct.pack(">I", rounded))[0]


def quantize_matrix(M: list[list[float]], mode: str) -> list[list[float]]:
    if mode == "fp64":
        return [list(row) for row in M]
    if mode == "bf16":
        return [[quantize_bf16_scalar(x) for x in row] for row in M]
    if mode in ("int8", "int4"):
        qmax = 127 if mode == "int8" else 7
        out = []
        for row in M:
            amax = max(abs(x) for x in row)
            if amax == 0.0:
                out.append([0.0] * len(row))
            else:
                scale = amax / qmax
                out.append([round(x / scale) * scale for x in row])
        return out
    raise ValueError(f"Unknown quant mode: {mode}")


def exact_integer_kernel_basis(K_int: list[list[int]]) -> list[list[int]]:
    """Exact row-space integer basis for {a in Z^d : a^T K_int = 0} via exact Rational RREF."""
    # Solve K_int^T * a = 0 over Q using Fraction, then clear denominators to Z.
    d = len(K_int)
    k = len(K_int[0])
    mat = [[Fraction(K_int[c][r]) for c in range(d)] for r in range(k)]

    pivot_cols: list[int] = []
    row = 0
    for col in range(d):
        if row >= k:
            break
        piv = None
        for r in range(row, k):
            if mat[r][col] != 0:
                piv = r
                break
        if piv is None:
            continue
        mat[row], mat[piv] = mat[piv], mat[row]
        pv = mat[row][col]
        mat[row] = [x / pv for x in mat[row]]
        for r in range(k):
            if r != row and mat[r][col] != 0:
                factor = mat[r][col]
                mat[r] = [mat[r][c] - factor * mat[row][c] for c in range(d)]
        pivot_cols.append(col)
        row += 1

    pivot_set = set(pivot_cols)
    free_cols = [c for c in range(d) if c not in pivot_set]

    int_basis: list[list[int]] = []
    for fc in free_cols:
        vec = [Fraction(0)] * d
        vec[fc] = Fraction(1)
        for r_idx, pc in enumerate(pivot_cols):
            vec[pc] = -mat[r_idx][fc]
        lcm_den = 1
        for x in vec:
            lcm_den = math.lcm(lcm_den, x.denominator)
        ivec = [int(x * lcm_den) for x in vec]
        g = 0
        for x in ivec:
            g = math.gcd(g, abs(x))
        if g > 1:
            ivec = [x // g for x in ivec]
        int_basis.append(ivec)
    return int_basis


def run_quantized_orthogonal_packing_experiment(
    d: int = 24,
    k0: int = 6,
    n_adapters: int = 6,
    rank: int = 2,
    seed: int = 20261119,
) -> dict:
    """Measure cumulative cross-adapter leakage ||sum Q(Delta_j) K0||_F / ||W0 K0||_F."""
    rng = random.Random(seed)
    W0 = [[rng.gauss(0.0, 1.0 / math.sqrt(d)) for _ in range(d)] for _ in range(d)]
    K0 = [[rng.gauss(0.0, 1.0) for _ in range(k0)] for _ in range(d)]
    denom = frob_norm(matmul(W0, K0))

    Q0 = orthonormal_basis_cols(K0)

    # Build N sequential BetaEdit low-rank adapters: A_j K0 = 0 and A_j K_i = 0 (i < j)
    accum_keys = [list(row) for row in K0]
    adapters: list[tuple[list[list[float]], list[list[float]]]] = []
    for _ in range(n_adapters):
        Q_prev = orthonormal_basis_cols(accum_keys)
        B_raw = [[rng.gauss(0.0, 0.25) for _ in range(rank)] for _ in range(d)]
        A_raw = [[rng.gauss(0.0, 0.25) for _ in range(d)] for _ in range(rank)]
        A_orth = project_rows_right_null(A_raw, Q_prev)
        adapters.append((B_raw, A_orth))
        # Append 2 preservation keys per adapter for subsequent adapters
        K_new = [[rng.gauss(0.0, 1.0) for _ in range(2)] for _ in range(d)]
        for r_i in range(d):
            accum_keys[r_i].extend(K_new[r_i])

    modes = [
        ("fp64_both", "fp64", "fp64"),
        ("bf16_both", "bf16", "bf16"),
        ("int8_both", "int8", "int8"),
        ("int4_both", "int4", "int4"),
        ("asym_fp64A_int4B", "int4", "fp64"),
        ("asym_int8A_int4B", "int4", "int8"),
    ]
    curves: dict[str, list[float]] = {name: [] for name, _, _ in modes}

    for name, b_mode, a_mode in modes:
        sum_delta = [[0.0] * d for _ in range(d)]
        for j in range(n_adapters):
            B_j, A_j = adapters[j]
            Q_B = quantize_matrix(B_j, b_mode)
            Q_A = quantize_matrix(A_j, a_mode)
            sum_delta = matadd(sum_delta, matmul(Q_B, Q_A))
            leak = frob_norm(matmul(sum_delta, K0)) / denom
            curves[name].append(leak)

    # Exact integer-lattice kernel packing over small integer K_Z in {-1, 0, 1}^{d x k0}
    # plus dense INT8 K_Z to demonstrate the Siegel coefficient-growth catch.
    K_sparse_int = [[rng.choice([-1, 0, 1]) for _ in range(k0)] for _ in range(d)]
    sparse_ker = exact_integer_kernel_basis(K_sparse_int)
    max_sparse_coeff = max(abs(x) for v in sparse_ker for x in v)

    # Compose N=6 integer-lattice adapters with arbitrary INT4 quantized B_j -> EXACT 0 leakage
    exact_int_leak = 0
    for j in range(n_adapters):
        # Pick 2 integer kernel rows for A_j_Z
        A_int = [sparse_ker[(2 * j) % len(sparse_ker)], sparse_ker[(2 * j + 1) % len(sparse_ker)]]
        # Arbitrary INT4 integer left factor B_int in [-7, 7]
        B_int = [[rng.randint(-7, 7) for _ in range(2)] for _ in range(d)]
        # Verify exact integer product (B_int @ A_int) @ K_sparse_int == 0
        for row_i in range(d):
            for col_c in range(k0):
                val = 0
                for t in range(2):
                    ak = sum(A_int[t][u] * K_sparse_int[u][col_c] for u in range(d))
                    val += B_int[row_i][t] * ak
                exact_int_leak += abs(val)

    # Demonstrate Siegel growth on denser INT8 K_Z as preservation rank k rises (k=4 vs k=10 at d=16)
    d_small = 16
    K_dense_k4 = [[rng.randint(-8, 8) for _ in range(4)] for _ in range(d_small)]
    K_dense_k10 = [[rng.randint(-8, 8) for _ in range(10)] for _ in range(d_small)]
    ker_k4 = exact_integer_kernel_basis(K_dense_k4)
    ker_k10 = exact_integer_kernel_basis(K_dense_k10)
    siegel_max_k4 = max(abs(x) for v in ker_k4 for x in v)
    siegel_max_k10 = max(abs(x) for v in ker_k10 for x in v)

    return {
        "curves": curves,
        "sparse_ker_dim": len(sparse_ker),
        "max_sparse_coeff": max_sparse_coeff,
        "exact_int_leak": exact_int_leak,
        "siegel_max_k4": siegel_max_k4,
        "siegel_max_k10": siegel_max_k10,
    }


# ---------------------------------------------------------------------------
# Unit Tests Verifying Every Claim & Table in docs/05
# ---------------------------------------------------------------------------

class TestConvergences(unittest.TestCase):
    def test_part1_vertical_zone_compilation(self):
        out1 = compile_vertical_zone_manifest(STANDARD_ZONE_MANIFEST)
        out2 = compile_vertical_zone_manifest(STANDARD_ZONE_MANIFEST)
        # 0-byte deterministic projection across all 5 layers
        self.assertEqual(out1, out2)
        # Reachable masks collapse from 2^4 - 1 = 15 down to 4 distinct masks (<= 5 zones)
        self.assertEqual(out1["l3_warp"]["max_theoretical_masks"], 15)
        self.assertEqual(out1["l3_warp"]["reachable_mask_count"], 4)
        # L2 y=0 preservation partition for formal_verification excludes prose/ui/condensed/code
        fv_part = out1["l2_weft"]["formal_verification"]
        self.assertEqual(fv_part["active_zones"], ["formal_proof"])
        self.assertEqual(fv_part["y_zero_preserve_zones"], ["prose", "ui_module", "condensed_json", "code"])
        self.assertEqual(fv_part["co_active_partners"], ["corpus_epistemic"])
        # L1 bank tags are unique 128-bit (32-hex) digests per zone
        tags = list(out1["l1_loom"].values())
        self.assertEqual(len(set(tags)), 5)
        for tag in tags:
            self.assertEqual(len(tag), CAPABILITY_TAG_HEX_LEN)
            self.assertTrue(all(ch in "0123456789abcdef" for ch in tag))

        # Any 1-bit change in manifest atomically rotates the root hash and all L1 tags
        mutated = json.loads(json.dumps(STANDARD_ZONE_MANIFEST))
        mutated["plane1_tree_sha256"] = "b" * 64
        out_mut = compile_vertical_zone_manifest(mutated)
        self.assertNotEqual(out1["manifest_sha256"], out_mut["manifest_sha256"])
        for z in STANDARD_ZONE_MANIFEST["zones"]:
            self.assertNotEqual(out1["l1_loom"][z], out_mut["l1_loom"][z])

        # Hard Veto 2: any CONTESTED cell fails closed
        contested = json.loads(json.dumps(STANDARD_ZONE_MANIFEST))
        contested["precedence"]["ui_module"]["corpus_prose"] = "CONTESTED"
        with self.assertRaises(ContestedManifestError):
            compile_vertical_zone_manifest(contested)

    def test_part2_continuous_discrete_duality(self):
        seeds = list(range(100, 120))  # 20 fixed seeds
        budget = 2000

        # Arm 1: Blind 1-step greedy hill-climber deadlocks 0/20 on exact 2-step cliff
        blind_solves = sum(1 for s in seeds if run_blind_1step_hillclimb(s, budget)[0])
        self.assertEqual(blind_solves, 0)

        # Arm 2: Uniform multi-step mutation without seams, continuous prior, or lexicase
        unif_results = [run_uniform_multistep_scalar(s, budget) for s in seeds]
        unif_solves = sum(1 for ok, _ in unif_results if ok)

        # Arm 2b: L5 structural seam groups only (uniform sampling, scalar selection)
        seam_results = [run_seam_grouped_uniform_scalar(s, budget) for s in seeds]
        seam_solves = sum(1 for ok, _ in seam_results if ok)
        mean_seam_evals = sum(e for _, e in seam_results) / len(seeds)

        # Arm 3: Coupled L5 seams + L2 continuous prior + two-tier lexicase + private holdout
        coupled_results = [
            run_coupled_continuous_lexicase(s, budget, use_private_holdout=True)
            for s in seeds
        ]
        coupled_solves = sum(1 for res, _ in coupled_results if res == "true_solve")
        coupled_hacks = sum(1 for res, _ in coupled_results if res == "goodhart_hack")
        mean_coupled_evals = sum(e for _, e in coupled_results) / len(seeds)

        # Coupled loop outperforms blind 1-step (0/20) and uniform 2-step, with 0 Goodhart hacks
        self.assertEqual(coupled_hacks, 0)
        self.assertGreaterEqual(coupled_solves, 18)  # >= 90% solve rate
        self.assertGreater(coupled_solves, unif_solves)
        self.assertGreaterEqual(seam_solves, unif_solves)
        self.assertLess(mean_coupled_evals, 700.0)
        self.assertGreater(mean_seam_evals, 0.0)

        # Regime 2 (Deceptive generalist trap): scalar L5 seams stall on 2-anchor trap,
        # while coupled continuous prior + two-tier lexicase preserves specialists and solves!
        dec_seam = [
            run_seam_grouped_uniform_scalar(s, budget, eval_fn=eval_deceptive_tradeoff_program)
            for s in seeds
        ]
        dec_coupled = [
            run_coupled_continuous_lexicase(
                s, budget, use_private_holdout=True, eval_override=eval_deceptive_tradeoff_program
            )
            for s in seeds
        ]
        dec_seam_solves = sum(1 for ok, _ in dec_seam if ok)
        dec_coupled_solves = sum(1 for res, _ in dec_coupled if res == "true_solve")
        self.assertLessEqual(dec_seam_solves, 4)
        self.assertGreaterEqual(dec_coupled_solves, 16)

        # Scripted Ablations (verifying docs/05 Section 2.2 findings directly):
        # (a) Removing behavioral deduplication (dedup_pool=False) degrades Regime 2 severely.
        dec_nodedup = [
            run_coupled_continuous_lexicase(
                s, budget, use_private_holdout=True, eval_override=eval_deceptive_tradeoff_program, dedup_pool=False
            )
            for s in seeds
        ]
        dec_nodedup_solves = sum(1 for res, _ in dec_nodedup if res == "true_solve")
        self.assertLess(dec_nodedup_solves, dec_coupled_solves)

        # (b) Reinforcing already-solved seam groups slows Regime 1 vs uniform seam selection.
        r1_grp = [
            run_coupled_continuous_lexicase(s, budget, use_private_holdout=True, reinforce_groups=True)
            for s in seeds
        ]
        mean_r1_grp = sum(e for _, e in r1_grp) / len(seeds)
        self.assertGreater(mean_r1_grp, mean_coupled_evals)

        # Honest Failure Bound F1: Pure binary needle (0 stepping stones) defeats continuous priors
        needle_results = [
            run_coupled_continuous_lexicase(s, budget, use_private_holdout=True, needle_mode=True)
            for s in seeds
        ]
        needle_solves = sum(1 for res, _ in needle_results if res == "true_solve")
        self.assertEqual(needle_solves, 0)

        # Honest Failure Bound F2: Disabling private holdout lets the coupled loop fall into
        # the easier 2-slot Goodhart shortcut on a substantial fraction of seeds!
        no_holdout_results = [
            run_coupled_continuous_lexicase(s, budget, use_private_holdout=False)
            for s in seeds
        ]
        no_holdout_hacks = sum(1 for res, _ in no_holdout_results if res == "goodhart_hack")
        self.assertGreaterEqual(no_holdout_hacks, 8)
        vis_hack, ho_hack = eval_discrete_program(SHORTCUT_TRAP + (0, 0) + HOLDOUT_TAIL)
        self.assertEqual(vis_hack, [1, 1, 1, 1])
        self.assertEqual(ho_hack, 0)

    def test_part3_quantized_orthogonal_packing(self):
        res = run_quantized_orthogonal_packing_experiment()
        c = res["curves"]

        # 1. Float64 maintains ~1e-15 machine-epsilon orthogonality across all N=6 adapters
        self.assertLess(c["fp64_both"][-1], 1e-13)

        # 2. Asymmetric Theorem: quantizing B_j to INT4 while keeping A_j in FP64 causes
        #    EXACT ZERO additional null-space leakage (~1e-15, identical order to FP64!)
        self.assertLess(c["asym_fp64A_int4B"][-1], 1e-13)

        # 3. Quantizing A_j breaks float64 orthogonality by >= 10 orders of magnitude:
        #    fp64 (~1e-15) << bf16 (~1e-3) < int8 (~1e-3..1e-2) << int4 (~1e-1)
        self.assertGreater(c["bf16_both"][-1], 1e-4)
        self.assertGreater(c["int4_both"][-1], c["int8_both"][-1] * 5.0)
        self.assertGreater(c["int4_both"][-1], 0.05)  # phase transition past 5% leakage

        # 4. Asymmetric INT8-A + INT4-B beats uniform INT4 by > 10x
        self.assertLess(c["asym_int8A_int4B"][-1] * 10.0, c["int4_both"][-1])

        # 5. Exact integer-lattice kernel projection achieves LITERALLY ZERO (0) integer drift
        self.assertEqual(res["exact_int_leak"], 0)
        self.assertEqual(res["sparse_ker_dim"], 18)  # d=24 - k0=6 = 18

        # 6. Honest Siegel / Hadamard catch: dense high-rank preservation causes both
        #    Siegel shortest-vector bound (d * M)^(k/(d-k)) and unreduced RREF basis to blow up
        siegel_bound_k4 = (16 * 8) ** (4.0 / 12.0)
        siegel_bound_k10 = (16 * 8) ** (10.0 / 6.0)
        self.assertAlmostEqual(siegel_bound_k4, 5.039684, places=4)
        self.assertAlmostEqual(siegel_bound_k10, 3250.9974, places=3)
        self.assertGreater(siegel_bound_k10, 127 * 25)  # >25x INT8 overflow
        self.assertGreater(res["siegel_max_k10"], res["siegel_max_k4"] * 100)


def print_report() -> None:
    print("=== PART 1: VERTICAL ZONE COMPILATION ===")
    z = compile_vertical_zone_manifest(STANDARD_ZONE_MANIFEST)
    print(f"manifest_sha256={z['manifest_sha256'][:16]}...")
    print(f"max_masks={z['l3_warp']['max_theoretical_masks']} -> reachable={z['l3_warp']['reachable_mask_count']}")
    for m, zs in z["l3_warp"]["reachable_masks"].items():
        print(f"  mask {m}: {zs}")

    print("\n=== PART 2: CONTINUOUS-DISCRETE CLIFF (20 seeds, budget=2000) ===")
    seeds = list(range(100, 120))
    b1 = [run_blind_1step_hillclimb(s, 2000) for s in seeds]
    u2 = [run_uniform_multistep_scalar(s, 2000) for s in seeds]
    s2 = [run_seam_grouped_uniform_scalar(s, 2000) for s in seeds]
    cl = [run_coupled_continuous_lexicase(s, 2000, True, False) for s in seeds]
    nd = [run_coupled_continuous_lexicase(s, 2000, True, True) for s in seeds]
    nh = [run_coupled_continuous_lexicase(s, 2000, False, False) for s in seeds]
    print(f"Arm 1 (blind 1-step):         {sum(ok for ok,_ in b1)}/20 solves, mean_evals={sum(e for _,e in b1)/20:.1f}")
    print(f"Arm 2 (uniform 2-step):       {sum(ok for ok,_ in u2)}/20 solves, mean_evals={sum(e for _,e in u2)/20:.1f}")
    print(f"Arm 2b (L5 seams only):       {sum(ok for ok,_ in s2)}/20 solves, mean_evals={sum(e for _,e in s2)/20:.1f}")
    print(f"Arm 3 (coupled+lex+holdout):  {sum(r=='true_solve' for r,_ in cl)}/20 solves, mean_evals={sum(e for _,e in cl)/20:.1f}")
    ds = [run_seam_grouped_uniform_scalar(s, 2000, eval_fn=eval_deceptive_tradeoff_program) for s in seeds]
    dc = [run_coupled_continuous_lexicase(s, 2000, True, False, eval_deceptive_tradeoff_program) for s in seeds]
    dc_nd = [run_coupled_continuous_lexicase(s, 2000, True, False, eval_deceptive_tradeoff_program, dedup_pool=False) for s in seeds]
    r1_rg = [run_coupled_continuous_lexicase(s, 2000, True, False, None, True, True) for s in seeds]
    print(f"Regime 1 ablation (reinforce_groups):  {sum(r=='true_solve' for r,_ in r1_rg)}/20 solves, mean_evals={sum(e for _,e in r1_rg)/20:.1f}")
    print(f"Regime 2 (deceptive, L5 seams scalar): {sum(ok for ok,_ in ds)}/20 solves, mean_evals={sum(e for _,e in ds)/20:.1f}")
    print(f"Regime 2 (deceptive, coupled+lex):     {sum(r=='true_solve' for r,_ in dc)}/20 solves, mean_evals={sum(e for _,e in dc)/20:.1f}")
    print(f"Regime 2 ablation (no dedup_pool):     {sum(r=='true_solve' for r,_ in dc_nd)}/20 solves, mean_evals={sum(e for _,e in dc_nd)/20:.1f}")
    print(f"Fail F1 (binary needle):      {sum(r=='true_solve' for r,_ in nd)}/20 solves, mean_evals={sum(e for _,e in nd)/20:.1f}")
    print(f"Fail F2 (no holdout):         {sum(r=='true_solve' for r,_ in nh)}/20 true, {sum(r=='goodhart_hack' for r,_ in nh)}/20 hacks")

    print("\n=== PART 3: QUANTIZED ORTHOGONAL PACKING (d=24, k0=6, N=1..6, r=2) ===")
    q = run_quantized_orthogonal_packing_experiment()
    for name, vals in q["curves"].items():
        row = " ".join(f"{v:.3e}" for v in vals)
        print(f"  {name:18s}: {row}")
    print(f"Exact integer kernel (sparse {{-1, 0, 1}} K_Z): dim={q['sparse_ker_dim']}, max_coeff={q['max_sparse_coeff']}, leak={q['exact_int_leak']}")
    print(f"Siegel growth (dense [-8, 8] M=8, d=16): k=4 max_coeff={q['siegel_max_k4']}, k=10 max_coeff={q['siegel_max_k10']}")


if __name__ == "__main__":
    if "--report" in sys.argv:
        print_report()
    else:
        unittest.main()
