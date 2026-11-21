#!/usr/bin/env python3
"""gatecheck: five conformance relations for any accept/reject gate.

Standard-library only (Apache-2.0). Companion to docs/09-gate-contracts.md.

A gate is a program whose verdict promotes a result: a certificate auditor, a file-header
reader, a loader. Each relation below compares runs of the same gate with each other. None
of them needs to know whether the claim inside a submission is true.

  R1 default reject    empty, blank, status-less and unknown-status inputs are rejected
  R2 omission          deleting required evidence from a rejected input never accepts it
  R3 encoding          a re-spelled input is rejected, or is read as the same typed value
  R4 optimizer parity  the verdict is the same under python3, python3 -O and -W error
  R5 isolation         every named check has a fixture that only that check rejects

Usage
  python3 -B gatecheck.py --self-test
  python3 -B gatecheck.py --adapter my_gate.py[:builder] [--repo DIR] --out DIR

An adapter file defines a builder function (default name `build`) that takes the
repository path and returns (adapter, accepted_fixtures, rejected_fixtures). The adapter
subclasses Adapter and implements run(text, meta, flags) -> Verdict, where flags is a list
of interpreter flags such as ["-O", "-B"]. Fixtures are Fixture(name, text, meta).
Optional adapter hooks:
  run_inproc(text, meta)   fast in-process call that must equal run(text, meta, PLAIN)
  plants()                 [(label, adapter)]: copies of the gate with one bare assert
                           turned into a failing assert
  check_variants()         [(check_name, adapter)]: copies of the gate with one check removed
Optional adapter attributes: required_keys, content_paths, cap, fail_fast, check_names,
extra_defaults, skip_defaults, reads_input. See class Adapter. An adapter closes every file
it opens: the self-test and the suite in verify_gate_contracts.py run under -W error.

Output of an adapter run: R1.json to R5.json (every violation with a reproducer),
baseline.json (fixtures the gate did not treat as labelled) and summary.json (one status
per relation, the run counts, and the SHA-256 of this file so a result names its harness).

Reading the result. Each relation reports one status:
  fail            a violation was found. The reproducer is in R<n>.json.
  pass            every generated case was run and none violated the relation.
  not_shown       no violation was found, but the run cannot support a pass: it was
                  sampled, or it accepted deletions that nobody has read, or the gate
                  stops at its first failure and no check-deleted copies were given.
  exposed         (R4 only) verdicts agree on every fixture, but a bare assert sits on
                  the accepting path and does not run under -O.
  vacuous         the gate rejects every fixture that was labelled accepted.
  not_applicable  the gate reads no artifact, or names no checks.
A pass is evidence about the fixtures that were run. It is not a proof about the gate.

Exit code: 0 no relation failed, 1 at least one relation failed, 2 usage or adapter error.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import copy
import hashlib
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import warnings
from dataclasses import dataclass, field
from fractions import Fraction

PLAIN, OPT, WERR = ["-B"], ["-O", "-B"], ["-B", "-W", "error"]
RELATIONS = ("R1", "R2", "R3", "R4", "R5")
STATUS_KEY = re.compile(r"status|verdict", re.I)


@dataclass
class Verdict:
    accept: bool
    value: str = ""        # what the gate says it accepted (a status word, a parsed header)
    codes: tuple = ()      # named checks that rejected, when the gate reports them
    crash: bool = False    # the gate died instead of answering. Counted as a rejection.


@dataclass
class Fixture:
    name: str
    text: str
    meta: dict = field(default_factory=dict)


class Adapter:
    name = "gate"
    check_names: tuple = ()
    fail_fast = False            # the gate reports only its first failing check
    cap = None                   # None runs every mutant. A number samples that many per relation.
    workers = 8
    shrink_limit = 8             # reproducers shrunk per relation (each costs extra gate runs)
    extra_defaults: tuple = ()   # more default-reject inputs, as (label, text)
    skip_defaults: tuple = ()    # default labels that are valid input for this gate
    required_keys = None         # key paths the gate's rules require, "*" for a list index.
                                 # None: use the keys that every accepted fixture carries.
    content_paths: tuple = ()    # key path prefixes that hold content, not evidence (a tensor
                                 # name in a header): deleting one gives another valid artifact
    reads_input = True           # False for a verifier that takes no artifact

    def run(self, text: str, meta: dict, flags: list) -> Verdict:  # pragma: no cover
        raise NotImplementedError


# ---------- JSON helpers ----------
class _Raw:
    def __init__(self, s):
        self.s = s


def pparse(text):
    try:
        return json.loads(text)
    except Exception:
        return _Raw(text)


def same(a, b):
    """Equality that also compares types (3 != 3.0, 1 != True)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def dump(obj, like):
    pretty = "\n  " in like
    s = json.dumps(obj, indent=2 if pretty else None)
    return s + "\n" if like.endswith("\n") else s


