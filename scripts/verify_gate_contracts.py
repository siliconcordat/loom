"""Deterministic verification of docs/09-gate-contracts.md in siliconcordat/loom.

Standard-library only (Apache-2.0). Run with:
    python3 -B -W error -m unittest -v scripts/verify_gate_contracts.py
    python3 -O -B -W error -m unittest -v scripts/verify_gate_contracts.py
    python3 -B scripts/verify_gate_contracts.py --report

Every check is a function that raises CheckFailed, so python3 -O removes nothing. Each
test class ends with a test that breaks what the checks guard and requires them to fail.
All arithmetic that the document calls exact is done with fractions.Fraction.
"""

import contextlib
import decimal
import hashlib
import io
import itertools
import json
import math
import os
import random
import struct
import sys
import tempfile
import types
import unittest
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
GATECHECK_PATH = os.path.join(HERE, "gatecheck.py")
SEED = 20261120


class CheckFailed(Exception):
    """A guarded statement does not hold."""


def require(cond, msg):
    if not cond:
        raise CheckFailed(msg)


def goes_red(fn, *args):
    """True when fn(*args) raises CheckFailed. Any other exception is a bug and propagates."""
    try:
        fn(*args)
    except CheckFailed:
        return True
    return False


@contextlib.contextmanager
def broken(name, replacement):
    """Swap one function of this module for a broken one, to show that the checks notice."""
    module = sys.modules[__name__]
    original = getattr(module, name)
    setattr(module, name, replacement)
    try:
        yield original
    finally:
        setattr(module, name, original)


