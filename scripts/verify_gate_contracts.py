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
import hashlib
import io
import itertools
import json
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
        self.assertGreater(census["boundary_strictly_between_0_and_1"], 50)

    def test_doc09_c4_stationary_point_and_gradient_steps(self):
        self.assertGreaterEqual(run_local_latch_census(), 50)
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
        self.assertGreater(accepted, 0)
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
        self.assertEqual(census["systems"], 60)
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
        # Thousandths counted with 64-bit floats show no excess, so the count depends on the 32-bit step.
        self.assertEqual(sum(F(k / 1000) > F(k, 1000) for k in range(1, 1001)) == 503, False)


def print_report():
    g = load_gatecheck()
    counts = check_toy_counts(g, real=True)
    print("Contract 1, toy gates:", counts)
    print("  harness sabotages that must go red:", len(SABOTAGES))
    print("Contract 4, latch census:", run_latch_census())
    print("  stationary-point instances:", run_local_latch_census(), " gradient-descent instances:", run_descent_census())
    runs, accepted = check_exact_gate_is_sound_under_feedback()
    print("Contract 3, exact gate under feedback: loops run", runs, " loops that ended in an accept", accepted, " false accepts 0")
    print("  unsound gates exploited without feedback:", check_unsound_gate_is_exploitable())
    print("  sampled oracle, (samples, committed false passes, false passes after one detailed answer):",
          check_detail_exposes_a_sampled_oracle())
    print("Closure census:", run_closure_census())
    print("Polarity census:", run_polarity_census())
    print("Thousandths as 32-bit floats (above, below, equal, n/1024 exact):", thousandths_as_float32())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        print_report()
    else:
        unittest.main()