def compact(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def paths(obj, pre=()):
    """Yield (path, value) for every key and list element."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield pre + (k,), v
            yield from paths(v, pre + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield pre + (i,), v
            yield from paths(v, pre + (i,))


def norm(p):
    return tuple("*" if isinstance(x, int) else x for x in p)


def show(p):
    return "/".join(map(str, p))


def get(obj, p):
    for x in p:
        obj = obj[x]
    return obj


def setp(obj, p, v):
    o = copy.deepcopy(obj)
    t = o
    for x in p[:-1]:
        t = t[x]
    t[p[-1]] = v
    return o


def delp(obj, p):
    o = copy.deepcopy(obj)
    t = o
    for x in p[:-1]:
        t = t[x]
    del t[p[-1]]
    return o


def sample(items, cap, seed=0):
    if cap is None or len(items) <= cap:
        return list(items)
    return random.Random(seed).sample(items, cap)


def diff_paths(o, accs):
    """Paths where o differs from the closest accepted input (the planted defect, if o was made from one)."""
    def d(a, b, pre):
        if isinstance(a, dict) and isinstance(b, dict):
            out = []
            for k in sorted(set(a) | set(b), key=str):
                out += [pre + (k,)] if (k not in a or k not in b) else d(a[k], b[k], pre + (k,))
            return out
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            return [q for i in range(len(a)) for q in d(a[i], b[i], pre + (i,))]
        return [] if same(a, b) else [pre]
    best = None
    for a in accs:
        r = d(o, a, ())
        if best is None or len(r) < len(best):
            best = r
    return best or []


def probe_value(v):
    """A different value of the same type. If the gate rejects it, the gate pins this leaf."""
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return v + 1
    if isinstance(v, float):
        return v + 1.0
    return str(v) + "X"


def leaf_mutants(v):
    """(label, value-or-raw-json, is_raw): other spellings of one leaf."""
    out = []
    if isinstance(v, bool):
        return [("bool-as-int", "1" if v else "0", True), ("bool-as-string", str(v).lower(), False)]
    if isinstance(v, int):
        out += [("int-as-float", f"{v}.0", True), ("int-as-exponent", f"{v}e0", True), ("int-as-string", str(v), False),
                ("int-as-string-nonascii", "".join(chr(0x660 + int(c)) if c.isdigit() else c for c in str(v)), False)]
        if abs(v) >= 100:
            out.append(("int-digit-separators", f"{str(v)[:-2]}_{str(v)[-2:]}", False))
    elif isinstance(v, float):
        out += [("float-as-string", repr(v), False)]
    elif isinstance(v, str):
        out += [("trailing-newline", v + "\n", False), ("padded", " " + v + " ", False)]
        for lab, w in (("upper", v.upper()), ("lower", v.lower())):
            if w != v:
                out.append((lab, w, False))
        if re.fullmatch(r"-?\d+", v):
            out += [("digits-nonascii", "".join(chr(0x660 + int(c)) if c.isdigit() else c for c in v), False)]
            if len(v) > 2:
                out.append(("digits-separators", v[:-2] + "_" + v[-2:], False))
        if re.fullmatch(r"-?\d+/\d+", v):
            n, d = map(int, v.split("/"))
            out += [("rational-as-decimal-string", format(float(Fraction(n, d)), ".17g"), False)]
    return out


# Spellings that leave the intended value alone. Applied to rejected inputs: the rejection must survive.
SAME_VALUE = ("int-as-float", "int-as-exponent", "int-as-string", "int-as-string-nonascii", "int-digit-separators",
              "bool-as-int", "bool-as-string", "trailing-newline", "padded", "digits-nonascii", "digits-separators")
RAW_MARK, RAW_JSON = "\0R\0", '"\\u0000R\\u0000"'


def respell(o, p, value, raw, like):
    """Text of o with the leaf at p re-spelled. raw means value is JSON source, not a JSON string."""
    t = dump(setp(o, p, RAW_MARK if raw else value), like)
    return t.replace(RAW_JSON, value) if raw else t


# ---------- engine ----------
class Engine:
    def __init__(self, ad: Adapter, accepted=(), rejected=()):
        self.ad, self.acc_all, self.rej_all = ad, list(accepted), list(rejected)
        self.acc, self.rej = self.acc_all, self.rej_all    # narrowed by all() to what the gate really does
        self.runs = self.crashes = 0
        self._r1 = None

    def _run(self, text, meta, flags, real):
        try:
            if not real and flags == PLAIN and hasattr(self.ad, "run_inproc"):
                return self.ad.run_inproc(text, meta)
            return self.ad.run(text, meta, flags)
        except Exception as exc:    # an adapter failure is a crash, counted as a rejection
            return Verdict(False, "", ("ADAPTER_ERROR:" + type(exc).__name__,), True)

    def _count(self, verdicts):
        self.runs += len(verdicts)
        self.crashes += sum(bool(v.crash) for v in verdicts)

    def one(self, text, meta, flags=PLAIN, real=False):
        v = self._run(text, meta, flags, real)
        self._count([v])
        return v

    def many(self, jobs, flags=PLAIN, real=False):
        if not real and flags == PLAIN and hasattr(self.ad, "run_inproc"):
            vs = [self._run(t, m, flags, real) for t, m in jobs]
        else:
            with cf.ThreadPoolExecutor(self.ad.workers) as ex:
                vs = list(ex.map(lambda j: self._run(j[0], j[1], flags, real), jobs))
        self._count(vs)     # counted here, in one thread
        return vs

    def accepts(self, obj, meta, like=""):
        return self.one(dump(obj, like), meta).accept

    def baseline(self):
        out = []
        for f, want in [(f, True) for f in self.acc_all] + [(f, False) for f in self.rej_all]:
            v = self.one(f.text, f.meta)
            if v.accept != want:
                out.append(dict(fixture=f.name, expected="accept" if want else "reject",
                                got="accept" if v.accept else "reject", detail=v.value))
        return out

    # R1 default reject
    def r1(self):
        defaults = [("empty", ""), ("blank", " \n\t"), ("empty-object", "{}"), ("empty-list", "[]"), ("null", "null"),
                    ("status-empty", '{"epistemic_status": ""}'), ("status-unknown", '{"epistemic_status": "UNKNOWN"}'),
                    ("status-banana", '{"status": "banana"}')] + list(self.ad.extra_defaults)
        for f in self.acc:    # status words of accepted inputs replaced by unknown ones
            o = pparse(f.text)
            for p, v in paths(o) if not isinstance(o, _Raw) else []:
                if isinstance(v, str) and STATUS_KEY.search(str(p[-1])):
                    defaults.append((f"{f.name}:{show(p)}=unknown", dump(setp(o, p, "NOT_A_STATUS"), f.text)))
                    defaults.append((f"{f.name}:{show(p)}=blank", dump(setp(o, p, ""), f.text)))
                    defaults.append((f"{f.name}:{show(p)}=removed", dump(delp(o, p), f.text)))
        defaults = [d for d in defaults if d[0] not in self.ad.skip_defaults]
        meta = self.acc[0].meta if self.acc else {}
        vs = self.many([(t, meta) for _, t in defaults])
        viol = [dict(kind="default_accepted", mutation=lab, reproducer=t, verdict=v.value)
                for (lab, t), v in zip(defaults, vs) if v.accept]
        self._r1 = dict(generated=len(defaults), run=len(defaults), violations=viol)
        return self._r1

    # R2 omission
    def r2(self):
        r1 = self._r1 or self.r1()
        acc = [o for o in (pparse(f.text) for f in self.acc) if not isinstance(o, _Raw)]
        if self.ad.required_keys is not None:
            required, source = {tuple(k) for k in self.ad.required_keys}, "declared by the adapter"
        else:
            key_sets = [{norm(p) for p, _ in paths(o)} for o in acc]
            required = set.intersection(*key_sets) if key_sets else set()
            source = f"inferred: keys carried by all {len(acc)} accepted fixtures"
        empty_ok = {norm(p) for o in acc for p, v in paths(o) if v == []}
        content = [tuple(c) for c in self.ad.content_paths]
        jobs = []
        for f in self.rej:
            o = pparse(f.text)
            if isinstance(o, _Raw):
                continue
            jobs += [(f, p, o) for p, _ in paths(o)]
        gen = len(jobs)
        jobs = sample(jobs, self.ad.cap)
        vs = self.many([(dump(delp(o, p), f.text), f.meta) for f, p, o in jobs])
        defect = {f.name: diff_paths(pparse(f.text), acc) for f in self.rej if not isinstance(pparse(f.text), _Raw)}
        viol, to_read, restored, cont = [], [], [], []
        for (f, p, o), v in zip(jobs, vs):
            if not v.accept:
                continue
            after = delp(o, p)
            rec = dict(kind="omission_accepted", fixture=f.name, deleted=show(p), verdict=v.value,
                       list_element=isinstance(p[-1], int),
                       removes_defect=any(p == d[:len(p)] or d == p[:len(d)] for d in defect[f.name]))
            if isinstance(p[-1], int):
                hard = len(get(o, p[:-1])) == 1 and norm(p[:-1]) not in empty_ok
            else:
                hard = norm(p) in required
            if hard:
                rec["also_r1"] = bool(r1["violations"]) and bool(STATUS_KEY.search(str(p[-1])))
                if len(viol) < self.ad.shrink_limit:
                    rec["rejected_before"], rec["accepted_after"] = self.shrink_pair(f, p, o)
                viol.append(rec)
            elif any(same(after, a) for a in acc):
                restored.append(rec)      # the deletion gave back a fixture that is accepted anyway
            elif any(norm(p)[:len(c)] == c for c in content):
                cont.append(rec)
            else:
                to_read.append(rec)
        return dict(generated=gen, run=len(jobs), sampled=len(jobs) < gen, required_source=source,
                    violations=viol, beyond_r1=sum(not r.get("also_r1") for r in viol),
                    to_read=to_read, restored=restored, content=cont)

    def shrink_pair(self, f, p, o):
        """Greedy: drop other top-level keys while the gate still rejects the input and accepts it minus p."""
        cur = o
        if isinstance(cur, dict):
            for k in list(cur):
                if k == p[0]:
                    continue
                c = delp(cur, (k,))
                if not self.accepts(c, f.meta, f.text) and self.accepts(delp(c, p), f.meta, f.text):
                    cur = c
        return compact(cur), compact(delp(cur, p))

    # R3 encoding
    def r3(self):
        jobs = []    # (fixture, label, text, kind, path)
        for f in self.acc:
            o = pparse(f.text)
            for lab, t in [("trailing-newline", f.text + "\n"), ("trailing-spaces", f.text + "  "),
                           ("leading-whitespace", "  \n" + f.text), ("crlf", f.text.replace("\n", "\r\n"))]:
                jobs.append((f, lab, t, "text", None))
            if isinstance(o, _Raw):
                continue
            for p, v in paths(o):
                for lab, nv, raw in leaf_mutants(v):
                    jobs.append((f, lab, respell(o, p, nv, raw, f.text), "leaf", p))
            if isinstance(o, dict):
                for k in o:
                    t = "{" + json.dumps(k) + ": null, " + dump(o, f.text).lstrip()[1:]
                    jobs.append((f, "duplicate-key-first-null", t, "dup", (k,)))
        rjobs = []   # the same spellings applied to rejected inputs
        for f in self.rej:
            o = pparse(f.text)
            if isinstance(o, _Raw):
                continue
            for p, v in paths(o):
                for lab, nv, raw in leaf_mutants(v):
                    if lab not in SAME_VALUE or (isinstance(v, str) and not v.strip()):
                        continue
                    rjobs.append((f, lab, respell(o, p, nv, raw, f.text), "rej", p))
        gen = len(jobs) + len(rjobs)
        text_jobs = [j for j in jobs if j[3] == "text"]
        jobs = text_jobs + sample([j for j in jobs if j[3] != "text"], self.ad.cap) + sample(rjobs, self.ad.cap)
        base = {f.name: self.one(f.text, f.meta) for f in self.acc}
        vs = self.many([(t, f.meta) for f, _, t, _, _ in jobs])
        bypass, spelling, soft = [], [], []
        for (f, lab, t, kind, p), v in zip(jobs, vs):
            if not v.accept:
                continue
            o, m = pparse(f.text), pparse(t)
            rec = dict(kind=lab, fixture=f.name, path=show(p) if p else "", reproducer=t, verdict=v.value)
            if kind == "rej":      # a rejected input was accepted after a same-value re-spelling
                rec["kind"] = "rejected_input_accepted:" + lab
                if len(bypass) < self.ad.shrink_limit and not isinstance(m, _Raw):
                    rec["rejected_before"], rec["reproducer"] = self.shrink_respelled(f, p, o, m, None)
                bypass.append(rec)
            elif kind == "dup":
                soft.append(dict(rec, kind="duplicate_key_accepted_last_wins"))
            elif isinstance(m, _Raw):
                spelling.append(dict(rec, kind="unparseable_accepted"))
            elif same(o, m):
                continue           # another text for the same typed value
            elif (p and STATUS_KEY.search(str(p[-1])) and lab in ("upper", "lower", "padded", "trailing-newline")
                  and v.value == base[f.name].value):
                continue           # the gate reports the same normalized status word
            elif o == m:
                soft.append(dict(rec, kind="type_confusion_accepted:" + lab))
            else:
                probe = probe_value(get(o, p))
                if self.accepts(setp(o, p, probe), f.meta, f.text):
                    continue       # a different value passes too, so the gate does not pin this leaf
                rec["kind"] = "noncanonical_accepted:" + lab
                if len(spelling) < self.ad.shrink_limit:
                    rec["reproducer"] = self.shrink_respelled(f, p, o, m, probe)[1]
                spelling.append(rec)
        return dict(generated=gen, run=len(jobs), sampled=len(jobs) < gen, violations=bypass + spelling,
                    bypass=len(bypass), spelling=len(spelling), soft=soft)

    def shrink_respelled(self, f, p, o, m, probe):
        """Drop other top-level keys from the original o and its re-spelled copy m together.

        Keeps: the gate accepts m. With probe None (a bypass) it also still rejects o. With a
        probe (a spelling) it also still rejects o with the probe value at p."""
        if isinstance(o, dict) and isinstance(m, dict):
            for k in list(o):
                if k == p[0] or k not in m:
                    continue
                o2, m2 = delp(o, (k,)), delp(m, (k,))
                other = o2 if probe is None else setp(o2, p, probe)
                if self.accepts(m2, f.meta, f.text) and not self.accepts(other, f.meta, f.text):
                    o, m = o2, m2
        return compact(o), compact(m)

    # R4 optimizer parity
    def r4(self):
        fx = self.acc_all + self.rej_all
        jobs = [(f.text, f.meta) for f in fx]
        base = self.many(jobs, PLAIN, real=True)
        viol = []
        for mode, flags in (("-O", OPT), ("-W error", WERR)):
            for f, b, v in zip(fx, base, self.many(jobs, flags, real=True)):
                if (b.accept, b.value) != (v.accept, v.value):
                    viol.append(dict(kind="verdict_differs", mode=mode, fixture=f.name, plain=[b.accept, b.value],
                                     other=[v.accept, v.value], reproducer=f.text))
        mismatch = []    # the fast in-process path must be the same function as the real run
        if hasattr(self.ad, "run_inproc"):
            for f, b in zip(fx, base):
                v = self.one(f.text, f.meta)
                if (b.accept, b.value, tuple(b.codes)) != (v.accept, v.value, tuple(v.codes)):
                    mismatch.append(f.name)
        plants, exposures = [], []
        good = next((f for f, b in zip(fx, base) if b.accept), None)
        for label, ad2 in (self.ad.plants() if hasattr(self.ad, "plants") and good else []):
            e2 = Engine(ad2)
            p, o = e2.one(good.text, good.meta, PLAIN, real=True), e2.one(good.text, good.meta, OPT, real=True)
            self.runs += 2
            plants.append(dict(plant=label, plain_rejects=not p.accept, O_rejects=not o.accept))
            if not p.accept and o.accept:
                exposures.append(dict(kind="assert_stripped_under_O", plant=label, fixture=good.name))
        n = 3 * len(fx) + 2 * len(plants)
        return dict(generated=n, run=n, violations=viol, exposures=exposures, plants=plants,
                    inproc_mismatches=mismatch, bare_asserts=getattr(self.ad, "bare_asserts", None))

    # R5 isolation
    def r5(self):
        names = list(self.ad.check_names)
        if not names:
            return dict(applicable=False, reason="gate names no checks", violations=[])
        seen = {}
        for f, v in zip(self.rej, self.many([(f.text, f.meta) for f in self.rej])):
            if not v.accept and len(set(v.codes)) == 1:
                seen.setdefault(next(iter(v.codes)), f.name)
        missing = [c for c in names if c not in seen]
        variants = self.ad.check_variants() if hasattr(self.ad, "check_variants") else []
        deletable = []
        for c, ad2 in variants:
            e2 = Engine(ad2)
            killed = any(e2.one(f.text, f.meta).accept for f in self.rej)
            self.runs += e2.runs
            if not killed:
                deletable.append(c)
        out = dict(applicable=True, fail_fast=self.ad.fail_fast, check_names=names, isolated=seen, run=len(self.rej),
                   no_isolating_fixture=missing, variants=len(variants), deletable=deletable)
        if variants:
            # Deleting a check and watching the fixtures does not depend on how reasons are named.
            out["violations"] = [dict(kind="check_deletable", check=c) for c in deletable]
            if not self.ad.fail_fast and {c for c, _ in variants} == set(names):
                out["disagreement"] = sorted(set(missing) ^ set(deletable))
        else:
            out["violations"] = [dict(kind="no_isolating_fixture", check=c) for c in missing]
        return out

    def all(self):
        res = dict(baseline=self.baseline())
        wrong = {b["fixture"] for b in res["baseline"]}
        self.acc = [f for f in self.acc_all if f.name not in wrong]
        self.rej = [f for f in self.rej_all if f.name not in wrong]
        for k in RELATIONS:
            if self.ad.reads_input or k == "R4":
                res[k] = getattr(self, k.lower())()
            else:
                res[k] = dict(applicable=False, reason="gate reads no artifact", violations=[])
        res["vacuous"] = [b["fixture"] for b in res["baseline"] if b["expected"] == "accept"]
        res["runs"], res["crashes"] = self.runs, self.crashes
        res["summary"] = summarize(res, bool(self.acc), bool(self.rej))
        return res


def summarize(res, any_accepted=True, any_rejected=True):
    """One status per relation, with the counts a reader needs to weigh it."""
    out = {}
    for k in RELATIONS:
        r = res[k]
        n = len(r.get("violations", []))
        if r.get("applicable") is False:
            s, note = "not_applicable", r.get("reason", "")
        elif k == "R1":
            s, note = ("fail" if n else "pass"), f"{r['run']} default inputs"
        elif k == "R2":
            unread = len(r["to_read"])
            note = f"{r['run']} of {r['generated']} deletions run, {n} required-evidence deletions accepted"
            note += f" ({r['beyond_r1']} beyond the R1 defect), {unread} other accepted deletions to read"
            if n:
                s = "fail"
            elif not any_rejected:
                s, note = "not_applicable", "the gate rejects no fixture labelled rejected, so nothing to delete from"
            else:
                s = "not_shown" if (r["sampled"] or unread) else "pass"
        elif k == "R3":
            note = (f"{r['run']} of {r['generated']} spellings run, {r['bypass']} rejected inputs accepted after "
                    f"re-spelling, {r['spelling']} other spellings of a pinned value accepted, {len(r['soft'])} soft")
            if n:
                s = "fail"
            elif not any_accepted and not any_rejected:
                s = "vacuous"
            else:    # with no accepted fixture only the rejected-input half ran
                s = "not_shown" if (r["sampled"] or not any_accepted) else "pass"
        elif k == "R4":
            note = f"{n} verdict differences, {len(r['exposures'])} of {len(r['plants'])} planted asserts stripped by -O"
            if r["inproc_mismatches"]:
                s, note = "fail", "adapter error: run_inproc differs from run on " + ", ".join(r["inproc_mismatches"])
            else:
                s = "fail" if n else ("exposed" if r["exposures"] else "pass")
            if s == "pass" and not any_accepted:
                s = "vacuous"    # a gate that accepts nothing agrees with itself in every mode
        else:
            total = len(r["no_isolating_fixture"])
            note = f"{len(r['check_names']) - total} of {len(r['check_names'])} named checks have an isolating fixture"
            if r["variants"]:
                note += f", {len(r['deletable'])} of {r['variants']} checks can be deleted with every fixture verdict unchanged"
            if n:
                s = "fail"
            elif r["fail_fast"] and not r["variants"]:
                s, note = "not_shown", note + " (the gate stops at its first failure: give check_variants)"
            else:
                s = "pass"
        out[k] = dict(status=s, violations=n, note=note)
    return out


# ---------- toy gates (self-test) ----------
# One source text for both toy gates. The strict gate follows the contract in docs/09. Each
# line of the leaky gate that carries a comment breaks the relation named there.
TOY_SRC = r'''
import json, re, warnings

GOOD_STATUS = ("VERIFIED", "LOWER_BOUND")
KEYS = ("status", "digest", "n", "adapter", "xs", "checked", "dual", "witness")


def _no_duplicates(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError("duplicate key")
        d[k] = v
    return d


def gate(mode, raw, off=()):
    codes = []

    def flag(c):
        if c not in off and c not in codes:
            codes.append(c)
    try:
        d = json.loads(raw, object_pairs_hook=_no_duplicates) if mode == "strict" else json.loads(raw)
        if not isinstance(d, dict):
            raise ValueError("shape")
    except Exception:
        return {"accept": False, "value": "", "codes": ["C_PARSE"]}
    if mode == "strict":
        st, dg, n, ad, xs, w = (d.get(k) for k in ("status", "digest", "n", "adapter", "xs", "witness"))
        if any(k not in KEYS for k in d):
            flag("C_KEYS")
        if type(st) is not str or st not in GOOD_STATUS:
            flag("C_STATUS")
        if type(dg) is not str or not re.fullmatch("[0-9a-f]{64}", dg):
            flag("C_DIGEST")
        if type(n) is not int or n < 0 or n == 7:
            flag("C_N")
        if type(ad) is not str or not re.fullmatch("[A-Za-z0-9._-]+", ad):
            flag("C_ADAPTER")
        if type(xs) is not list or len(xs) != 3 or any(type(x) is not int or x != 1 for x in xs):
            flag("C_XS")
        if d.get("checked") is not True:
            flag("C_CHECKED")
        if type(d.get("dual")) is not bool:
            flag("C_DUAL")
        if (d.get("dual") is True or "witness" in d) and (type(w) is not str or not re.fullmatch("[a-z0-9]+", w)):
            flag("C_WITNESS")
        value = st if not codes else ""
    else:
        st = d.get("status")
        if st is not None and str(st).strip().upper() not in GOOD_STATUS:
            flag("C_STATUS")                      # R1, R2: an absent status passes
        if "digest" in d and not re.match("^[0-9a-f]{64}$", str(d["digest"])):
            flag("C_DIGEST")                      # R3: "$" lets a trailing newline through
        if "n" in d and int(d["n"]) < 0:
            flag("C_N")
            flag("C_SUB")                         # R5: C_SUB never fires without C_N
        try:
            if "adapter_path" in d:
                warnings.warn("adapter_path is deprecated", DeprecationWarning)
            if "adapter" in d and not d["adapter"]:
                flag("C_ADAPTER")                 # R2: an absent adapter passes
        except Exception:
            pass                                  # R4: under -W error the warning skips the check
        if "xs" in d and any(x != 1 for x in d["xs"]):
            flag("C_XS")                          # R2: the submission supplies the list that is checked
        if d.get("checked") is False:
            flag("C_CHECKED")                     # R3: 0 and "false" are not False, so they pass
        if d.get("dual") is True and not d.get("witness"):
            flag("C_WITNESS")                     # R3: dual written as 1 switches the check off
        assert d.get("n", 0) != 7, "n must not be 7"      # R4: python3 -O removes this line
        value = str(d.get("status", "")).strip().upper() if not codes else ""
    return {"accept": not codes, "value": value, "codes": codes}


if __name__ == "__main__":
    import sys
    print(json.dumps(gate(sys.argv[1], sys.stdin.read(), tuple(json.loads(sys.argv[2])))))
'''
TOY_ASSERT = 'assert d.get("n", 0) != 7, "n must not be 7"'
TOY_CHECKS = {"strict": ("C_KEYS", "C_STATUS", "C_DIGEST", "C_N", "C_ADAPTER", "C_XS", "C_CHECKED", "C_DUAL", "C_WITNESS"),
              "leaky": ("C_STATUS", "C_DIGEST", "C_N", "C_SUB", "C_ADAPTER", "C_XS", "C_CHECKED", "C_WITNESS")}


class ToyAdapter(Adapter):
    shrink_limit = 1000
    required_keys = (("status",), ("digest",), ("n",), ("adapter",), ("xs",), ("checked",), ("dual",))

    def __init__(self, mode, src=TOY_SRC, off=(), real=True):
        self.mode, self.src, self.off, self.real, self.name = mode, src, tuple(off), real, "toy-" + mode
        self.check_names = TOY_CHECKS[mode]
        self._gates = {}

    def _call(self, text, optimize, werror):
        """The toy gate in this process. optimize=1 drops assert statements the way python3 -O does."""
        if optimize not in self._gates:
            ns = {"__name__": "toy_gate"}
            # an explicit optimize level, so the result does not depend on how this harness was started
            exec(compile(self.src, "<toy-gate>", "exec", dont_inherit=True, optimize=optimize), ns)
            self._gates[optimize] = ns["gate"]
        with warnings.catch_warnings():
            warnings.simplefilter("error" if werror else "ignore")
            try:
                j = self._gates[optimize](self.mode, text, self.off)
            except Exception:
                return Verdict(False, "", ("CRASH",), True)
        return Verdict(j["accept"], j["value"], tuple(j["codes"]))

    def run_inproc(self, text, meta):
        return self._call(text, 0, False)

    def run(self, text, meta, flags):
        if not self.real:    # stand-in for the interpreter flags, used to make repeated self-tests fast
            return self._call(text, 1 if "-O" in flags else 0, "error" in flags)
        r = subprocess.run([sys.executable, "-I", *flags, "-c", self.src, self.mode, json.dumps(self.off)],
                           input=text, capture_output=True, text=True, timeout=60)
        try:
            j = json.loads(r.stdout)
        except Exception:
            return Verdict(False, "", ("CRASH",), True)
        return Verdict(j["accept"], j["value"], tuple(j["codes"]))

    def plants(self):
        planted = self.src.replace(TOY_ASSERT, 'assert False, "planted"')
        return [("toy-gate:assert-1", ToyAdapter(self.mode, planted, self.off, self.real))]

    def check_variants(self):
        return [(c, ToyAdapter(self.mode, self.src, self.off + (c,), self.real)) for c in self.check_names]


def toy_fixtures():
    good = {"status": "VERIFIED", "digest": "a" * 64, "n": 5, "adapter": "x.bin", "xs": [1, 1, 1],
            "checked": True, "dual": True, "witness": "w1"}

    def mk(drop=(), **kw):
        return json.dumps({k: v for k, v in {**good, **kw}.items() if k not in drop}, indent=2) + "\n"
    acc = [Fixture("good", mk()), Fixture("good-lower-bound", mk(drop=("witness",), status="LOWER_BOUND", dual=False))]
    rej = [Fixture("bad-status", mk(status="BANANA")), Fixture("no-status", mk(drop=("status",))),
           Fixture("bad-digest", mk(digest="zz")), Fixture("bad-n", mk(n=-1)), Fixture("bad-n7", mk(n=7)),
           Fixture("bad-adapter", mk(adapter="")), Fixture("bad-xs", mk(xs=[1, 2, 1])),
           Fixture("bad-checked", mk(checked=False)), Fixture("bad-dual", mk(drop=("witness",), dual="yes")),
           Fixture("bad-witness", mk(drop=("witness",))), Fixture("bad-two", mk(adapter="", xs=[3, 1, 1])),
           Fixture("bad-legacy", mk(adapter="", adapter_path="")), Fixture("unknown-key", mk(extra=1))]
    return acc, rej


def fingerprint(res):
    """The parts of a result that the self-test pins: which violations, of which kind, where."""
    r1, r2, r3, r4, r5 = (res[k] for k in RELATIONS)
    return {
        "baseline": sorted(b["fixture"] for b in res["baseline"]),
        "status": {k: res["summary"][k]["status"] for k in RELATIONS},
        "R1": sorted(v["mutation"] for v in r1["violations"]),
        "R2": sorted(f"{v['fixture']} - {v['deleted']}" for v in r2["violations"]),
        "R2_beyond_r1": r2["beyond_r1"],
        "R2_to_read": sorted(f"{v['fixture']} - {v['deleted']}" for v in r2["to_read"]),
        "R2_restored": sorted(f"{v['fixture']} - {v['deleted']}" for v in r2["restored"]),
        "R2_pairs": sorted({(v["rejected_before"], v["accepted_after"]) for v in r2["violations"]}),
        "R3": sorted(f"{v['kind']} {v['fixture']} {v['path']}" for v in r3["violations"]),
        "R3_soft": sorted({v["kind"] for v in r3["soft"]}),
        "R3_reproducers": sorted({v["reproducer"] for v in r3["violations"]}),
        "R4": sorted(f"{v['mode']} {v['fixture']}" for v in r4["violations"]),
        "R4_exposures": [e["plant"] for e in r4["exposures"]],
        "R4_inproc_mismatches": r4["inproc_mismatches"],
        "R5": sorted(v["check"] for v in r5["violations"]),
        "R5_no_isolating_fixture": sorted(r5["no_isolating_fixture"]),
        "R5_disagreement": r5.get("disagreement"),
    }


A64 = "a" * 64
EXPECTED = {
    "strict": {
        "baseline": [],
        "status": {"R1": "pass", "R2": "pass", "R3": "pass", "R4": "pass", "R5": "pass"},
        "R1": [], "R2": [], "R2_beyond_r1": 0, "R2_to_read": [], "R2_restored": ["unknown-key - extra"], "R2_pairs": [],
        "R3": [], "R3_soft": [], "R3_reproducers": [], "R4": [], "R4_exposures": [], "R4_inproc_mismatches": [],
        "R5": [], "R5_no_isolating_fixture": [], "R5_disagreement": [],
    },
    "leaky": {
        "baseline": ["bad-dual", "no-status", "unknown-key"],
        "status": {"R1": "fail", "R2": "fail", "R3": "fail", "R4": "fail", "R5": "fail"},
        "R1": ["empty-object", "good-lower-bound:status=removed", "good:status=removed", "status-empty", "status-unknown"],
        "R2": ["bad-adapter - adapter", "bad-checked - checked", "bad-digest - digest", "bad-legacy - adapter",
               "bad-n - n", "bad-n7 - n", "bad-status - status", "bad-witness - dual", "bad-xs - xs"],
        "R2_beyond_r1": 8,
        "R2_to_read": ["bad-xs - xs/1"],
        "R2_restored": [],
        "R2_pairs": [('{"adapter":""}', "{}"), ('{"checked":false}', "{}"), ('{"digest":"zz"}', "{}"),
                     ('{"dual":true}', "{}"), ('{"n":-1}', "{}"), ('{"n":7}', "{}"), ('{"status":"BANANA"}', "{}"),
                     ('{"xs":[1,2,1]}', "{}")],
        "R3": ["noncanonical_accepted:bool-as-string good checked", "noncanonical_accepted:bool-as-string good-lower-bound checked",
               "noncanonical_accepted:bool-as-string good-lower-bound dual",
               "noncanonical_accepted:trailing-newline good digest", "noncanonical_accepted:trailing-newline good-lower-bound digest",
               "rejected_input_accepted:bool-as-int bad-checked checked", "rejected_input_accepted:bool-as-int bad-witness dual",
               "rejected_input_accepted:bool-as-string bad-checked checked", "rejected_input_accepted:bool-as-string bad-witness dual",
               "rejected_input_accepted:int-as-string bad-n7 n", "rejected_input_accepted:int-as-string-nonascii bad-n7 n"],
        "R3_soft": ["duplicate_key_accepted_last_wins", "type_confusion_accepted:bool-as-int",
                    "type_confusion_accepted:int-as-exponent", "type_confusion_accepted:int-as-float"],
        "R3_reproducers": ['{"checked":"false"}', '{"checked":"true"}', '{"checked":0}', '{"digest":"' + A64 + '\\n"}',
                           '{"dual":"false"}', '{"dual":"true"}', '{"dual":1}', '{"n":"7"}', '{"n":"\\u0667"}'],
        "R4": ["-O bad-n7", "-W error bad-legacy"],
        "R4_exposures": ["toy-gate:assert-1"],
        "R4_inproc_mismatches": [],
        "R5": ["C_N", "C_SUB"], "R5_no_isolating_fixture": ["C_N", "C_SUB"], "R5_disagreement": [],
    },
}


def run_toy(mode, real=True):
    acc, rej = toy_fixtures()
    return Engine(ToyAdapter(mode, real=real), acc, rej).all()


def self_test(quiet=False, real=True):
    """Run both toy gates and compare every pinned violation. Returns 0 when all match.

    real=True starts a fresh interpreter for every R4 run (python3, python3 -O, python3 -W error).
    real=False uses the in-process stand-in for those three modes."""
    say = (lambda *a: None) if quiet else print
    ok = True
    for mode in ("leaky", "strict"):
        res = run_toy(mode, real)
        got = fingerprint(res)
        say(mode, {k: f"{v['status']} {v['violations']}" for k, v in res["summary"].items()})
        for key, want in EXPECTED[mode].items():
            have = got[key]
            have = [list(x) for x in have] if key == "R2_pairs" else have
            want = [list(x) for x in want] if key == "R2_pairs" else want
            if have != want:
                ok = False
                say(f"  MISMATCH {mode} {key}\n    expected {want}\n    got      {have}")
    say("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


# ---------- command line ----------
def load_adapter(spec, repo):
    path, _, func = spec.rpartition(":") if not os.path.exists(spec) else (spec, "", "")
    func = func or "build"
    mspec = importlib.util.spec_from_file_location("gatecheck_adapter", path)
    if mspec is None or mspec.loader is None:
        raise SystemExit(f"gatecheck: cannot load adapter file {path}")
    mod = importlib.util.module_from_spec(mspec)
    mspec.loader.exec_module(mod)
    if not hasattr(mod, func):
        names = sorted(n for n in vars(mod) if n.startswith("build"))
        raise SystemExit(f"gatecheck: {path} has no function {func}. Builders found: {', '.join(names) or 'none'}. "
                         f"Name one with --adapter {path}:NAME")
    return getattr(mod, func)(repo)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Conformance relations R1 to R5 for an accept/reject gate.")
    ap.add_argument("--self-test", action="store_true", help="run both toy gates and compare every pinned violation")
    ap.add_argument("--adapter", help="adapter file, optionally FILE.py:builder (default builder name: build)")
    ap.add_argument("--repo", default=os.environ.get("GATE_REPO", "."), help="path handed to the builder")
    ap.add_argument("--out", help="directory for R1.json to R5.json, baseline.json and summary.json")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.adapter or not a.out:
        ap.print_usage(sys.stderr)
        return 2
    try:
        ad, acc, rej = load_adapter(a.adapter, a.repo)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    res = Engine(ad, acc, rej).all()
    with open(os.path.abspath(__file__), "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    summary = dict(gate=ad.name, harness_sha256=digest, python=".".join(map(str, sys.version_info[:3])),
                   fixtures=dict(accepted=len(acc), rejected=len(rej)), baseline_mismatches=len(res["baseline"]),
                   vacuous=res["vacuous"], runs=res["runs"], crashes=res["crashes"], relations=res["summary"])
    os.makedirs(a.out, exist_ok=True)
    for k in RELATIONS + ("baseline",):
        with open(os.path.join(a.out, f"{k}.json"), "w", encoding="utf-8") as fh:
            json.dump(res[k], fh, indent=1)
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    for k in RELATIONS:
        print(k, res["summary"][k]["status"], "-", res["summary"][k]["note"])
    return 1 if any(v["status"] == "fail" for v in res["summary"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