# ======================================================================================
# Part 1. Contract 1: the conformance harness against a leaky and a strict toy gate
# ======================================================================================
def load_gatecheck(source=None, name="gatecheck_under_test"):
    """gatecheck.py, or a patched copy of its source text, as a fresh module."""
    if source is None:
        with open(GATECHECK_PATH, encoding="utf-8") as fh:
            source = fh.read()
    mod = types.ModuleType(name)
    mod.__file__ = GATECHECK_PATH
    sys.modules[name] = mod     # dataclasses look their module up while the class is built
    try:
        exec(compile(source, GATECHECK_PATH, "exec", dont_inherit=True), mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod


def check_self_test(g, real=False):
    require(g.self_test(quiet=True, real=real) == 0, "the harness self-test does not match its pinned violations")


def check_toy_counts(g, real=False):
    """The counts quoted in docs/09 section 3.3, read from the result and not from the pinned table."""
    leaky, strict = g.run_toy("leaky", real), g.run_toy("strict", real)
    got = {k: len(leaky[k]["violations"]) for k in g.RELATIONS}
    require(got == {"R1": 5, "R2": 9, "R3": 11, "R4": 2, "R5": 2}, f"leaky toy counts {got}")
    require((leaky["R3"]["bypass"], leaky["R3"]["spelling"]) == (6, 5), "leaky R3 classes")
    require(len(leaky["R4"]["exposures"]) == 1 and len(leaky["R2"]["to_read"]) == 1, "leaky exposure or unread deletion")
    require(all(v["status"] == "fail" for v in leaky["summary"].values()), "leaky toy does not fail every relation")
    require(all(len(strict[k]["violations"]) == 0 for k in g.RELATIONS), "strict toy has a violation")
    require(all(v["status"] == "pass" for v in strict["summary"].values()), "strict toy does not pass every relation")
    require(strict["R3"]["soft"] == [] and strict["R4"]["exposures"] == [] and strict["baseline"] == [], "strict toy extras")
    return {"leaky": got, "leaky_runs": leaky["runs"], "strict_runs": strict["runs"]}


def check_status_rules(g):
    """Result statuses and R2 rules that the two toy gates do not reach."""
    class FnGate(g.Adapter):
        shrink_limit = 0

        def __init__(self, fn, **kw):
            self.fn = fn
            self.__dict__.update(kw)

        def run_inproc(self, text, meta):
            try:
                ok = bool(self.fn(json.loads(text)))
            except Exception:
                return g.Verdict(False, "", ("CRASH",), True)
            return g.Verdict(ok, "ok" if ok else "", () if ok else ("C",))

        def run(self, text, meta, flags):
            return self.run_inproc(text, meta)

    def fx(name, obj):
        return g.Fixture(name, json.dumps(obj))

    def run(ad, acc, rej):
        return g.Engine(ad, acc, rej).all()

    def status(res):
        return {k: v["status"] for k, v in res["summary"].items()}

    acc, rej = g.toy_fixtures()
    # 1. A sampled run is never a pass.
    capped = g.ToyAdapter("strict", real=False)
    capped.cap = 5
    s = status(run(capped, acc, rej))
    require(s["R2"] == "not_shown" and s["R3"] == "not_shown", f"a sampled run reported {s['R2']} and {s['R3']}")
    # 2. An accepted deletion that nobody has read is never a pass.
    opt = FnGate(lambda d: d["a"] == 1 and d.get("b", 2) == 2)
    res = run(opt, [fx("good", {"a": 1, "c": 0})], [fx("bad", {"a": 1, "b": 3, "c": 5})])
    require(status(res)["R2"] == "not_shown" and len(res["R2"]["to_read"]) == 1 and not res["R2"]["violations"],
            "an unread accepted deletion was not reported as not_shown")
    # 3. A deletion inside declared content is expected.
    def bag(d):
        return all(type(v) is int for v in d["tensors"].values())
    fixtures = ([fx("good", {"tensors": {"a": 1, "c": 2}})], [fx("bad", {"tensors": {"a": 1, "b": "x"}})])
    require(status(run(FnGate(bag), *fixtures))["R2"] == "not_shown", "content deletion without a declaration")
    res = run(FnGate(bag, content_paths=(("tensors",),)), *fixtures)
    require(status(res)["R2"] == "pass" and len(res["R2"]["content"]) == 1, "declared content deletion was not a pass")
    # 4. Deleting the only element of a list that is never empty is a violation.
    listy = FnGate(lambda d: all(x == 1 for x in d["items"]))
    res = run(listy, [fx("good", {"items": [1, 1]})], [fx("bad", {"items": [2]})])
    require(status(res)["R2"] == "fail" and [v["deleted"] for v in res["R2"]["violations"]] == ["items/0"],
            "emptying a list was not reported")
    # 5. A gate that stops at its first failure cannot show isolation by reason names alone.
    one = lambda d: d["a"] == 1
    for fail_fast, want in ((True, "not_shown"), (False, "pass")):
        ad = FnGate(one, check_names=("C",), fail_fast=fail_fast)
        got = status(run(ad, [fx("good", {"a": 1})], [fx("bad", {"a": 2})]))["R5"]
        require(got == want, f"R5 with fail_fast={fail_fast} reported {got}")
    # 6. A gate that accepts nothing shows nothing.
    res = run(FnGate(lambda d: False), [fx("good", {"a": 1})], [fx("bad", {"a": 2})])
    s = status(res)
    require(res["vacuous"] == ["good"] and s["R3"] == "not_shown" and s["R4"] == "vacuous", f"reject-all gate reported {s}")
    require(status(run(FnGate(lambda d: False), [fx("good", {"a": 1})], []))["R3"] == "vacuous", "no usable fixture at all")
    # 7. A bare assert that no fixture reaches is an exposure, not a failure.
    keep = [f for f in rej if f.name not in ("bad-n7", "bad-legacy")]
    res = run(g.ToyAdapter("leaky", real=False), acc, keep)
    require(status(res)["R4"] == "exposed" and not res["R4"]["violations"], "exposure-only run was not reported as exposed")
    # 8. With no declared rules, required keys are the keys every accepted fixture carries.
    inferred = g.ToyAdapter("leaky", real=False)
    inferred.required_keys = None
    res = run(inferred, acc, rej)
    require(res["R2"]["required_source"].startswith("inferred") and len(res["R2"]["violations"]) == 9, "inferred required keys")
    # 9. An in-process fast path that answers differently from the real run is an adapter error.
    class Split(FnGate):
        def run(self, text, meta, flags):
            v = self.run_inproc(text, meta)
            return g.Verdict(v.accept, v.value + "-real", v.codes)
    res = run(Split(one), [fx("good", {"a": 1})], [fx("bad", {"a": 2})])
    require(status(res)["R4"] == "fail" and res["R4"]["inproc_mismatches"] == ["good", "bad"],
            "an in-process path that differs from the real run was not reported")


ADAPTER_FILE = '''
import gatecheck as g


def build_strict(repo):
    acc, rej = g.toy_fixtures()
    return g.ToyAdapter("strict", real=False), acc, rej


def build_leaky(repo):
    acc, rej = g.toy_fixtures()
    return g.ToyAdapter("leaky", real=False), acc, rej
'''


def check_cli(g):
    """The documented command line: a named builder, the result files, and the exit codes."""
    saved = sys.modules.get("gatecheck")
    sys.modules["gatecheck"] = g       # the adapter file imports the module under test by this name
    try:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "toy_adapter.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(ADAPTER_FILE)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    rc_strict = g.main(["--adapter", path + ":build_strict", "--out", os.path.join(d, "s")])
                    rc_leaky = g.main(["--adapter", path + ":build_leaky", "--out", os.path.join(d, "l")])
                    rc_missing = g.main(["--adapter", path, "--out", os.path.join(d, "m")])
                except Exception as exc:
                    raise CheckFailed(f"the command line crashed: {type(exc).__name__}: {exc}") from None
            require((rc_strict, rc_leaky, rc_missing) == (0, 1, 2), f"exit codes {(rc_strict, rc_leaky, rc_missing)}")
            require("build_leaky, build_strict" in err.getvalue(), "a missing builder did not list the builders found")
            with open(os.path.join(d, "s", "summary.json"), encoding="utf-8") as fh:
                summary = json.load(fh)
            require(all(v["status"] == "pass" for v in summary["relations"].values()), "strict summary file")
            require(len(summary["harness_sha256"]) == 64 and summary["fixtures"] == {"accepted": 2, "rejected": 13}, "summary header")
            require(sorted(os.listdir(os.path.join(d, "l"))) == ["R1.json", "R2.json", "R3.json", "R4.json", "R5.json",
                                                                "baseline.json", "summary.json"], "result files")
    finally:
        if saved is None:
            sys.modules.pop("gatecheck", None)
        else:
            sys.modules["gatecheck"] = saved


def check_harness(g):
    check_self_test(g)
    check_toy_counts(g)
    check_status_rules(g)
    check_cli(g)


# Each entry breaks one path of gatecheck.py: (what is broken, exact source text, replacement).
# The first fourteen are the breaks tried in the two earlier reviews of the harness.
SABOTAGES = [
    ("R1 reports nothing",
     "for (lab, t), v in zip(defaults, vs) if v.accept]", "for (lab, t), v in zip(defaults, vs) if False]"),
    ("R2 reports nothing",
     "            if not v.accept:\n                continue\n            after = delp(o, p)",
     "            if True:\n                continue\n            after = delp(o, p)"),
    ("R3 never reports a spelling of a pinned value", "                spelling.append(rec)", "                pass"),
    ("R3 never reports a rejected input accepted after re-spelling", "                bypass.append(rec)", "                pass"),
    ("R4 never reports a verdict difference", "if (b.accept, b.value) != (v.accept, v.value):", "if False:"),
    ("R5 reports no missing isolating fixture", "missing = [c for c in names if c not in seen]", "missing = []"),
    ("strict gate over-reported by R3 (typed comparison removed)",
     "    if type(a) is not type(b):\n        return False\n", "    return False\n"),
    ("strict gate over-reported by R2 (every accepted key deletion counted)",
     "                hard = norm(p) in required", "                hard = True"),
    ("R4 planted-assert check never fires", "            if not p.accept and o.accept:", "            if False:"),
    ("R1 status words of accepted fixtures not mutated",
     "        for f in self.acc:    # status words", "        for f in []:    # status words"),
    ("R5 a fixture with several codes counts as isolating",
     "if not v.accept and len(set(v.codes)) == 1:", "if not v.accept and len(set(v.codes)) >= 1:"),
    ("R2 reproducers are not shrunk",
     "                if not self.accepts(c, f.meta, f.text) and self.accepts(delp(c, p), f.meta, f.text):",
     "                if False:"),
    ("R3 pinned-leaf probe always says the leaf is free",
     "                if self.accepts(setp(o, p, probe), f.meta, f.text):", "                if True:"),
    ("fixtures the gate wrongly accepts are kept in R2 and R5",
     "        self.rej = [f for f in self.rej_all if f.name not in wrong]", "        self.rej = list(self.rej_all)"),
    ("R3 skips true written as 1 on rejected inputs (the earlier harness did)",
     "if lab not in SAME_VALUE or (isinstance(v, str) and not v.strip()):",
     'if lab not in SAME_VALUE or (lab == "bool-as-int" and v is True) or (isinstance(v, str) and not v.strip()):'),
    ("R3 reproducers are not shrunk",
     "                if self.accepts(m2, f.meta, f.text) and not self.accepts(other, f.meta, f.text):",
     "                if False:"),
    ("R5 check deletion never reports a deletable check", "            if not killed:", "            if False:"),
    ("R2 does not recognise a deletion that restores an accepted fixture",
     "            elif any(same(after, a) for a in acc):", "            elif False:"),
    ("R2 ignores declared content paths",
     "            elif any(norm(p)[:len(c)] == c for c in content):", "            elif False:"),
    ("R2 never counts emptying a list",
     "                hard = len(get(o, p[:-1])) == 1 and norm(p[:-1]) not in empty_ok", "                hard = False"),
    ("R2 counts the R1 defect again without saying so",
     'rec["also_r1"] = bool(r1["violations"]) and bool(STATUS_KEY.search(str(p[-1])))', 'rec["also_r1"] = False'),
    ("a sampled or unread R2 run is reported as a pass",
     '                s = "not_shown" if (r["sampled"] or unread) else "pass"', '                s = "pass"'),
    ("a sampled R3 run is reported as a pass",
     '                s = "not_shown" if (r["sampled"] or not any_accepted) else "pass"', '                s = "pass"'),
    ("a planted exposure is reported as a pass",
     '                s = "fail" if n else ("exposed" if r["exposures"] else "pass")', '                s = "fail" if n else "pass"'),
    ("a first-failure gate is reported as isolated",
     '            elif r["fail_fast"] and not r["variants"]:', "            elif False:"),
    ("a gate that accepts nothing is reported as passing R4",
     '            if s == "pass" and not any_accepted:', "            if False:"),
    ("accepted fixtures the gate rejects are kept",
     "        self.acc = [f for f in self.acc_all if f.name not in wrong]", "        self.acc = list(self.acc_all)"),
    ("the in-process toy gate drops assert statements",
     "        return self._call(text, 0, False)", "        return self._call(text, 1, False)"),
    ("the stand-in for python3 -O keeps assert statements",
     'return self._call(text, 1 if "-O" in flags else 0, "error" in flags)',
     'return self._call(text, 0, "error" in flags)'),
    ("the stand-in for python3 -W error ignores warnings",
     'return self._call(text, 1 if "-O" in flags else 0, "error" in flags)',
     'return self._call(text, 1 if "-O" in flags else 0, False)'),
    ("the command line calls build() whatever builder was named (the earlier harness did)",
     "    return getattr(mod, func)(repo)", "    return mod.build(repo)"),
    ("the command line exits 0 when a relation fails",
     '    return 1 if any(v["status"] == "fail" for v in res["summary"].values()) else 0', "    return 0"),
]


def sabotage(source, old, new):
    require(source.count(old) == 1, f"sabotage target not found exactly once: {old[:60]!r}")
    return source.replace(old, new)


class TestGateHarness(unittest.TestCase):
    """docs/09 section 3: what a gate reads."""

    @classmethod
    def setUpClass(cls):
        cls.g = load_gatecheck()
        with open(GATECHECK_PATH, encoding="utf-8") as fh:
            cls.source = fh.read()

    def test_doc09_c1_leaky_toy_breaks_every_relation_strict_toy_breaks_none(self):
        # Real interpreter runs for R4: python3, python3 -O and python3 -W error.
        check_self_test(self.g, real=True)
        counts = check_toy_counts(self.g, real=True)
        self.assertEqual(counts["leaky"], {"R1": 5, "R2": 9, "R3": 11, "R4": 2, "R5": 2})
        # The in-process stand-in for the three interpreter modes gives the same pinned result.
        check_self_test(self.g, real=False)

    def test_doc09_c1_statuses_and_rules_the_toys_do_not_reach(self):
        check_status_rules(self.g)

    def test_doc09_c1_command_line_and_named_builder(self):
        check_cli(self.g)

    def test_doc09_c1_every_harness_sabotage_goes_red(self):
        check_harness(self.g)      # control: the unbroken harness passes every check used below
        stayed_green = []
        for name, old, new in SABOTAGES:
            broken = load_gatecheck(sabotage(self.source, old, new), "gatecheck_sabotaged")
            if not goes_red(check_harness, broken):
                stayed_green.append(name)
        self.assertEqual(stayed_green, [])
        self.assertEqual(len(SABOTAGES), 32)


# ======================================================================================
# Part 2. Contract 4: the latch, in exact rational arithmetic
# ======================================================================================
def tr(A):
    return [list(r) for r in zip(*A)]


def mm(A, B):
    Bt = tr(B)
    return [[sum(a * b for a, b in zip(r, c)) for c in Bt] for r in A]


def mv(A, v):
    return [sum(a * b for a, b in zip(r, v)) for r in A]


def dot(u, v):
    return sum(a * b for a, b in zip(u, v))


def sub(u, v):
    return [a - b for a, b in zip(u, v)]


def add(u, v):
    return [a + b for a, b in zip(u, v)]


def scale(c, u):
    return [c * a for a in u]


def rref(M):
    """Reduced row echelon form and pivot columns, exact."""
    M = [[F(x) for x in row] for row in M]
    piv, r = [], 0
    for c in range(len(M[0]) if M else 0):
        p = next((i for i in range(r, len(M)) if M[i][c] != 0), None)
        if p is None:
            continue
        M[r], M[p] = M[p], M[r]
        M[r] = [x / M[r][c] for x in M[r]]
        for i in range(len(M)):
            if i != r and M[i][c] != 0:
                M[i] = [x - M[i][c] * y for x, y in zip(M[i], M[r])]
        piv.append(c)
        r += 1
        if r == len(M):
            break
    return M, piv


def rank(A):
    return len(rref(A)[1])


def solve(A, b):
    """One exact solution of A x = b (free variables set to 0)."""
    k = len(A[0])
    M, piv = rref([list(row) + [bb] for row, bb in zip(A, b)])
    require(k not in piv, "inconsistent linear system")
    x = [F(0)] * k
    for i, c in enumerate(piv):
        x[c] = M[i][k]
    return x


def null_space(A):
    """A basis of {x : A x = 0}."""
    k = len(A[0])
    M, piv = rref(A)
    basis = []
    for free in (c for c in range(k) if c not in piv):
        x = [F(0)] * k
        x[free] = F(1)
        for i, c in enumerate(piv):
            x[c] = -M[i][free]
        basis.append(x)
    return basis


def outside_part(w, Phi):
    """w minus its orthogonal projection on the column space of Phi, by Gram-Schmidt on the columns."""
    basis = []
    for col in tr(Phi):
        v = list(col)
        for b in basis:
            v = sub(v, scale(dot(v, b) / dot(b, b), b))
        if any(x != 0 for x in v):
            basis.append(v)
    out = list(w)
    for b in basis:
        out = sub(out, scale(dot(out, b) / dot(b, b), b))
    return out


def fit(Phi, r0, weights=None):
    """A minimiser of the (weighted) squared norm of r0 - Phi theta, from the normal equations."""
    Wt = tr(Phi) if weights is None else [[w * x for w, x in zip(weights, col)] for col in tr(Phi)]
    return solve(mm(Wt, Phi), mv(Wt, r0))


def residual(Phi, r0, theta):
    return sub(r0, mv(Phi, theta))


def rnd(rng, lo=-5, hi=5, den=7):
    return F(rng.randint(lo, hi), rng.randint(1, den))


def rvec(rng, n):
    return [rnd(rng) for _ in range(n)]


def instance(rng, m, k, rk):
    """An m x k rational matrix of rank exactly rk, as a product of two random factors."""
    while True:
        Phi = mm([rvec(rng, rk) for _ in range(m)], [rvec(rng, k) for _ in range(rk)])
        if rank(Phi) == rk:
            return Phi


def check_latch(Phi, r0, theta, audits_in_span):
    """Claim 10 (a) and (b): after adaptation Phi^T r = 0, and every audit in the column space reads zero."""
    r = residual(Phi, r0, theta)
    require(all(x == 0 for x in mv(tr(Phi), r)), "Phi^T r is not zero after adaptation")
    for w in audits_in_span:
        require(dot(w, r) == 0, "an audit inside the column space did not read zero")
    return r


def check_surviving_fraction(Phi, w, claimed):
    """Claim 10 (c): for a leak along w, the audit w keeps the fraction `claimed` of its reading."""
    require(dot(w, w) != 0, "zero audit")
    r = residual(Phi, w, fit(Phi, w))
    require(dot(w, r) / dot(w, w) == claimed, "surviving fraction differs from the claim")


def check_survivor_bound(Phi, audits, claimed_bound):
    """Claim 10 (d): the audits' readings on post-adaptation residuals span at most claimed_bound dimensions."""
    survivors = rank([outside_part(w, Phi) for w in audits])
    require(survivors <= claimed_bound, f"{survivors} independent audits survive, more than the claimed {claimed_bound}")
    return survivors


def check_budget(Phi, r0, r, claimed_left):
    """The leftover total: |r0|^2 splits exactly into the absorbed part and |r|^2, and the trace of I - P,
    which is the expected |r|^2 for uncorrelated noise of unit width, equals claimed_left."""
    absorbed = sub(r0, r)
    require(dot(r0, r0) == dot(absorbed, absorbed) + dot(r, r), "the squared norm of r0 does not split into absorbed and left over")
    m = len(r0)
    trace = sum(outside_part([F(int(i == j)) for j in range(m)], Phi)[i] for i in range(m))
    require(trace == claimed_left, f"the trace of I - P is {trace}, not the claimed {claimed_left}")


def run_latch_census(seed=SEED, full_rank=200, rank_deficient=100, boundary=100):
    rng = random.Random(seed)
    out = {"full_rank": 0, "rank_deficient": 0, "boundary": 0, "boundary_strictly_between_0_and_1": 0, "weighted": 0}
    plan = [("full_rank", full_rank), ("rank_deficient", rank_deficient)]
    for kind, count in plan:
        for _ in range(count):
            k = rng.randint(1, 4) if kind == "full_rank" else rng.randint(2, 4)
            rk = k if kind == "full_rank" else rng.randint(1, k - 1)
            m = rng.randint(rk + 1, rk + 5)
            Phi, r0 = instance(rng, m, k, rk), rvec(rng, m)
            theta = fit(Phi, r0)
            audits = [mv(Phi, rvec(rng, k)) for _ in range(3)]
            r = check_latch(Phi, r0, theta, audits)
            # theta is a minimiser, exactly: any other theta adds the squared norm of Phi d
            d = rvec(rng, k)
            other = residual(Phi, r0, add(theta, d))
            require(dot(other, other) == dot(r, r) + dot(mv(Phi, d), mv(Phi, d)), "theta is not a minimiser")
            # the residual after adaptation is the part of r0 outside the column space, by an independent route
            require(r == outside_part(r0, Phi), "post-adaptation residual is not the outside part of r0")
            # the total that adaptation cannot remove, and its expected size for unit noise
            check_budget(Phi, r0, r, m - rk)
            # whatever the true gap: adding any amount inside the column space changes nothing afterwards
            shifted = add(r0, mv(Phi, rvec(rng, k)))
            require(residual(Phi, shifted, fit(Phi, shifted)) == r, "the absorbed part of the gap changed the residual")
            # a second minimiser, when Phi is rank deficient, leaves the same residual
            for nv in null_space(Phi)[:1]:
                require(residual(Phi, r0, add(theta, nv)) == r, "another minimiser changed the residual")
            # general reading: w.r = (outside part of w).r0 for any audit w
            w = rvec(rng, m)
            require(dot(w, r) == dot(outside_part(w, Phi), r0), "audit reading is not the outside part against r0")
            # (d) at most m - rank audits survive, and the left null space attains it
            left_null = null_space(tr(Phi))
            require(len(left_null) == m - rk, "left null space has the wrong dimension")
            check_survivor_bound(Phi, [rvec(rng, m) for _ in range(m - rk + 2)], m - rk)
            require(check_survivor_bound(Phi, left_null, m - rk) == m - rk, "the bound m - rank is not attained")
            for n_ in left_null:
                require(dot(n_, r) == dot(n_, r0), "an audit orthogonal to the column space changed its reading")
            out[kind] += 1
    for _ in range(boundary):
        k = rng.randint(1, 3)
        m = rng.randint(k + 1, k + 5)
        Phi = instance(rng, m, k, k)
        w = rvec(rng, m)
        if all(x == 0 for x in w):
            continue
        wo = outside_part(w, Phi)
        sin2 = dot(wo, wo) / dot(w, w)      # squared sine of the angle between w and the column space
        check_surviving_fraction(Phi, w, sin2)
        require(0 <= sin2 <= 1, "squared sine out of range")
        out["boundary"] += 1
        out["boundary_strictly_between_0_and_1"] += 0 < sin2 < 1
        check_surviving_fraction(Phi, mv(Phi, [F(1)] * k), F(0))                 # inside: nothing survives
        check_surviving_fraction(Phi, null_space(tr(Phi))[0], F(1))             # orthogonal: everything survives
        # weighted least squares: the blind directions are W times the column space
        wts = [F(rng.randint(1, 9), rng.randint(1, 4)) for _ in range(m)]
        r0 = rvec(rng, m)
        rw = residual(Phi, r0, fit(Phi, r0, wts))
        require(all(x == 0 for x in mv(tr(Phi), [a * b for a, b in zip(wts, rw)])), "Phi^T W r is not zero")
        u = rvec(rng, k)
        require(dot([a * b for a, b in zip(wts, mv(Phi, u))], rw) == 0, "a weighted in-span audit did not read zero")
        out["weighted"] += 1
    return out


def poly_map(A, B, c, theta):
    """phi(theta) = A theta + (theta^T B theta) c: a residual map that is not linear in theta."""
    q = dot(theta, mv(B, theta))
    return add(mv(A, theta), scale(q, c))


def poly_jacobian(A, B, c, theta):
    grad_q = add(mv(B, theta), mv(tr(B), theta))
    return [[A[i][j] + c[i] * grad_q[j] for j in range(len(theta))] for i in range(len(A))]


def check_stationary(r0, A, B, c, theta, directions):
    """Exact derivative of |r0 - phi(theta + t u)|^2 at t = 0, by a stencil that is exact for degree 4."""
    def g(t, u):
        r = sub(r0, poly_map(A, B, c, add(theta, scale(t, u))))
        return dot(r, r)
    for u in directions:
        slope = (g(F(-2), u) - 8 * g(F(-1), u) + 8 * g(F(1), u) - g(F(2), u)) / 12
        require(slope == 0, "theta is not a stationary point of the squared residual norm")


def run_local_latch_census(seed=SEED, count=60):
    """Claim 10, remark on stationary points: at a stationary point of a differentiable residual map, audits in the Jacobian's column space read zero."""
    rng = random.Random(seed + 1)
    done = 0
    for _ in range(count):
        k = rng.randint(1, 3)
        m = rng.randint(k + 1, k + 4)
        A, B, c, theta = [rvec(rng, k) for _ in range(m)], [rvec(rng, k) for _ in range(k)], rvec(rng, m), rvec(rng, k)
        J = poly_jacobian(A, B, c, theta)
        left_null = null_space(tr(J))
        r_star = [F(0)] * m
        for n_ in left_null:
            r_star = add(r_star, scale(F(rng.randint(1, 5)), n_))
        if all(x == 0 for x in r_star):
            continue
        r0 = add(r_star, poly_map(A, B, c, theta))
        dirs = [rvec(rng, k) for _ in range(3)] + [[F(int(i == j)) for i in range(k)] for j in range(k)]
        check_stationary(r0, A, B, c, theta, dirs)
        for _ in range(3):
            require(dot(mv(J, rvec(rng, k)), r_star) == 0, "an audit in the Jacobian's column space did not read zero")
        require(dot(r_star, r_star) != 0, "the residual itself should still be visible")
        done += 1
    return done


def run_descent_census(seed=SEED, count=60, steps=5):
    """Claim 10, remark on steps before convergence: every gradient step leaves the outside part alone and shrinks the inside part."""
    rng = random.Random(seed + 2)
    done = 0
    for _ in range(count):
        k = rng.randint(1, 3)
        m = rng.randint(k + 1, k + 4)
        Phi, r = instance(rng, m, k, rng.randint(1, k)), rvec(rng, m)
        G = mm(tr(Phi), Phi)
        eta = 1 / sum(G[i][i] for i in range(k))       # 1 / trace, at most 1 / (largest eigenvalue)
        fixed = outside_part(r, Phi)
        for _ in range(steps):
            nxt = sub(r, scale(eta, mv(Phi, mv(tr(Phi), r))))
            require(outside_part(nxt, Phi) == fixed, "a gradient step changed the part outside the column space")
            inside_before, inside_after = sub(r, fixed), sub(nxt, fixed)
            if any(x != 0 for x in inside_before):
                require(dot(inside_after, inside_after) < dot(inside_before, inside_before),
                        "a gradient step did not shrink the part inside the column space")
            r = nxt
        done += 1
    return done


class TestLatch(unittest.TestCase):
    """docs/09 section 6: when a gate is judged."""

    def test_doc09_c4_latch_on_random_rational_instances(self):
        census = run_latch_census()
        self.assertEqual((census["full_rank"], census["rank_deficient"]), (200, 100))

    def test_doc09_c4_squared_sine_boundary_and_weights(self):
        census = run_latch_census(full_rank=0, rank_deficient=0)
        self.assertEqual(census["boundary"], 100)
        self.assertEqual(census["weighted"], 100)
        self.assertEqual(census["boundary_strictly_between_0_and_1"], 100)

    def test_doc09_c4_stationary_point_and_gradient_steps(self):
        self.assertEqual(run_local_latch_census(), 60)
        self.assertEqual(run_descent_census(), 60)

    def test_doc09_c4_smallest_examples(self):
        # Two residuals, one adjustable direction (1, 1). The audit r1 + r2 is blind, r1 - r2 is not.
        Phi, r0 = [[F(1)], [F(1)]], [F(5), F(1)]
        r = check_latch(Phi, r0, fit(Phi, r0), [[F(1), F(1)]])
        self.assertEqual(r, [F(2), F(-2)])
        self.assertEqual(dot([F(1), F(-1)], r), dot([F(1), F(-1)], r0))
        # An audit at 45 degrees to the column space keeps one half.
        check_surviving_fraction(Phi, [F(1), F(0)], F(1, 2))
        # Rank-deficient Phi: two minimisers, one residual, two different outside anchors.
        Phi2, target = [[F(1), F(1)]], [F(2)]
        a, b = [F(1), F(1)], [F(2), F(0)]
        self.assertEqual(residual(Phi2, target, a), residual(Phi2, target, b))
        self.assertNotEqual(dot([F(1), F(0)], a), dot([F(1), F(0)], b))

    def test_doc09_c4_latch_checks_go_red(self):
        Phi = [[F(1), F(0)], [F(1), F(1)], [F(1), F(2)], [F(1), F(3)]]
        r0 = [F(1), F(0), F(2), F(1)]
        theta = fit(Phi, r0)
        inside, outside = mv(Phi, [F(2), F(-1)]), [F(1), F(-1), F(1), F(-1)]
        check_latch(Phi, r0, theta, [inside])                                   # control
        self.assertTrue(goes_red(check_latch, Phi, r0, [theta[0] + F(1, 10**6), theta[1]], [inside]))
        self.assertTrue(goes_red(check_latch, Phi, r0, theta, [outside]))
        wo = outside_part(outside, Phi)
        sin2 = dot(wo, wo) / dot(outside, outside)
        check_surviving_fraction(Phi, outside, sin2)                            # control
        self.assertTrue(goes_red(check_surviving_fraction, Phi, outside, 1 - sin2))      # cosine squared
        self.assertTrue(goes_red(check_surviving_fraction, Phi, outside, sin2 + F(1, 10**6)))
        full = [[F(int(i == j)) for i in range(4)] for j in range(4)]
        self.assertEqual(check_survivor_bound(Phi, full, 2), 2)                # control: m - rank = 4 - 2
        self.assertTrue(goes_red(check_survivor_bound, Phi, full, 1))
        r_ok = residual(Phi, r0, theta)
        check_budget(Phi, r0, r_ok, 2)                                          # control: m - rank = 4 - 2
        self.assertTrue(goes_red(check_budget, Phi, r0, r_ok, 3))                # a wrong count of what is left
        self.assertTrue(goes_red(check_budget, Phi, r0, [r_ok[0] + F(1, 10**6)] + r_ok[1:], 2))   # the total does not split
        # A point that is not stationary fails the exact derivative test.
        A, B, c = [[F(1)], [F(2)]], [[F(1)]], [F(1), F(-1)]
        J = poly_jacobian(A, B, c, [F(1)])
        r_star = null_space(tr(J))[0]
        r0n = add(r_star, poly_map(A, B, c, [F(1)]))
        check_stationary(r0n, A, B, c, [F(1)], [[F(1)]])                        # control
        self.assertTrue(goes_red(check_stationary, r0n, A, B, c, [F(3, 2)], [[F(1)]]))
        # A census run on a fit that is slightly off is caught.
        true_fit = fit
        with broken("fit", lambda Phi_, r0_, weights=None: [x + F(1, 10**9) for x in true_fit(Phi_, r0_, weights)]):
            self.assertTrue(goes_red(run_latch_census, SEED, 5, 0, 0))
        # So is a projection that forgets one basis vector.
        with broken("outside_part", lambda w, Phi_: list(w)):
            self.assertTrue(goes_red(run_latch_census, SEED, 5, 0, 0))


# ======================================================================================
# Part 2b. Contract 4: absorbing a failed anchor, and revising the specification (Claim 9)
# ======================================================================================
SEED_ABSORB = 20261121
SEED_SEVERAL = 20261122
SEED_REVISE = 20261123


def project(Phi, v):
    """The orthogonal projection of v on the column space of Phi, exact."""
    return sub(v, outside_part(v, Phi))


def hstack(A, B):
    return [list(r) + list(s) for r, s in zip(A, B)]


def absorb_one(Phi, r_star, a):
    """The least change to the output, inside the column space, that makes the anchor a read zero."""
    p = project(Phi, a)
    pp = dot(p, p)
    e = dot(a, r_star)
    require(pp != 0, "the anchor has no part in the column space, so no adaptation can silence it")
    return sub(r_star, scale(e / pp, p)), e, p, pp


def inflation_law(e, pp):
    return e * e / pp


def check_inflation(Phi, r0, a, law=None):
    """Absorbing one anchor: it reads zero, and the squared residual rises by exactly e^2 / |P a|^2."""
    law = law or inflation_law
    r_star = outside_part(r0, Phi)
    r_ad, e, p, pp = absorb_one(Phi, r_star, a)
    require(dot(a, r_ad) == 0, "the absorbed anchor does not read zero")
    require(dot(r_ad, r_ad) == dot(r_star, r_star) + law(e, pp), "the cost of absorbing differs from the law")
    return r_star, r_ad


def check_silencing(Phi, r0, a, delta, law=None):
    """Any change delta that is an adaptation (inside the column space) and silences a costs at least the law.
    The least change meets it with equality."""
    law = law or inflation_law
    r_star = outside_part(r0, Phi)
    r_ad, e, p, pp = absorb_one(Phi, r_star, a)
    require(all(x == 0 for x in outside_part(delta, Phi)), "the change is not inside the column space")
    shifted = sub(r_star, delta)
    require(dot(a, shifted) == 0, "the change does not silence the anchor")
    cost = dot(shifted, shifted) - dot(r_star, r_star)
    require(cost >= law(e, pp), "a change that silences the anchor costs less than the law")
    if delta == scale(e / pp, p):
        require(cost == law(e, pp), "the least change does not meet the law with equality")


def check_outside_unchanged(Phi, r_before, r_after, fresh):
    """Absorption leaves the part of the residual outside the column space exactly unchanged. So the outside
    count of every fresh anchor b, ((I - P) b) . r, is the same before and after."""
    require(outside_part(r_after, Phi) == outside_part(r_before, Phi), "the outside part of the residual moved")
    for b in fresh:
        ob = outside_part(b, Phi)
        require(dot(ob, r_after) == dot(ob, r_before), "an outside count moved")
        require(dot(ob, r_before) == dot(b, r_before), "the outside count is not the reading before absorbing")


def old_falsifier_fires(r_before, r_after, fresh):
    """The wording that Falsifier 6 had: fresh anchors drawn after adaptation read smaller, taken over all of
    them, so absorbing is read as closing the gap."""
    before = sum(dot(b, r_before) ** 2 for b in fresh)
    after = sum(dot(b, r_after) ** 2 for b in fresh)
    return after < before


def check_old_falsifier_misfires(Phi, r_before, r_after, fresh):
    """The old falsifier fires, while the outside part is unchanged and the total residual did not fall."""
    require(old_falsifier_fires(r_before, r_after, fresh), "the old falsifier did not fire")
    check_outside_unchanged(Phi, r_before, r_after, fresh)
    require(dot(r_after, r_after) >= dot(r_before, r_before), "the total residual fell")


def helps_rule(x):
    if 0 < x < 2:
        return "helps"
    if x in (0, 2):
        return "tie"
    return "hurts"


def check_helps_rule(Phi, r0, a, b, rule=helps_rule, reading=lambda e_b, x: e_b * (1 - x)):
    """On a fresh anchor b the reading becomes e_b (1 - x) with x = e (P a . b) / (e_b |P a|^2), and its size
    falls, stays or rises as the rule says."""
    r_star = outside_part(r0, Phi)
    r_ad, e, p, pp = absorb_one(Phi, r_star, a)
    e_b = dot(b, r_star)
    require(e_b != 0, "the fresh anchor reads zero before absorbing, so x is not defined")
    x = e * dot(p, b) / (e_b * pp)
    after = dot(b, r_ad)
    require(after == reading(e_b, x), "the reading after absorbing is not e_b (1 - x)")
    actual = "helps" if abs(after) < abs(e_b) else ("tie" if abs(after) == abs(e_b) else "hurts")
    require(actual == rule(x), f"x = {x}: the reading {actual}, the rule says {rule(x)}")
    return x, actual


def check_several_anchors(Phi, r0, anchors, form=None, coefficients=None):
    """Several anchors at once: all read zero, and the squared residual rises by e^T (A^T P A)^-1 e.
    The change is P A s with (A^T P A) s = e. A control may pass other coefficients s."""
    r_star = outside_part(r0, Phi)
    P_anchors = [project(Phi, a) for a in anchors]
    M = [[dot(a, pa) for pa in P_anchors] for a in anchors]
    e = [dot(a, r_star) for a in anchors]
    if form is None:
        form = lambda M_, e_: dot(e_, solve(M_, e_))
    s = solve(M, e) if coefficients is None else coefficients(M, e)
    shift = [sum(c * pa[i] for c, pa in zip(s, P_anchors)) for i in range(len(r_star))]
    r_ad = sub(r_star, shift)
    require(all(dot(a, r_ad) == 0 for a in anchors), "an absorbed anchor does not read zero")
    require(dot(r_ad, r_ad) == dot(r_star, r_star) + form(M, e), "the cost of absorbing several anchors differs from the formula")


def random_case(rng, anchor_count=1):
    """A random exact instance: Phi of rank 1 to 3 with 1 to 4 columns, a residual, and anchors that see Phi."""
    for _ in range(1000):
        m = rng.randint(5, 8)
        rk = rng.randint(1, 3)
        k = rng.randint(rk, 4)
        Phi = instance(rng, m, k, rk)
        r0 = rvec(rng, m)
        r_star = outside_part(r0, Phi)
        anchors = [rvec(rng, m) for _ in range(anchor_count)]
        if all(dot(a, r_star) != 0 and any(project(Phi, a)) for a in anchors):
            return Phi, r0, r_star, anchors
    raise CheckFailed("no instance with anchors that see the column space in 1000 draws")


def run_absorption_census(seed=SEED_ABSORB, count=150):
    rng = random.Random(seed)
    out = {"instances": 0, "rank_deficient": 0, "old_falsifier_fired": 0, "classes": {"helps": 0, "hurts": 0, "tie_at_0": 0, "tie_at_2": 0}}
    while out["instances"] < count:
        Phi, r0, r_star, (a,) = random_case(rng)
        _, r_ad = check_inflation(Phi, r0, a)
        p = project(Phi, a)
        pp = dot(p, p)
        e = dot(a, r_star)
        # Any other way of silencing the anchor inside the column space costs at least as much.
        u = rvec(rng, len(Phi[0]))
        phi_u = mv(Phi, u)
        if dot(a, phi_u) != 0:
            check_silencing(Phi, r0, a, scale(e / dot(a, phi_u), phi_u))
        check_silencing(Phi, r0, a, scale(e / pp, p))
        # Fresh anchors of the same kind, and unrelated ones.
        same = [[ai + F(rng.randint(-1, 1), 4) for ai in a] for _ in range(12)]
        fresh = same + [rvec(rng, len(a)) for _ in range(6)]
        check_outside_unchanged(Phi, r_star, r_ad, fresh)
        if old_falsifier_fires(r_star, r_ad, same):
            check_old_falsifier_misfires(Phi, r_star, r_ad, same)
            out["old_falsifier_fired"] += 1
        # The rule 0 < x < 2, on random anchors and on anchors built to sit at the two ties.
        b0 = rvec(rng, len(a))
        e_b = dot(b0, r_star)
        for b in fresh[12:] + [b0]:
            if dot(b, r_star) != 0:
                x, actual = check_helps_rule(Phi, r0, a, b)
                if actual != "tie":
                    out["classes"][actual] += 1
        if e_b != 0:
            tie0 = sub(b0, scale(dot(p, b0) / pp, p))
            tie2 = add(b0, scale(2 * e_b / e - dot(p, b0) / pp, p))
            require(check_helps_rule(Phi, r0, a, tie0) == (0, "tie"), "the anchor built for x = 0 is not a tie")
            require(check_helps_rule(Phi, r0, a, tie2) == (2, "tie"), "the anchor built for x = 2 is not a tie")
            out["classes"]["tie_at_0"] += 1
            out["classes"]["tie_at_2"] += 1
        out["instances"] += 1
        out["rank_deficient"] += rank(Phi) < len(Phi[0])
    require(out["old_falsifier_fired"] * 2 >= out["instances"], "the old falsifier fires on fewer than half of the instances")
    require(all(v > 0 for v in out["classes"].values()), "a class of the rule was never met")
    return out


def run_several_census(seed=SEED_SEVERAL, count=100):
    rng = random.Random(seed)
    done = 0
    while done < count:
        q = rng.randint(2, 3)
        Phi, r0, r_star, anchors = random_case(rng, q)
        P_anchors = [project(Phi, a) for a in anchors]
        M = [[dot(a, pa) for pa in P_anchors] for a in anchors]
        if rank(M) < q:
            continue
        check_several_anchors(Phi, r0, anchors)
        done += 1
    return done


def check_revision(Phi, Psi, r0, claimed_total=None):
    """Adding the columns Psi to the specification never raises the total residual (noiseless model), and
    the total is |r*|^2 minus the squared part of r* inside the span of the new columns' outside parts."""
    r_star = outside_part(r0, Phi)
    r_rev = outside_part(r0, hstack(Phi, Psi))
    require(dot(r_rev, r_rev) <= dot(r_star, r_star), "adding a direction raised the total residual")
    new_dirs = tr([outside_part(c, Phi) for c in tr(Psi)])
    require(r_rev == outside_part(r_star, new_dirs), "the revised residual is not r* minus its part inside the new directions")
    inside = sub(r_star, r_rev)
    expected = dot(r_star, r_star) - dot(inside, inside)
    total = dot(r_rev, r_rev) if claimed_total is None else claimed_total
    require(expected == total, "the total after revising differs from |r*|^2 minus the squared part inside the new directions")
    return r_rev


def check_revision_zeroes(Phi, Psi, r0, anchors):
    """A revision whose span contains the outside residual zeroes every anchor."""
    r_rev = outside_part(r0, hstack(Phi, Psi))
    require(all(dot(b, r_rev) == 0 for b in anchors), "an anchor still reads nonzero after the revision")


def run_revision_census(seed=SEED_REVISE, count=100):
    rng = random.Random(seed)
    done = 0
    while done < count:
        Phi, r0, r_star, (a,) = random_case(rng)
        m = len(r0)
        width = rng.randint(1, 2)
        Psi = [[rnd(rng) for _ in range(width)] for _ in range(m)]
        r_rev = check_revision(Phi, Psi, r0)
        r_ad = absorb_one(Phi, r_star, a)[0]
        require(dot(r_rev, r_rev) <= dot(r_star, r_star) < dot(r_ad, r_ad), "a revision ended above the absorbed residual")
        containing = [[x] for x in r_star]
        check_revision_zeroes(Phi, containing, r0, [rvec(rng, m) for _ in range(5)] + [a])
        done += 1
    return done


def check_per_anchor_counterexample(v):
    """Five residuals, Phi on the first two coordinates, outside residual 5 in the third. Adding the direction v
    lowers the total from 25 to 16 and raises the reading of the fresh anchor (0, 0, 1, -1, 0)."""
    Phi = [[F(int(i == j)) for j in range(2)] for i in range(5)]
    r0 = [F(0), F(0), F(5), F(0), F(0)]
    fresh = [F(0), F(0), F(1), F(-1), F(0)]
    r_rev = check_revision(Phi, [[x] for x in v], r0)
    before, after = dot(fresh, r0) ** 2, dot(fresh, r_rev) ** 2
    require(after > before, "the revision does not raise the reading of the fresh anchor")
    return dot(r_rev, r_rev), before, after


def check_noisy_counterexample(direction):
    """A noisy residual. Adding a wrong direction lowers the residual on the data and raises the error against the truth."""
    Phi = [[F(1)], [F(1)], [F(0)], [F(0)]]
    truth = [F(0), F(0), F(2), F(0)]
    noise = [F(1, 3), F(-1, 2), F(1, 5), F(3, 4)]
    y = add(truth, noise)
    wider = hstack(Phi, [[x] for x in direction])
    res1, res2 = outside_part(y, Phi), outside_part(y, wider)
    err1, err2 = sub(truth, project(Phi, y)), sub(truth, project(wider, y))
    require(dot(res2, res2) < dot(res1, res1), "the residual on the data did not fall")
    require(dot(err2, err2) > dot(err1, err1), "the error against the truth did not rise")
    return (dot(res1, res1), dot(res2, res2)), (dot(err1, err1), dot(err2, err2))


class TestAnchorAbsorption(unittest.TestCase):
    """docs/09 Claim 9 and Falsifier 6: what absorbing a failed anchor does in the linear model of section 6.1."""

    def test_doc09_c9_cost_outside_part_old_falsifier_and_the_x_rule(self):
        census = run_absorption_census()
        self.assertEqual(census["instances"], 150)
        self.assertGreater(census["rank_deficient"], 0)

    def test_doc09_c9_several_anchors_and_revision(self):
        self.assertEqual(run_several_census(), 100)
        self.assertEqual(run_revision_census(), 100)

    def test_doc09_c9_exact_counterexamples_of_the_open_forms(self):
        third = F(3, 5), F(4, 5)
        total, before, after = check_per_anchor_counterexample([F(0), F(0), third[0], third[1], F(0)])
        self.assertEqual((total, before, after), (F(16), F(25), F(784, 25)))
        data, truth = check_noisy_counterexample([F(0), F(0), F(0), F(1)])
        self.assertEqual(data, (F(20699, 3600), F(9337, 1800)))
        self.assertEqual(truth, (F(289, 72), F(659, 144)))

    def test_doc09_c9_absorption_checks_go_red(self):
        Phi = [[F(1), F(0)], [F(0), F(1)], [F(0), F(0)], [F(0), F(0)], [F(0), F(0)]]
        r0 = [F(2), F(-1), F(3), F(1), F(-2)]
        a = [F(1), F(1), F(1), F(0), F(0)]
        r_star, r_ad = check_inflation(Phi, r0, a)                                          # control
        self.assertTrue(goes_red(check_inflation, Phi, r0, a, lambda e, pp: e * e / (2 * pp)))
        self.assertTrue(goes_red(check_inflation, Phi, r0, a, lambda e, pp: e * e))
        # Silencing: the least change meets the law, a worse change passes, a cheaper claim fails.
        p = project(Phi, a)
        pp, e = dot(p, p), dot(a, r_star)
        check_silencing(Phi, r0, a, scale(e / pp, p))                                       # control
        check_silencing(Phi, r0, a, scale(e / dot(a, [F(1), F(0), F(0), F(0), F(0)]), [F(1), F(0), F(0), F(0), F(0)]))
        self.assertTrue(goes_red(check_silencing, Phi, r0, a, scale(e / pp, p), lambda e_, pp_: 2 * e_ * e_ / pp_))
        self.assertTrue(goes_red(check_silencing, Phi, r0, a, scale(e / dot(a, a), a)))     # outside the column space
        self.assertTrue(goes_red(check_silencing, Phi, r0, a, [F(0)] * 5))                  # silences nothing
        # Two controls that each only one guard can catch. The first change silences a and costs more than the law,
        # but leaves the column space. The second is a real adaptation, checked against an inflated claimed law.
        u = [F(0), F(0), F(0), F(2), F(1)]                                                  # orthogonal to a and to r_ad
        self.assertTrue(goes_red(check_silencing, Phi, r0, a, add(scale(e / pp, p), u)))
        x1 = [F(1), F(0), F(0), F(0), F(0)]
        self.assertTrue(goes_red(check_silencing, Phi, r0, a, scale(e / dot(a, x1), x1), lambda e_, pp_: 100 * e_ * e_ / pp_))
        # A change that is not an adaptation moves the outside part, so the check of the outside part goes red.
        moved = sub(r_star, scale(e / dot(a, a), a))
        fresh = [[F(1), F(0), F(1), F(0), F(0)], [F(0), F(0), F(2), F(1), F(0)]]
        check_outside_unchanged(Phi, r_star, r_ad, fresh)                                   # control
        self.assertTrue(goes_red(check_outside_unchanged, Phi, r_star, moved, fresh))
        # The old falsifier fires on an absorption that closed nothing. It does not fire when nothing moved,
        # and the misfire check refuses an absorption that did change the outside part.
        same = [[F(1), F(1), F(1), F(0), F(0)], [F(1), F(1), F(3, 4), F(0), F(0)], [F(5, 4), F(1), F(1), F(0), F(0)]]
        check_old_falsifier_misfires(Phi, r_star, r_ad, same)                               # control
        self.assertTrue(old_falsifier_fires(r_star, moved, same))                          # so the next control fails on the outside part
        self.assertTrue(goes_red(check_old_falsifier_misfires, Phi, r_star, r_star, same))
        self.assertTrue(goes_red(check_old_falsifier_misfires, Phi, r_star, moved, same))
        # Readings fall and the outside part is unchanged, but the total residual fell: not an absorption.
        same2 = [[F(1), F(1), F(1), F(0), F(0)], [F(1), F(1), F(3, 4), F(0), F(0)], [F(2), F(2), F(1), F(0), F(0)]]
        r_hi = add(r_star, [F(3), F(-3), F(0), F(0), F(0)])
        r_lo = add(r_star, [F(-1, 2), F(-1, 2), F(0), F(0), F(0)])
        self.assertTrue(old_falsifier_fires(r_hi, r_lo, same2))
        check_outside_unchanged(Phi, r_hi, r_lo, same2)                                    # so only the total can catch it
        self.assertTrue(goes_red(check_old_falsifier_misfires, Phi, r_hi, r_lo, same2))
        # The x rule: the old label at the ties and a wrong upper bound both go red.
        b_help = [F(1), F(0), F(2), F(0), F(0)]
        tie0 = sub(b_help, scale(dot(p, b_help) / pp, p))
        check_helps_rule(Phi, r0, a, b_help)                                                # control
        self.assertEqual(check_helps_rule(Phi, r0, a, tie0), (0, "tie"))
        old_rule = lambda x: "hurts" if x <= 0 or x >= 2 else "helps"
        self.assertTrue(goes_red(check_helps_rule, Phi, r0, a, tie0, old_rule))
        b_mid = [F(2), F(1), F(1), F(0), F(0)]                                             # x = 3/2
        self.assertEqual(check_helps_rule(Phi, r0, a, b_mid), (F(3, 2), "helps"))
        self.assertTrue(goes_red(check_helps_rule, Phi, r0, a, b_mid, lambda x: "helps" if 0 < x < 1 else "hurts"))
        self.assertTrue(goes_red(check_helps_rule, Phi, r0, a, b_help, helps_rule, lambda e_b, x: e_b * (1 + x)))
        # Several anchors.
        two = [a, [F(0), F(1), F(0), F(1), F(1)]]
        check_several_anchors(Phi, r0, two)                                                 # control
        self.assertTrue(goes_red(check_several_anchors, Phi, r0, two, lambda M, e_: dot(e_, mv(M, e_))))
        self.assertTrue(goes_red(check_several_anchors, Phi, r0, two, lambda M, e_: sum(x * x for x in e_)))
        # The sign-flipped change costs the same, so only the check that every anchor reads zero can catch it.
        flipped = lambda M, e_: [-x for x in solve(M, e_)]
        self.assertTrue(goes_red(check_several_anchors, Phi, r0, two, None, flipped))
        # Revision.
        Psi = [[F(0)], [F(0)], [F(1)], [F(0)], [F(0)]]
        check_revision(Phi, Psi, r0)                                                        # control
        self.assertTrue(goes_red(check_revision, Phi, Psi, r0, F(10**6)))
        self.assertTrue(goes_red(check_revision_zeroes, Phi, Psi, r0, [r_star]))
        check_revision_zeroes(Phi, [[x] for x in r_star], r0, [r_star, a])                  # control
        # The counterexamples need a direction that does the harm: a direction orthogonal to the outside residual
        # leaves the total alone, and a direction along the truth lowers the error against the truth.
        self.assertTrue(goes_red(check_per_anchor_counterexample, [F(0), F(0), F(0), F(1), F(0)]))
        self.assertTrue(goes_red(check_noisy_counterexample, [F(0), F(0), F(1), F(0)]))
        # The census catches a wrong law in the code it runs.
        with broken("inflation_law", lambda e, pp: e * e / (2 * pp)):
            self.assertTrue(goes_red(run_absorption_census, SEED_ABSORB, 3))
        with broken("outside_part", lambda w, Phi_: list(w)):
            self.assertTrue(goes_red(run_absorption_census, SEED_ABSORB, 3))


# ======================================================================================
# Part 3. Contract 3: what may flow back to the proposer
# ======================================================================================
ARTIFACTS = (0, 1, 2)
SUBSETS = [frozenset(s) for n in range(4) for s in itertools.combinations(ARTIFACTS, n)]
FEEDBACKS = list(itertools.product((0, 1), repeat=3))            # every map from an artifact to one bit of detail
STRATEGIES = [(q1, q2, q3) for q1 in ARTIFACTS
              for q2 in itertools.product(ARTIFACTS, repeat=2)
              for q3 in itertools.product(ARTIFACTS, repeat=4)]   # every adaptive proposer of depth 3


def run_loop(gate, feedback, strategy, depth=3):
    """Propose, read the verdict, and on a rejection read the detail. Return the first accepted artifact."""
    q1, q2, q3 = strategy
    a = q1
    if a in gate:
        return a
    f1 = feedback[a]
    a = q2[f1]
    if a in gate or depth == 2:
        return a if a in gate else None
    f2 = feedback[a]
    a = q3[2 * f1 + f2]
    return a if a in gate else None


def check_exact_gate_is_sound_under_feedback(sound=lambda gate, truth: gate <= truth):
    """Claim 5, exhaustively: no feedback and no adaptive proposer gets a false claim through an exact gate."""
    runs = accepted = 0
    for truth in SUBSETS:
        for gate in SUBSETS:
            if not sound(gate, truth):
                continue
            for feedback in FEEDBACKS:
                for strategy in STRATEGIES:
                    out = run_loop(gate, feedback, strategy)
                    runs += 1
                    if out is not None:
                        accepted += 1
                        require(out in truth, f"a false claim was accepted: truth {set(truth)} gate {set(gate)}")
    return runs, accepted


def check_unsound_gate_is_exploitable():
    """The converse: a gate that accepts one false claim loses to a proposer that needs no feedback at all."""
    pairs = 0
    for truth in SUBSETS:
        for gate in SUBSETS:
            if gate <= truth:
                continue
            bad = min(gate - truth)
            blind = (bad, (bad, bad), (bad, bad, bad, bad))
            require(all(run_loop(gate, fb, blind) not in truth for fb in FEEDBACKS), "an unsound gate was not exploited")
            pairs += 1
    return pairs


def check_detail_changes_speed_not_truth():
    """With two proposals allowed, one bit of detail finds an accepted artifact whenever one exists. No blind proposer does."""
    nonempty = [g for g in SUBSETS if g]
    blind = [s for s in {(q1, (a, a), (0, 0, 0, 0)) for q1 in ARTIFACTS for a in ARTIFACTS}]
    zero = (0, 0, 0)
    blind_complete = [s for s in blind if all(run_loop(g, zero, s, depth=2) is not None for g in nonempty)]
    require(blind_complete == [], "a blind proposer of depth 2 found every gate")
    guided = (0, (2, 1), (0, 0, 0, 0))
    for g in nonempty:
        detail = tuple(1 if (a + 1) % 3 in g else 0 for a in ARTIFACTS)      # says whether the next artifact passes
        out = run_loop(g, detail, guided, depth=2)
        require(out is not None and out in g, "the guided proposer missed an accepted artifact")
    return len(blind), len(nonempty)


def check_detail_exposes_a_sampled_oracle(n=6, k=3, detail=True):
    """A sampled oracle checks k hidden points of n. One detailed answer lets a wrong artifact pass every sample."""
    points = range(n)
    samples = [frozenset(s) for s in itertools.combinations(points, k)]
    committed = adaptive = exact_false_accepts = 0
    fixed_wrong = frozenset(range(k, n))                       # an artifact that is wrong on n - k points
    for sample in samples:
        committed += not (fixed_wrong & sample)              # committed before seeing anything
        first = frozenset(points)                              # proposal 1: wrong everywhere, rejected
        seen = (first & sample) if detail else frozenset()     # the detail: which sampled points failed
        second = frozenset(points) - seen if detail else fixed_wrong
        adaptive += not (second & sample)
        require(len(second) == n - k, "the second proposal should be wrong on n - k points")
        exact_false_accepts += len(second) == 0                # an exact gate accepts only the artifact with no wrong point
    require(committed == 1, "a committed wrong artifact should pass exactly one sample in twenty")
    require(exact_false_accepts == 0, "the exact gate accepted a wrong artifact")
    require(adaptive == (len(samples) if detail else 1), "false passes of the adaptive proposer")
    return len(samples), committed, adaptive


class TestReturnPath(unittest.TestCase):
    """docs/09 section 5: what may flow back to the proposer."""

    def test_doc09_c3_exact_gate_stays_sound_under_any_feedback(self):
        runs, accepted = check_exact_gate_is_sound_under_feedback()
        self.assertEqual(len(STRATEGIES), 2187)
        self.assertEqual(runs, 27 * 8 * 2187)             # 27 pairs with gate inside truth, 8 feedback maps
        self.assertEqual(accepted, 266328)                  # the count quoted in docs/09 section 5.2
        self.assertEqual(check_unsound_gate_is_exploitable(), 64 - 27)

    def test_doc09_c3_detail_changes_speed_not_truth(self):
        self.assertEqual(check_detail_changes_speed_not_truth(), (9, 7))

    def test_doc09_c3_detail_from_a_sampled_oracle_exposes_the_sample(self):
        self.assertEqual(check_detail_exposes_a_sampled_oracle(), (20, 1, 20))
        self.assertEqual(check_detail_exposes_a_sampled_oracle(detail=False), (20, 1, 1))

    def test_doc09_c3_return_path_checks_go_red(self):
        # Call a gate "exact" when it accepts one false claim: the exhaustive check finds the false accept.
        almost = lambda gate, truth: len(gate - truth) <= 1
        self.assertTrue(goes_red(check_exact_gate_is_sound_under_feedback, almost))
        # A loop that hands back its first proposal whether or not the gate accepted it is caught.
        with broken("run_loop", lambda gate, feedback, strategy, depth=3: strategy[0]):
            self.assertTrue(goes_red(check_exact_gate_is_sound_under_feedback))
            self.assertTrue(goes_red(check_detail_changes_speed_not_truth))
        # A sampled oracle that checks every point is not a sampled oracle: the counts change.
        self.assertTrue(goes_red(check_detail_exposes_a_sampled_oracle, 6, 6))


# ======================================================================================
# Part 4. The closure defect
# ======================================================================================
def forks(states, step, phi):
    """Pairs of states with the same image whose successors have different images."""
    return [(x, y) for x in states for y in states
            if x < y and phi(x) == phi(y) and phi(step[x]) != phi(step[y])]


def image(states, step, phi):
    return {(phi(x), phi(step[x])) for x in states}


def missing_steps(states, step, phi, spec):
    """States whose one concrete step has no abstract step in the specification."""
    return [x for x in states if (phi(x), phi(step[x])) not in spec]


class CountingStep:
    """A step table that counts how many states were looked up."""

    def __init__(self, step):
        self.step, self.looked_up = step, set()

    def __getitem__(self, x):
        self.looked_up.add(x)
        return self.step[x]


def check_fork_witness(step, phi, x, y):
    """Verify a claimed fork. Cost: two concrete steps, whatever the number of states."""
    counted = CountingStep(step)
    require(phi(x) == phi(y) and phi(counted[x]) != phi(counted[y]), "not a fork")
    require(len(counted.looked_up) == 2, "a fork should need exactly two concrete steps")


def run_closure_census():
    """Every deterministic system on four states under the quotient {0,1} and {2,3}."""
    states = (0, 1, 2, 3)
    phi = lambda x: x // 2
    specs = [dict(zip((0, 1), s)) for s in itertools.product((0, 1), repeat=2)]     # every deterministic abstract step
    out = {"systems": 0, "closed": 0, "not_closed": 0, "one_state_changes_tried": 0, "subsets_fooled": 0}
    for values in itertools.product(states, repeat=4):
        step = dict(zip(states, values))
        fk = forks(states, step, phi)
        out["systems"] += 1
        exact_specs = [s for s in specs if not missing_steps(states, step, phi, set(s.items()))]
        if fk:
            out["not_closed"] += 1
            check_fork_witness(step, phi, *fk[0])                      # Claim 12 (a): a two-step refutation
            require(exact_specs == [], "a deterministic specification covered a quotient that is not closed")
            continue
        out["closed"] += 1
        require(len(exact_specs) == 1, "a closed quotient should have exactly one deterministic specification")
        require(image(states, step, phi) == set(exact_specs[0].items()), "the specification is not the image")
        # Claim 12 (b): change the step at any one state and closure can break, with every other state unchanged.
        for x0 in states:
            other_class = next(z for z in states if phi(z) != phi(step[x0]))
            changed = dict(step)
            changed[x0] = other_class
            out["one_state_changes_tried"] += 1
            require(forks(states, changed, phi) != [], "changing one state did not break closure")
            require(all(changed[x] == step[x] for x in states if x != x0), "more than one state changed")
        # So a checker that skips any state accepts some system that is not closed.
        for size in range(4):
            for looked in itertools.combinations(states, size):
                x0 = next(x for x in states if x not in looked)
                changed = dict(step)
                changed[x0] = next(z for z in states if phi(z) != phi(step[x0]))
                require(all(changed[x] == step[x] for x in looked) and forks(states, changed, phi),
                        "a partial look could tell the closed system from every non-closed one")
                out["subsets_fooled"] += 1
    return out


def distances(nodes, edges, goals):
    """Fewest steps from each node to a goal, None when no goal is reachable."""
    dist = {n: (0 if n in goals else None) for n in nodes}
    frontier = [n for n in nodes if n in goals]
    while frontier:
        nxt = []
        for a, b in edges:
            if b in frontier and dist[a] is None:
                dist[a] = dist[b] + 1
                nxt.append(a)
        frontier = nxt
    return dist


def exceeds(bound, true):
    """A claimed lower bound exceeds the true distance (None means no route exists, an infinite distance)."""
    return true is not None and (bound is None or bound > true)


def check_bound_is_valid(states, phi, bound, true):
    """Claim 13 (a): no state has a bound from the quotient above its true distance."""
    wrong = [x for x in states if exceeds(bound[phi(x)], true[x])]
    require(wrong == [], "a specification that allows more gave an invalid lower bound")


def shortest_route(nodes, edges, goals, start, dist):
    route = [start]
    while route[-1] not in goals:
        route.append(next(b for a, b in sorted(edges) if a == route[-1] and dist[b] == dist[a] - 1))
    return route


def run_polarity_census(seed=SEED, systems=60, allows_more=lambda img, spec: img <= spec):
    """Claim 13: lower bounds from the quotient stay valid when the specification allows more, and not when it allows less."""
    rng = random.Random(seed + 3)
    states, classes = range(6), range(3)
    phi = lambda x: x // 2
    goal, abstract_goal = {5}, {2}
    all_abstract = [(p, q) for p in classes for q in classes]
    out = {"systems": 0, "specs_allowing_more": 0, "specs_allowing_less": 0, "unsound_bounds": 0, "void_specs": 0,
           "refuted_by_one_step": 0}
    for _ in range(systems):
        edges = {(a, b) for a in states for b in states if a != b and rng.random() < 0.3}
        img = {(phi(a), phi(b)) for a, b in edges}
        true = distances(states, edges, goal)
        exact = distances(classes, img, abstract_goal)
        out["systems"] += 1
        for bits in itertools.product((0, 1), repeat=len(all_abstract)):
            spec = {e for e, bit in zip(all_abstract, bits) if bit}
            bound = distances(classes, spec, abstract_goal)
            wrong = [x for x in states if exceeds(bound[phi(x)], true[x])]
            if allows_more(img, spec):      # the specification allows at least what the system does
                out["specs_allowing_more"] += 1
                check_bound_is_valid(states, phi, bound, true)
                require(all(not exceeds(bound[q], exact[q]) for q in classes), "allowing more raised a bound")
            else:                # some real step has no abstract step
                out["specs_allowing_less"] += 1
                out["unsound_bounds"] += len(wrong)
                out["void_specs"] += bool(wrong)
                for x in wrong:  # the refutation is one real step on a real shortest route
                    route = shortest_route(states, edges, goal, x, true)
                    require(any((phi(a), phi(b)) not in spec for a, b in zip(route, route[1:])),
                            "an invalid bound without a missing step on the route")
                    out["refuted_by_one_step"] += 1
    require(out["unsound_bounds"] > 0, "no specification that allows less ever gave an invalid bound")
    return out


class TestClosure(unittest.TestCase):
    """docs/09 section 7: the closure defect."""

    def test_doc09_c5_closure_fails_in_two_steps_and_holds_only_after_all_states(self):
        census = run_closure_census()
        self.assertEqual((census["systems"], census["closed"], census["not_closed"]), (256, 64, 192))
        self.assertEqual(census["one_state_changes_tried"], 64 * 4)
        self.assertEqual(census["subsets_fooled"], 64 * 15)        # every proper subset of four states

    def test_doc09_c5_toy_systems(self):
        states, phi = range(6), (lambda x: x // 2)
        closed = {x: (x + 2) % 6 for x in states}                  # the image is q -> q + 1 mod 3
        self.assertEqual(forks(states, closed, phi), [])
        self.assertEqual(image(states, closed, phi), {(0, 1), (1, 2), (2, 0)})
        broken = dict(closed)
        broken[1] = 5                                              # state 1 now lands in class 2, state 0 still in class 1
        self.assertEqual(forks(states, broken, phi), [(0, 1)])
        check_fork_witness(broken, phi, 0, 1)
        self.assertEqual(missing_steps(states, broken, phi, {(0, 1), (1, 2), (2, 0)}), [1])

    def test_doc09_c5_polarity_of_bounds(self):
        census = run_polarity_census()
        # the counts quoted in docs/09 section 7.3
        self.assertEqual(census, {"systems": 60, "specs_allowing_more": 694, "specs_allowing_less": 30026,
                                  "unsound_bounds": 31680, "void_specs": 14720, "refuted_by_one_step": 31680})
        self.assertEqual(census["specs_allowing_more"] + census["specs_allowing_less"], 60 * 512)
        self.assertEqual(census["refuted_by_one_step"], census["unsound_bounds"])
        self.assertGreater(census["void_specs"], 0)

    def test_doc09_c5_closure_checks_go_red(self):
        states, phi = range(6), (lambda x: x // 2)
        closed = {x: (x + 2) % 6 for x in states}
        self.assertTrue(goes_red(check_fork_witness, closed, phi, 0, 1))          # a closed system has no fork
        self.assertTrue(goes_red(check_fork_witness, closed, phi, 0, 2))          # different images are not a fork
        with broken("forks", lambda states_, step, phi_: []):                     # a detector that sees no fork
            self.assertTrue(goes_red(run_closure_census))
        with broken("missing_steps", lambda states_, step, phi_, spec: []):       # a replay that sees no missing step
            self.assertTrue(goes_red(run_closure_census))
        # Polarity reversed: call a bound invalid when it is below the true distance.
        with broken("exceeds", lambda bound, true: true is not None and bound is not None and bound < true):
            self.assertTrue(goes_red(run_polarity_census, SEED, 5))
        # Treat every specification as if it allowed at least what the system does: an invalid bound shows up.
        self.assertTrue(goes_red(run_polarity_census, SEED, 5, lambda img, spec: True))
        # A bound of 3 where the true distance is 1 is invalid. A bound of 1 where it is 3 is only loose.
        one_class = lambda x: 0
        self.assertTrue(goes_red(check_bound_is_valid, (0, 1), one_class, {0: 3}, {0: 1, 1: 5}))
        check_bound_is_valid((0, 1), one_class, {0: 1}, {0: 3, 1: 5})
        self.assertTrue(goes_red(check_bound_is_valid, (0, 1), one_class, {0: None}, {0: 3, 1: 5}))


# ======================================================================================
# Part 5. Numbers quoted in the document
# ======================================================================================
# (arm, family): (items, oracle passes, oracle passes the grader rejected). docs/09 section 4.2.
ORACLE_GAP = {
    ("bare model", "A"): (12, 1, 0), ("bare model", "B"): (12, 9, 4), ("bare model", "C"): (12, 11, 11), ("bare model", "D"): (12, 2, 0),
    ("adapter", "A"): (12, 0, 0), ("adapter", "B"): (12, 4, 4), ("adapter", "C"): (12, 10, 10), ("adapter", "D"): (12, 0, 0),
}


def check_oracle_gap_totals(table, claimed):
    for arm, (passes, rejected) in claimed.items():
        rows = [v for (a, _), v in table.items() if a == arm]
        require(all(0 <= r <= p <= n for n, p, r in rows), "a row is not ordered rejected <= passes <= items")
        require((sum(p for _, p, _ in rows), sum(r for _, _, r in rows)) == (passes, rejected), f"totals for {arm}")


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def thousandths_as_float32():
    above = sum(F(f32(k / 1000)) > F(k, 1000) for k in range(1, 1001))
    below = sum(F(f32(k / 1000)) < F(k, 1000) for k in range(1, 1001))
    exact_1024 = sum(F(f32(n / 1024)) == F(n, 1024) for n in range(0, 1025))
    return above, below, 1000 - above - below, exact_1024


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_matched_audit_fires_first(tolerance, threshold, noise):
    """One-residual leak, audit matched to it. If no residual crosses the tolerance by noise alone,
    the audit fires at a leak size no larger than the single check does."""
    require(-tolerance <= noise < tolerance, "the noise alone crosses the tolerance")
    audit_fires_at = max(F(0), threshold - noise)        # leak size where noise + leak exceeds the audit threshold
    single_fires_at = tolerance - noise                  # leak size where noise + leak exceeds the tolerance
    require(audit_fires_at < single_fires_at, "the single check fired first")


class TestQuotedNumbers(unittest.TestCase):
    """Arithmetic behind numbers that docs/09 quotes from other repositories."""

    def test_doc09_c2_oracle_gap_table_totals(self):
        check_oracle_gap_totals(ORACLE_GAP, {"bare model": (23, 15), "adapter": (14, 14)})
        self.assertEqual(sum(n for n, _, _ in ORACLE_GAP.values()), 96)

    def test_doc09_c1_float_spelling_changes_a_digest(self):
        # One number, two spellings that two languages print, two digests.
        self.assertEqual(json.dumps(0.00001), "1e-05")
        a, b = '{"corpus":1e-05}', '{"corpus":0.00001}'
        self.assertEqual(json.loads(a), json.loads(b))
        self.assertNotEqual(digest(a), digest(b))
        # A whole number written as 1 or as 1.0 is one float and two byte strings.
        self.assertEqual((json.dumps(1.0), json.dumps(1)), ("1.0", "1"))
        self.assertEqual(float(json.loads("1")), json.loads("1.0"))
        # An integer numerator over a power of two has one spelling.
        n = 205
        self.assertEqual(json.dumps(json.loads(json.dumps(n))), "205")
        self.assertEqual(F(f32(n / 1024)), F(n, 1024))

    def test_doc09_c1_thousandths_as_32_bit_floats(self):
        self.assertEqual(thousandths_as_float32(), (503, 489, 8, 1025))

    def test_doc09_c4_matched_audit_fires_before_a_single_check(self):
        grid = [F(n, 4) for n in range(-24, 25)]
        cases = 0
        for tolerance in (F(3), F(7, 2), F(4), F(6)):
            for noise in grid:
                if -tolerance <= noise < tolerance:
                    check_matched_audit_fires_first(tolerance, F(329, 200), noise)     # threshold 1.645 noise widths
                    cases += 1
        self.assertEqual(cases, 24 + 28 + 32 + 48)      # quarter steps of noise inside each tolerance

    def test_doc09_quoted_number_checks_go_red(self):
        wrong = dict(ORACLE_GAP)
        wrong[("bare model", "C")] = (12, 11, 10)
        self.assertTrue(goes_red(check_oracle_gap_totals, wrong, {"bare model": (23, 15), "adapter": (14, 14)}))
        self.assertTrue(goes_red(check_oracle_gap_totals, ORACLE_GAP, {"bare model": (23, 14), "adapter": (14, 14)}))
        # With the audit threshold above the tolerance the single check can fire first.
        self.assertTrue(goes_red(check_matched_audit_fires_first, F(3), F(4), F(0)))
        # Noise that already crosses the tolerance is outside the statement.
        self.assertTrue(goes_red(check_matched_audit_fires_first, F(3), F(329, 200), F(3)))
        # Thousandths counted with 64-bit floats give another count, so 503 depends on the 32-bit step.
        self.assertEqual(sum(F(k / 1000) > F(k, 1000) for k in range(1, 1001)), 499)


# ======================================================================================
# Part 6. A worked case in physics: decimation of the Ising model (docs/09 section 7.7)
# ======================================================================================
# Spins of +1 or -1 on the sites of a graph, coupling K > 0, y = e^K. Sites are split into a
# kept set A and a summed-out set B with no edge inside B. The weight of a configuration a of A is
# W(a) = sum over configurations of B of y^(sum over edges of the product of the two spins).
# All weights below are exact Fractions at rational y, or Laurent polynomials in y.
SEED_DECIM = 20261124
DECIM_COUPLINGS = (F(2), F(3, 2), F(5, 3))                     # y = e^K, so K = ln y > 0


def decim_weight_product(sums, y):
    """W as the product over summed-out sites of y^s + y^-s, where s is the sum of the neighbour spins."""
    w = F(1)
    for s in sums:
        w *= y ** s + y ** (-s)
    return w


def decim_weight_brute(edges, a, nb, y):
    """W straight from the definition: sum over every configuration of the summed-out sites.
    edges: pairs (b, site of A) with b in range(nb). Each edge has one end in B and one in A."""
    counts = {}
    for sb in itertools.product((1, -1), repeat=nb):
        e = sum(sb[b] * a[i] for b, i in edges)
        counts[e] = counts.get(e, 0) + 1
    return sum(c * y ** e for e, c in counts.items())


# ---- the ring: 2N sites, A the even ones, B the odd ones --------------------------------
def ring_edges(n):
    """b is between a[b] and a[(b+1) % n]."""
    return [(b, b) for b in range(n)] + [(b, (b + 1) % n) for b in range(n)]


def ring_nn(a):
    return sum(a[i] * a[(i + 1) % len(a)] for i in range(len(a)))


def ring_sums(a):
    return [a[b] + a[(b + 1) % len(a)] for b in range(len(a))]


def check_ring_has_no_fork(n, spec, weight, couplings=DECIM_COUPLINGS):
    """Group the 2^n coarse configurations by the value of spec and require one weight per group.
    Returns the number of classes."""
    classes = {}
    for a in itertools.product((1, -1), repeat=n):
        classes.setdefault(spec(a), []).append(a)
    for y in couplings:
        for key, members in classes.items():
            ws = {weight(a, y) for a in members}
            require(len(ws) == 1, "fork on the ring: size %d, class %r, y = %s" % (n, key, y))
    return len(classes)


def ring_weight_brute(a, y):
    return decim_weight_brute(ring_edges(len(a)), a, len(a), y)


def check_ring_closed_form(n, y, shift=0):
    """W = 2^n * cosh(2K)^(number of aligned coarse bonds), so W depends on the nn sum alone."""
    c2 = (y * y + 1 / (y * y)) / 2
    for a in itertools.product((1, -1), repeat=n):
        aligned = (n + ring_nn(a)) // 2 + shift
        require(ring_weight_brute(a, y) == 2 ** n * c2 ** aligned, "ring closed form fails")


def run_ring_census(sizes=(3, 4, 5, 6, 7), couplings=DECIM_COUPLINGS):
    out = {"sizes": sizes, "couplings": [str(y) for y in couplings], "classes": {}}
    for n in sizes:
        out["classes"][n] = check_ring_has_no_fork(n, ring_nn, ring_weight_brute, couplings)
        check_ring_closed_form(n, couplings[0])
    return out


# ---- the torus: Lx by Ly sites, A where i + j is even, B where i + j is odd --------------
def torus_b_sites(lx, ly):
    return [(i, j) for i in range(lx) for j in range(ly) if (i + j) % 2]


def torus_a_sites(lx, ly):
    return [(i, j) for i in range(lx) for j in range(ly) if (i + j) % 2 == 0]


def torus_nbrs(b, lx, ly):
    """The four neighbours of b in cyclic order east, north, west, south."""
    i, j = b
    return [((i + 1) % lx, j), (i, (j + 1) % ly), ((i - 1) % lx, j), (i, (j - 1) % ly)]


def torus_all_ones(lx, ly):
    return {s: 1 for s in torus_a_sites(lx, ly)}


def torus_sums(a, lx, ly):
    return [sum(a[s] for s in torus_nbrs(b, lx, ly)) for b in torus_b_sites(lx, ly)]


def torus_weight(a, lx, ly, y):
    return decim_weight_product(torus_sums(a, lx, ly), y)


def torus_cyclic_pairs(a, lx, ly):
    """The nearest-neighbour description: for each summed-out site the four products of cyclically
    adjacent neighbours. A coarse nearest-neighbour bond lies next to two summed-out sites, so this
    is twice the sum over distinct coarse bonds."""
    t = 0
    for b in torus_b_sites(lx, ly):
        e, n_, w, s = (a[x] for x in torus_nbrs(b, lx, ly))
        t += e * n_ + n_ * w + w * s + s * e
    return t


def torus_across_pairs(a, lx, ly):
    t = 0
    for b in torus_b_sites(lx, ly):
        e, n_, w, s = (a[x] for x in torus_nbrs(b, lx, ly))
        t += e * w + n_ * s
    return t


def torus_four_spin(a, lx, ly):
    t = 0
    for b in torus_b_sites(lx, ly):
        e, n_, w, s = (a[x] for x in torus_nbrs(b, lx, ly))
        t += e * n_ * w * s
    return t


def torus_spec_nn(a, lx, ly):
    return (torus_cyclic_pairs(a, lx, ly),)


def torus_spec_enlarged(a, lx, ly):
    return (torus_cyclic_pairs(a, lx, ly), torus_across_pairs(a, lx, ly), torus_four_spin(a, lx, ly))


def torus_spec_no_four_spin(a, lx, ly):
    return (torus_cyclic_pairs(a, lx, ly), torus_across_pairs(a, lx, ly))


def torus_classes(lx, ly, spec):
    """All 2^|A| coarse configurations grouped by the value of spec."""
    sites = torus_a_sites(lx, ly)
    classes = {}
    for vals in itertools.product((1, -1), repeat=len(sites)):
        a = dict(zip(sites, vals))
        classes.setdefault(spec(a, lx, ly), []).append(a)
    return classes


def torus_forking_classes(lx, ly, spec, weight=torus_weight, couplings=DECIM_COUPLINGS):
    """Classes of spec with two different weights at some coupling in the list, and the class count."""
    classes = torus_classes(lx, ly, spec)
    bad = [key for key, members in classes.items()
           if any(len({weight(a, lx, ly, y) for a in members}) > 1 for y in couplings)]
    return bad, len(classes)


def check_closes(lx, ly, spec, weight=torus_weight, couplings=DECIM_COUPLINGS):
    bad, n = torus_forking_classes(lx, ly, spec, weight, couplings)
    require(not bad, "%d of %d classes fork on the %dx%d torus" % (len(bad), n, lx, ly))
    return n


def check_torus_weight_formula(lx, ly, y, weight=torus_weight, seed=SEED_DECIM, count=24):
    """The product formula against the definition, on seeded random coarse configurations."""
    rng = random.Random(seed)
    sites, bs = torus_a_sites(lx, ly), torus_b_sites(lx, ly)
    index = {s: k for k, s in enumerate(sites)}
    edges = [(m, index[x]) for m, b in enumerate(bs) for x in torus_nbrs(b, lx, ly)]
    for _ in range(count):
        a = {s: rng.choice((1, -1)) for s in sites}
        brute = decim_weight_brute(edges, [a[s] for s in sites], len(bs), y)
        require(brute == weight(a, lx, ly, y), "product formula differs from the definition")


def torus_flipped(lx, ly, flips):
    a = torus_all_ones(lx, ly)
    for s in flips:
        a[s] = -1
    return a


# The witness on a torus with both sides even and at least 6: two flipped sites that share no summed-out
# neighbour, against three flipped sites at corners of one coarse plaquette (an L).
WITNESS_TWO = ((0, 0), (3, 3))
WITNESS_L = ((0, 0), (1, 1), (2, 0))


def check_torus_fork(lx, ly, a1, a2, y):
    """A claimed fork of the nearest-neighbour description: equal descriptions, different weights."""
    require(torus_spec_nn(a1, lx, ly) == torus_spec_nn(a2, lx, ly), "the two configurations differ in the description")
    require(torus_weight(a1, lx, ly, y) != torus_weight(a2, lx, ly, y), "the two weights are equal, so this is not a fork")


def check_witness(lx, ly, y):
    a1, a2 = torus_flipped(lx, ly, WITNESS_TWO), torus_flipped(lx, ly, WITNESS_L)
    check_torus_fork(lx, ly, a1, a2, y)
    c2 = (y * y + 1 / (y * y)) / 2
    require(torus_weight(a1, lx, ly, y) / torus_weight(a2, lx, ly, y) == c2 ** 2, "the weight ratio is not cosh^2(2K)")
    require(c2 ** 2 > 1, "ratio not above 1")
    return torus_spec_nn(a1, lx, ly)[0]


def signature(a, lx, ly):
    """How many summed-out sites have |s| = 0, 2, 4."""
    s = [abs(v) for v in torus_sums(a, lx, ly)]
    return (s.count(0), s.count(2), s.count(4))


def check_local_identity(y, q_shift=0):
    """For every pattern of the four neighbours of a summed-out site, with c2 = cosh 2K and c4 = cosh 4K:
    (2 cosh Ks)^8 = 256 c2^4 c4 * c4^P * (c4 / c2^4)^Q, where P is the sum of the six pair products and Q the product.
    This is ln 2cosh(Ks) = alpha + beta P + gamma Q, raised to the eighth power so that it is exact in Fractions."""
    c2, c4 = (y * y + 1 / (y * y)) / 2, (y ** 4 + 1 / y ** 4) / 2
    for nb in itertools.product((1, -1), repeat=4):
        s = sum(nb)
        pairs = sum(nb[i] * nb[j] for i, j in itertools.combinations(range(4), 2))
        q = nb[0] * nb[1] * nb[2] * nb[3]
        require((y ** s + y ** (-s)) ** 8 == 256 * c2 ** 4 * c4 * c4 ** pairs * (c4 / c2 ** 4) ** (q + q_shift),
                "local identity fails for neighbours %r" % (nb,))


def run_torus_census(couplings=DECIM_COUPLINGS):
    out = {"couplings": [str(y) for y in couplings]}
    # the 4x4 torus by enumeration: nn description forks, enlarged description closes
    bad, n = torus_forking_classes(4, 4, torus_spec_nn, couplings=couplings)
    out["4x4_nn_classes"], out["4x4_nn_forking"] = n, len(bad)
    # the two signatures behind that fork, in one class of the description, give a fork at every K by the product formula
    members = torus_classes(4, 4, torus_spec_nn)[bad[0]]
    sigs = {signature(a, 4, 4) for a in members}
    require({(0, 8, 0), (4, 4, 0)} <= sigs, "the two signatures are not both present in the forking class")
    out["4x4_signatures_in_forking_class"] = sorted(sigs)
    out["4x4_enlarged_classes"] = check_closes(4, 4, torus_spec_enlarged, couplings=couplings)
    out["4x4_without_four_spin_forking"] = len(torus_forking_classes(4, 4, torus_spec_no_four_spin, couplings=couplings)[0])
    check_torus_weight_formula(4, 4, couplings[0])
    for y in couplings:
        check_local_identity(y)
    # the witness at several sizes and couplings
    out["witness_sizes"] = [(6, 6), (6, 8), (8, 6), (8, 8), (10, 10)]
    for lx, ly in out["witness_sizes"]:
        for y in couplings:
            check_witness(lx, ly, y)
    out["witness_nn_value"] = check_witness(6, 6, couplings[0])
    return out


# ---- the second step ---------------------------------------------------------------------
# After the first step the weight on the coarse spins is the product over coarse faces F (the four corners
# (u,v), (u+1,v), (u,v+1), (u+1,v+1)) of p^(P_F) * q^(Q_F). P_F is the sum of the six pair products in the face
# and Q_F is the product of its four spins. On the K curve p^8 = cosh 4K and q^8 = cosh 4K / cosh^4 2K.
# Two coarse sites interact when they share a face, so same-colour sites of a checkerboard interact and the
# second step sums out the even-even quarter of the coarse sites. Each such site has 8 kept neighbours.
BLOCK_NN = ((1, 0), (0, 1), (-1, 0), (0, -1))
BLOCK_DIAG = ((1, 1), (-1, 1), (-1, -1), (1, -1))
BLOCK_SITES = BLOCK_NN + BLOCK_DIAG
BLOCK_FACES = [[BLOCK_SITES.index(c) for c in ((u0, v0), (u0 + 1, v0), (u0 + 1, v0 + 1), (u0, v0 + 1)) if c != (0, 0)]
               for (u0, v0) in ((0, 0), (-1, 0), (0, -1), (-1, -1))]


def block_exponents(pat):
    """For one summed-out coarse site with neighbour pattern pat (8 spins): integers (kept, S, T) such that the
    block factor is p^kept * (p^S q^T + p^-S q^-T). kept is the pair sum among kept spins over the four faces."""
    kept = s = t = 0
    for others in BLOCK_FACES:
        x, y, z = (pat[i] for i in others)
        kept += x * y + y * z + x * z
        s += x + y + z
        t += x * y * z
    return kept, s, t


def block_poly(pat):
    kept, s, t = block_exponents(pat)
    out = {}
    for key in ((kept + s, t), (kept - s, -t)):
        out[key] = out.get(key, 0) + 1                  # both terms coincide when S = T = 0
    return out


def poly_times(a, b):
    out = {}
    for (i, j), c in a.items():
        for (k, m), d in b.items():
            key = (i + k, j + m)
            out[key] = out.get(key, 0) + c * d
    return {k: v for k, v in out.items() if v}


def block_group():
    """The 16 maps of the 8 neighbour positions given by the rotations and reflections of the square, and the flip."""
    def rot(s):
        return (-s[1], s[0])

    def refl(s):
        return (s[0], -s[1])
    maps = []
    for r in range(4):
        for f in range(2):
            m = []
            for s in BLOCK_SITES:
                for _ in range(r):
                    s = rot(s)
                m.append(BLOCK_SITES.index(refl(s) if f else s))
            maps.append(m)
    return maps


BLOCK_MAPS = block_group()
BLOCK_PATTERNS = list(itertools.product((1, -1), repeat=8))


def block_class_of(pat):
    best = None
    for m in BLOCK_MAPS:
        moved = tuple(pat[m[i]] for i in range(8))
        for cand in (moved, tuple(-v for v in moved)):
            if best is None or cand < best:
                best = cand
    return best


def block_orbit_of(subset):
    return min(tuple(sorted(m[i] for i in subset)) for m in BLOCK_MAPS)


def block_even_orbits():
    orbits = {}
    for r in range(0, 9, 2):
        for sub in itertools.combinations(range(8), r):
            orbits.setdefault(block_orbit_of(sub), []).append(sub)
    return orbits


def block_tables():
    """Classes of block patterns, even orbits, and the integer table M[class][orbit] of orbit sums."""
    classes = sorted({block_class_of(p) for p in BLOCK_PATTERNS})
    orbits = sorted(block_even_orbits().items(), key=lambda kv: (len(kv[0]), kv[0]))
    table = []
    for c in classes:
        row = []
        for _, members in orbits:
            row.append(sum(prod_of(c, sub) for sub in members))
        table.append(row)
    return classes, [o for o, _ in orbits], table


def prod_of(pat, sub):
    r = 1
    for i in sub:
        r *= pat[i]
    return r


def check_block_symmetry():
    """The block exponents are unchanged by the square's symmetries up to the sign that the flip gives S and T."""
    for pat in BLOCK_PATTERNS:
        kept, s, t = block_exponents(pat)
        flipped = block_exponents(tuple(-v for v in pat))
        require(flipped == (kept, -s, -t), "the block factor is not flip symmetric")
        for m in BLOCK_MAPS:
            moved = block_exponents(tuple(pat[m[i]] for i in range(8)))
            require(moved == (kept, s, t), "the block factor is not symmetric under the square's maps")
    return len(BLOCK_PATTERNS)


def check_invertible(table):
    require(len(table) == len(table[0]) and rank(table) == len(table), "the orbit table is not invertible")


def dual_vector(table, o):
    """Integer vector of least size with orbit sums zero except orbit number o: the orbit sums are the table's
    transpose applied to the histogram of classes."""
    n = len(table)
    transposed = [[F(table[c][k]) for c in range(n)] for k in range(n)]
    x = solve(transposed, [F(int(k == o)) for k in range(n)])
    den = 1
    for v in x:
        den = den * v.denominator // math.gcd(den, v.denominator)
    ints = [int(v * den) for v in x]
    g = 0
    for v in ints:
        g = math.gcd(g, abs(v))
    return [v // g for v in ints]


def check_dual_vector(table, o, vec):
    n = len(table)
    for k in range(n):
        total = sum(table[c][k] * vec[c] for c in range(n))
        require((total != 0) == (k == o), "not a dual vector for orbit %d" % o)


# ---- step 2 on the 4 by 4 coarse torus: 4 summed-out sites, 12 kept spins, 4096 configurations ------------
COARSE = 4
COARSE_B = [(u, v) for u in range(0, COARSE, 2) for v in range(0, COARSE, 2)]
COARSE_KEPT = [(u, v) for u in range(COARSE) for v in range(COARSE) if (u % 2, v % 2) != (0, 0)]


def coarse_block_pattern(cfg, b):
    return tuple(cfg[((b[0] + du) % COARSE, (b[1] + dv) % COARSE)] for du, dv in BLOCK_SITES)


def coarse_weight_poly(cfg, block_polys):
    """W2 as a polynomial in p and q, exact: the product over the four summed-out sites of the block factor."""
    w = {(0, 0): 1}
    for b in COARSE_B:
        w = poly_times(w, block_polys[coarse_block_pattern(cfg, b)])
    return tuple(sorted(w.items()))


def coarse_weight_brute(cfg, y_p, y_q):
    """W2 from its definition, as a number at rational p and q: the sum over the four summed-out spins of the
    product over the 16 faces."""
    total = F(0)
    for sb in itertools.product((1, -1), repeat=len(COARSE_B)):
        full = dict(cfg)
        full.update(zip(COARSE_B, sb))
        e_p = e_q = 0
        for u in range(COARSE):
            for v in range(COARSE):
                c = [full[(u, v)], full[((u + 1) % COARSE, v)], full[(u, (v + 1) % COARSE)], full[((u + 1) % COARSE, (v + 1) % COARSE)]]
                e_p += sum(c[i] * c[j] for i in range(4) for j in range(i + 1, 4))
                e_q += c[0] * c[1] * c[2] * c[3]
        total += y_p ** e_p * y_q ** e_q
    return total


def coarse_eval(poly, p, q):
    return sum(c * p ** i * q ** j for (i, j), c in poly)


def check_coarse_product(cfg, block_polys, p, q):
    """The product of block factors against the definition of W2, at rational p and q."""
    require(coarse_eval(coarse_weight_poly(cfg, block_polys), p, q) == coarse_weight_brute(cfg, p, q),
            "the block product differs from the definition")


def coarse_pair_set(kind):
    """Pairs of kept coarse sites for the descriptions that the first step suggests."""
    pairs = {}
    for a in COARSE_KEPT:
        for c in COARSE_KEPT:
            if a < c:
                d = ((c[0] - a[0]) % COARSE, (c[1] - a[1]) % COARSE)
                d = min(d, ((-d[0]) % COARSE, (-d[1]) % COARSE))
                pairs.setdefault(d, []).append((a, c))
    if kind == "nn_and_diag":
        nn = [pr for d in ((1, 0), (0, 1)) for pr in pairs.get(d, [])]
        dg = [pr for d in ((1, 1), (1, 3)) for pr in pairs.get(d, [])]
        return [nn, dg]
    return [pairs[d] for d in sorted(pairs)]


def coarse_configs():
    for vals in itertools.product((1, -1), repeat=len(COARSE_KEPT)):
        yield dict(zip(COARSE_KEPT, vals))


def coarse_orbit_vector(cfg, table_index, table):
    """The 27 orbit sums: for each summed-out site add the table row of its pattern's class."""
    vec = [0] * len(table[0])
    for b in COARSE_B:
        row = table[table_index[block_class_of(coarse_block_pattern(cfg, b))]]
        for k, v in enumerate(row):
            vec[k] += v
    return tuple(vec)


def coarse_forks(keys_and_polys):
    """Classes (value of the description) that hold two different weights, and the class count."""
    classes = {}
    for key, poly in keys_and_polys:
        classes.setdefault(key, set()).add(poly)
    return [k for k, v in classes.items() if len(v) > 1], len(classes)


def coarse_census(drop=()):
    """Weights as polynomials, and the descriptions D0 (restricted first-step description), D1 (all pair sums),
    D2 (the 27 orbit sums, minus the orbits listed in drop)."""
    block_polys = {pat: block_poly(pat) for pat in BLOCK_PATTERNS}
    classes, orbits, table = block_tables()
    index = {c: i for i, c in enumerate(classes)}
    d0, d1 = coarse_pair_set("nn_and_diag"), coarse_pair_set("all")
    keep = [k for k in range(len(orbits)) if k not in drop]
    rows = []
    for cfg in coarse_configs():
        poly = coarse_weight_poly(cfg, block_polys)
        vec = coarse_orbit_vector(cfg, index, table)
        rows.append((cfg, poly, vec))
    return rows, classes, orbits, table, d0, d1, keep


def pair_sums(cfg, groups):
    return tuple(sum(cfg[a] * cfg[c] for a, c in g) for g in groups)


def root8_interval(r, bits=64):
    """Exact Fractions lo <= r^(1/8) <= hi, with hi - lo = 2^-bits."""
    m = (r.numerator << (8 * bits)) // r.denominator
    n = int(round(m ** (1 / 8)))
    while n ** 8 > m:
        n -= 1
    while (n + 1) ** 8 <= m:
        n += 1
    return F(n, 2 ** bits), F(n + 1, 2 ** bits)


def curve_interval(x):
    """Intervals for p and q on the K curve at x = e^(2K), x a rational above 1."""
    c2, c4 = (x + 1 / x) / 2, (x * x + 1 / (x * x)) / 2
    return root8_interval(c4), root8_interval(c4 / c2 ** 4)


def poly_interval(poly, pi, qi):
    """Exact enclosure of sum c * p^i * q^j for p in pi, q in qi, all terms with positive c."""
    lo = hi = F(0)
    for (i, j), c in poly:
        require(c > 0, "interval sums need positive coefficients")
        lo += c * (pi[0] if i >= 0 else pi[1]) ** i * (qi[0] if j >= 0 else qi[1]) ** j
        hi += c * (pi[1] if i >= 0 else pi[0]) ** i * (qi[1] if j >= 0 else qi[0]) ** j
    return lo, hi


def check_fork_on_curve(poly1, poly2, x):
    """The two weights are different numbers on the K curve at x: their enclosures do not meet."""
    pi, qi = curve_interval(x)
    a, b = poly_interval(poly1, pi, qi), poly_interval(poly2, pi, qi)
    require(a[1] < b[0] or b[1] < a[0], "the enclosures of the two weights meet at x = %s" % x)


def first_fork(rows, key_of):
    classes = {}
    for cfg, poly, vec in rows:
        classes.setdefault(key_of(cfg, vec), {}).setdefault(poly, cfg)
    for key, polys in classes.items():
        if len(polys) > 1:
            return list(polys)[:2]
    return None


def run_second_step_census(curve_points=(F(2), F(3, 2), F(7, 5), F(5))):
    rows, classes, orbits, table, d0, d1, keep = coarse_census()
    out = {"class_count": len(classes), "orbit_count": len(orbits)}
    out["blocks_checked"] = check_block_symmetry()
    check_invertible(table)
    # the weight formula against the definition on seeded configurations at generic rational p and q
    rng = random.Random(SEED_DECIM)
    block_polys = {pat: block_poly(pat) for pat in BLOCK_PATTERNS}
    for _ in range(6):
        cfg = {s: rng.choice((1, -1)) for s in COARSE_KEPT}
        for p, q in ((F(3, 2), F(5, 4)), (F(7, 5), F(2, 3))):
            check_coarse_product(cfg, block_polys, p, q)
    # D2 closes, D0 and D1 fork
    f2 = coarse_forks([(vec, poly) for cfg, poly, vec in rows])
    require(not f2[0], "the 27 orbit sums fork")
    f0 = coarse_forks([(pair_sums(cfg, d0), poly) for cfg, poly, vec in rows])
    f1 = coarse_forks([(pair_sums(cfg, d1), poly) for cfg, poly, vec in rows])
    require(f0[0] and f1[0], "the restricted or the pair description should fork")
    out["D2"], out["D0"], out["D1"] = (f2[1], len(f2[0])), (f0[1], len(f0[0])), (f1[1], len(f1[0]))
    for name, groups in (("D0", d0), ("D1", d1)):
        pair = first_fork(rows, lambda cfg, vec, g=groups: pair_sums(cfg, g))
        for x in curve_points:
            check_fork_on_curve(pair[0], pair[1], x)
    out["curve_points"] = [str(x) for x in curve_points]
    return out


def run_drop_census():
    """Drop orbits from the 27 on the 4 by 4 coarse torus: no fork, for every single orbit of degree 4 or more
    and for all of degrees 6 and 8 together. Keeping only the constant and the degree-2 orbits forks."""
    rows, classes, orbits, table, d0, d1, keep = coarse_census()
    degree = [len(o) for o in orbits]
    def forks_without(dropped):
        kept = [k for k in range(len(orbits)) if k not in dropped]
        return coarse_forks([(tuple(vec[k] for k in kept), poly) for cfg, poly, vec in rows])
    out = {"single_drops_without_fork": 0}
    for k in range(len(orbits)):
        if degree[k] >= 4:
            f = forks_without({k})
            require(not f[0], "dropping orbit %d forks on the 4x4 coarse torus" % k)
            out["single_drops_without_fork"] += 1
    f = forks_without({k for k in range(len(orbits)) if degree[k] >= 6})
    require(not f[0], "dropping degrees 6 and 8 forks on the 4x4 coarse torus")
    out["degree_6_and_8_dropped"] = (f[1], len(f[0]))
    g = forks_without({k for k in range(len(orbits)) if degree[k] >= 4})
    require(g[0], "keeping degrees 0 and 2 should fork")
    out["degree_0_and_2_only"] = (g[1], len(g[0]))
    return out


def dual_bounds():
    """For each non-constant orbit: the sum of absolute values of its least integer dual vector, and so the least
    number of summed-out sites on which dropping that orbit alone can fork, half that sum."""
    classes, orbits, table = block_tables()
    out = {}
    for k, o in enumerate(orbits):
        if len(o) == 0:
            continue
        vec = dual_vector(table, k)
        check_dual_vector(table, k, vec)
        out.setdefault(len(o), []).append(sum(abs(v) for v in vec) // 2)
    return {d: sorted(v) for d, v in out.items()}


# ---- the coefficients of the weight in the spin-monomial (Walsh) basis -----------------------------------------
# ln(2 cosh h) over the 8 neighbours of a summed-out coarse site, with h = beta*S + gamma*T and beta, gamma from the
# K curve. Its coefficient on a monomial is the average of the function times the monomial over the 256 patterns.
# Arithmetic: 40-digit Decimal. This is numerical, not exact, and no error bound is carried.
DECIMAL_DIGITS = 40


def walsh_groups():
    """Patterns grouped by (S, T), with for each even orbit the sum of its representative monomial over the group."""
    reps = sorted(block_even_orbits(), key=lambda k: (len(k), k))
    groups = {}
    for pat in BLOCK_PATTERNS:
        _, s, t = block_exponents(pat)
        g = groups.setdefault((s, t), [0] * len(reps))
        for k, r in enumerate(reps):
            g[k] += prod_of(pat, r)
    return reps, groups


def walsh_coefficients(x, reps, groups):
    """The 27 coefficients at x = e^(2K), a rational above 1."""
    with decimal.localcontext() as ctx:
        ctx.prec = DECIMAL_DIGITS
        xd = decimal.Decimal(x.numerator) / decimal.Decimal(x.denominator)
        c2, c4 = (xd + 1 / xd) / 2, (xd * xd + 1 / (xd * xd)) / 2
        beta = c4.ln() / 8
        gamma = beta - c2.ln() / 2
        out = [decimal.Decimal(0)] * len(reps)
        for (s, t), w in groups.items():
            h = beta * s + gamma * t
            v = (h.exp() + (-h).exp()).ln()
            out = [o + wk * v for o, wk in zip(out, w)]
        return [o / 256 for o in out]


def check_sign_change(before, after):
    require(before * after < 0, "no sign change between the two ends")


def zero_scan_grid():
    """x = 1 + i/50 up to 3, then 3 + i/10 up to 40."""
    return [F(50 + i, 50) for i in range(1, 101)] + [F(30 + i, 10) for i in range(1, 371)]


def scan_for_zeros():
    reps, groups = walsh_groups()
    xs = zero_scan_grid()
    prev = walsh_coefficients(xs[0], reps, groups)
    smallest = min(abs(v) for v in prev)
    found = []
    for a, b in zip(xs, xs[1:]):
        cur = walsh_coefficients(b, reps, groups)
        smallest = min(smallest, min(abs(v) for v in cur))
        found += [(k, a, b) for k in range(len(reps)) if prev[k] * cur[k] < 0]
        prev = cur
    return reps, groups, found, smallest


def locate_zero(k, a, b, reps, groups, steps=45):
    """Bisect the sign change of orbit k between a and b, with exact rational midpoints."""
    sa = walsh_coefficients(a, reps, groups)[k]
    sb = walsh_coefficients(b, reps, groups)[k]
    check_sign_change(sa, sb)
    for _ in range(steps):
        mid = (a + b) / 2
        if walsh_coefficients(mid, reps, groups)[k] * sa > 0:
            a = mid
        else:
            b = mid
    return a, b


def run_zero_census():
    reps, groups, found, smallest = scan_for_zeros()
    out = {"grid_points": len(zero_scan_grid()), "smallest_abs_coefficient_on_grid": float(smallest), "zeros": []}
    for k, a, b in found:
        lo, hi = locate_zero(k, a, b, reps, groups)
        out["zeros"].append((len(reps[k]), reps[k], float((lo + hi) / 2)))
    return out


class TestDecimation(unittest.TestCase):
    """docs/09 section 7.7: decimation of the Ising model as a closure defect."""

    def test_doc09_c5_decimation_ring_has_no_fork(self):
        census = run_ring_census()
        self.assertEqual(census["classes"], {3: 2, 4: 3, 5: 3, 6: 4, 7: 4})
        self.assertEqual(census["couplings"], ["2", "3/2", "5/3"])

    def test_doc09_c5_decimation_torus_fork_and_one_step_closure(self):
        census = run_torus_census()
        self.assertEqual((census["4x4_nn_classes"], census["4x4_nn_forking"]), (7, 1))
        self.assertEqual(census["4x4_signatures_in_forking_class"][:1], [(0, 8, 0)])
        self.assertIn((4, 4, 0), census["4x4_signatures_in_forking_class"])
        self.assertEqual(census["4x4_enlarged_classes"], 12)
        self.assertEqual(census["4x4_without_four_spin_forking"], 1)
        self.assertEqual(census["witness_nn_value"], 40)

    def test_doc09_c5_decimation_second_step_and_dropped_terms(self):
        census = run_second_step_census()
        self.assertEqual((census["class_count"], census["orbit_count"]), (27, 27))
        self.assertEqual((census["D2"], census["D0"], census["D1"]), ((115, 0), (29, 19), (268, 21)))
        drops = run_drop_census()
        self.assertEqual(drops, {"single_drops_without_fork": 20, "degree_6_and_8_dropped": (115, 0), "degree_0_and_2_only": (108, 6)})
        self.assertEqual(dual_bounds(), {2: [15, 15, 16, 16, 32, 32], 4: [12, 12, 15, 15, 15, 15, 16, 16, 16, 16, 16, 64, 64],
                                         6: [15, 15, 16, 16, 32, 32], 8: [64]})

    def test_doc09_c5_decimation_isolated_zeros_of_block_coefficients(self):
        census = run_zero_census()
        got = sorted((deg, round(x, 6)) for deg, _, x in census["zeros"])
        self.assertEqual(got, [(4, 2.062078), (4, 3.755034), (4, 4.250651), (6, 1.987456)])
        self.assertGreater(census["smallest_abs_coefficient_on_grid"], 1e-30)

    def test_doc09_c5_decimation_checks_go_red(self):
        # Ring: the magnetization is not a closed description, and a corrupted weight forks.
        self.assertTrue(goes_red(check_ring_has_no_fork, 5, lambda a: sum(a), ring_weight_brute))
        first = tuple([1] * 5)
        self.assertTrue(goes_red(check_ring_has_no_fork, 5, ring_nn,
                                 lambda a, y: ring_weight_brute(a, y) + (1 if a == first else 0)))
        self.assertTrue(goes_red(check_ring_closed_form, 4, F(2), 1))                  # one extra aligned bond
        # Torus: the witness with its two configurations made equal is not a fork, and unequal descriptions are not either.
        a1 = torus_flipped(6, 6, WITNESS_TWO)
        self.assertTrue(goes_red(check_torus_fork, 6, 6, a1, dict(a1), F(2)))
        self.assertTrue(goes_red(check_torus_fork, 6, 6, a1, torus_flipped(6, 6, WITNESS_L[:1]), F(2)))
        # Enlarged description: without the four-spin term it forks, and a corrupted weight forks.
        self.assertTrue(goes_red(check_closes, 4, 4, torus_spec_no_four_spin))
        self.assertTrue(goes_red(check_closes, 4, 4, torus_spec_enlarged,
                                 lambda a, lx, ly, y: torus_weight(a, lx, ly, y) * (10 + a[(0, 0)])))
        # The local identity with a wrong power of the four-spin factor is refused.
        self.assertTrue(goes_red(check_local_identity, F(2), 1))
        # Weight formula against the definition: a wrong coupling in the formula is caught.
        self.assertTrue(goes_red(check_torus_weight_formula, 4, 4, F(2),
                                 lambda a, lx, ly, y: decim_weight_product(torus_sums(a, lx, ly), y + 1)))
        cfg = {s: 1 for s in COARSE_KEPT}
        wrong = {pat: {(0, 0): 2} for pat in BLOCK_PATTERNS}
        self.assertTrue(goes_red(check_coarse_product, cfg, wrong, F(3, 2), F(5, 4)))
        # Second step: a rank-deficient orbit table, a corrupted dual vector, and weights that meet are all refused.
        _, _, table = block_tables()
        self.assertTrue(goes_red(check_invertible, [row[:] for row in table[:-1]] + [list(table[0])]))
        vec = dual_vector(table, 26)
        self.assertTrue(goes_red(check_dual_vector, table, 26, vec[:-1] + [vec[-1] + 1]))
        w = (((0, 0), 1),)
        self.assertTrue(goes_red(check_fork_on_curve, w, w, F(2)))
        # A bracket with no sign change is refused.
        reps, groups = walsh_groups()
        self.assertTrue(goes_red(locate_zero, 0, F(2), F(3), reps, groups))


def print_report():
    g = load_gatecheck()
    counts = check_toy_counts(g, real=True)
    print("Contract 1, toy gates:", counts)
    print("  harness sabotages that must go red:", len(SABOTAGES))
    print("Contract 4, latch census:", run_latch_census())
    print("  stationary-point instances:", run_local_latch_census(), " gradient-descent instances:", run_descent_census())
    runs, accepted = check_exact_gate_is_sound_under_feedback()
    ab = run_absorption_census()
    print("Claim 9, one anchor absorbed (seed %d):" % SEED_ABSORB, ab)
    print("  several anchors (seed %d): %d  revisions (seed %d): %d" % (SEED_SEVERAL, run_several_census(), SEED_REVISE, run_revision_census()))
    print("Contract 3, exact gate under feedback: loops run", runs, " loops that ended in an accept", accepted, " false accepts 0")
    print("  unsound gates exploited without feedback:", check_unsound_gate_is_exploitable())
    print("  sampled oracle, (samples, committed false passes, false passes after one detailed answer):",
          check_detail_exposes_a_sampled_oracle())
    print("Closure census:", run_closure_census())
    print("Polarity census:", run_polarity_census())
    print("Decimation, ring (sizes, couplings y = e^K, classes per size):", run_ring_census())
    print("Decimation, torus (seed %d):" % SEED_DECIM, run_torus_census())
    print("Decimation, second step on the 4x4 coarse torus:", run_second_step_census())
    print("  dropped orbits:", run_drop_census(), " least summed-out sites per single dropped orbit, by degree:", dual_bounds())
    print("  zeros of block coefficients:", run_zero_census())
    print("Thousandths as 32-bit floats (above, below, equal, n/1024 exact):", thousandths_as_float32())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        print_report()
    else:
        unittest.main()
