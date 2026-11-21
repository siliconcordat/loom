"""Executable checks for docs/10 (exact inertia certificates).

Covers:
  1. The checker (scripts/inertia_cert.py) against an independent inertia method on random exact
     Hermitian matrices.
  2. Must-fail controls. Each tampers one thing in a good certificate. For each guard, a copy of the
     checker with that guard removed must accept the control, which shows the control isolates it.
  3. Exact tests of the rank bounds (A), (B), the family, and its best member, with exact ranks,
     plus tight examples.
  4. The two-bar truss matrices as embedded rational data.
  5. A small synthetic adapter with exact binary fractions, the spectral-bound equivalence, and a
     forged weight matrix rejected by a loader that recomputes the matrix.
  6. The sharp rank bound R_opt: fresh random exact matrices against the family and against the
     true count of the compression, explicit exact witnesses of sharpness, and null controls.
  7. Margin certificates (scripts/margin_cert.py): floors, perturbations, one must-fail control per
     check, and a guard-removal mutant for every guard of that file.

The producer below is untrusted: the checker re-verifies everything it emits. The independent
method shares no code with the checker or the producer.

Standard-library Python 3 only (Apache-2.0). No network. Run tests:
    python3 -B -W error -m unittest -v scripts/verify_inertia.py
    python3 -O -B -W error -m unittest -v scripts/verify_inertia.py
Print the timing table quoted in docs/10:
    python3 -B scripts/verify_inertia.py --report
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER_PATH = os.path.join(HERE, "inertia_cert.py")
MARGIN_PATH = os.path.join(HERE, "margin_cert.py")

# Random-trial counts. An earlier, slower run of this logic used 2,000 matrices and 5,000 bound instances.
# Each bound instance is tested against (A), (B), seven family members and the best member.
N_PROPERTY = 1000
N_BOUNDS = 2000
# Counts for the sharp rank bound R_opt and the margin certificates (docs/10, sections 3.7 and 2.4).
# Seeds are fixed here and repeated in every failure message, so a run can be replayed.
N_ROPT = 600
SEED_ROPT = 20261201
N_MARGIN = 300
SEED_MARGIN = 20261202
SEED_MARGIN_E = 20261203
STATS = {}  # counts gathered by the tests, printed by "--stats"


def load_checker(path=CHECKER_PATH, name="inertia_cert_under_test"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ic = load_checker()
with open(CHECKER_PATH, encoding="utf-8") as _fh:
    SRC = _fh.read()

Z = (F(0), F(0))


# ---------------------------------------------------------------------------
# Untrusted producer: exact Bunch-Kaufman LDL* over Q(i)
# ---------------------------------------------------------------------------

ALPHA2 = F(5, 8) ** 2


def cadd(a, b):
    return (a[0] + b[0], a[1] + b[1])


def csub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def cmul(a, b):
    return (a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0])


def cconj(a):
    return (a[0], -a[1])


def cscale(a, s):
    return (a[0] * s, a[1] * s)


def m2(a):
    return a[0] * a[0] + a[1] * a[1]


def to_c(x):
    return (F(x[0]), F(x[1])) if isinstance(x, (tuple, list)) else (F(x), F(0))


def fmt(c):
    f = lambda x: "%d/%d" % (x.numerator, x.denominator)
    return f(c[0]) if c[1] == 0 else [f(c[0]), f(c[1])]


def swap(A, L, perm, k, r, done):
    if k == r:
        return
    A[k], A[r] = A[r], A[k]
    for row in A:
        row[k], row[r] = row[r], row[k]
    for c in range(done):
        L[k][c], L[r][c] = L[r][c], L[k][c]
    perm[k], perm[r] = perm[r], perm[k]


def factor(M):
    """M is n by n Hermitian with entries Fraction, int or (re, im). Returns (perm, L, D)."""
    n = len(M)
    A = [[to_c(x) for x in row] for row in M]
    perm = list(range(n))
    L = [[(F(1), F(0)) if i == j else Z for j in range(n)] for i in range(n)]
    D = [[Z] * n for _ in range(n)]
    k = 0
    while k < n:
        lam, r = F(0), k
        for i in range(k + 1, n):
            if m2(A[i][k]) > lam:
                lam, r = m2(A[i][k]), i
        size = 1
        if lam == 0 or m2(A[k][k]) >= ALPHA2 * lam:
            pass
        else:
            sig = max([m2(A[i][r]) for i in range(k, n) if i != r])
            if m2(A[k][k]) * sig >= ALPHA2 * lam * lam:
                pass
            elif m2(A[r][r]) >= ALPHA2 * sig:
                swap(A, L, perm, k, r, k)
            else:
                swap(A, L, perm, k + 1, r, k)
                size = 2
        if size == 1:
            d = A[k][k][0]
            D[k][k] = (d, F(0))
            if d != 0:
                for i in range(k + 1, n):
                    L[i][k] = cscale(A[i][k], 1 / d)
                    for j in range(k + 1, n):
                        A[i][j] = csub(A[i][j], cscale(cmul(A[i][k], cconj(A[j][k])), 1 / d))
        else:
            a, b, c = A[k][k][0], A[k + 1][k], A[k + 1][k + 1][0]
            det = a * c - m2(b)
            inv = [[(c / det, F(0)), cscale(cconj(b), -1 / det)],
                   [cscale(b, -1 / det), (a / det, F(0))]]
            D[k][k], D[k + 1][k], D[k][k + 1], D[k + 1][k + 1] = (a, F(0)), b, cconj(b), (c, F(0))
            for i in range(k + 2, n):
                x = [A[i][k], A[i][k + 1]]
                for col in range(2):
                    L[i][k + col] = cadd(cmul(x[0], inv[0][col]), cmul(x[1], inv[1][col]))
            for i in range(k + 2, n):
                for j in range(k + 2, n):
                    t = Z
                    for p in range(2):
                        for q in range(2):
                            t = cadd(t, cmul(cmul(L[i][k + p], D[k + p][k + q]), cconj(L[j][k + q])))
                    A[i][j] = csub(A[i][j], t)
        k += size
    return perm, L, D


def certify(M):
    perm, L, D = factor(M)
    return {"M": [[fmt(to_c(x)) for x in row] for row in M], "P": perm,
            "L": [[fmt(x) for x in row] for row in L], "D": [[fmt(x) for x in row] for row in D]}


def certified_inertia(M):
    """Produce a certificate, then let the checker decide. Returns the checker's inertia."""
    return ic.check(json.dumps(certify(M)))


# ---------------------------------------------------------------------------
# Independent inertia: exact characteristic polynomial and Descartes' rule of signs
# ---------------------------------------------------------------------------

def charpoly(A):
    """Faddeev-LeVerrier over Q. Coefficients of x^n + c1 x^(n-1) + ... + cn."""
    n = len(A)
    Mk = [[F(0)] * n for _ in range(n)]
    c = [F(1)]
    for k in range(1, n + 1):
        Mk = [[sum(A[i][t] * Mk[t][j] for t in range(n)) + (c[-1] if i == j else 0)
               for j in range(n)] for i in range(n)]
        tr = sum(A[i][t] * Mk[t][i] for i in range(n) for t in range(n))
        c.append(-tr / k)
    return c


def sign_changes(c):
    s = [x for x in c if x != 0]
    return sum(1 for a, b in zip(s, s[1:]) if (a > 0) != (b > 0))


def real_embedding(H):
    """Hermitian n by n with entries (re, im) to real symmetric 2n by 2n. Each eigenvalue doubles."""
    n = len(H)
    R = [[F(0)] * (2 * n) for _ in range(2 * n)]
    for i in range(n):
        for j in range(n):
            re, im = H[i][j]
            R[i][j] = R[n + i][n + j] = re
            R[i][n + j] = -im
            R[n + i][j] = im
    return R


