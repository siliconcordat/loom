#!/usr/bin/env python3
"""Exact inertia checker for docs/08. Standard library only (Apache-2.0).

Verifies a certificate P M P* = L D L* over Q(i) by exact multiplication and returns the
inertia (positive, negative, zero eigenvalue counts) of the matrix M in the certificate.
It certifies the matrix it is given. Binding that matrix to real data is the caller's job.
Command line (prints three counts, exits 1 with REJECT on stderr when the certificate fails):
    python3 -B scripts/inertia_cert.py certificate.json
"""
import json
import re
import sys
from fractions import Fraction as F

MAXN = 64
NUM = re.compile(r"-?[0-9]+/[1-9][0-9]*")
ZERO = (F(0), F(0))
ONE = (F(1), F(0))


class CertError(ValueError):
    pass


def need(ok, msg):
    if not ok:
        raise CertError(msg)


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def mul(a, b):
    return (a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0])


def conj(a):
    return (a[0], -a[1])


def frac(s):
    need(type(s) is str and NUM.fullmatch(s) is not None, "entry is not a string p/q: %r" % (s,))
    return F(s)


def entry(e):
    if type(e) is str:
        return (frac(e), F(0))
    need(type(e) is list and len(e) == 2, "complex entry must be a pair of strings")
    return (frac(e[0]), frac(e[1]))


def matrix(rows, n, name):
    need(type(rows) is list and len(rows) == n, name + ": wrong row count")
    for r in rows:
        need(type(r) is list and len(r) == n, name + ": wrong shape")
    return [[entry(e) for e in r] for r in rows]


def no_dupes(pairs):
    keys = [k for k, _ in pairs]
    need(len(keys) == len(set(keys)), "duplicate JSON key")
    return dict(pairs)


def no_float(s):
    raise CertError("float or constant in JSON: " + s)


def parse(text):
    try:
        return json.loads(text, object_pairs_hook=no_dupes,
                          parse_float=no_float, parse_constant=no_float)
    except (json.JSONDecodeError, RecursionError) as e:
        raise CertError("bad JSON: %s" % e)


def block_inertia(d):
    """Signs of a Hermitian block [[a,b],[conj b,c]] with b != 0, a and c real."""
    a, c, b2 = d[0][0][0], d[1][1][0], d[0][1][0] ** 2 + d[0][1][1] ** 2
    det = a * c - b2
    if det < 0:
        return (1, 1, 0)
    s = 1 if a + c > 0 else -1
    return (2, 0, 0) if s > 0 and det > 0 else (0, 2, 0) if det > 0 else \
        ((1, 0, 1) if s > 0 else (0, 1, 1))


def d_inertia(D, n):
    pos = neg = zero = i = 0
    while i < n:
        need(D[i][i][1] == 0, "D diagonal entry not real")
        sub = D[i + 1][i] if i + 1 < n else ZERO
        if sub == ZERO:
            v = D[i][i][0]
            pos, neg, zero = pos + (v > 0), neg + (v < 0), zero + (v == 0)
            i += 1
            continue
        need(D[i][i + 1] == conj(sub), "D block not Hermitian")
        need(D[i + 1][i + 1][1] == 0, "D diagonal entry not real")
        p, q, z = block_inertia([[D[i][i], D[i][i + 1]], [D[i + 1][i], D[i + 1][i + 1]]])
        pos, neg, zero, i = pos + p, neg + q, zero + z, i + 2
    return pos, neg, zero


def check(text):
    """Return (pos, neg, zero) for the matrix M in the certificate, or raise CertError."""
    c = parse(text)
    need(type(c) is dict, "certificate must be an object")
    need(set(c) in ({"M", "P", "L", "D"}, {"M", "P", "L", "D", "claim"}), "wrong keys")
    M = c["M"]
    need(type(M) is list and 1 <= len(M) <= MAXN, "bad M")
    n = len(M)
    M, L, D = matrix(M, n, "M"), matrix(c["L"], n, "L"), matrix(c["D"], n, "D")
    P = c["P"]
    need(type(P) is list and len(P) == n and all(type(p) is int for p in P)
         and sorted(P) == list(range(n)), "P is not a permutation")
    for i in range(n):
        for j in range(n):
            need(M[i][j] == conj(M[j][i]), "M not Hermitian")
            need(D[i][j] == ZERO or abs(i - j) <= 1, "D not block diagonal")
            need(D[i][j] == conj(D[j][i]), "D not Hermitian")
            need(L[i][j] == (ONE if i == j else ZERO) if j >= i else True, "L not unit lower triangular")
    # blocks may not overlap: two adjacent nonzero subdiagonals are rejected
    for i in range(n - 2):
        need(not (D[i + 1][i] != ZERO and D[i + 2][i + 1] != ZERO), "overlapping D blocks")
    inertia = d_inertia(D, n)
    for i in range(n):
        for j in range(n):
            lhs = M[P[i]][P[j]]
            rhs = ZERO
            for k in range(n):
                for m in range(max(0, k - 1), min(n, k + 2)):
                    if D[k][m] != ZERO:
                        rhs = add(rhs, mul(mul(L[i][k], D[k][m]), conj(L[j][m])))
            need(lhs == rhs, "P M P* != L D L* at (%d,%d)" % (i, j))
    if "claim" in c:
        cl = c["claim"]
        need(type(cl) is list and len(cl) == 3 and all(type(x) is int for x in cl)
             and tuple(cl) == inertia, "claimed inertia %r != verified %r" % (cl, inertia))
    return inertia


if __name__ == "__main__":
    try:
        with open(sys.argv[1], encoding="utf-8") as fh:
            print("%d %d %d" % check(fh.read()))
    except (CertError, OSError, IndexError, UnicodeDecodeError, RecursionError) as e:
        print("REJECT: %s" % e, file=sys.stderr)
        sys.exit(1)
