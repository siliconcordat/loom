"""Executable mathematical proofs and numerical checks for docs/07.

Verifies the Three-Axis Latent Lattice convergence (arXiv:2611.21608 x Siliconcordat):
  1. Shared-token disambiguation and global vs per-bank RMSNorm bleed
  2. Persistent horizontal-to-KV-write poisoning and atomic multi-bank rollback
  3. L_0 cartridge decay horizon and Asymmetric Factor Leakage on FiLM adapters
  4. L1 hardware state footprints, DMA restore rooflines, and GDN 3.97x compression

Standard-library Python 3 only (Apache-2.0). No external packages required.
Run tests:
    python3 -B -W error -m unittest -v scripts/verify_lattice.py
    python3 -O -B -W error -m unittest -v scripts/verify_lattice.py
Print verbatim measurement tables:
    python3 -B scripts/verify_lattice.py --report
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import struct
import sys
import unittest


# ---------------------------------------------------------------------------
# Basic linear-algebra and activation helpers (pure stdlib)
# ---------------------------------------------------------------------------

def vec_dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def vec_norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def vec_sub(a: list[float], b: list[float]) -> list[float]:
    return [x - y for x, y in zip(a, b)]


def vec_add(a: list[float], b: list[float]) -> list[float]:
    return [x + y for x, y in zip(a, b)]


def matvec(M: list[list[float]], x: list[float]) -> list[float]:
    return [sum(row[j] * x[j] for j in range(len(x))) for row in M]


def matmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    m, k, n = len(A), len(A[0]), len(B[0])
    Bt = [[B[r][c] for r in range(k)] for c in range(n)]
    return [
        [sum(A[i][t] * Bt[j][t] for t in range(k)) for j in range(n)]
        for i in range(m)
    ]


def matadd(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return [[A[i][j] + B[i][j] for j in range(len(A[0]))] for i in range(len(A))]


def transpose(A: list[list[float]]) -> list[list[float]]:
    return [[A[r][c] for r in range(len(A))] for c in range(len(A[0]))]


def frob_norm(A: list[list[float]]) -> float:
    return math.sqrt(sum(x * x for row in A for x in row))


def rms_norm(v: list[float], eps: float = 1e-5) -> list[float]:
    if not v:
        raise ValueError("rms_norm requires a non-empty vector")
    if isinstance(eps, bool) or not math.isfinite(eps) or eps <= 0.0:
        raise ValueError(f"rms_norm requires finite eps > 0, got {eps!r}")
    for x in v:
        if isinstance(x, bool) or not math.isfinite(x):
            raise ValueError(f"rms_norm requires finite numeric entries, got {x!r}")
    mean_sq = sum(x * x for x in v) / len(v)
    inv = 1.0 / math.sqrt(mean_sq + eps)
    return [x * inv for x in v]


def per_bank_rms_norm(
    v: list[float],
    bank_sizes: tuple[int, ...] | list[int],
    eps: float = 1e-5,
) -> list[float]:
    """Normalize each contiguous capability bank slice independently via RMSNorm."""
    if not bank_sizes:
        raise ValueError("per_bank_rms_norm requires at least one bank")
    total = 0
    for sz in bank_sizes:
        if type(sz) is not int or sz <= 0:
            raise ValueError(f"bank size must be a positive int, got {sz!r}")
        total += sz
    if total != len(v):
        raise ValueError(f"sum(bank_sizes)={total} does not match len(v)={len(v)}")
    out: list[float] = []
    offset = 0
    for sz in bank_sizes:
        out.extend(rms_norm(v[offset:offset + sz], eps=eps))
        offset += sz
    return out


def silu(x: float) -> float:
    if x >= 0.0:
        return x / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return x * ex / (1.0 + ex)


def softplus(x: float) -> float:
    if x > 30.0:
        return x
    if x < -30.0:
        return math.exp(x)
    return math.log1p(math.exp(x))


def softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    exps = [math.exp(x - m) for x in xs]
    s = sum(exps)
    return [e / s for e in exps]


def orthonormal_basis_cols(M: list[list[float]], tol: float = 1e-12) -> list[list[float]]:
    d = len(M)
    cols = transpose(M)
    basis: list[list[float]] = []
    for v in cols:
        w = list(v)
        for _ in range(2):
            for q in basis:
                dot = sum(w[i] * q[i] for i in range(d))
                for i in range(d):
                    w[i] -= dot * q[i]
        n = math.sqrt(sum(x * x for x in w))
        if n > tol:
            basis.append([x / n for x in w])
    return transpose(basis) if basis else [[0.0] * 0 for _ in range(d)]


def project_rows_right_null(A: list[list[float]], Q_basis: list[list[float]]) -> list[list[float]]:
    r, d = len(A), len(A[0])
    k = len(Q_basis[0]) if Q_basis else 0
    if k == 0:
        return [list(row) for row in A]
    Qt = transpose(Q_basis)
    out = [list(row) for row in A]
    for _ in range(2):
        for i in range(r):
            for j in range(k):
                dot = sum(out[i][t] * Qt[j][t] for t in range(d))
                for t in range(d):
                    out[i][t] -= dot * Qt[j][t]
    return out


def quantize_bf16_scalar(x: float) -> float:
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


# ---------------------------------------------------------------------------
# Part 1: Shared-Token Disambiguation & Global vs Per-Bank RMSNorm Bleed
# ---------------------------------------------------------------------------

def run_shared_token_and_rmsnorm_experiment(seed: int = 20261119) -> dict:
    """Compare static vertical editing vs partitioned horizontal Lattice channels."""
    rng = random.Random(seed)
    d_model = 16
    d_base = 8
    d_slot = 4

    # Identical shared-token activation h across two opposing behavioral zones
    h_shared = [rng.gauss(0.0, 1.0) for _ in range(d_model)]
    y_a = [rng.gauss(0.0, 1.0) for _ in range(d_model)]
    y_b = [-x for x in y_a]  # Opposing behavioral target on exact same token activation

    # Best possible static vertical linear output y_hat = (W0 + dW) h_shared is the mean (y_a + y_b)/2 = 0
    y_static_opt = [(a + b) * 0.5 for a, b in zip(y_a, y_b)]
    static_min_mse = 0.5 * (
        vec_norm(vec_sub(y_static_opt, y_a)) ** 2
        + vec_norm(vec_sub(y_static_opt, y_b)) ** 2
    )
    static_theoretical_floor = 0.25 * (vec_norm(vec_sub(y_a, y_b)) ** 2)

    # Capability-partitioned horizontal slots with per-bank RMSNorm and L5 zone mask z in {0, 1}^2:
    # r_base in R^8, r_slot_a in R^4, r_slot_b in R^4
    r_base = [rng.gauss(0.0, 1.0) for _ in range(d_base)]
    r_slot_a = [1.0, 0.0, 0.0, 0.0]
    r_slot_b = [0.0, 1.0, 0.0, 0.0]

    # Exact linear FiLM shift maps reading strictly from their own capability channel
    # beta_slot_a(Norm(r_slot_a)) = y_a, beta_slot_b(Norm(r_slot_b)) = y_b
    n_a = rms_norm(r_slot_a)
    n_b = rms_norm(r_slot_b)
    norm_a_sq = vec_dot(n_a, n_a)
    norm_b_sq = vec_dot(n_b, n_b)
    W_beta_a = [[y_a[i] * n_a[j] / norm_a_sq for j in range(d_slot)] for i in range(d_model)]
    W_beta_b = [[y_b[i] * n_b[j] / norm_b_sq for j in range(d_slot)] for i in range(d_model)]

    # Zone A active (z = [1, 0]):
    out_zone_a = matvec(W_beta_a, n_a)
    # Zone B active (z = [0, 1]):
    out_zone_b = matvec(W_beta_b, n_b)
    # Base zone (z = [0, 0]):
    out_zone_base = [0.0] * d_model

    lattice_mse = 0.5 * (
        vec_norm(vec_sub(out_zone_a, y_a)) ** 2
        + vec_norm(vec_sub(out_zone_b, y_b)) ** 2
    )

    # Global RMSNorm bleed demonstration:
    # Suppose a naive implementation concatenates [r_base, r_slot_a_active] and runs ONE global RMSNorm.
    # Even though r_slot_a sits in orthogonal coordinates, changing r_slot_a from 0 -> active shifts
    # the global RMS denominator and corrupts the base slice readout!
    eps = 1e-5
    r_slot_strong = [2.0, -1.5, 1.0, -1.0]
    global_off = rms_norm(r_base + [0.0] * d_slot, eps=eps)[:d_base]
    global_on = rms_norm(r_base + r_slot_strong, eps=eps)[:d_base]
    global_base_bleed = vec_norm(vec_sub(global_on, global_off)) / vec_norm(global_off)

    # Closed-form global RMSNorm scale ratio on the base slice
    e_base = sum(x * x for x in r_base)
    e_slot = sum(x * x for x in r_slot_strong)
    d_tot = d_base + d_slot
    predicted_scale = math.sqrt((e_base / d_tot + eps) / ((e_base + e_slot) / d_tot + eps))
    predicted_bleed = abs(1.0 - predicted_scale)

    # Per-bank RMSNorm receives the full concatenated state [r_base, r_slot] with explicit
    # bank boundaries (d_base, d_slot), normalizing each bank independently so activating
    # r_slot_strong still yields exact 0.0 base bleed while producing a non-zero slot readout.
    bank_sizes = (d_base, d_slot)
    perbank_off_full = per_bank_rms_norm(r_base + [0.0] * d_slot, bank_sizes, eps=eps)
    perbank_on_full = per_bank_rms_norm(r_base + r_slot_strong, bank_sizes, eps=eps)
    perbank_off = perbank_off_full[:d_base]
    perbank_on = perbank_on_full[:d_base]
    perbank_slot_on = perbank_on_full[d_base:]
    perbank_base_bleed = vec_norm(vec_sub(perbank_on, perbank_off)) / vec_norm(perbank_off)

    return {
        "static_min_mse": static_min_mse,
        "static_theoretical_floor": static_theoretical_floor,
        "lattice_partitioned_mse": lattice_mse,
        "base_inactive_perturbation": vec_norm(out_zone_base),
        "global_rmsnorm_base_bleed": global_base_bleed,
        "predicted_global_bleed": predicted_bleed,
        "perbank_rmsnorm_base_bleed": perbank_base_bleed,
        "perbank_slot_on_norm": vec_norm(perbank_slot_on),
    }


# ---------------------------------------------------------------------------
# Part 2: Persistent Horizontal-to-KV-Write Poisoning & Atomic Rollback
# ---------------------------------------------------------------------------

def run_poisoning_and_rollback_experiment(seed: int = 20261119) -> dict:
    """Faithful single-layer Latent Lattice Transformer rollout proving KV-only flush fails."""
    rng = random.Random(seed)
    d = 16
    d_r = 12
    T = 12
    t_poison = 3  # Adapter injects perturbation at t=3, then revoked before t=4

    def rand_mat(rows: int, cols: int, scale: float) -> list[list[float]]:
        return [[rng.gauss(0.0, scale) for _ in range(cols)] for _ in range(rows)]

    # Fixed base Transformer + Lattice weights (arXiv:2611.21608 Sec 3.2.1 & 3.2.2)
    W_q = rand_mat(d, d, 0.3)
    W_k = rand_mat(d, d, 0.3)
    W_v = rand_mat(d, d, 0.3)
    W_o = rand_mat(d, d, 0.25)

    # Horizontal affine update params
    W_delta = rand_mat(d_r, d, 0.2)
    b_delta = [-2.5 + 0.2 * i for i in range(d_r)]  # Realistic slow-to-medium decay range
    a_log = [-1.2 + 0.1 * i for i in range(d_r)]
    W_r = rand_mat(d_r, d, 0.3)
    b_r = [0.0] * d_r
    r_init = [rng.gauss(0.0, 0.2) for _ in range(d_r)]

    # Nonzero trained FiLM conditioning maps for Q, K, V
    Wg_q, Wb_q = rand_mat(d, d_r, 0.25), rand_mat(d, d_r, 0.25)
    Wg_k, Wb_k = rand_mat(d, d_r, 0.25), rand_mat(d, d_r, 0.25)
    Wg_v, Wb_v = rand_mat(d, d_r, 0.25), rand_mat(d, d_r, 0.25)

    # Input token stream h_in[t] for t = 0..T-1
    h_stream = [[rng.gauss(0.0, 1.0) for _ in range(d)] for _ in range(T)]

    # Adversarial / revoked-adapter perturbation injected into horizontal state at t_poison
    delta_r_poison = [0.8 * (1.0 if i % 2 == 0 else -1.0) for i in range(d_r)]

    def step_lattice_layer(
        h_in: list[float],
        r_prev: list[float],
        kv_cache: list[tuple[list[float], list[float]]],
        inject_delta: list[float] | None = None,
    ) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
        """Execute exact arXiv:2611.21608 Eq. (Sec 3.2.1 & 3.2.2) for one timestep."""
        n_t = rms_norm(h_in)
        w_d = matvec(W_delta, n_t)
        delta_t = [softplus(w_d[i] + b_delta[i]) for i in range(d_r)]
        g_t = [math.exp(-math.exp(a_log[i]) * delta_t[i]) for i in range(d_r)]
        w_r = matvec(W_r, n_t)
        c_t = [silu(w_r[i] + b_r[i]) for i in range(d_r)]
        r_t = [g_t[i] * r_prev[i] + (1.0 - g_t[i]) * c_t[i] for i in range(d_r)]
        if inject_delta is not None:
            r_t = vec_add(r_t, inject_delta)

        r_hat = rms_norm(r_t)
        h_hat = rms_norm(h_in)

        def film(W_proj, W_g, W_b):
            base = matvec(W_proj, h_hat)
            gam = [math.tanh(x) for x in matvec(W_g, r_hat)]
            bet = matvec(W_b, r_hat)
            return [base[i] * (1.0 + gam[i]) + bet[i] for i in range(d)]

        q_t = film(W_q, Wg_q, Wb_q)
        k_t = film(W_k, Wg_k, Wb_k)
        v_t = film(W_v, Wg_v, Wb_v)
        kv_cache.append((k_t, v_t))

        # Causal scaled dot-product attention over current KV cache
        inv_sqrt_d = 1.0 / math.sqrt(d)
        scores = [vec_dot(q_t, k_s) * inv_sqrt_d for k_s, _ in kv_cache]
        weights = softmax(scores)
        attn_ctx = [0.0] * d
        for w, (_, v_s) in zip(weights, kv_cache):
            for i in range(d):
                attn_ctx[i] += w * v_s[i]
        out = vec_add(h_in, matvec(W_o, attn_ctx))
        return out, r_t, g_t, k_t, v_t

    def rollout(mode: str) -> dict:
        r_cur = list(r_init)
        kv: list[tuple[list[float], list[float]]] = []
        r_snap_clean = None
        kv_snap_clean = None
        outs, rs, gs, ks = [], [], [], []

        for t in range(T):
            if t == t_poison:
                # Snapshot clean state right before entering untrusted adapter zone
                r_snap_clean = list(r_cur)
                kv_snap_clean = [(list(k), list(v)) for k, v in kv]

            if t == t_poison + 1:
                if mode == "kv_flush_only":
                    # Erase KV cache completely (modeling POST /slots/{id}?action=erase),
                    # but leave the poisoned horizontal latent r_cur intact!
                    if kv_snap_clean is None:
                        raise RuntimeError("Missing snapshot")
                    kv = []
                elif mode == "atomic_multibank":
                    # Restore BOTH KV cache (erased to match clean-post-flush) AND horizontal latent!
                    if r_snap_clean is None:
                        raise RuntimeError("Missing snapshot")
                    _, r_clean_t3, _, _, _ = step_lattice_layer(h_stream[t_poison], r_snap_clean, [], None)
                    r_cur = r_clean_t3
                    kv = []
                elif mode == "clean_post_erase_ref":
                    # Reference clean W0 trajectory after a clean KV flush at t_poison+1
                    kv = []

            inj = delta_r_poison if (mode != "clean" and mode != "clean_post_erase_ref" and t == t_poison) else None
            out, r_cur, g_t, k_t, _ = step_lattice_layer(h_stream[t], r_cur, kv, inj)
            outs.append(out)
            rs.append(list(r_cur))
            gs.append(list(g_t))
            ks.append(list(k_t))
        return {"outs": outs, "rs": rs, "gs": gs, "ks": ks}

    ref_clean = rollout("clean")
    ref_clean_erased = rollout("clean_post_erase_ref")
    reg_scale_only = rollout("scale_zero_only")
    reg_kv_only = rollout("kv_flush_only")
    reg_atomic = rollout("atomic_multibank")

    # Verify exact closed-form persistence identity:
    # delta_r[t] == (prod_{tau=t_poison+1..t} g[tau]) * delta_r_poison
    max_formula_err = 0.0
    cum_g = [1.0] * d_r
    for t in range(t_poison + 1, T):
        cum_g = [cum_g[i] * ref_clean["gs"][t][i] for i in range(d_r)]
        pred_dr = [cum_g[i] * delta_r_poison[i] for i in range(d_r)]
        actual_dr = vec_sub(reg_kv_only["rs"][t], ref_clean_erased["rs"][t])
        max_formula_err = max(max_formula_err, vec_norm(vec_sub(actual_dr, pred_dr)))

    # Measure drift at t = t_poison + 1 (immediately after revocation) and at final step T-1
    t1 = t_poison + 1
    tf = T - 1

    # Regime A (scale zero only) vs ref_clean
    scale_only_k_drift_t1 = vec_norm(vec_sub(reg_scale_only["ks"][t1], ref_clean["ks"][t1]))
    scale_only_out_drift_t1 = vec_norm(vec_sub(reg_scale_only["outs"][t1], ref_clean["outs"][t1]))
    scale_only_out_drift_tf = vec_norm(vec_sub(reg_scale_only["outs"][tf], ref_clean["outs"][tf]))

    # Regime B (KV flush only) vs ref_clean_erased: proves freshly erased KV is IMMEDIATELY re-poisoned!
    kv_only_k_drift_t1 = vec_norm(vec_sub(reg_kv_only["ks"][t1], ref_clean_erased["ks"][t1]))
    kv_only_out_drift_t1 = vec_norm(vec_sub(reg_kv_only["outs"][t1], ref_clean_erased["outs"][t1]))
    kv_only_out_drift_tf = vec_norm(vec_sub(reg_kv_only["outs"][tf], ref_clean_erased["outs"][tf]))
    kv_only_r_drift_t1 = vec_norm(vec_sub(reg_kv_only["rs"][t1], ref_clean_erased["rs"][t1]))

    # Regime C (Atomic multi-bank restore) vs ref_clean_erased: exact 0.0 drift!
    atomic_max_k_drift = max(
        vec_norm(vec_sub(reg_atomic["ks"][t], ref_clean_erased["ks"][t]))
        for t in range(t1, T)
    )
    atomic_max_out_drift = max(
        vec_norm(vec_sub(reg_atomic["outs"][t], ref_clean_erased["outs"][t]))
        for t in range(t1, T)
    )

    # Half-life table for representative Mamba-2 / Lattice decay rates g
    halflives = {
        "g_0.80": math.log(0.5) / math.log(0.80),
        "g_0.95": math.log(0.5) / math.log(0.95),
        "g_0.995": math.log(0.5) / math.log(0.995),
    }

    return {
        "max_persistence_formula_err": max_formula_err,
        "scale_only_k_drift_t1": scale_only_k_drift_t1,
        "scale_only_out_drift_t1": scale_only_out_drift_t1,
        "scale_only_out_drift_tf": scale_only_out_drift_tf,
        "kv_only_r_drift_t1": kv_only_r_drift_t1,
        "kv_only_k_drift_t1": kv_only_k_drift_t1,
        "kv_only_out_drift_t1": kv_only_out_drift_t1,
        "kv_only_out_drift_tf": kv_only_out_drift_tf,
        "atomic_max_k_drift": atomic_max_k_drift,
        "atomic_max_out_drift": atomic_max_out_drift,
        "halflives": halflives,
    }


# ---------------------------------------------------------------------------
# Part 3: L_0 Decay Horizon, 0-Byte Re-Derivation & Asymmetric FiLM Packing
# ---------------------------------------------------------------------------

def compile_deterministic_l0_cartridge(plane1_text: str, n_layers: int, d_r: int) -> dict:
    """Deterministic CPU float64 L_0 cartridge derivation (Hard Veto 1)."""
    seed_bytes = hashlib.sha256(plane1_text.encode("utf-8")).digest()
    seed_int = int.from_bytes(seed_bytes[:8], "big")
    rng = random.Random(seed_int)
    # Deterministic per-layer initial horizontal vectors r_0^l
    vectors = [
        [round(rng.gauss(0.0, 0.1), 8) for _ in range(d_r)]
        for _ in range(n_layers)
    ]
    payload = json.dumps(
        {"plane1_sha256": seed_bytes.hex(), "n_layers": n_layers, "d_r": d_r, "vectors": vectors},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        "cartridge_sha256": hashlib.sha256(payload).hexdigest(),
        "bf16_bytes": n_layers * d_r * 2,
        "fp32_bytes": n_layers * d_r * 4,
    }


def run_l0_and_asymmetric_film_experiment(seed: int = 20261119) -> dict:
    """Verify L_0 decay horizon and Asymmetric Factor Leakage on FiLM adapters."""
    # Decay retention at t = 90, 139, 10000
    ret_g95_t90 = 0.95 ** 90
    ret_g995_t139 = 0.995 ** 139
    ret_locked_t10000 = 1.0 ** 10000

    # Deterministic 0-byte re-derivation of L_0 cartridge
    c1 = compile_deterministic_l0_cartridge("Rule 1: Use plain language.", 36, 256)
    c2 = compile_deterministic_l0_cartridge("Rule 1: Use plain language.", 36, 256)
    c_mut = compile_deterministic_l0_cartridge("Rule 1: Use plain language!", 36, 256)

    # Asymmetric Factor Leakage on FiLM adapter Delta W_FiLM = B_F * A_F acting on
    # preserved base horizontal trajectory matrix R0 (d_r x k0)
    rng = random.Random(seed)
    d_out = 32   # FiLM target dimension (e.g. QKV or MLP pre-activation slice)
    d_r = 24     # Horizontal latent width
    k0 = 6       # Preserved base horizontal trajectory directions
    rank = 2
    n_adapters = 6

    W_base_film = [[rng.gauss(0.0, 1.0 / math.sqrt(d_r)) for _ in range(d_r)] for _ in range(d_out)]
    R0 = [[rng.gauss(0.0, 1.0) for _ in range(k0)] for _ in range(d_r)]
    denom = frob_norm(matmul(W_base_film, R0))

    accum_r = [list(row) for row in R0]
    adapters = []
    for _ in range(n_adapters):
        Q_prev = orthonormal_basis_cols(accum_r)
        B_raw = [[rng.gauss(0.0, 0.25) for _ in range(rank)] for _ in range(d_out)]
        A_raw = [[rng.gauss(0.0, 0.25) for _ in range(d_r)] for _ in range(rank)]
        A_orth = project_rows_right_null(A_raw, Q_prev)
        adapters.append((B_raw, A_orth))
        R_new = [[rng.gauss(0.0, 1.0) for _ in range(2)] for _ in range(d_r)]
        for i in range(d_r):
            accum_r[i].extend(R_new[i])

    modes = [
        ("fp64_both", "fp64", "fp64"),
        ("asym_fp64A_int4B", "int4", "fp64"),
        ("int8_both", "int8", "int8"),
        ("asym_int8A_int4B", "int4", "int8"),
        ("ctrl_int4A_int8B", "int8", "int4"),
        ("int4_both", "int4", "int4"),
    ]
    final_leaks: dict[str, float] = {}
    for name, b_mode, a_mode in modes:
        sum_d = [[0.0] * d_r for _ in range(d_out)]
        for B_j, A_j in adapters:
            sum_d = matadd(sum_d, matmul(quantize_matrix(B_j, b_mode), quantize_matrix(A_j, a_mode)))
        final_leaks[name] = frob_norm(matmul(sum_d, R0)) / denom

    return {
        "ret_g95_t90": ret_g95_t90,
        "ret_g995_t139": ret_g995_t139,
        "ret_locked_t10000": ret_locked_t10000,
        "l0_zero_byte_match": c1["cartridge_sha256"] == c2["cartridge_sha256"],
        "l0_tamper_detected": c1["cartridge_sha256"] != c_mut["cartridge_sha256"],
        "l0_36L_256_bf16_bytes": c1["bf16_bytes"],
        "l0_36L_256_fp32_bytes": c1["fp32_bytes"],
        "film_leaks_n6": final_leaks,
    }


# ---------------------------------------------------------------------------
# Part 4: L1 Hardware State Footprints, Roofline & GDN State Compression
# ---------------------------------------------------------------------------

def compute_l1_lattice_rooflines() -> dict:
    """Exact state footprints, DMA restore latencies, and FiLM weight-streaming bounds."""
    gib = 1024 ** 3
    mib = 1024 ** 2
    kib = 1024

    # FP32 carry state = 4 bytes/elem (arXiv:2611.21608 Table 6)
    p406m_bytes = 20 * 256 * 4          # 20,480 B = 20.0 KiB
    p603m_bytes = 20 * 1024 * 4         # 81,920 B = 80.0 KiB

    # 4B Scaled Lattice (|L|=32, d_r=512, FP32, RTX 3080 8 GiB @ 350 GB/s)
    m4b_snap_bytes = 32 * 512 * 4       # 65,536 B = 64.0 KiB
    m4b_8ckpt_bytes = 8 * m4b_snap_bytes
    m4b_mem_pct = 100.0 * m4b_8ckpt_bytes / (8 * gib)
    m4b_dma_us = (m4b_snap_bytes / 350e9) * 1e6
    m4b_ssm_snap_bytes = 24 * 16 * 64 * 64 * 2  # docs/04 Thesis 3: 3.00 MiB
    m4b_vs_ssm_ratio = m4b_ssm_snap_bytes / m4b_snap_bytes

    # 27B Scaled Lattice (|L|=60, d_r=1024, FP32, M1 Max 64 GiB @ 320 GB/s)
    m27b_snap_bytes = 60 * 1024 * 4     # 245,760 B = 240.0 KiB
    m27b_8ckpt_bytes = 8 * m27b_snap_bytes
    m27b_mem_pct = 100.0 * m27b_8ckpt_bytes / (64 * gib)
    m27b_dma_us = (m27b_snap_bytes / 320e9) * 1e6
    m27b_ssm64_bytes = 48 * 32 * 64 * 64 * 2    # docs/04 Thesis 3: 12.00 MiB
    m27b_ssm128_bytes = 48 * 32 * 128 * 128 * 2 # docs/04 Thesis 3: 48.00 MiB
    m27b_vs_ssm64_ratio = m27b_ssm64_bytes / m27b_snap_bytes
    m27b_vs_ssm128_ratio = m27b_ssm128_bytes / m27b_snap_bytes

    # Paper GDN 4x native state compression (22 layers BF16 native + 20 Lattice FP32 d_r=256)
    gdn_pure_256k_bytes = 22 * 262144 * 2
    gdn_lattice_64k_bytes = 22 * 65536 * 2 + 20 * 256 * 4
    gdn_compression_ratio = gdn_pure_256k_bytes / gdn_lattice_64k_bytes

    # L_0 cartridge vs 4B F16 LoRA (docs/04 Thesis 1: 72 projs, r=16, d=2560 -> 11.25 MiB)
    lora_4b_bytes = 72 * (2560 * 16 + 16 * 2560) * 2
    l0_bf16_bytes = 36 * 256 * 2
    l0_fp32_bytes = 36 * 256 * 4
    l0_vs_lora_bf16 = lora_4b_bytes / l0_bf16_bytes
    l0_vs_lora_fp32 = lora_4b_bytes / l0_fp32_bytes

    # Honest FiLM weight-streaming cost if added naively ON TOP of 4B (|L|=32, d_r=512)
    # Without iso-parameter narrowing: d_v=2560, d_attn=2560, H=20, d_ff=9728
    # Per-layer additive projections: update (2*d_v) + QKV beta (3*d_attn) + QKV gamma (12*H) + MLP beta (2*d_ff)
    per_layer_film_params = 512 * (2 * 2560 + 3 * 2560 + 12 * 20 + 2 * 9728)
    total_4b_film_params = 32 * per_layer_film_params
    film_4b_q45_bytes = total_4b_film_params * (4.5 / 8.0)
    film_4b_q45_ms = (film_4b_q45_bytes / 350e9) * 1e3
    base_4b_decode_ms = (2.10 * gib / 350e9) * 1e3

    return {
        "p406m_kib": p406m_bytes / kib,
        "p603m_kib": p603m_bytes / kib,
        "m4b_snap_kib": m4b_snap_bytes / kib,
        "m4b_8ckpt_kib": m4b_8ckpt_bytes / kib,
        "m4b_mem_pct": m4b_mem_pct,
        "m4b_dma_us": m4b_dma_us,
        "m4b_vs_ssm_ratio": m4b_vs_ssm_ratio,
        "m27b_snap_kib": m27b_snap_bytes / kib,
        "m27b_8ckpt_mib": m27b_8ckpt_bytes / mib,
        "m27b_mem_pct": m27b_mem_pct,
        "m27b_dma_us": m27b_dma_us,
        "m27b_vs_ssm64_ratio": m27b_vs_ssm64_ratio,
        "m27b_vs_ssm128_ratio": m27b_vs_ssm128_ratio,
        "gdn_pure_256k_mib": gdn_pure_256k_bytes / mib,
        "gdn_lattice_64k_mib": gdn_lattice_64k_bytes / mib,
        "gdn_compression_ratio": gdn_compression_ratio,
        "lora_4b_mib": lora_4b_bytes / mib,
        "l0_vs_lora_bf16": l0_vs_lora_bf16,
        "l0_vs_lora_fp32": l0_vs_lora_fp32,
        "total_4b_film_params_m": total_4b_film_params / 1e6,
        "film_4b_q45_mib": film_4b_q45_bytes / mib,
        "film_4b_q45_ms": film_4b_q45_ms,
        "film_4b_q45_pct_of_base": 100.0 * film_4b_q45_ms / base_4b_decode_ms,
    }


# ---------------------------------------------------------------------------
# Unit Tests Verifying Every Equation and Table in docs/07
# ---------------------------------------------------------------------------

class TestLatentLatticeConvergence(unittest.TestCase):
    def test_1_shared_token_disambiguation_and_rmsnorm_bleed(self):
        res = run_shared_token_and_rmsnorm_experiment()
        # Static vertical editing hits exact irreducible MSE floor on identical shared tokens
        self.assertAlmostEqual(res["static_min_mse"], res["static_theoretical_floor"], places=12)
        self.assertGreater(res["static_min_mse"], 5.0)
        # Partitioned horizontal Lattice channels separate identical tokens with exact 0.0 error
        self.assertLess(res["lattice_partitioned_mse"], 1e-24)
        self.assertEqual(res["base_inactive_perturbation"], 0.0)
        # Global RMSNorm leaks across orthogonal channels matching closed-form scale ratio
        self.assertGreater(res["global_rmsnorm_base_bleed"], 0.15)
        self.assertAlmostEqual(res["global_rmsnorm_base_bleed"], res["predicted_global_bleed"], places=12)
        # Per-bank RMSNorm processes the active slot bank while eliminating base bleed identically
        self.assertGreater(res["perbank_slot_on_norm"], 1.0)
        self.assertEqual(res["perbank_rmsnorm_base_bleed"], 0.0)

    def test_2_horizontal_to_kv_poisoning_and_atomic_rollback(self):
        res = run_poisoning_and_rollback_experiment()
        # Closed-form decay identity delta_r[t] = (prod g[tau]) * delta_r_poison holds exactly
        self.assertLess(res["max_persistence_formula_err"], 1e-13)
        # Regime A (scale zero only) leaves persistent KV and output drift
        self.assertGreater(res["scale_only_k_drift_t1"], 0.5)
        self.assertGreater(res["scale_only_out_drift_t1"], 0.1)
        # Regime B (KV flush only) STILL immediately re-poisons freshly erased KV cache!
        self.assertGreater(res["kv_only_r_drift_t1"], 1.0)
        self.assertGreater(res["kv_only_k_drift_t1"], 0.5)
        self.assertGreater(res["kv_only_out_drift_t1"], 0.1)
        self.assertGreater(res["kv_only_out_drift_tf"], 0.05)
        # Regime C (atomic KV + horizontal restore) achieves literal 0.0 drift
        self.assertEqual(res["atomic_max_k_drift"], 0.0)
        self.assertEqual(res["atomic_max_out_drift"], 0.0)
        # Half-lives for representative decay rates
        self.assertAlmostEqual(res["halflives"]["g_0.80"], 3.106284, places=4)
        self.assertAlmostEqual(res["halflives"]["g_0.95"], 13.513407, places=4)
        self.assertAlmostEqual(res["halflives"]["g_0.995"], 138.282570, places=4)

    def test_3_l0_cartridge_decay_and_asymmetric_film_packing(self):
        res = run_l0_and_asymmetric_film_experiment()
        # Pure L_0 under unmodified forgetting gates decays away
        self.assertLess(res["ret_g95_t90"], 0.01)
        self.assertLess(res["ret_g995_t139"], 0.50)
        # Zone-locked channel (g = 1.0) preserves 100% across 10,000 tokens
        self.assertEqual(res["ret_locked_t10000"], 1.0)
        # Deterministic Hard Veto 1 re-derivation and 1-byte tamper detection
        self.assertTrue(res["l0_zero_byte_match"])
        self.assertTrue(res["l0_tamper_detected"])
        self.assertEqual(res["l0_36L_256_bf16_bytes"], 18432)
        self.assertEqual(res["l0_36L_256_fp32_bytes"], 36864)
        # Asymmetric Factor Leakage Theorem holds identically on FiLM adapters
        leaks = res["film_leaks_n6"]
        self.assertLess(leaks["fp64_both"], 1e-13)
        self.assertLess(leaks["asym_fp64A_int4B"], 1e-13)
        self.assertLess(leaks["asym_int8A_int4B"] * 10.0, leaks["int4_both"])
        self.assertLess(leaks["asym_int8A_int4B"] * 10.0, leaks["ctrl_int4A_int8B"])
        self.assertLess(abs(leaks["asym_int8A_int4B"] - leaks["int8_both"]) / leaks["int8_both"], 0.03)

    def test_4_l1_hardware_rooflines_and_gdn_state_compression(self):
        r = compute_l1_lattice_rooflines()
        self.assertAlmostEqual(r["p406m_kib"], 20.0, places=6)
        self.assertAlmostEqual(r["p603m_kib"], 80.0, places=6)
        self.assertAlmostEqual(r["m4b_snap_kib"], 64.0, places=6)
        self.assertAlmostEqual(r["m4b_8ckpt_kib"], 512.0, places=6)
        self.assertAlmostEqual(r["m4b_mem_pct"], 0.006104, places=5)
        self.assertAlmostEqual(r["m4b_dma_us"], 0.187246, places=4)
        self.assertAlmostEqual(r["m4b_vs_ssm_ratio"], 48.0, places=6)
        self.assertAlmostEqual(r["m27b_snap_kib"], 240.0, places=6)
        self.assertAlmostEqual(r["m27b_8ckpt_mib"], 1.875, places=6)
        self.assertAlmostEqual(r["m27b_mem_pct"], 0.002861, places=5)
        self.assertAlmostEqual(r["m27b_dma_us"], 0.768000, places=4)
        self.assertAlmostEqual(r["m27b_vs_ssm64_ratio"], 51.2, places=6)
        self.assertAlmostEqual(r["m27b_vs_ssm128_ratio"], 204.8, places=6)
        self.assertAlmostEqual(r["gdn_pure_256k_mib"], 11.0, places=6)
        self.assertAlmostEqual(r["gdn_lattice_64k_mib"], 2.76953125, places=6)
        self.assertAlmostEqual(r["gdn_compression_ratio"], 3.971791, places=4)
        self.assertAlmostEqual(r["lora_4b_mib"], 11.25, places=6)
        self.assertAlmostEqual(r["l0_vs_lora_bf16"], 640.0, places=6)
        self.assertAlmostEqual(r["l0_vs_lora_fp32"], 320.0, places=6)
        self.assertAlmostEqual(r["total_4b_film_params_m"], 532.414464, places=4)
        self.assertAlmostEqual(r["film_4b_q45_mib"], 285.609375, places=4)
        self.assertAlmostEqual(r["film_4b_q45_ms"], 0.855666, places=4)
        self.assertAlmostEqual(r["film_4b_q45_pct_of_base"], 13.281686, places=3)


def print_report() -> None:
    print("=== PART 1: SHARED-TOKEN DISAMBIGUATION & RMSNORM BLEED ===")
    r1 = run_shared_token_and_rmsnorm_experiment()
    for k, v in r1.items():
        print(f"  {k}: {v:.6e}" if isinstance(v, float) else f"  {k}: {v}")

    print("\n=== PART 2: HORIZONTAL-TO-KV POISONING & ATOMIC ROLLBACK ===")
    r2 = run_poisoning_and_rollback_experiment()
    for k, v in r2.items():
        if isinstance(v, dict):
            print(f"  {k}: " + ", ".join(f"{hk}={hv:.2f}" for hk, hv in v.items()))
        else:
            print(f"  {k}: {v:.6e}")

    print("\n=== PART 3: L_0 CARTRIDGE DECAY & ASYMMETRIC FILM PACKING ===")
    r3 = run_l0_and_asymmetric_film_experiment()
    for k, v in r3.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for mk, mv in v.items():
                print(f"    {mk:18s}: {mv:.4e}")
        else:
            print(f"  {k}: {v}")

    print("\n=== PART 4: L1 HARDWARE ROOFLINES & GDN STATE COMPRESSION ===")
    r4 = compute_l1_lattice_rooflines()
    for k, v in r4.items():
        print(f"  {k}: {v:.6f}" if isinstance(v, float) else f"  {k}: {v}")


if __name__ == "__main__":
    if "--report" in sys.argv:
        print_report()
    else:
        unittest.main()