def indep_inertia(H, complex_entries):
    """H has entries (re, im). All roots are real, so positive roots = sign changes."""
    A = real_embedding(H) if complex_entries else [[x[0] for x in row] for row in H]
    n = len(A)
    c = charpoly(A)
    zero = 0
    while c and c[-1] == 0:
        c.pop()
        zero += 1
    pos = sign_changes(c)
    neg = sign_changes([x * (-1) ** (len(c) - 1 - i) for i, x in enumerate(c)])
    if complex_entries:
        if pos % 2 or neg % 2 or zero % 2:
            raise ValueError("independent method: embedding counts not even")
        pos, neg, zero = pos // 2, neg // 2, zero // 2
    if pos + neg + zero != (n // 2 if complex_entries else n):
        raise ValueError("independent method inconsistent")
    return pos, neg, zero


# ---------------------------------------------------------------------------
# Exact complex helpers for the bound tests
# ---------------------------------------------------------------------------

def rnd(rng):
    return F(rng.randint(-6, 6), rng.choice([1, 1, 2, 3, 4, 5]))


def zero_matrix(n):
    return [[Z] * n for _ in range(n)]


def herm_rank1(v, w):
    """w * v v*, entries (re, im)."""
    n = len(v)
    return [[(w * (v[i][0] * v[j][0] + v[i][1] * v[j][1]),
              w * (v[i][1] * v[j][0] - v[i][0] * v[j][1])) for j in range(n)] for i in range(n)]


def addm(A, B, s=1):
    return [[(a[0] + s * b[0], a[1] + s * b[1]) for a, b in zip(ra, rb)] for ra, rb in zip(A, B)]


def scalem(A, s):
    return [[(x[0] * s, x[1] * s) for x in r] for r in A]


def exact_rank(A):
    """Exact rank of a complex matrix: Fraction elimination on the real embedding, halved."""
    n = len(A)
    R = real_embedding(A)
    rk = 0
    for col in range(2 * n):
        piv = next((r for r in range(rk, 2 * n) if R[r][col] != 0), None)
        if piv is None:
            continue
        R[rk], R[piv] = R[piv], R[rk]
        for r in range(rk + 1, 2 * n):
            if R[r][col] != 0:
                f = R[r][col] / R[rk][col]
                R[r] = [x - f * y for x, y in zip(R[r], R[rk])]
        rk += 1
    if rk % 2:
        raise ValueError("embedding rank is odd")
    return rk // 2


def trace(A):
    return sum(A[i][i][0] for i in range(len(A)))


def fro2(A):
    return sum(x[0] * x[0] + x[1] * x[1] for row in A for x in row)


# ---------------------------------------------------------------------------
# Random matrices for the property test
# ---------------------------------------------------------------------------

def gen_matrix(rng, n, kind, cplx):
    def entry():
        return (rnd(rng), rnd(rng) if cplx else F(0))
    if kind == "plain":
        H = [[None] * n for _ in range(n)]
        for i in range(n):
            H[i][i] = (rnd(rng), F(0))
            for j in range(i):
                H[i][j] = entry()
                H[j][i] = (H[i][j][0], -H[i][j][1])
        return H
    if kind == "zerodiag":
        H = gen_matrix(rng, n, "plain", cplx)
        for i in range(n):
            H[i][i] = Z
        return H
    s = rng.randint(0, n)
    H = zero_matrix(n)
    for _ in range(s):
        H = addm(H, herm_rank1([entry() for _ in range(n)], 1 if kind == "psd" else rng.choice([1, -1])))
    return H


# ---------------------------------------------------------------------------
# Controls: a good certificate, tampered one way at a time
# ---------------------------------------------------------------------------

# 4 by 4 complex Hermitian, indefinite, zero diagonal so the producer must use 2 by 2 pivot blocks.
H4 = [[Z, (F(1), F(0)), (F(2), F(1)), Z],
      [(F(1), F(0)), Z, Z, (F(3), F(-1))],
      [(F(2), F(-1)), Z, Z, (F(1), F(0))],
      [Z, (F(3), F(1)), (F(1), F(0)), Z]]
GOOD = certify(H4)
GOOD["claim"] = list(ic.check(json.dumps(GOOD)))
ONE_S, ZERO_S = "1/1", "0/1"

# Overlapping 2 by 2 blocks: D tridiagonal, M = D, true inertia (2,1,0), eigenvalues 1 and 1 +- sqrt 2.
OVERLAP = {"M": [[ONE_S, ONE_S, ZERO_S], [ONE_S, ONE_S, ONE_S], [ZERO_S, ONE_S, ONE_S]], "P": [0, 1, 2],
           "L": [[ONE_S, ZERO_S, ZERO_S], [ZERO_S, ONE_S, ZERO_S], [ZERO_S, ZERO_S, ONE_S]],
           "D": [[ONE_S, ONE_S, ZERO_S], [ONE_S, ONE_S, ONE_S], [ZERO_S, ONE_S, ONE_S]]}

# M = diag(1, -1) with P = [0, 0]: P M P* reads M[0][0] four times, so a certificate for the
# all-ones matrix passes the identity and reports (1,0,1). The true inertia is (1,1,0).
BAD_P = {"M": [[ONE_S, ZERO_S], [ZERO_S, "-1/1"]], "P": [0, 0],
         "L": [[ONE_S, ZERO_S], [ONE_S, ONE_S]], "D": [[ONE_S, ZERO_S], [ZERO_S, ZERO_S]]}

# L = [[1, 1], [1, 1]] has a unit diagonal but a nonzero entry above it, so it is singular. With
# D = I the identity holds for M = [[2, 2], [2, 2]], whose true inertia is (1,0,1), not (2,0,0).
L_UPPER = {"M": [["2/1", "2/1"], ["2/1", "2/1"]], "P": [0, 1],
           "L": [[ONE_S, ONE_S], [ONE_S, ONE_S]], "D": [[ONE_S, ZERO_S], [ZERO_S, ONE_S]]}


def bump(s):
    f = lambda t: "%d/%d" % ((F(t) + 1).numerator, (F(t) + 1).denominator)
    return f(s) if isinstance(s, str) else [f(s[0]), s[1]]


def run(mod, cert, raw=None):
    text = raw if raw is not None else json.dumps(cert)
    try:
        return ("ACCEPT", mod.check(text))
    except ic.CertError as e:
        return ("REJECT", str(e))


def controls():
    v = {}
    c = copy.deepcopy(GOOD); c["L"][3][0] = bump(c["L"][3][0]); v["tamper_L_entry"] = c
    c = copy.deepcopy(GOOD); c["D"][0][0] = bump(c["D"][0][0]); v["tamper_D_entry"] = c
    c = copy.deepcopy(GOOD); c["M"][2][2] = bump(c["M"][2][2]); v["tamper_M_entry"] = c
    c = copy.deepcopy(GOOD)
    c["claim"] = [GOOD["claim"][0] + 1, GOOD["claim"][1] - 1, GOOD["claim"][2]]
    v["wrong_claimed_inertia"] = c
    # Columns 0 and 1 of L doubled and the first D block quartered: P M P* = L D L* still holds
    # exactly, so only the unit-diagonal guard can reject it.
    c = copy.deepcopy(GOOD)
    for r in range(4):
        for k in (0, 1):
            c["L"][r][k] = fmt(cscale(ic.entry(c["L"][r][k]), F(2)))
            if r < 2:
                c["D"][r][k] = fmt(cscale(ic.entry(c["D"][r][k]), F(1, 4)))
    v["non_unit_diagonal"] = c
    c = copy.deepcopy(GOOD); c["M"][0][2] = [c["M"][0][2][0], "5/1"]; v["M_not_hermitian_one_entry"] = c
    c = copy.deepcopy(GOOD); c["P"] = [0, 0, 2, 3]; v["P_not_permutation"] = c
    v["P_repeat_hides_negative_eigenvalue"] = BAD_P
    v["overlapping_D_blocks"] = OVERLAP
    v["L_entry_above_diagonal"] = L_UPPER
    return v


LONG = "1" * 5000  # past Python's default 4300-digit limit for integer strings

RAW = {
    "float_in_json": json.dumps(GOOD).replace('"1/1"', "1.0", 1),
    "decimal_string": json.dumps(GOOD).replace('"1/1"', '"0.5"', 1),
    "duplicate_key": json.dumps(GOOD)[:-1] + ', "P": %s}' % json.dumps(GOOD["P"]),
    "nan_constant": json.dumps(GOOD).replace('"1/1"', "NaN", 1),
    "truncated": json.dumps(GOOD)[:50],
    "zero_denominator": json.dumps(GOOD).replace('"1/1"', '"1/0"', 1),
    "entry_past_digit_limit": json.dumps(GOOD).replace('"1/1"', '"%s/1"' % LONG, 1),
    "json_integer_past_digit_limit": json.dumps(GOOD).replace('"P": [', '"P": [%s, ' % LONG, 1),
}

IDENTITY = "need(lhs == rhs,"
CLAIM = "tuple(cl) == inertia"
UNIT_DIAG = "need(L[i][j] == (ONE if i == j else ZERO)"
L_ZERO_ABOVE = 'if j >= i else True, "L not unit lower triangular")'
PERM = "and sorted(P) == list(range(n))"
OVERLAP_G = 'need(not (D[i + 1][i] != ZERO and D[i + 2][i + 1] != ZERO), "overlapping D blocks")'
HERM_M = 'need(M[i][j] == conj(M[j][i]), "M not Hermitian")'
BLOCK_SIGN = "    if det < 0:\n        return (1, 1, 0)"
DUPES = "object_pairs_hook=no_dupes,"

# control name -> (checker text to remove, replacement). Removing it must make the control ACCEPT.
MUTANTS = {
    "tamper_L_entry": (IDENTITY, "need(True or lhs == rhs,"),
    "tamper_D_entry": (IDENTITY, "need(True or lhs == rhs,"),
    "tamper_M_entry": (IDENTITY, "need(True or lhs == rhs,"),
    "wrong_claimed_inertia": (CLAIM, "True"),
    "non_unit_diagonal": (UNIT_DIAG, "need(L[i][j] == (L[i][j] if i == j else ZERO)"),
    "L_entry_above_diagonal": (L_ZERO_ABOVE, 'if j == i else True, "L not unit lower triangular")'),
    "P_repeat_hides_negative_eigenvalue": (PERM, "and True"),
    "overlapping_D_blocks": (OVERLAP_G, "pass"),
    "duplicate_key": (DUPES, ""),
}


def make_mutant(old, new, name="mutant", src=None, path=None):
    """A copy of a checker with one piece of source replaced. Default: scripts/inertia_cert.py."""
    text = SRC if src is None else src
    if text.count(old) != 1:
        raise ValueError("mutation target not found exactly once: %r" % old)
    mod = type(sys)(name)
    if path is not None:
        mod.__dict__["__file__"] = path
    exec(compile(text.replace(old, new), name, "exec"), mod.__dict__)
    if src is None:
        mod.CertError = ic.CertError  # same class, so run() catches it
    return mod


# ---------------------------------------------------------------------------
# Truss data: the two-bar length box, as embedded rational matrices
# ---------------------------------------------------------------------------
# Pins at (-1, 0) and (1, 0), joint at p, bar i has natural length L_i, energy
# sum (1 / (2 L_i)) (|p - pin_i| - L_i)^2. Each matrix is the Hessian at an equilibrium, after the
# diagonal congruence diag(1, 1/y) that makes an off-line matrix rational.
TRUSS = {
    # name: (L1, L2, equilibrium description, 2 by 2 matrix as ((a, b), (c, d)) of Fractions)
    "corner_0.7_0.9": (F(7, 10), F(9, 10), "on the pin line at x = -1/8",
                       [[F(160, 63), F(0)], [F(0), F(32, 63)]]),
    "corner_0.7_1.5": (F(7, 10), F(3, 2), "off the line at x = -11/25, y = 21/50",
                       [[F(6688, 4375), F(4432, 3675)], [F(4432, 3675), F(29744, 9261)]]),
    "corner_1.3_0.9": (F(13, 10), F(9, 10), "off the line at x = 11/50, y^2 = 126/625",
                       [[F(1345388, 889785), F(-274760, 533871)], [F(-274760, 533871), F(2926000, 1601613)]]),
    "corner_1.3_1.5": (F(13, 10), F(3, 2), "off the line at x = -7/50, y^2 = 594/625",
                       [[F(2972984, 4119375), F(26528, 494325)], [F(26528, 494325), F(44576, 59319)]]),
    "interior_0.9_1.1": (F(9, 10), F(11, 10), "on the pin line at x = -1/10",
                         [[F(200, 99), F(0)], [F(0), F(0)]]),
}
PINS = (F(-1), F(1))


def online_equilibria(L):
    out = []
    for lo, hi, s in ((None, PINS[0], (-1, -1)), (PINS[0], PINS[1], (1, -1)), (PINS[1], None, (1, 1))):
        k = [1 / L[0], 1 / L[1]]
        x = sum(k[i] * (PINS[i] + s[i] * L[i]) for i in range(2)) / sum(k)
        if (lo is None or x > lo) and (hi is None or x < hi):
            out.append(x)
    return out


def online_hessian(x, L):
    kx = sum(1 / L[i] for i in range(2))
    ky = sum((1 / L[i]) * (abs(x - PINS[i]) - L[i]) / abs(x - PINS[i]) for i in range(2))
    return [[kx, F(0)], [F(0), ky]]


def offline_equilibrium(L):
    x = (L[0] ** 2 - L[1] ** 2) / 4
    y2 = L[0] ** 2 - (x + 1) ** 2
    return (x, y2) if y2 > 0 else None


def offline_matrix(x, L):
    dx = [x - PINS[0], x - PINS[1]]
    A = sum(dx[i] ** 2 / L[i] ** 3 for i in range(2))
    B = sum(dx[i] / L[i] ** 3 for i in range(2))
    C = sum(1 / L[i] ** 3 for i in range(2))
    return [[A, B], [B, C]]


def real_to_c(M):
    return [[(F(x), F(0)) for x in row] for row in M]


# ---------------------------------------------------------------------------
# Synthetic adapter: exact binary fractions
# ---------------------------------------------------------------------------

def adapter(seed, dout, r, din, rank=None):
    """B is dout by r and A is r by din with entries k/16. rank < r makes columns of B repeat."""
    rng = random.Random(seed)
    B = [[F(rng.randint(-8, 8), 16) for _ in range(r)] for _ in range(dout)]
    A = [[F(rng.randint(-8, 8), 16) for _ in range(din)] for _ in range(r)]
    if rank is not None:
        for j in range(rank, r):
            for i in range(dout):
                B[i][j] = B[i][j % rank]
    return B, A


def mm(X, Y):
    return [[sum(X[i][k] * Y[k][j] for k in range(len(Y))) for j in range(len(Y[0]))] for i in range(len(X))]


def tr(X):
    return [list(r) for r in zip(*X)]


def q_matrix(B, A, s):
    """Q(s) = s G_B - G_B G_A G_B with G_B = B* B and G_A = A A*."""
    GB, GA = mm(tr(B), B), mm(A, tr(A))
    GBGAGB = mm(mm(GB, GA), GB)
    return [[s * GB[i][j] - GBGAGB[i][j] for j in range(len(GB))] for i in range(len(GB))]


def direct_matrix(B, A, s):
    """s I - (B A)(B A)*, whose positive semidefiniteness is sigma_max(B A)^2 <= s by definition."""
    BA = mm(B, A)
    K = mm(BA, tr(BA))
    return [[(s if i == j else 0) - K[i][j] for j in range(len(K))] for i in range(len(K))]


def fmt_real(M):
    return [[fmt((x, F(0))) for x in r] for r in M]


def make_cert(M):
    cert = certify(M)
    cert["claim"] = list(ic.check(json.dumps(cert)))
    return cert


def loader_accepts(B, A, s, cert_text):
    """Stand-in for a loader. It recomputes Q(s) from the weights it holds, requires the
    certificate's M to equal it, runs the checker, and requires no negative eigenvalue."""
    try:
        c = ic.parse(cert_text)
        if c.get("M") != fmt_real(q_matrix(B, A, s)):
            return False, "certificate matrix is not Q(s) for these weights"
        pos, neg, zero = ic.check(cert_text)
    except ic.CertError as e:
        return False, "checker: %s" % e
    return (neg == 0), "inertia (%d,%d,%d)" % (pos, neg, zero)


def psd_by_cert(B, A, s):
    return make_cert(real_to_c(q_matrix(B, A, s)))["claim"][1] == 0


def psd_direct(B, A, s):
    return indep_inertia(real_to_c(direct_matrix(B, A, s)), False)[1] == 0


# ---------------------------------------------------------------------------
# Rank-bound instances
# ---------------------------------------------------------------------------

def bound_instance(rng):
    n = rng.randint(1, 6)
    cplx = rng.random() < 0.5
    ent = lambda: (rnd(rng) / 2, rnd(rng) / 2 if cplx else F(0))
    P, Q = zero_matrix(n), zero_matrix(n)
    for _ in range(rng.randint(0, n)):
        P = addm(P, herm_rank1([ent() for _ in range(n)], abs(rnd(rng)) + F(1, 4)))
    for _ in range(rng.randint(0, 3)):
        Q = addm(Q, herm_rank1([ent() for _ in range(n)], rng.choice([-1, 1]) * (abs(rnd(rng)) + F(1, 4))))
    if rng.random() < 0.5:  # shrink so eigenvalues land near 1 and 2, where the bounds bind
        s = F(1, rng.randint(2, 6))
        P, Q = scalem(P, s), scalem(Q, s)
    return P, Q


def rhs_A(tp, tq, nn, b):
    return 2 * (tp + tq) - nn - b


def rhs_B(tp, tq, nn, b):
    return 2 * tp + 4 * tq - 4 * b - nn


def rhs_family(c, tp, tq, nn, b):
    return 2 * (tp + tq) - nn + c * tq - (1 + F(c) / 2) ** 2 * b


def rhs_best(tp, tq, nn, b):
    """Best member of the family: (tr Q)^2 / b form when tr Q >= b > 0, else (A)."""
    if b > 0 and tq >= b:
        return 2 * tp + tq * tq / b - nn
    return rhs_A(tp, tq, nn, b)


def e(i, j, n, v=F(1)):
    M = zero_matrix(n)
    M[i][j] = (v, F(0))
    return M


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCheckerProperty(unittest.TestCase):
    def test_certified_inertia_equals_independent_inertia(self):
        rng = random.Random(20261119)
        kinds = ["plain", "zerodiag", "psd", "signed"]
        seen = {}
        for t in range(N_PROPERTY):
            n = rng.randint(1, 7)
            kind = kinds[t % 4]
            cplx = rng.random() < 0.5
            H = gen_matrix(rng, n, kind, cplx)
            want = indep_inertia(H, cplx)
            got = certified_inertia(H)
            self.assertEqual(got, want, "n=%d kind=%s" % (n, kind))
            key = (kind, "singular" if want[2] else "regular", "indef" if want[0] and want[1] else "semidef")
            seen[key] = seen.get(key, 0) + 1
        for need in (("plain", "regular", "indef"), ("signed", "singular", "indef"),
                     ("psd", "singular", "semidef"), ("zerodiag", "regular", "indef")):
            self.assertGreater(seen.get(need, 0), 0, "coverage hole %r" % (need,))

    def test_base_matrix_needs_two_by_two_blocks(self):
        sub = [i for i in range(3) if GOOD["D"][i + 1][i] != ZERO_S]
        self.assertTrue(sub, "base certificate has no 2 by 2 block")
        self.assertEqual(tuple(GOOD["claim"]), indep_inertia(H4, True))
        self.assertEqual(tuple(GOOD["claim"]), (2, 2, 0))


class TestControls(unittest.TestCase):
    def test_good_certificate_accepts(self):
        self.assertEqual(run(ic, GOOD), ("ACCEPT", (2, 2, 0)))

    def test_every_control_is_rejected(self):
        for name, cert in controls().items():
            r = run(ic, cert)
            self.assertEqual(r[0], "REJECT", "%s: %r" % (name, r))

    def test_raw_json_controls_are_rejected(self):
        for name, raw in RAW.items():
            r = run(ic, None, raw)
            self.assertEqual(r[0], "REJECT", "%s: %r" % (name, r))

    def test_each_guard_removed_makes_its_control_accepted(self):
        cs = controls()
        for name, (old, new) in MUTANTS.items():
            r = run(make_mutant(old, new, "mut_" + name), cs[name] if name in cs else None,
                    RAW.get(name))
            self.assertEqual(r[0], "ACCEPT", "control %s is not isolating its guard: %r" % (name, r))

    def test_overlap_guard_carries_soundness(self):
        self.assertEqual(run(ic, OVERLAP)[0], "REJECT")
        m = make_mutant(OVERLAP_G, "pass", "mut_overlap")
        self.assertEqual(run(m, OVERLAP), ("ACCEPT", (2, 0, 1)))
        H = [[(F(x), F(0)) for x in row] for row in [[1, 1, 0], [1, 1, 1], [0, 1, 1]]]
        self.assertEqual(indep_inertia(H, False), (2, 1, 0))

    def test_repeated_index_in_p_gives_wrong_inertia_without_its_guard(self):
        m = make_mutant(PERM, "and True", "mut_perm")
        self.assertEqual(run(m, BAD_P), ("ACCEPT", (1, 0, 1)))
        H = [[(F(1), F(0)), Z], [Z, (F(-1), F(0))]]
        self.assertEqual(indep_inertia(H, False), (1, 1, 0))

    def test_nonzero_entry_above_the_diagonal_of_l_gives_wrong_inertia_without_its_guard(self):
        m = make_mutant(L_ZERO_ABOVE, 'if j == i else True, "L not unit lower triangular")', "mut_upper")
        self.assertEqual(run(m, L_UPPER), ("ACCEPT", (2, 0, 0)))
        H = [[(F(2), F(0))] * 2 for _ in range(2)]
        self.assertEqual(indep_inertia(H, False), (1, 0, 1))

    def test_every_row_of_the_two_by_two_block_table(self):
        # The producer's pivoting only emits 2 by 2 blocks with a negative determinant, so the
        # property test never reaches the other rows. Each block here is sent directly as D = M.
        blocks = {
            "det below zero": ((F(0), F(0)), (F(1), F(0)), (F(0), F(0)), (1, 1, 0)),
            "det above zero, positive trace": ((F(2), F(0)), (F(1), F(0)), (F(2), F(0)), (2, 0, 0)),
            "det above zero, negative trace": ((F(-2), F(0)), (F(1), F(0)), (F(-2), F(0)), (0, 2, 0)),
            "det zero, positive trace": ((F(1), F(0)), (F(1), F(0)), (F(1), F(0)), (1, 0, 1)),
            "det zero, negative trace": ((F(-1), F(0)), (F(1), F(0)), (F(-1), F(0)), (0, 1, 1)),
            "complex, det above zero, negative trace": ((F(-3), F(0)), (F(1), F(1)), (F(-1), F(0)), (0, 2, 0)),
            "complex, det zero, positive trace": ((F(2), F(0)), (F(1), F(1)), (F(1), F(0)), (1, 0, 1)),
        }
        for name, (a, b, c, want) in blocks.items():
            H = [[a, b], [cconj(b), c]]
            text = json.dumps({"M": [[fmt(x) for x in r] for r in H], "P": [0, 1],
                               "L": [[ONE_S, ZERO_S], [ZERO_S, ONE_S]], "D": [[fmt(x) for x in r] for r in H]})
            self.assertEqual(ic.check(text), want, name)
            self.assertEqual(indep_inertia(H, b[1] != 0), want, name)

    def test_block_sign_count_is_checked_against_the_independent_method(self):
        m = make_mutant(BLOCK_SIGN, "    if det < 0:\n        return (2, 0, 0)", "mut_block")
        text = json.dumps({k: GOOD[k] for k in "MPLD"})
        self.assertEqual(ic.check(text), indep_inertia(H4, True))
        self.assertNotEqual(m.check(text), indep_inertia(H4, True))

    def test_hermitian_check_on_m_is_a_second_layer(self):
        c = controls()["M_not_hermitian_one_entry"]
        m = make_mutant(HERM_M, "pass", "mut_herm")
        self.assertEqual(run(m, c)[0], "REJECT")

    def test_checker_restored_after_controls(self):
        self.assertEqual(run(ic, GOOD), ("ACCEPT", (2, 2, 0)))


class TestRankBounds(unittest.TestCase):
    def test_tight_examples(self):
        n = 2
        # (A): P1 = e1 e1*, Q = 0, b = 0.
        P, Q, b = e(0, 0, n), zero_matrix(n), 0
        M = addm(P, Q)
        self.assertEqual(exact_rank(P), 1)
        self.assertEqual(rhs_A(trace(P), trace(Q), fro2(M), b), 1)
        # (B): P1 = e2 e2*, Q = 2 e1 e1*, b = 1.
        P, Q, b = e(1, 1, n), e(0, 0, n, F(2)), 1
        M = addm(P, Q)
        self.assertEqual(exact_rank(P), 1)
        self.assertEqual(rhs_B(trace(P), trace(Q), fro2(M), b), 1)
        # Family member c = 4 and best member: Q = 3 e1 e1*. (B) gives 0, the best member is tight.
        Q = e(0, 0, n, F(3))
        M = addm(P, Q)
        tp, tq, nn = trace(P), trace(Q), fro2(M)
        self.assertEqual(rhs_B(tp, tq, nn, b), 0)
        self.assertEqual(rhs_family(4, tp, tq, nn, b), 1)
        self.assertEqual(rhs_best(tp, tq, nn, b), 1)
        self.assertEqual(exact_rank(P), 1)

    def test_a_b_family_and_best_member_on_random_instances(self):
        rng = random.Random(5000)
        tight = {"A": 0, "B": 0, "best": 0}
        b_stronger = best_beats_b = 0
        for t in range(N_BOUNDS):
            P, Q = bound_instance(rng)
            if t % 3 == 0:  # push Q up so tr Q >= b more often
                Q = scalem(Q, F(rng.randint(1, 5)))
            H = addm(P, Q)
            b = certified_inertia(Q)[0]  # exact count of positive eigenvalues of Q, from a checked certificate
            r = exact_rank(P)
            tp, tq, nn = trace(P), trace(Q), fro2(H)
            a_rhs, b_rhs, g_rhs = rhs_A(tp, tq, nn, b), rhs_B(tp, tq, nn, b), rhs_best(tp, tq, nn, b)
            for name, rhs in (("A", a_rhs), ("B", b_rhs), ("best", g_rhs)):
                self.assertGreaterEqual(r, rhs, "violation of %s at instance %d" % (name, t))
                if r == rhs and (r > 0 or b > 0):
                    tight[name] += 1
            for c in (F(0), F(1, 2), F(1), F(2), F(3), F(7, 2), F(2) * (tq - b) / b if b and tq >= b else F(0)):
                self.assertGreaterEqual(r, rhs_family(c, tp, tq, nn, b), "family c=%s instance %d" % (c, t))
            self.assertGreaterEqual(g_rhs, max(a_rhs, b_rhs))
            b_stronger += b_rhs > a_rhs
            best_beats_b += g_rhs > b_rhs
        self.assertGreater(b_stronger, 0)
        self.assertGreater(best_beats_b, 0)

    def test_differences_between_the_bounds(self):
        rng = random.Random(11)
        for _ in range(100):
            tq, b, tp, nn = (F(rng.randint(1, 40), 4), rng.randint(1, 5), F(rng.randint(0, 30), 4),
                             F(rng.randint(1, 60), 4))
            self.assertEqual(rhs_B(tp, tq, nn, b) - rhs_A(tp, tq, nn, b), 2 * tq - 3 * b)
            if tq >= b:
                self.assertEqual(rhs_best(tp, tq, nn, b) - rhs_B(tp, tq, nn, b), (tq - 2 * b) ** 2 / b)
                self.assertEqual(rhs_best(tp, tq, nn, b) - rhs_A(tp, tq, nn, b), (tq - b) ** 2 / b)

    def test_best_member_is_the_maximum_over_c(self):
        rng = random.Random(3)
        for _ in range(100):
            tq, b = F(rng.randint(4, 60), 4), rng.randint(1, 4)
            if tq < b:
                continue
            best = rhs_family(F(2) * (tq - b) / b, F(0), tq, F(0), b)
            self.assertEqual(best, rhs_best(F(0), tq, F(0), b))
            for c in (F(k, 4) for k in range(0, 80)):
                self.assertLessEqual(rhs_family(c, F(0), tq, F(0), b), best)

    def test_a_violated_rank_would_be_caught(self):
        # Negative control: claim the rank is one less than it is and the comparison must fail.
        P, Q, b = e(1, 1, 2), e(0, 0, 2, F(2)), 1
        H = addm(P, Q)
        self.assertLess(exact_rank(P) - 1, rhs_B(trace(P), trace(Q), fro2(H), b))


class TestTrussBox(unittest.TestCase):
    def label(self, M):
        p, n, z = certified_inertia(real_to_c(M))
        return (p, n, z)

    def test_four_corners_are_positive_definite(self):
        for name in ("corner_0.7_0.9", "corner_0.7_1.5", "corner_1.3_0.9", "corner_1.3_1.5"):
            M = TRUSS[name][3]
            self.assertEqual(self.label(M), (2, 0, 0), name)
            self.assertEqual(indep_inertia(real_to_c(M), False), (2, 0, 0), name)

    def test_interior_point_is_singular(self):
        M = TRUSS["interior_0.9_1.1"][3]
        self.assertEqual(self.label(M), (1, 0, 1))
        self.assertEqual(indep_inertia(real_to_c(M), False), (1, 0, 1))
        L1, L2, _, _ = TRUSS["interior_0.9_1.1"]
        self.assertLess(TRUSS["corner_0.7_0.9"][0], L1)
        self.assertLess(L1, TRUSS["corner_1.3_0.9"][0])
        self.assertLess(TRUSS["corner_0.7_0.9"][1], L2)
        self.assertLess(L2, TRUSS["corner_0.7_1.5"][1])

    def test_embedded_data_matches_the_model(self):
        for name, (L1, L2, _, M) in TRUSS.items():
            L = (L1, L2)
            off = offline_equilibrium(L)
            if name == "corner_0.7_0.9":
                self.assertIsNone(off)
                (x,) = [x for x in online_equilibria(L) if x == F(-1, 8)]
                self.assertEqual(online_hessian(x, L), M)
            elif name == "interior_0.9_1.1":
                self.assertIsNone(off)
                self.assertEqual(online_hessian(F(-1, 10), L), M)
            else:
                self.assertEqual(offline_matrix(off[0], L), M)

    def test_off_line_congruence_keeps_inertia(self):
        # The raw Hessian is [[A, B y], [B y, C y^2]]. Check with y = 1/2 and y = 3 that the
        # exact inertia of the raw form equals that of [[A, B], [B, C]].
        for name in ("corner_0.7_1.5", "corner_1.3_0.9"):
            A, B, C = TRUSS[name][3][0][0], TRUSS[name][3][0][1], TRUSS[name][3][1][1]
            for y in (F(1, 2), F(3)):
                raw = [[A, B * y], [B * y, C * y * y]]
                self.assertEqual(indep_inertia(real_to_c(raw), False), (2, 0, 0))

    def test_affine_family_stays_positive_definite_between_corners(self):
        # Why corners suffice for an affine family: M(t) = (1 - t) M0 + t M1 is a convex
        # combination, and positive definiteness survives convex combinations.
        M0, M1 = TRUSS["corner_0.7_1.5"][3], TRUSS["corner_1.3_0.9"][3]
        for t in (F(1, 4), F(1, 2), F(3, 4)):
            mid = [[(1 - t) * M0[i][j] + t * M1[i][j] for j in range(2)] for i in range(2)]
            self.assertEqual(self.label(mid), (2, 0, 0))

    def test_truss_matrix_is_not_affine_in_the_lengths(self):
        # The interior point is singular while all four corners are positive definite, so the
        # matrix cannot be affine in the lengths. A positive combination of the corner matrices
        # could not be singular.
        L1, L2, _, M = TRUSS["interior_0.9_1.1"]
        self.assertEqual(self.label(M), (1, 0, 1))
        for name in ("corner_0.7_0.9", "corner_0.7_1.5", "corner_1.3_0.9", "corner_1.3_1.5"):
            self.assertEqual(self.label(TRUSS[name][3]), (2, 0, 0))

    def test_inertia_on_each_branch_across_the_singular_line(self):
        # The line is L1 + L2 = 2. Below it the only equilibrium between the pins is on the pin line.
        # Above it a second equilibrium appears off the line. Stable branch: positive definite on both
        # sides and singular on the line. The inertia change happens on the on-line branch.
        for d, side in ((F(-1, 10), "below"), (F(-1, 100), "below"), (F(0), "on"), (F(1, 100), "above"),
                        (F(1, 10), "above")):
            L = (F(9, 10), F(11, 10) + d)
            (x,) = [x for x in online_equilibria(L) if PINS[0] < x < PINS[1]]
            on_line = self.label(online_hessian(x, L))
            off = offline_equilibrium(L)
            if side == "below":
                self.assertEqual((off, on_line), (None, (2, 0, 0)))
            elif side == "on":
                self.assertEqual((off, on_line), (None, (1, 0, 1)))
            else:
                self.assertEqual(on_line, (1, 1, 0))
                self.assertEqual(self.label(offline_matrix(off[0], L)), (2, 0, 0))

    def test_near_flat_pair_is_exactly_positive_definite(self):
        L = (F(9, 10), F(11, 10) + F(1, 10 ** 9))
        x, y2 = offline_equilibrium(L)
        M = offline_matrix(x, L)
        self.assertEqual(self.label(M), (2, 0, 0))
        A, B, C = M[0][0], M[0][1], M[1][1]
        # Raw Hessian [[A, B y], [B y, C y^2]]: determinant (A C - B^2) y^2 and trace A + C y^2.
        # The smaller eigenvalue is at most 2 det / trace, because the larger is at least trace / 2.
        smallest_upper = 2 * (A * C - B * B) * y2 / (A + C * y2)
        self.assertGreater(A * C - B * B, 0)
        self.assertLess(smallest_upper, F(1, 10 ** 7))


class TestAdapterBound(unittest.TestCase):
    def test_equivalence_with_the_definition_at_every_probe(self):
        for seed, rank in ((1, None), (2, 2), (3, 1)):
            B, A = adapter(seed, 8, 4, 8, rank)
            hi = trace(real_to_c(mm(mm(B, A), tr(mm(B, A)))))  # Frobenius norm squared bounds sigma^2
            lo = F(0)
            self.assertTrue(psd_by_cert(B, A, hi))
            self.assertTrue(psd_direct(B, A, hi))
            self.assertFalse(psd_direct(B, A, lo) and sum(abs(x) for r in B for x in r) > 0)
            for _ in range(14):
                mid = (lo + hi) / 2
                by_q, by_def = psd_by_cert(B, A, mid), psd_direct(B, A, mid)
                self.assertEqual(by_q, by_def, "seed %d rank %s s=%s" % (seed, rank, mid))
                lo, hi = (lo, mid) if by_q else (mid, hi)
            self.assertFalse(psd_direct(B, A, lo))
            self.assertTrue(psd_direct(B, A, hi))

    def test_singular_gram_matrix_gives_zero_eigenvalues_never_definite(self):
        B, A = adapter(2, 8, 4, 8, 2)
        s = trace(real_to_c(mm(mm(B, A), tr(mm(B, A)))))
        p, n, z = make_cert(real_to_c(q_matrix(B, A, s)))["claim"]
        self.assertEqual(n, 0)
        self.assertGreaterEqual(z, 2)
        GB = mm(tr(B), B)
        self.assertEqual(indep_inertia(real_to_c(GB), False)[2], 2)

    def test_zero_b_matrix(self):
        B, A = adapter(4, 8, 4, 8)
        B0 = [[F(0)] * 4 for _ in range(8)]
        self.assertEqual(make_cert(real_to_c(q_matrix(B0, A, F(0))))["claim"], [0, 0, 4])
        self.assertTrue(psd_by_cert(B0, A, F(0)))
        self.assertTrue(psd_by_cert(B0, A, F(5)))

    def test_forgery_is_rejected_by_a_loader_that_recomputes_the_matrix(self):
        B, A = adapter(5, 8, 4, 8)
        hi = trace(real_to_c(mm(mm(B, A), tr(mm(B, A)))))
        lo = F(0)
        for _ in range(14):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if psd_by_cert(B, A, mid) else (mid, hi)
        s = hi
        text = json.dumps(make_cert(real_to_c(q_matrix(B, A, s))))
        ok, why = loader_accepts(B, A, s, text)
        self.assertTrue(ok, why)
        B8 = [[8 * x for x in r] for r in B]
        ok, why = loader_accepts(B8, A, s, text)
        self.assertFalse(ok)
        self.assertIn("not Q(s)", why)
        fresh = json.dumps(make_cert(real_to_c(q_matrix(B8, A, s))))
        ok, why = loader_accepts(B8, A, s, fresh)
        self.assertFalse(ok)
        self.assertIn("inertia (", why)
        lie = json.loads(fresh)
        lie["claim"] = [4, 0, 0]
        ok, why = loader_accepts(B8, A, s, json.dumps(lie))
        self.assertFalse(ok)
        self.assertIn("claimed inertia", why)
        splice = json.loads(text)
        splice["M"] = fmt_real(q_matrix(B8, A, s))
        ok, why = loader_accepts(B8, A, s, json.dumps(splice))
        self.assertFalse(ok)
        self.assertIn("!= L D L*", why)
        ok, why = loader_accepts(B8, A, 64 * s, json.dumps(make_cert(real_to_c(q_matrix(B8, A, 64 * s)))))
        self.assertTrue(ok, why)

    def test_checker_alone_accepts_the_replayed_certificate(self):
        # Why the binding step matters: the old certificate is a valid certificate for the old
        # matrix, so the checker accepts it. Only the loader's recomputation rejects it.
        B, A = adapter(6, 8, 4, 8)
        s = trace(real_to_c(mm(mm(B, A), tr(mm(B, A)))))
        text = json.dumps(make_cert(real_to_c(q_matrix(B, A, s))))
        self.assertEqual(ic.check(text)[1], 0)
        B8 = [[8 * x for x in r] for r in B]
        self.assertFalse(loader_accepts(B8, A, s, text)[0])


# ---------------------------------------------------------------------------
# Sharp rank bound R_opt (docs/10, section 3.7)
# ---------------------------------------------------------------------------

class BoundError(ValueError):
    """Raised by a rank-bound check. The checks raise and never use assert, so python -O changes nothing."""


def ropt(u, t, S, b):
    """The joint optimum of the family over scale and weight, in closed form, as Fractions.
    u = tr P, t = tr Q, S = |P + Q|_F^2, b = declared bound on the positive eigenvalues of Q."""
    if u <= 0 or u + t <= 0:
        return F(0)
    if b > 0 and t > 0 and t * (u + t) >= b * S:
        den = S - t * t / b
        if den <= 0:
            raise BoundError("regime 1 with S - t^2/b <= 0: inputs are not those of a real pair")
        return u * u / den
    if S <= 0:
        raise BoundError("S <= 0 with u + t > 0: inputs are not those of a real pair")
    return max(F(0), (u + t) ** 2 / S - b)


def ropt_case(u, t, S, b):
    """Which branch of ropt applies: 0 (zero), 1 (u^2 / (S - t^2 / b)), 2 ((u+t)^2 / S - b), or 'edge'."""
    if u <= 0 or u + t <= 0:
        return 0
    if b > 0 and t > 0 and t * (u + t) == b * S:
        return "edge"
    return 1 if (b > 0 and t > 0 and t * (u + t) > b * S) else 2


def family_members(tp, tq, nn, b):
    """The right sides of (A), (B), the family at seven weights, and the best member."""
    cs = (F(0), F(1, 2), F(1), F(2), F(3), F(7, 2), F(2) * (tq - b) / b if b and tq >= b else F(0))
    return ([rhs_A(tp, tq, nn, b), rhs_B(tp, tq, nn, b), rhs_best(tp, tq, nn, b)]
            + [rhs_family(c, tp, tq, nn, b) for c in cs])


def check_dominates_family(R, members):
    for m in members:
        if R < m:
            raise BoundError("R_opt %s is below a family member %s" % (R, m))


def check_below_count(R, count):
    if R > count:
        raise BoundError("R_opt %s exceeds the true count %d" % (R, count))


def cinner(a, H, c):
    """a* H c for column vectors a, c and a matrix H, all with (re, im) entries."""
    n = len(a)
    tot = Z
    for i in range(n):
        for j in range(n):
            tot = cadd(tot, cmul(cmul(cconj(a[i]), H[i][j]), c[j]))
    return tot


def orthogonal_basis(rng, n, cplx):
    """n pairwise orthogonal nonzero vectors with (re, im) Fraction entries, by exact Gram-Schmidt."""
    out = []
    while len(out) < n:
        w = [(rnd(rng), rnd(rng) if cplx else F(0)) for _ in range(n)]
        for v in out:
            nv = sum(x[0] * x[0] + x[1] * x[1] for x in v)
            dot = Z
            for i in range(n):
                dot = cadd(dot, cmul(cconj(v[i]), w[i]))
            mu = (dot[0] / nv, dot[1] / nv)
            w = [csub(w[i], cmul(mu, v[i])) for i in range(n)]
        if any(x != Z for x in w):
            out.append(w)
    return out


def ropt_instance(rng):
    """P PSD, Q Hermitian with an exactly known eigenbasis. Returns P, Q, the basis and the eigenvalues of Q."""
    n = rng.randint(1, 5)
    cplx = rng.random() < 0.5
    vs = orthogonal_basis(rng, n, cplx)
    ws = [rng.choice([-3, -2, -1, 0, 1, 2, 3, 5]) * F(rng.randint(1, 4), 4) for _ in range(n)]
    flat = rng.random() < 0.3  # equal positive eigenvalues and no negative ones: the branch u^2 / (S - t^2 / b)
    if flat:
        top = max(ws)
        ws = [top if w > 0 else F(0) for w in ws]
    Q = zero_matrix(n)
    for v, w in zip(vs, ws):
        nv = sum(x[0] * x[0] + x[1] * x[1] for x in v)
        Q = addm(Q, herm_rank1(v, w / nv))
    P = zero_matrix(n)
    for _ in range(rng.randint(0, n)):
        ent = lambda: (rnd(rng) / 2, rnd(rng) / 2 if cplx else F(0))
        P = addm(P, herm_rank1([ent() for _ in range(n)], abs(rnd(rng)) + F(1, 4)))
    if flat or rng.random() < 0.4:  # a small P next to a large Q
        P = scalem(P, F(1, rng.randint(4, 12)))
    return P, Q, vs, ws


def compression_count(H, vs, ws):
    """Number of positive eigenvalues of the compression of H to the complement of the positive
    eigenspace of Q. The complement is spanned by the basis vectors with eigenvalue <= 0.
    The count does not depend on the basis of the complement (congruence), and the repo's checker reads it."""
    cols = [v for v, w in zip(vs, ws) if w <= 0]
    if not cols:
        return 0
    Hc = [[cinner(a, H, c) for c in cols] for a in cols]
    return certified_inertia(Hc)[0]


def check_witness(Pd, Qd, b_declared, rank_claimed):
    """Pd and Qd are the diagonals of P and Q (Fractions). The pair must be a valid instance of the
    bound's hypotheses, and rank_claimed must be the sharp value max(1, ceil R_opt) of its four numbers."""
    n = len(Pd)
    if len(Qd) != n or any(p < 0 for p in Pd):
        raise BoundError("P is not positive semidefinite")
    P = real_to_c([[Pd[i] if i == j else F(0) for j in range(n)] for i in range(n)])
    Q = real_to_c([[Qd[i] if i == j else F(0) for j in range(n)] for i in range(n)])
    if exact_rank(P) != rank_claimed:
        raise BoundError("rank of P is %d, not %d" % (exact_rank(P), rank_claimed))
    if certified_inertia(Q)[0] > b_declared:
        raise BoundError("Q has more than %d positive eigenvalues" % b_declared)
    u, t, S = trace(P), trace(Q), fro2(addm(P, Q))
    if u <= 0:
        raise BoundError("tr P is not positive")
    sharp = max(1, math.ceil(ropt(u, t, S, b_declared)))
    if sharp != rank_claimed:
        raise BoundError("sharp value is %d, not %d" % (sharp, rank_claimed))
    return u, t, S


def check_request(u, t, S, b, k):
    """Can the four numbers be realised with rank P = k? Only if k is at least max(1, ceil R_opt)."""
    if k < max(1, math.ceil(ropt(u, t, S, b))):
        raise BoundError("rank %d is below the sharp value" % k)


def witness(kind, r, b, u, t, x=F(0)):
    """Explicit diagonal pairs (P, Q) of rank r with b positive eigenvalues in Q.
    "lo" realises the smallest S for the regime  (u+t)^2 / S - b,  "hi" the one for  u^2 / (S - t^2 / b),
    both with R_opt = r. A nonzero x adds a coordinate with P = 0 and Q = -x, and lifts the first
    positive entry of Q by x. That keeps u, t and b and raises S by 2 x^2 + 2 x q0."""
    if kind == "lo":
        h = (u + t) / (r + b)
        Pd, Qd = [F(0)] * b + [u / r] * r, [h] * b + [-(b * h - t) / r] * r
    elif kind == "hi":
        Pd, Qd = [F(0)] * b + [u / r] * r, [t / b] * b + [F(0)] * r
    else:
        raise ValueError(kind)
    if x != 0:
        Qd = [Qd[0] + x] + Qd[1:] + [-x]
        Pd = Pd + [F(0)]
    return Pd, Qd


# (kind, r, b, u, t, x): the regime is checked from the numbers, not taken from this table.
SHARP_TUPLES = [
    ("lo", 1, 1, F(2), F(1), F(0)), ("lo", 1, 1, F(2), F(1), F(1, 2)), ("lo", 3, 2, F(5), F(-1), F(0)),
    ("lo", 2, 0, F(3), F(-1), F(0)), ("lo", 4, 3, F(2), F(1), F(1, 20)), ("lo", 2, 1, F(3), F(1, 2), F(1, 4)),
    ("hi", 2, 1, F(1), F(3), F(0)), ("hi", 3, 2, F(1), F(4), F(0)), ("hi", 1, 1, F(1), F(2), F(1, 3)),
    ("hi", 2, 1, F(1), F(3), F(1, 20)), ("hi", 3, 2, F(1), F(4), F(1, 100)),
    # the regime boundary r t = b u, built by both constructions
    ("lo", 1, 1, F(2), F(2), F(0)), ("hi", 1, 1, F(2), F(2), F(0)),
    ("lo", 2, 3, F(4), F(6), F(0)), ("hi", 2, 3, F(4), F(6), F(0)),
]


class TestSharpRankBound(unittest.TestCase):
    def test_random_exact_matrices(self):
        rng = random.Random(SEED_ROPT)
        cases = {0: 0, 1: 0, 2: 0, "edge": 0}
        beats_best = 0
        for k in range(N_ROPT):
            P, Q, vs, ws = ropt_instance(rng)
            H = addm(P, Q)
            b = certified_inertia(Q)[0]  # exact positive count of Q, from a checked certificate
            self.assertEqual(b, sum(1 for w in ws if w > 0), "seed %d instance %d" % (SEED_ROPT, k))
            tp, tq, nn = trace(P), trace(Q), fro2(H)
            R = ropt(tp, tq, nn, b)
            cases[ropt_case(tp, tq, nn, b)] += 1
            check_dominates_family(R, family_members(tp, tq, nn, b))
            count = compression_count(H, vs, ws)
            check_below_count(R, count)
            self.assertLessEqual(count, exact_rank(P), "chain, seed %d instance %d" % (SEED_ROPT, k))
            beats_best += R > max(F(0), rhs_best(tp, tq, nn, b))
        for case in (0, 1, 2):
            self.assertGreater(cases[case], 0, "no instance reached case %r" % (case,))
        self.assertGreater(beats_best, 0)
        STATS["ropt_instances"] = N_ROPT
        STATS["ropt_cases"] = {str(k): v for k, v in cases.items()}
        STATS["ropt_strictly_beats_best_member"] = beats_best

    def test_declaring_b_one_too_small_must_fail(self):
        # Null control for the check "R_opt never exceeds the true count".
        rng = random.Random(SEED_ROPT)
        fired = inconsistent = tried = 0
        for _ in range(N_ROPT):
            P, Q, vs, ws = ropt_instance(rng)
            H = addm(P, Q)
            b = certified_inertia(Q)[0]
            if b == 0:
                continue
            tried += 1
            try:
                R = ropt(trace(P), trace(Q), fro2(H), b - 1)
            except BoundError:  # the numbers cannot belong to a pair with that b: refused before the comparison
                inconsistent += 1
                continue
            try:
                check_below_count(R, compression_count(H, vs, ws))
            except BoundError:
                fired += 1
        self.assertGreater(fired, 0, "the control never fired in %d tries" % tried)
        STATS["ropt_b_one_too_small"] = {"tried": tried, "R_opt_above_true_count": fired,
                                         "refused_as_inconsistent": inconsistent}

    def test_a_wrong_r_opt_must_fail_the_family_check(self):
        # Null control for "R_opt is at least every family member": R_opt replaced by zero.
        rng = random.Random(SEED_ROPT)
        fired = 0
        for _ in range(N_ROPT):
            P, Q, vs, ws = ropt_instance(rng)
            b = certified_inertia(Q)[0]
            try:
                check_dominates_family(F(0), family_members(trace(P), trace(Q), fro2(addm(P, Q)), b))
            except BoundError:
                fired += 1
        self.assertGreater(fired, 0)
        STATS["ropt_zero_fired_family_check"] = fired

    def test_explicit_witnesses_of_sharpness(self):
        seen = set()
        for kind, r, b, u, t, x in SHARP_TUPLES:
            Pd, Qd = witness(kind, r, b, u, t, x)
            tup = check_witness(Pd, Qd, b, r)
            seen.add(ropt_case(*tup, b))
            for k in range(1, r):  # every smaller rank is excluded for these four numbers
                self.assertRaises(BoundError, check_request, *tup, b, k)
            check_request(*tup, b, r)
            check_request(*tup, b, r + 1)
        self.assertEqual(seen, {1, 2, "edge"})
        STATS["sharp_tuples"] = len(SHARP_TUPLES)

    def test_zero_branch_witnesses(self):
        # u + t <= 0 gives R_opt = 0 and the smallest rank is 1. P = [u], Q = [t], one coordinate.
        for u, t in ((F(2), F(-5)), (F(3), F(-3)), (F(1, 2), F(-1, 2))):
            tup = check_witness([u], [t], 0, 1)
            self.assertEqual(ropt_case(*tup, 0), 0)
            self.assertRaises(BoundError, check_request, *tup, 0, 0)

    def test_requesting_one_rank_lower_must_fail(self):
        # Null control: for every witness, rank r - 1 (or rank 0 when r = 1) is refused by the check.
        for kind, r, b, u, t, x in SHARP_TUPLES:
            Pd, Qd = witness(kind, r, b, u, t, x)
            tup = check_witness(Pd, Qd, b, r)
            self.assertRaises(BoundError, check_request, *tup, b, r - 1)
            self.assertRaises(BoundError, check_witness, Pd, Qd, b, r - 1)

    def test_declaring_b_one_too_small_must_fail_the_witness_check(self):
        for kind, r, b, u, t, x in SHARP_TUPLES:
            if b >= 1:
                Pd, Qd = witness(kind, r, b, u, t, x)
                self.assertRaises(BoundError, check_witness, Pd, Qd, b - 1, r)

    def test_a_witness_pushed_too_far_must_fail(self):
        # Lifting S past the point where R_opt drops to r - 1 or below: the rank claimed is no longer sharp.
        Pd, Qd = witness("lo", 4, 3, F(2), F(1), F(3))
        self.assertRaises(BoundError, check_witness, Pd, Qd, 3, 4)
        Pd, Qd = witness("hi", 2, 1, F(1), F(3), F(5, 2))
        self.assertRaises(BoundError, check_witness, Pd, Qd, 1, 2)

    def test_a_witness_that_is_not_psd_must_fail(self):
        self.assertRaises(BoundError, check_witness, [F(2), F(-1)], [F(0), F(0)], 0, 1)

    def test_the_formula_is_the_supremum_over_scale_and_weight(self):
        # The scaled family bound for the pair (sP, sQ) with weight C >= 1 is
        #   g(s, C) = 2 s u + 2 C s t - C^2 b - s^2 S.
        # R_opt is max(0, sup g). Exact check: no grid point is above R_opt, and the closed-form
        # maximiser reaches it. This needs S > t^2 / b, which makes g concave.
        g = lambda u, t, S, b, s, C: 2 * s * u + 2 * C * s * t - C * C * b - s * s * S
        rng = random.Random(SEED_ROPT + 1)
        regime = {1: 0, 2: 0}
        for _ in range(300):
            u, b = F(rng.randint(1, 12), rng.randint(1, 4)), rng.randint(1, 4)
            t = F(rng.randint(-30, 30), rng.randint(1, 4))
            S = F(rng.randint(1, 80), rng.randint(1, 4)) + max(F(0), t * t / b)
            R = ropt(u, t, S, b)
            for s in (F(k, 8) for k in range(1, 40)):
                for C in (F(1), F(3, 2), F(2), F(3), F(5)):
                    self.assertLessEqual(g(u, t, S, b, s, C), R)
            if t > 0 and t * (u + t) >= b * S:
                s = u / (S - t * t / b)
                C = s * t / b
                self.assertGreaterEqual(C, 1)
                self.assertEqual(g(u, t, S, b, s, C), R)
                regime[1] += 1
            elif u + t > 0:
                s = (u + t) / S
                self.assertEqual(g(u, t, S, b, s, F(1)), (u + t) ** 2 / S - b)
                self.assertEqual(R, max(F(0), g(u, t, S, b, s, F(1))))
                regime[2] += 1
        self.assertTrue(regime[1] > 0 and regime[2] > 0)


# ---------------------------------------------------------------------------
# Margin certificates (docs/10, section 2.4)
# ---------------------------------------------------------------------------

mc = load_checker(MARGIN_PATH, "margin_cert_under_test")
with open(MARGIN_PATH, encoding="utf-8") as _fh:
    MSRC = _fh.read()


def frac_s(x):
    x = F(x)
    return "%d/%d" % (x.numerator, x.denominator)


def mstr(M):
    return [[frac_s(x) for x in r] for r in M]


def margin_text(M, P, L, D, lam, claim=False, extra=None):
    o = {"M": mstr(M), "P": list(P), "L": mstr(L), "D": mstr(D), "lambda": frac_s(lam)}
    if claim:
        o["claim_floor"] = frac_s(lam)
    if extra:
        o.update(extra)
    return json.dumps(o)


def build_margin(rng, n, lam, dvec=None, zero_prob=F(1, 3)):
    """Untrusted producer. M = P^T L D L^T P + lam I with L unit lower triangular and D = diag(dvec)."""
    L = [[F(1) if i == j else (rnd(rng) if j < i else F(0)) for j in range(n)] for i in range(n)]
    if dvec is None:
        dvec = [F(0) if rng.random() < zero_prob else abs(rnd(rng)) + F(1, 4) for _ in range(n)]
    P = list(range(n))
    rng.shuffle(P)
    G = [[sum(L[i][k] * dvec[k] * L[j][k] for k in range(n)) for j in range(n)] for i in range(n)]
    M = [[F(0)] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            M[P[i]][P[j]] = G[i][j] + (lam if i == j else 0)
    return M, P, L, [[dvec[i] if i == j else F(0) for j in range(n)] for i in range(n)], lam


def shifted(M, lam):
    return [[M[i][j] - (lam if i == j else 0) for j in range(len(M))] for i in range(len(M))]


def msum(A, B):
    return [[A[i][j] + B[i][j] for j in range(len(A))] for i in range(len(A))]


def null_vector(L, P, D):
    """A rational x with (M - lam I) x = 0, from the first zero pivot of D. None when there is none."""
    n = len(L)
    ks = [k for k in range(n) if D[k][k] == 0]
    if not ks:
        return None
    k = ks[0]
    z = [F(0)] * n
    z[k] = F(1)
    for i in range(k - 1, -1, -1):  # solve L^T z = e_k, L unit lower
        z[i] = -sum(L[j][i] * z[j] for j in range(i + 1, n))
    x = [F(0)] * n
    for i in range(n):
        x[P[i]] = z[i]
    return x


def rank_one(x, scale):
    nx = sum(v * v for v in x)
    return [[scale * x[i] * x[j] / nx for j in range(len(x))] for i in range(len(x))]


def mrun(fn):
    try:
        return ("ACCEPT", fn())
    except mc.CertError as e:
        return ("REJECT", str(e))


def real_inertia(X):
    """Independent exact inertia of a real symmetric matrix, and the repo checker's reading of it."""
    c = real_to_c(X)
    want = indep_inertia(c, False)
    got = certified_inertia(c)
    if want != got:
        raise BoundError("independent inertia %r differs from the checker's %r" % (want, got))
    return got


# A fixed 4 by 4 certificate with a zero pivot, so the floor lam = 3/2 is attained.
MB = build_margin(random.Random(7), 4, F(3, 2), dvec=[F(2), F(0), F(1), F(3, 2)])
MB_TEXT = margin_text(*MB)
MB_X = null_vector(MB[2], MB[1], MB[3])


def margin_controls():
    """name -> (what to run on a module, source text to remove, replacement, unsound or None).
    Each run must be rejected by the real checker. With the guard removed it must be accepted.
    unsound() is True when the accepted claim would be false, so the control is a soundness control.
    None marks a format control: the claim is true, the format forbids it."""
    M, P, L, D, lam = MB
    n = 4
    x = MB_X
    past = rank_one(x, -(lam + F(1, 100)))
    both_ok = rank_one(x, -lam)
    c = {}
    c["perturbation_just_past_lambda"] = (
        lambda m: m.psd_verdict(MB_TEXT, E=mstr(past)),
        'need(f2 <= lam * lam, "||E||_F^2 exceeds lambda^2: margin not certified")',
        'need(True, "||E||_F^2 exceeds lambda^2: margin not certified")',
        lambda: real_inertia(msum(M, past))[1] > 0)
    c["wrong_lambda"] = (
        lambda m: m.check(margin_text(M, P, L, D, lam + F(1, 2))),
        'need(lhs == rhs, "P (M - lambda I) P^T != L D L^T at (%d,%d)" % (i, j))',
        'need(True or lhs == rhs, "P (M - lambda I) P^T != L D L^T at (%d,%d)" % (i, j))',
        lambda: real_inertia(shifted(M, lam + F(1, 2)))[1] > 0)
    dneg = build_margin(random.Random(8), 4, F(3, 2), dvec=[F(2), F(-1), F(1), F(3, 2)])
    c["negative_pivot"] = (
        lambda m: m.check(margin_text(*dneg)),
        'need(D[k][k] >= 0, "D has a negative entry")', 'need(True, "D has a negative entry")',
        lambda: real_inertia(shifted(dneg[0], dneg[4]))[1] > 0)
    L2 = [r[:] for r in L]
    D2 = [r[:] for r in D]
    for r in range(n):
        L2[r][0] *= 2
    D2[0][0] /= 4
    c["non_unit_L"] = (
        lambda m: m.check(margin_text(M, P, L2, D2, lam)),
        'need(i != j or L[i][i] == 1, "L diagonal is not 1")', 'need(True, "L diagonal is not 1")', None)
    c["L_entry_above_the_diagonal"] = (
        lambda m: m.check(margin_text([[F(2)] * 2] * 2, [0, 1], [[F(1), F(1)], [F(1), F(1)]],
                                      [[F(1), F(0)], [F(0), F(1)]], F(0))),
        'need(j <= i or L[i][j] == 0, "L not lower triangular")', 'need(True, "L not lower triangular")', None)
    c["D_not_diagonal"] = (
        lambda m: m.check(margin_text([[F(0)] * 2] * 2, [0, 1], [[F(1), F(0)], [F(0), F(1)]],
                                      [[F(0), F(5)], [F(5), F(0)]], F(0))),
        'need(i == j or D[i][j] == 0, "D not diagonal")', 'need(True, "D not diagonal")', None)
    c["repeated_index_in_P"] = (
        lambda m: m.check(margin_text([[F(-1), F(0)], [F(0), F(1)]], [1, 1], [[F(1), F(0)], [F(1), F(1)]],
                                      [[F(1), F(0)], [F(0), F(0)]], F(0))),
        'and sorted(P) == list(range(n)), "P is not a permutation")', 'and True, "P is not a permutation")',
        lambda: real_inertia([[F(-1), F(0)], [F(0), F(1)]])[1] > 0)
    d = json.loads(MB_TEXT)
    d["M"][0][0] = "%d/%d" % (2 * F(M[0][0]).numerator, 2 * F(M[0][0]).denominator)
    c["non_canonical_rational"] = (
        lambda m: m.check(json.dumps(d)),
        'need(s != "-0/1" and gcd(p, q) == 1, "entry is not in lowest terms")',
        'need(True, "entry is not in lowest terms")', None)
    d2 = json.loads(MB_TEXT)
    d2["L"][0][1] = "-0/1"
    c["negative_zero"] = (
        lambda m: m.check(json.dumps(d2)),
        'need(s != "-0/1" and gcd(p, q) == 1, "entry is not in lowest terms")',
        'need(True, "entry is not in lowest terms")', None)
    indef = ([[F(-16), F(0)], [F(0), F(5)]], [0, 1], [[F(1), F(0)], [F(0), F(1)]],
             [[F(84), F(0)], [F(0), F(105)]], F(-100))
    c["negative_lambda_read_as_psd"] = (
        lambda m: m.psd_verdict(margin_text(*indef)),
        'need(lam >= 0, "lambda < 0: a floor, not a PSD certificate")',
        'need(True, "lambda < 0: a floor, not a PSD certificate")',
        lambda: real_inertia(indef[0])[1] > 0)
    c["negative_lambda_with_a_frobenius_perturbation"] = (
        lambda m: m.psd_verdict(margin_text(*indef), E=mstr([[F(0), F(0)], [F(0), F(0)]])),
        'need(lam >= 0, "lambda < 0: the Frobenius test needs lambda >= 0")',
        'need(True, "lambda < 0: the Frobenius test needs lambda >= 0")',
        lambda: real_inertia(indef[0])[1] > 0)
    E_low = [[-2 * lam if i == j else F(0) for j in range(n)] for i in range(n)]
    idn = [[F(1) if i == j else F(0) for j in range(n)] for i in range(n)]
    zer = [[F(0)] * n for _ in range(n)]
    c["second_certificate_floor_below_zero"] = (
        lambda m: m.psd_verdict(MB_TEXT, E_text=margin_text(E_low, list(range(n)), idn, zer, -2 * lam)),
        'need(floor >= 0, "certified floor of M + E is below zero")',
        'need(True, "certified floor of M + E is below zero")',
        lambda: real_inertia(msum(M, E_low))[1] > 0)
    c["claim_floor_differs_from_lambda"] = (
        lambda m: m.check(margin_text(M, P, L, D, lam, extra={"claim_floor": frac_s(lam + 1)})),
        'need(frac(c["claim_floor"]) == lam, "claim_floor differs from lambda")',
        'need(True, "claim_floor differs from lambda")', None)
    c["both_E_and_E_text_given"] = (
        lambda m: m.psd_verdict(MB_TEXT, E=mstr(both_ok), E_text=margin_text(zer, list(range(n)), idn, zer, F(0))),
        'need(E is None or E_text is None, "give E or E_text, not both")',
        'need(True, "give E or E_text, not both")', None)
    c["E_text_of_the_wrong_size"] = (
        lambda m: m.psd_verdict(MB_TEXT, E_text=margin_text([[F(0)]], [0], [[F(1)]], [[F(0)]], F(0))),
        'need(len(Em) == n, "E has the wrong size")', 'need(True, "E has the wrong size")', None)
    c["E_not_symmetric"] = (
        lambda m: m.psd_verdict(MB_TEXT, E=mstr([[F(0), F(1, 100)] + [F(0)] * 2] + [[F(0)] * 4] * 3)),
        'need(Eq[i][j] == Eq[j][i], "E not symmetric")', 'need(True, "E not symmetric")', None)
    return c


MARGIN_RAW = {
    "float_in_json": MB_TEXT.replace('"3/2"', "1.5", 1),
    "decimal_string": MB_TEXT.replace('"3/2"', '"1.5"', 1),
    "bare_integer": MB_TEXT.replace('"1/1"', '"1"', 1),
    "plus_sign": MB_TEXT.replace('"1/1"', '"+1/1"', 1),
    "trailing_newline_in_entry": MB_TEXT.replace('"3/2"', '"3/2\\n"', 1),
    "zero_denominator": MB_TEXT.replace('"1/1"', '"1/0"', 1),
    "leading_zero": MB_TEXT.replace('"3/2"', '"03/2"', 1),
    "duplicate_key": MB_TEXT[:-1] + ', "P": %s}' % json.dumps(MB[1]),
    "missing_lambda": json.dumps({k: v for k, v in json.loads(MB_TEXT).items() if k != "lambda"}),
    "extra_key": MB_TEXT[:-1] + ', "x": 1}',
    "entry_past_digit_limit": MB_TEXT.replace('"3/2"', '"%s/1"' % LONG, 1),
    "truncated": MB_TEXT[:60],
    "not_an_object": "[]",
}

# source lines of margin_cert.py that call need(): all must be mutated above or sit in this list
MARGIN_PARSE_ONLY = (
    'need(type(s) is str and CANON.fullmatch(s) is not None, "entry is not a canonical string p/q")',
    'need(type(rows) is list and len(rows) == n, name + ": wrong row count")',
    'need(type(r) is list and len(r) == n, name + ": wrong shape")',
    'need(type(c) is dict, "certificate must be an object")',
    'need(set(c) in ({"M", "P", "L", "D", "lambda"}, {"M", "P", "L", "D", "lambda", "claim_floor"}), "wrong keys")',
    'need(type(c["M"]) is list and 1 <= len(c["M"]) <= MAXN, "bad M")',
    'need(M[i][j] == M[j][i], "M not symmetric")',  # a second layer: the identity implies it
)


class TestMarginCertificates(unittest.TestCase):
    def test_floor_on_random_certificates(self):
        rng = random.Random(SEED_MARGIN)
        tight = strict = neg_lambda = indefinite = 0
        for k in range(N_MARGIN):
            n = rng.randint(1, 6)
            lam = rnd(rng)
            M, P, L, D, lam = build_margin(rng, n, lam)
            text = margin_text(M, P, L, D, lam)
            where = "seed %d instance %d" % (SEED_MARGIN, k)
            self.assertEqual(mc.check(text), lam, where)
            zeros = sum(1 for i in range(n) if D[i][i] == 0)
            pos, neg, zero = real_inertia(shifted(M, lam))  # independent method and the repo checker agree
            self.assertEqual((neg, zero), (0, zeros), where)
            # the repo's block-pivot checker, given the same L and D, also reads no negative eigenvalue
            self.assertEqual(ic.check(json.dumps({"M": mstr_c(shifted(M, lam)), "P": P, "L": mstr_c(L),
                                                  "D": mstr_c(D)})), (n - zeros, 0, zeros), where)
            if zeros:
                tight += 1
                # the floor is attained: any larger lambda is not a floor of M
                self.assertGreaterEqual(real_inertia(shifted(M, lam + F(1, 1000)))[1], zeros, where)
                self.assertRaises(mc.CertError, mc.check, margin_text(M, P, L, D, lam + F(1, 1000)))
            else:
                strict += 1
            if lam < 0:
                neg_lambda += 1
                indefinite += real_inertia(M)[1] > 0
                self.assertRaises(mc.CertError, mc.psd_verdict, text)  # a floor below zero is not a PSD proof
            else:
                self.assertEqual(mc.psd_verdict(text), "PD" if lam > 0 else "PSD", where)
                inertia = real_inertia(M)
                self.assertEqual(inertia[1], 0, where)
                if lam > 0:
                    self.assertEqual(inertia[2], 0, where)
        for count in (tight, strict, neg_lambda, indefinite):
            self.assertGreater(count, 0)
        STATS["margin_floor"] = {"certificates": N_MARGIN, "tight": tight, "strict": strict,
                                 "lambda_below_zero": neg_lambda, "lambda_below_zero_and_M_indefinite": indefinite}

    def test_second_certificate_for_E_is_exact(self):
        rng = random.Random(SEED_MARGIN_E)
        frob_weaker = strict = 0
        for k in range(N_MARGIN):
            n = rng.randint(1, 5)
            lam = abs(rnd(rng)) + F(1, 4)
            M, P, L, D, lam = build_margin(rng, n, lam)
            # E - mu I = L' D' L'^T with D' >= 0, built directly. mu = -lam + delta, delta >= 0, so
            # the certified floor of M + E is lam + mu = delta.
            delta = F(0) if rng.random() < 0.5 else F(rng.randint(1, 4), rng.randint(1, 4))
            Ee, Pe, Le, De, mu = build_margin(rng, n, -lam + delta)
            where = "seed %d instance %d" % (SEED_MARGIN_E, k)
            text, etext = margin_text(M, P, L, D, lam), margin_text(Ee, Pe, Le, De, mu)
            verdict = mc.psd_verdict(text, E_text=etext)
            Sum = msum(M, Ee)
            pos, neg, zero = real_inertia(Sum)
            self.assertEqual(neg, 0, where)
            self.assertEqual(verdict, "PD" if delta > 0 else "PSD", where)
            if delta > 0:
                strict += 1
                self.assertEqual(zero, 0, where)
            floor = mc.check(text) + mc.check(etext)
            self.assertEqual(floor, delta, where)
            # Weyl, exactly: M + E - (lam + mu) I has no negative eigenvalue
            self.assertEqual(real_inertia(shifted(Sum, floor))[1], 0, where)
            f2 = sum(x * x for r in Ee for x in r)
            if f2 > lam * lam:
                frob_weaker += 1
                self.assertRaises(mc.CertError, mc.psd_verdict, text, E=mstr(Ee))
            else:
                self.assertIn(mc.psd_verdict(text, E=mstr(Ee)), ("PSD", "PD"))
        self.assertGreater(frob_weaker, 0)
        self.assertGreater(strict, 0)
        STATS["margin_second_certificate"] = {"pairs": N_MARGIN, "strictly_positive_floor": strict,
                                              "frobenius_test_refuses_but_exact_route_accepts": frob_weaker}

    def test_sharpness_of_the_frobenius_constant(self):
        M, P, L, D, lam = MB
        x = MB_X
        self.assertEqual([sum(shifted(M, lam)[i][j] * x[j] for j in range(4)) for i in range(4)], [F(0)] * 4)
        at = rank_one(x, -lam)  # ||E||_F = lam exactly: PSD, singular, accepted
        self.assertEqual(mc.psd_verdict(MB_TEXT, E=mstr(at)), "PSD")
        pos, neg, zero = real_inertia(msum(M, at))
        self.assertEqual((neg, zero >= 1), (0, True))
        for k in (1, 2, 7, 100, 10 ** 9):  # just past lambda: not PSD, and the check refuses
            past = rank_one(x, -(lam + F(1, k)))
            self.assertEqual(real_inertia(msum(M, past))[1], 1, "k=%d" % k)
            self.assertRaises(mc.CertError, mc.psd_verdict, MB_TEXT, E=mstr(past))
        # the one-sided test (second certificate) refuses it too, since E + lam I has a negative eigenvalue
        E_past = rank_one(x, -(lam + F(1, 7)))
        self.assertEqual(real_inertia(msum(E_past, [[lam if i == j else F(0) for j in range(4)] for i in range(4)]))[1], 1)

    def test_pencil_example(self):
        # B = [1/2], W = [1], so K = B^T W B = 1/4 and G = B^T B = 1/4. lambda = 1 is certified by
        # K - lambda G = 0 (a zero pivot). A change of W of size lambda is covered. A change E' of
        # the reduced matrix K of size lambda is not. It is covered only up to lambda * gamma, with
        # G - gamma I certified PSD, here gamma = 1/4.
        K, G, lam = F(1, 4), F(1, 4), F(1)
        self.assertEqual(real_inertia([[K - lam * G]]), (0, 0, 1))
        B = F(1, 2)
        dW = F(-1)  # |dW| <= lambda
        self.assertEqual(real_inertia([[B * (1 + dW) * B]])[1], 0)
        self.assertEqual(real_inertia([[K + F(-1, 2)]])[1], 1)  # E' = -1/2, |E'| <= lambda, breaks
        gamma = F(1, 4)
        self.assertEqual(real_inertia([[G - gamma]]), (0, 0, 1))
        self.assertEqual(real_inertia([[K + F(-1, 4)]])[1], 0)  # E' = -lambda * gamma still passes
        self.assertEqual(real_inertia([[K + F(-1, 4) - F(1, 1000)]])[1], 1)

    def test_every_margin_control_is_rejected_by_the_real_checker(self):
        for name, (run_it, old, new, unsound) in margin_controls().items():
            r = mrun(lambda: run_it(mc))
            self.assertEqual(r[0], "REJECT", "%s: %r" % (name, r))

    def test_raw_margin_controls_are_rejected(self):
        for name, raw in MARGIN_RAW.items():
            r = mrun(lambda: mc.check(raw))
            self.assertEqual(r[0], "REJECT", "%s: %r" % (name, r))

    def test_each_margin_guard_removed_makes_its_control_accepted(self):
        survivors = []
        for name, (run_it, old, new, unsound) in margin_controls().items():
            mut = make_mutant(old, new, "mut_margin_" + name, src=MSRC, path=MARGIN_PATH)
            r = mrun(lambda: run_it(mut))
            if r[0] != "ACCEPT":
                survivors.append(name)
            if unsound is not None:
                self.assertTrue(unsound(), "%s is not a soundness control" % name)
        self.assertEqual(survivors, [], "guards whose removal is not detected by a control")
        STATS["margin_guard_mutants"] = len(margin_controls())

    def test_every_need_site_of_margin_cert_has_a_control_or_a_reason(self):
        norm = lambda t: " ".join(t.split())
        olds = [norm(v[1]) for v in margin_controls().values()]
        parse_only = [norm(t) for t in MARGIN_PARSE_ONLY]
        sites = [norm(ast.get_source_segment(MSRC, node)) for node in ast.walk(ast.parse(MSRC))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "need"]
        self.assertGreater(len(sites), 15)
        for site in sites:
            covered = site in parse_only or any(o in site for o in olds)
            self.assertTrue(covered, "need() site without control: %s" % site)

    def test_symmetry_check_is_a_second_layer(self):
        bad = json.loads(MB_TEXT)
        bad["M"][0][1] = "9/1"
        self.assertEqual(mrun(lambda: mc.check(json.dumps(bad)))[0], "REJECT")
        mut = make_mutant('need(M[i][j] == M[j][i], "M not symmetric")', "pass", "mut_sym", src=MSRC, path=MARGIN_PATH)
        self.assertEqual(mrun(lambda: mut.check(json.dumps(bad)))[0], "REJECT")

    def test_check_accepts_the_good_certificate_and_reads_it_back(self):
        self.assertEqual(mc.check(MB_TEXT), F(3, 2))
        self.assertEqual(mc.check(margin_text(*MB, claim=True)), F(3, 2))
        self.assertEqual(mc.psd_verdict(MB_TEXT), "PD")  # lambda = 3/2 > 0

    def test_command_line_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good, bad = os.path.join(d, "good.json"), os.path.join(d, "bad.json")
            with open(good, "w", encoding="utf-8") as fh:
                fh.write(MB_TEXT)
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write(margin_text(*MB[:4], MB[4] + 1))
            ok = subprocess.run([sys.executable, "-B", MARGIN_PATH, good], capture_output=True, text=True)
            self.assertEqual((ok.returncode, ok.stdout.strip()), (0, "lambda_min >= 3/2"))
            no = subprocess.run([sys.executable, "-B", MARGIN_PATH, bad], capture_output=True, text=True)
            self.assertEqual(no.returncode, 1)
            self.assertIn("REJECT", no.stderr)
            self.assertEqual(subprocess.run([sys.executable, "-B", MARGIN_PATH], capture_output=True).returncode, 1)


def mstr_c(M):
    """Real matrix of Fractions as a certificate matrix for inertia_cert.py (strings p/q)."""
    return [[frac_s(x) for x in r] for r in M]


# ---------------------------------------------------------------------------
# Timing report (not part of the tests)
# ---------------------------------------------------------------------------

def power_bound(B, A):
    """Untrusted float estimate of sigma_max(B A)^2, as the largest eigenvalue of G_B G_A."""
    GB = [[float(x) for x in r] for r in mm(tr(B), B)]
    GA = [[float(x) for x in r] for r in mm(A, tr(A))]
    K = [[sum(GB[i][t] * GA[t][j] for t in range(len(GB))) for j in range(len(GB))] for i in range(len(GB))]
    v = [1.0 + 0.01 * i for i in range(len(K))]
    lam = 0.0
    for _ in range(400):
        w = [sum(K[i][j] * v[j] for j in range(len(v))) for i in range(len(v))]
        lam = max(abs(x) for x in w) / max(abs(x) for x in v)
        top = max(abs(x) for x in w)
        v = [x / top for x in w]
    return lam


def report():
    print("rank  dims    build Q (s)  produce (s)  check (s)  certificate bytes  checker verdict")
    for r in (4, 8, 16, 32):
        B, A = adapter(3, 64, r, 64)
        s = F(power_bound(B, A)) * F(1000001, 1000000)
        while True:
            t0 = time.perf_counter()
            M = real_to_c(q_matrix(B, A, s))
            t1 = time.perf_counter()
            text = json.dumps(certify(M))
            t2 = time.perf_counter()
            res = ic.check(text)
            t3 = time.perf_counter()
            if res[1] == 0:
                break
            s *= F(1001, 1000)
        print("%4d  64x64   %9.3f  %11.3f  %9.3f  %17d  inertia %r (no negative eigenvalue)"
              % (r, t1 - t0, t2 - t1, t3 - t2, len(text), res))


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    elif "--stats" in sys.argv:  # run the suite quietly and print the counts the tests gathered
        sys.argv.remove("--stats")
        res = unittest.main(exit=False, verbosity=0).result
        print(json.dumps(STATS, indent=1, sort_keys=True))
        sys.exit(0 if res.wasSuccessful() else 1)
    else:
        unittest.main()
