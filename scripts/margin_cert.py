#!/usr/bin/env python3
"""Margin certificate checker for docs/10, section 2.4. Standard library only (Apache-2.0).

A margin certificate has the keys M, P, L, D and lambda, plus optionally claim_floor. It states
    P (M - lambda I) P^T = L D L^T
with P a permutation, L unit lower triangular and D DIAGONAL with every entry d_k >= 0.
Then every eigenvalue of M is at least lambda, for either sign of lambda. check() returns lambda.
It never says "positive semidefinite" on its own: that needs lambda >= 0, which psd_verdict() asks for.

The format is the one of scripts/inertia_cert.py with two changes. The matrix is real symmetric, and
the identity is shifted by lambda. Entries are canonical rationals: strings p/q in lowest terms with
q >= 1, no leading zeros, no "-0". inertia_cert.py is imported and not changed. Its parser, its
CertError and its need() are the ones used here.

psd_verdict(text, E=None, E_text=None) answers whether M + E is positive semidefinite (PSD) or
positive definite (PD), for a symmetric E that is either given as rows of strings or certified by a
second certificate E_text of the same format whose M is E. The second route is exact: if E_text proves
lambda_min(E) >= mu, then lambda_min(M + E) >= lambda + mu (Weyl). The first route is a cheaper
sufficient test, the squared Frobenius norm of E at most lambda^2.

Command line (prints the floor, exits 1 with REJECT on stderr when the certificate fails):
    python3 -B scripts/margin_cert.py certificate.json
"""
import importlib.util
import os
import re
import sys
from fractions import Fraction as F
from math import gcd

MAXN = 64
CANON = re.compile(r"-?(0|[1-9][0-9]*)/[1-9][0-9]*")


def _load_inertia_cert():
    cached = sys.modules.get("inertia_cert")
    if cached is not None and hasattr(cached, "CertError"):
        return cached
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inertia_cert.py")
    spec = importlib.util.spec_from_file_location("inertia_cert", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["inertia_cert"] = mod
    spec.loader.exec_module(mod)
    return mod


ic = _load_inertia_cert()
CertError = ic.CertError
need = ic.need


def frac(s):
    """A canonical rational string p/q: lowest terms, q >= 1, no leading zeros, no negative zero."""
    need(type(s) is str and CANON.fullmatch(s) is not None, "entry is not a canonical string p/q")
    try:
        p, q = int(s.split("/")[0]), int(s.split("/")[1])
    except ValueError as e:  # Python refuses integer strings past its digit limit (4300 by default)
        raise CertError("entry too long: " + str(e)[:60])
    need(s != "-0/1" and gcd(p, q) == 1, "entry is not in lowest terms")
    return F(p, q)


def mat(rows, n, name):
    need(type(rows) is list and len(rows) == n, name + ": wrong row count")
    for r in rows:
        need(type(r) is list and len(r) == n, name + ": wrong shape")
    return [[frac(e) for e in r] for r in rows]


def read(text):
    """Parse and verify a margin certificate. Return (M, floor) with M a list of rows of Fractions."""
    c = ic.parse(text)
    need(type(c) is dict, "certificate must be an object")
    need(set(c) in ({"M", "P", "L", "D", "lambda"}, {"M", "P", "L", "D", "lambda", "claim_floor"}), "wrong keys")
    need(type(c["M"]) is list and 1 <= len(c["M"]) <= MAXN, "bad M")
    n = len(c["M"])
    M, L, D = mat(c["M"], n, "M"), mat(c["L"], n, "L"), mat(c["D"], n, "D")
    lam = frac(c["lambda"])
    P = c["P"]
    need(type(P) is list and len(P) == n and all(type(p) is int for p in P)
         and sorted(P) == list(range(n)), "P is not a permutation")
    for i in range(n):
        for j in range(n):
            need(M[i][j] == M[j][i], "M not symmetric")
            need(j <= i or L[i][j] == 0, "L not lower triangular")
            need(i != j or L[i][i] == 1, "L diagonal is not 1")
            need(i == j or D[i][j] == 0, "D not diagonal")
    for k in range(n):
        need(D[k][k] >= 0, "D has a negative entry")
    for i in range(n):
        for j in range(n):
            lhs = M[P[i]][P[j]] - (lam if i == j else 0)
            rhs = sum(L[i][k] * D[k][k] * L[j][k] for k in range(n))
            need(lhs == rhs, "P (M - lambda I) P^T != L D L^T at (%d,%d)" % (i, j))
    if "claim_floor" in c:
        need(frac(c["claim_floor"]) == lam, "claim_floor differs from lambda")
    return M, lam


def check(text):
    """Return the certified floor lambda (a Fraction): lambda_min(M) >= lambda. Raise CertError otherwise."""
    return read(text)[1]


def psd_verdict(text, E=None, E_text=None):
    """Return "PSD" or "PD" for M + E (for M alone when neither E nor E_text is given), or raise."""
    need(E is None or E_text is None, "give E or E_text, not both")
    M, lam = read(text)
    n = len(M)
    if E_text is not None:
        Em, mu = read(E_text)
        need(len(Em) == n, "E has the wrong size")
        floor = lam + mu
        need(floor >= 0, "certified floor of M + E is below zero")
        return "PD" if floor > 0 else "PSD"
    if E is None:
        need(lam >= 0, "lambda < 0: a floor, not a PSD certificate")
        return "PD" if lam > 0 else "PSD"
    need(lam >= 0, "lambda < 0: the Frobenius test needs lambda >= 0")
    Eq = mat(E, n, "E")
    for i in range(n):
        for j in range(n):
            need(Eq[i][j] == Eq[j][i], "E not symmetric")
    f2 = sum(x * x for r in Eq for x in r)
    need(f2 <= lam * lam, "||E||_F^2 exceeds lambda^2: margin not certified")
    return "PD" if f2 < lam * lam else "PSD"


if __name__ == "__main__":
    try:
        with open(sys.argv[1], encoding="utf-8") as fh:
            floor = check(fh.read())
            print("lambda_min >= %d/%d" % (floor.numerator, floor.denominator))
    except (CertError, OSError, IndexError, UnicodeDecodeError, RecursionError) as e:
        print("REJECT: %s" % e, file=sys.stderr)
        sys.exit(1)
