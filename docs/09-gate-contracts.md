# Gate Contracts

A gate is any program whose verdict promotes a result. A certificate auditor is a gate. So is a file-header reader, a model loader, an oracle that stops a repair loop, and a statistic that clears an alarm.
[`docs/02-unified-verification-primitive.md`](02-unified-verification-primitive.md) states four axioms for the game between a proposer and a verifier: who owns the oracle, commit before reveal, structural independence, and two-tier selection. It does not say what the gate program itself must satisfy. This document adds that.

One principle carries the document: **a gate's verdict must not be movable by what it judges.** Four contracts follow from it. Each has a test that needs no knowledge of whether the claim under judgement is true.
Each is set next to measurements made on the five layers and the working repositories on 2026-11-20.

A sibling team adopted these contracts and extended them into a nine-gate research protocol (`Foundation-0/cave-expedition`, `verification/PROTOCOL.md`) and a research method (`Foundation-0/aletheia`). An outside check of that team's results changed Claim 9, Falsifier 6 and Record C below.

Status tags follow this repository's evidence rule. `verified` means a proof given here and a check in [`scripts/verify_gate_contracts.py`](../scripts/verify_gate_contracts.py), or a count over committed public output files with its command shown.
`source claim` means measured or published elsewhere and not reproduced in this repository. `hypothesis` means a proposed rule with a test and a stated observation that would count against it. The hub contributing guide calls that third tag `proposed`.
Numbered claims are stated and tagged here. Lettered records are measurements made in other repositories, each tagged `source claim`.

## 1. The Four Contracts in Plain Words

| # | Contract | Plain statement | Test that needs no ground truth |
| --- | --- | --- | --- |
| 1 | What a gate reads | It derives what it checks from pinned rules or from bytes it measured. It never takes that from a list or a flag the submitter supplies. | Five relations between runs of the same gate (Section 3) |
| 2 | What a verdict means | An exact oracle never passes a false claim. A sampled oracle is a statistical test on finite data. An anchor tests the specification itself. A verdict says which of these it is. | Count how often an unseen grader rejects the oracle's passes (Section 4) |
| 3 | What may flow back to the proposer | From an exact oracle, every failure in full detail. From a sampled oracle, a budgeted number of bits. From an anchor, nothing. | The class written in the receipt fixes what the reply may carry (Section 5) |
| 4 | When a gate is judged | An audit is recorded before adaptation. A cleared alarm afterwards is not evidence. | The angle between the audit and what adaptation can adjust (Section 6) |

Under all four sits one object, the closure defect of a quotient (Section 7). A quotient is a coarser description of a system, one that merges states.

## 2. Definitions

- **Gate.** A deterministic program `G` that reads a submission `x` and returns `accept` or `reject`. An `accept` promotes a result: a change is merged, an adapter is mounted, a certificate is recorded as verified, a loop stops, or an alarm is cleared.
- **Submission.** `x` has two parts. The artifact `a` is the thing the claim is about: the bytes to be served, the route, the proof, the residuals. The declaration `d` is everything else the submitter writes: statuses, flags, digests, numbers, and lists of things to check.
- **Pinned rules `R`.** Data the gate's owner fixed before the submission existed and that the submitter cannot write. This is the root digest `h_oracle` of `docs/02` Axiom 1.
  `R` names the checks, their thresholds, the allowed status words, and the required evidence `K`: the fields a submission must carry for the claim it asks to promote. `K` is not empty. Where `R` pins the allowed status words, the status is part of `K`.
- **Measurement.** A value the gate computes itself from the bytes it is about to promote: the hash of the file the server opens, a flag read from the running process, a norm recomputed from the tensors.
- **Truth.** The claim has a truth value `T(a)` fixed by the artifact and the pinned rules. The declaration cannot change it.
- **Proposer.** Whoever or whatever writes submissions and can adapt to verdicts: a person, a search, a trained model.
- **Oracle.** A gate whose verdict a loop or another gate relies on. A stopping oracle ends a repair loop. A grader is a stricter oracle whose verdicts the loop never sees.
- **Receipt and fixture.** A receipt is the stored record of one verdict. A fixture is a stored test input for a gate, labelled accepted or rejected.
- **Residual, adaptation, audit.** A residual is the amount by which one constraint or prediction misses. Adaptation is any change the proposer makes to shrink residuals: a fit, a repair, a training step. An audit is a statistic of the residuals that is meant to raise an alarm when the specification does not fit.
- **Evidence-free edit.** One of three changes. (E1) Delete a piece of required evidence. (E2) Replace a value that has its declared type and spelling by another spelling that a lenient reader would take for the same value, such as `0` or `"false"` for `false`. (E3) Run the gate program in another interpreter mode.

**Principle, precise form.** No evidence-free edit turns `reject` into `accept`. None of the three edits adds evidence or touches the artifact, so none can make a false claim true. A gate whose rejection becomes an acceptance under one of them has a verdict that follows how the submission is written.

## 3. Contract 1: What a Gate Reads

### 3.1 Statement

A gate satisfies Contract 1 when all five clauses hold.

1. **Pinned checks.** The list of checks, the set each check ranges over, and each threshold come from `R` or from a measurement. No field of the submission selects them. The verdict is `accept` exactly when every check in the list passes.
2. **Absent means fail.** Every piece of required evidence in `K` has a check that fails when the evidence is absent.
3. **One spelling.** A check reads a value only at its declared type and spelling. Any other form fails that check.
4. **One function.** In every interpreter mode the deployment allows, the gate computes the same verdict for the same submission.
5. **Measured, not declared.** A value compared with a pinned rule is a measurement. A declared value may be checked against a measurement. It never stands in for one.

### 3.2 Five Relations

A relation is a rule about two or more runs of the same gate. Testing software through such rules, with no oracle for the right output, is metamorphic testing (`source claim`: Chen, Cheung and Yiu, 1998).

| Relation | Rule | A violation shows | Clause |
| --- | --- | --- | --- |
| R1 default reject | The empty text, blank text, `{}`, `[]` and `null` are rejected. Where `R` pins the status words, so is any input whose status is missing, empty or outside the list. | Every check ran only because the submission mentioned it. | 1, 2 |
| R2 omission | Deleting required evidence from a rejected input never gives an accepted one. | A missing field is read as a passing field. | 2 |
| R3 encoding | (i) An accepted input in which a value that a check reads is re-spelled is rejected. (ii) A rejected input stays rejected when any correctly typed value in it is re-spelled. | The check compares loosely. A test for `false` lets `0` through. | 3 |
| R4 optimizer parity | The verdict is equal under `python3`, `python3 -O` and `python3 -W error`. | A check lives in a bare `assert`, a statement that `python3 -O` removes, or a warning skips a check. | 4 |
| R5 isolation | Every named check has a fixture that only that check rejects. In another form: deleting the check changes the verdict of at least one fixture. | The check can be deleted with every test still passing. | evidence for 1 |

For a gate that reports every failing check, the two forms of R5 agree. For a gate that stops at its first failure, only the second form can be tested. R5 is the coverage rule known as modified condition/decision coverage, applied to trust checks (`source claim`: Chilenski and Miller, 1994).
Its deletion form has been measured on a verifier before. Hill (2026) disabled the refusal statements of a verifier for evidence bundles one at a time, and reports that 75 of 112 could be deleted with the whole suite and every tamper fixture still passing (`source claim`: arXiv 2608.26183).

**Claim 1 (`verified`).** A gate that satisfies clauses 1 to 4 satisfies R1, R2, R3 and R4 on every input. So each relation is a necessary condition of the contract. A violation is a pair of runs, and finding it needs no knowledge of `T`.

*Proof.* R1: an input that carries none of `K` fails a check by clause 2, because `K` is not empty. Where `R` pins the status words the status is in `K`, so a missing status fails by clause 2, and a status outside the list fails the status check that clause 1 pins. R2: clause 2.
R3: a re-spelled value has another type or spelling. If a check reads it, that check fails by clause 3, which gives (i). If no check reads it, every check gets the input it got before, so the same checks fail. A rejected input therefore stays rejected in both cases, which gives (ii).
R4: clause 4. The script checks the same on two toy gates, one built to the contract and one built to break each clause.

The relations are necessary and not sufficient. A gate can keep all five and still accept a false claim. None of them tests clause 5. That clause is tested by listing what the gate opens, hashes and asks for, as in Section 3.5.

### 3.3 The Harness

[`scripts/gatecheck.py`](../scripts/gatecheck.py) runs the five relations against any gate through a small adapter. It ships with two toy gates over one certificate format. The strict toy follows clauses 1 to 4. Each marked line of the leaky toy breaks one relation.

| Leaky line | Pair of runs the harness reports | Relation |
| --- | --- | --- |
| A status is checked only when present | `{"status":"BANANA"}` is rejected and `{}` is accepted | R1, R2 |
| `checked` is tested with `is False` | `{"checked":false}` is rejected, `{"checked":0}` and `{"checked":"false"}` are accepted | R3 (ii) |
| A witness is required only when `dual is True` | `{"dual":true}` with no witness is rejected, `{"dual":1}` with no witness is accepted | R3 (ii) |
| A digest is matched with `$` at the end | 64 hex characters followed by a newline are accepted | R3 (i) |
| One rule is a bare `assert` | a certificate with `n` equal to 7 is rejected under `python3` and accepted under `python3 -O` | R4 |
| A warning is raised inside a `try` that hides errors | a certificate with an empty adapter name and a deprecated field is rejected under `python3` and accepted under `python3 -W error` | R4 |
| `C_SUB` fires only together with `C_N` | either check can be deleted with every fixture verdict unchanged | R5 |

**Claim 2 (`verified`).** On the leaky toy the harness reports 5, 9, 11, 2 and 2 violations of R1 to R5, and one planted assert that `-O` removes. On the strict toy it reports none, with every relation at `pass`. The result is the same under `python3` and `python3 -O`.
Each of 32 planted breaks of the harness turns its own checks red. Fourteen of those were tried on the earlier copy, by its first author and by a second reviewer. The earlier self-test did not catch seven of them.

The harness reports one status per relation. Three of them guard against reading too much into a run with no violation.

- `not_shown`: no violation was found, but the run was sampled, or it accepted deletions that nobody has read, or the gate stops at its first failure and no check-deleted copies were given.
- `exposed`: verdicts agree on every fixture under all three modes, but a bare `assert` sits on the accepting path. Whether that costs anything depends on what else pins the value.
- `vacuous`: the gate rejects every fixture that was labelled accepted.

The harness tests less than the relations state, in these ways. For R2, when the gate publishes no list of required fields, the harness takes the keys carried by every accepted fixture. It lists every other accepted deletion for a reader.
For R3 (i), it counts a re-spelling only on a value the gate pins, meaning a different value of the same type is rejected. A range-checked value therefore looks unread.
It lists without counting the forms that Python compares as equal after decoding, such as `5.0` for `5` and `1` for `true`, and a repeated key where the last copy wins. It does not count a status word accepted in another letter case or with padding when the gate reports the same normalized word. Clause 3 would count all of these.
For R4, it tests Python interpreter flags only.

### 3.4 Conformance Snapshot, 2026-11-20

**Record A (`source claim`).** The table was produced by an earlier copy of the harness with adapters for each repository. The adapters and their fixtures are not published here, so a reader cannot rerun the table from this repository. A second reviewer re-ran ten of the eighteen rows from fresh clones at the same commits and got the same counts, kinds and baselines.
The reviewer's corrections are applied and marked. Each row is a snapshot of one commit. A number after FAIL is a count of violations. "k of n run" marks a sampled run.

| Gate | Commit | Re-run | R1 | R2 | R3 | R4 | R5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `aska-physical/cfrp-masts` main | a12b665f | yes | pass | pass, 100 of 247 run | pass | FAIL 3, planted (A) | n/a |
| `aska-physical/fibral-rigidity` main | 06520520 | yes | pass | pass, 40 of 1,351 run | pass, 84 of 770 run | FAIL 3, planted | n/a |
| `aska-physical/fibral-rigidity` pull request 3 | cbd092ea | yes | pass | pass, 40 of 1,363 run | pass, 84 of 787 run | pass | n/a |
| `Foundation-0/incentre-lattices` main, a verifier that reads no file | 2d374fff | no | n/a | n/a | n/a | pass | n/a |
| `Proven-Commons/mcproof` base of pull requests 10 and 11 | 71d1a58a | no | FAIL 13 | FAIL 7 | FAIL 19 | pass | FAIL 6 (B) |
| `Proven-Commons/mcproof` head of the first of those | 3e634b93 | no | FAIL 13 | FAIL 5 | FAIL 16 | pass | FAIL 6 (B) |
| `Proven-Commons/mcproof` head of the second | 7b60918d | no | pass | pass, 150 of 445 run (C) | FAIL 20 | pass | FAIL 6 (B) |
| `Proven-Commons/mcproof` feature branch with both merged | f0e7d271 | yes | pass | corrected: FAIL, 11 of 260 (C) | FAIL 15 (D) | pass | corrected: FAIL 4 (B) |
| `Foundation-0/permutation-sums` main | 3e587dc0 | no | pass | pass | pass, 204 of 400 run | pass | n/a |
| `Foundation-0/permutation-sums` branch head before its merge | 0281b7db | no | pass | pass | pass, 204 of 400 run | pass | n/a |
| `Foundation-0/quotient-lp-bounds` `verify_independent.py` | 65d8df3e | yes | pass | pass, 120 of 46,188 run | FAIL 20 (E) | pass | corrected: FAIL 33 of 42 (F) |
| `Foundation-0/quotient-lp-bounds` `verify.py` | 65d8df3e | yes | pass | pass, 120 of 52,432 run | pass, 244 of 173,736 run | pass | n/a |
| `ahrazzle/soko` main | 41b6f9ca | yes | FAIL 13 | FAIL 13 (G) | FAIL 20 (D) | pass | FAIL 3 |
| `ahrazzle/soko` pull request 68 | 9ccc9f48 | no | FAIL 13 | FAIL 13 (G) | FAIL 14 | pass | FAIL 3 |
| `ahrazzle/soko` pull request 69 | 760376fe | yes | pass | FAIL 4 (H) | FAIL 21 (D) | pass | FAIL 3 |
| `ahrazzle/soko` pull request 70 | b52b6830 | no | FAIL 13 | FAIL 13 (G) | FAIL 20 | pass | FAIL 3 |
| `siliconcordat/weft` main | 5d7eac03 | yes | FAIL 4 | n/a | pass, 194 of 314 run | pass | n/a |
| `siliconcordat/weft` pull request 10 | 77606ba2 | yes | pass | pass, 150 of 360 run | pass, 344 of 1,044 run | pass | pass |

Rows before and after a fix, read in pairs. The status fix in `soko` and the one in `mcproof` each take R1 from FAIL 13 to pass. The strict header reader in `weft` takes R1 from FAIL 4 to pass, and main rejects none of the 44 fixtures labelled rejected.
The `fibral-rigidity` change takes R4 from three planted asserts to pass. The full-match fix removes the trailing-newline cases from R3, six in `soko` and four in `mcproof`, and the other spellings remain. No fix in the table changes R5.

Notes.

- **A.** A planted test turns one `assert` into `assert False`, which `-O` always removes, so it cannot tell a harmless assert from a costly one. Here a certificate comparison pins every number, so `python3 -O verify.py` on an unmodified tree is sound.
  The real gap is narrower: with one input changed so the stiffness claim is false, `python3 -O verify.py --write` exits 0 and records the certificate, while `python3` rejects it.
- **B.** The adapter lacked fixtures for two of the six checks it listed. Deleting each of the 20 checks in turn and running the repository's own tests leaves four with no test on the feature branch. The three rows that were not re-run carry the same adapter gap.
- **C.** The first reading was `pass`. It came from the fixture set and from sampling 150 of 455 deletions. Running all 260 single top-level deletions accepts 11. One of them leaves a certificate marked verified with no witness and with its optimum flag false.
- **D.** Most violations on accepted inputs are another spelling of a good value, such as the string `"true"` for `true`. They cost little. The costly cases are on rejected inputs, where a red flag written as `0`, `"false"` or with a trailing newline passes.
  The earlier harness skipped `1` for `true` on rejected inputs. It therefore missed that writing one boolean as `1` switches off the check that a claimed match between oracles names more than one oracle, in both auditors.
- **E.** Each accepted spelling is the same rational number, so no false bound passes. The cost is which bytes were checked, and that the two checkers of that repository disagree about one file.
- **F.** The first reading was 47 of 48. It came from the adapter, which kept only the text before the first colon of each reason. Deleting each of the 42 rejection branches in turn and running the repository's tests leaves 33 deletions with the tests still passing.
- **G.** Nine of the thirteen are the R1 defect seen again: deleting the status leaves a certificate that main accepts. The other four are the same as in note H.
- **H.** The four deletions are not introduced by that pull request. Main accepts the same certificates. Two of them delete the red flag itself, so an absent field reads as a good one.

The findings in notes A to H that no earlier record covered are filed as issues in their own repositories. Section 8 names them.

The harness in this repository names three of these readings differently. A sampled run with no violation is `not_shown`. So is an isolation pass on a gate that stops at its first failure, as in the last row. A planted assert that no fixture reaches is `exposed`. The table was not re-run with it.

What the snapshot does not show: fixture coverage beyond what each adapter supplied, the unsampled part of each sampled run, and any gate that was not driven. The `mcproof` audit was called with no registry of witness digests, so its registry check was never reached.

### 3.5 Findings on the Stack

**Record B (`source claim`).** Every row was measured on current main, with a reproducer and its output in the issue named in Section 8, and was re-run by a second reviewer. Commits: `warp` e3899d3e, `weft` 5d7eac03, `mde` 52ce017, `exo` cb78b86.

| Layer | What was observed | Clause |
| --- | --- | --- |
| L3 `warp` | A bundle with a null `adapter_path` passes all four stages of a mount. The adapter bytes are never hashed, so the digest in the bundle is only a label. | 2 |
| L3 `warp` | The file Stage 1 hashed need not be the file the server loaded. A mount with a decoy file reports the file as verified while the server lists another path for that adapter id. | 5 |
| L3 `warp` | Runtime flags and base model digests on both sides of the Stage 1 comparison come from the daemon's own config. The gate compares its config with itself. A mount asks the server for nothing that returns context size, binary identity or model digest. | 5 |
| L3 `warp`, L2 `weft` | Stage 2 checks four certificate integers against bounds and never opens the adapter file. A file with one factor made 8 times larger mounts with the integers of the original file. The squared Frobenius norm of the update it applies, the sum of the squared entries, is about 746.8 against a limit of 20. | 5 |
| L3 `warp`, L2 `weft` | A file with byte-identical factors and the header value `alpha` changed from 4 to 32 also mounts. Integers recomputed from its tensors equal the original ones. The server multiplies the update by `alpha` over rank (a claim from the llama.cpp source), so the applied update is 8 times the certified one. | 5 |
| L5 `mde`, L4 `exo`, L3 `warp` | The zone manifest id is a SHA-256 over a body that holds floats. One language prints `1e-05` and another prints `0.00001`. A manifest written by `mde` with that scale and its own id is rejected by `warp` and `exo` as tampered. | 3 |
| L4 `exo` | The bridge turns a scale into thousandths. For 503 of the 1,000 thousandths the nearest 32-bit float is above the certified fraction. Every multiple of 1/1024 is exact. | 5 |
| L4 `exo` | Agent memory accepts an attempt outcome with no evidence field. Two attempts declared `regressed` move the plan to `escalate_human`. The same two declared `neutral` leave it at `recompile`. | 5 |

**Claim 3 (`verified`).** Two numbers in that table are arithmetic and are checked here. Python prints `0.00001` as `1e-05`, the two spellings decode to one number, and their SHA-256 digests differ.
Of the thousandths `k/1000` for `k` from 1 to 1000, the nearest 32-bit float is above the fraction for 503, below it for 489 and equal for 8. All 1,025 values `n/1024` are exact.

## 4. Contract 2: What a Verdict Means

### 4.1 Statement

Three classes of oracle, each relative to the claim it promotes.

- **Exact.** `G(x) = accept` implies the claim, for every input. It never passes a false claim. It may reject a true one. A proof kernel and an exact certificate checker are of this class.
- **Sampled.** A statistical test on finite data. Its `accept` supports the claim only with a stated probability, and only when the data were drawn independently of the input (`docs/02` Theorem 1).
- **Anchor.** A test of the specification itself. It measures, on data outside the specification, whether meeting the specification gives what was wanted. Its failure is a statement about the specification, not about the input. The grader in Section 4.2 and the route replay in Section 7.4 are anchors.

**Contract 2.** (a) Every gate records its class for the claim it promotes. A verdict of another class is never recorded with the word used for exact verdicts. (b) An oracle that is not shown to be exact for the claim it promotes is treated as sampled.
(c) A verdict used as a stopping rule, or as a source of calibration data, records its oracle gap for each task family and oracle version.

The **oracle gap** of an oracle against a grader on a set of items is the number of items the oracle passes and the grader rejects, over the number the oracle passes. The grader is unseen: its verdicts are computed after the run and never reach the loop.
The count compares two recorded verdicts per item. It needs no new judgement of any candidate.

### 4.2 Evidence

**Claim 4 (`verified`).** On the committed validation receipts of the repair loop in `Proven-Commons/mcproof` at commit 62164d63, the grader rejected 15 of the 23 candidates that the stopping oracle passed for the bare model, and 14 of 14 for the adapter. No item fails the oracle and passes the grader. On this split the oracle is a necessary condition and not a sufficient one.

| Arm | Family | Items | Oracle passes | Rejected by the grader among those |
| --- | --- | --- | --- | --- |
| bare model | A | 12 | 1 | 0 |
| bare model | B | 12 | 9 | 4 |
| bare model | C | 12 | 11 | 11 |
| bare model | D | 12 | 2 | 0 |
| adapter | A | 12 | 0 | 0 |
| adapter | B | 12 | 4 | 4 |
| adapter | C | 12 | 10 | 10 |
| adapter | D | 12 | 0 | 0 |

The count is over two committed files. The command and its output are in Section 11. The script here checks only that the rows add up to the totals.

That plausible repairs which pass a weak check often fail a stronger one is known in program repair (`source claim`: Qi, Long, Achour and Rinard, 2015, and Smith, Barr, Le Goues and Brun, 2015).

## 5. Contract 3: What May Flow Back to the Proposer

### 5.1 Statement

**Contract 3.** What a gate returns to the proposer depends on its class.

- From an exact oracle, every failure may return in full: which check, where, and by what exact amount.
- From a sampled oracle, each returned bit can be used against it, so answers are budgeted. This is `docs/02` Axiom 2: at most one binary verdict per committed finalist, and a cap on finalists per holdout epoch.
- From an anchor, nothing returns to the proposer. The result goes to whoever owns the specification.

The test is on the reply. A receipt that names its class as sampled or anchor carries no field beyond what that class allows.

### 5.2 Why Detail From an Exact Oracle Is Safe

**Claim 5 (`verified`).** Let `E` be exact for `T`. Let a proposer produce `a_1, a_2, ...` where each proposal may depend on everything `E` returned for the earlier ones, and on anything else. Let the loop output the first `a_t` that `E` accepts. Then the output satisfies `T`.

*Proof.* The output is accepted by `E`. Exactness says every accepted input satisfies `T`. The argument uses nothing about how the input was chosen.

Exactness is a statement about every input, so it holds for inputs chosen by any process, including one that has read the gate's answers. Detail changes whether and how fast a passing input is found. It does not change what a pass means.
The script checks this exhaustively on a toy with three artifacts: every truth set, every gate whose accept set lies inside it, every map from an artifact to one bit of detail, and all 2,187 adaptive proposers of depth three. That is 472,392 loops, 266,328 of which end in an accept, and no accepted output is false.
The converse is checked too. There are 37 pairs of a truth set and a gate that accepts at least one false artifact. In each of them a proposer that uses no feedback at all gets a false artifact accepted.
Feeding an exact verifier's counterexamples back to the proposer is the basis of counterexample-guided synthesis (`source claim`: Solar-Lezama and others, 2006).

**Claim 6 (`verified`, toy only).** On the same toy with two proposals allowed, none of the 9 proposers that ignore feedback finds an accepted artifact for all 7 non-empty gates. One proposer that reads a single bit of detail does. This shows only that detail can change speed. It measures nothing about real repair loops.

### 5.3 Why the Same Detail Breaks a Sampled Oracle

**Claim 7 (`verified`, toy only).** A sampled oracle checks 3 hidden points out of 6 and accepts an artifact that is right on all three. An artifact that is wrong on 3 points, committed before any answer, passes 1 of the 20 possible samples.
A proposer that first submits an artifact wrong everywhere, reads which sampled points failed, and then submits an artifact wrong on the other three, passes 20 of 20.

One detailed answer exposed the sample. That each answer from held-out data can be used to fit that data, and that answers must therefore be budgeted, is the subject of adaptive data analysis (`source claim`: Dwork, Feldman, Hardt, Pitassi, Reingold and Roth, 2015).

### 5.4 Two Statements That Look Opposed

"Detailed verifier feedback speeds repair" and "a holdout may leak at most one bit" are about different classes. The first is about exact oracles, where Claim 5 holds. The second is about sampled oracles, where Claim 7 holds. A loop that mixes them needs the class on every receipt, which is Contract 2.

**Claim 8 (`hypothesis`).** Telling a proposer the signed exact amount by which each constraint failed lets it repair in fewer rounds than telling it only which constraint failed and where.
A preregistered design with four feedback arms, fixed seeds and a paired test is open as a record.
The first registered run exists (`Moissanite-Labs/weft-loom` draft pull request 38). For the one model run so far, a mid-size model on one machine, the registered rule gives "not decided".
The run has two levels of difficulty, smaller problems with 4 variables and larger ones with 6.
On the smaller problems the signed amount solved 7 instances that the constraint-and-place arm did not, and that arm solved 13 that it did not (sign test p 0.942). That is against the claim. On the larger problems there were 7 such instances in all and the rule needs 10, so they cannot test the claim.
The logs showed a side channel that the plan did not foresee: replies that reason in the open where the answer lines belong. They make up almost all of the unreadable replies. On the smaller problems there were 117 unreadable replies, and 113 of the 198 passes after round 1 came straight after one.
So the arm totals mix repair from the feedback with how often the feedback led the model to think in the open. The registered run of a second, smaller model was still in progress when the record was written. The claim stays a hypothesis.

**Claim 9 (`hypothesis`).** The anchor rule is a routing rule: when an exact check passes and an anchor fails, stop adapting the proposer and revise the specification. Section 6 gives the reason for the first half. An anchor fed back to the proposer becomes one more direction the proposer can absorb.
As a claim about real loops it stays a hypothesis. In the linear model of Section 6.1 it has the exact status below.

**Status in the linear model (`verified`).** Let `a` be a failed anchor, so it reads `e = a . r*`, and let `P a`, its part in the column space, be not zero. To absorb `a` is to change the output inside the column space as little as possible so that `a` reads zero. That gives `r_adapt = r* - (e / |P a|^2) P a`. The script checks each statement below on fresh exact rational instances with logged seeds, rank-deficient `Phi` included.

- **Cost.** `|r_adapt|^2 = |r*|^2 + e^2 / |P a|^2`. This is the textbook restricted least squares formula for one restriction (`source claim`: Greene, Econometric Analysis, restricted least squares). Any other change inside the column space that silences `a` costs more.
- **A fresh anchor.** Take `b` with `e_b = b . r*` not zero. After absorbing, `b` reads `e_b (1 - x)`, where `x = e (P a . b) / (e_b |P a|^2)`. So absorbing helps on `b` exactly when `0 < x < 2`. It hurts when `x < 0` or `x > 2`. At `x = 0` and `x = 2` the size of the reading is unchanged.
- **Several anchors.** Let the anchors be the columns of `A`, let `e = A^T r*`, and let `A^T P A` be invertible. Silencing all of them costs `e^T (A^T P A)^-1 e`.
- **Revising.** Adding a direction to the specification never raises the total residual in the noiseless model. The new total is `|r*|^2` minus the squared part of `r*` inside the span of the new directions after `I - P` is applied to them. A revision whose span contains `r*` makes every anchor read zero.

Proof. `r*` is orthogonal to the column space, so a change `d` inside it gives `|r* - d|^2 = |r*|^2 + |d|^2`. For such `d`, `a . d = P a . d`. So the least `d` with `a . d = e` lies along `P a`, and its squared length is `e^2 / |P a|^2`. Any other such `d` is longer.
Then `b . r_adapt = e_b - (e / |P a|^2) (P a . b) = e_b (1 - x)`, and `|1 - x| < 1` exactly when `0 < x < 2`. For several anchors the least `d` with `A^T d = e` is `P A s` with `(A^T P A) s = e`, and `|d|^2 = s^T (A^T P A) s = e^T (A^T P A)^-1 e`.
A revision fits over a larger column space, so its residual is no longer. That residual is `r*` minus the projection of `r*` on the outside parts of the new directions. If their span contains `r*`, the residual is zero, and so is every anchor's reading.

**What stays open.** Two forms of "revising then helps" are not shown, and each has an exact counterexample. Per anchor: take five residuals, `Phi` on the first two coordinates, and an outside residual of 5 in the third. Adding the direction (0, 0, 3/5, 4/5, 0) lowers the total from 25 to 16 and raises the squared reading of the fresh anchor (0, 0, 1, -1, 0) from 25 to 784/25.
With noise: take `Phi` = (1, 1, 0, 0) as one column, truth (0, 0, 2, 0) and noise (1/3, -1/2, 1/5, 3/4). Adding the wrong direction (0, 0, 0, 1) lowers the squared residual on the data from 20699/3600 to 9337/1800 and raises the squared error against the truth from 289/72 to 659/144.

The cost, the reading `e_b (1 - x)` and the noiseless total-residual statement come from the two-loop study in `Foundation-0/continuum` draft pull request 3. Our outside check of it, in two passes, added the restricted least squares name, the several-anchor formula and the two counterexamples.
The first counterexample uses the draft's own revision from 25 to 16. The check also marked the exact ties at 0 and 2. The draft's text calls those points harmful, while its executable test and printed table treat them correctly.

## 6. Contract 4: When a Gate Is Judged

### 6.1 The Latch

Let `r0` be a vector of `m` residuals before adaptation. Let the proposer adjust `k` parameters `theta` that act on the residual linearly, `r = r0 - Phi theta`, where `Phi` is an `m` by `k` matrix. Adaptation picks a `theta` that minimises the squared norm of `r`. Write `r*` for the residual afterwards.
A linear audit is a vector `w`, and its reading is the dot product `w . r`. The column space of `Phi` is the set of all vectors `Phi u`, the changes adaptation can make to the residual. Let `P` be the orthogonal projection onto it.

**Claim 10 (`verified`).**

- (a) `Phi^T r* = 0`, for every minimiser.
- (b) Every audit `w` in the column space of `Phi` reads exactly zero after adaptation, whatever `r0` was.
- (c) `r* = (I - P) r0`. So every quantity computed from `r*`, linear or not, depends on `r0` only through the part of `r0` outside the column space. For any audit, `w . r* = ((I - P) w) . r0`.
  For a leak along the audit's own direction, `r0 = c w`, the reading falls to the squared sine of the angle between `w` and the column space: `(w . r*) / (w . r0) = |(I - P) w|^2 / |w|^2`.
- (d) The readings of all audits on residuals after adaptation span a space of dimension `m - rank(Phi)`. At most `m - rank(Phi)` independent residual audits survive, and that number is attained.

*Proof.* (a) For a minimiser `theta*` and any direction `u`, the function `g(t) = |r0 - Phi (theta* + t u)|^2` equals `|r*|^2 - 2 t (Phi u) . r* + t^2 |Phi u|^2`. It has its minimum at `t = 0`, so `(Phi u) . r* = 0` for every `u`. That is `Phi^T r* = 0`.
(b) If `w = Phi u` then `w . r* = u^T Phi^T r* = 0`.
(c) `r0 = Phi theta* + r*` splits `r0` into a part inside the column space and a part orthogonal to it. That split is unique, so `Phi theta* = P r0` and `r* = (I - P) r0`. Since `I - P` is symmetric, `w . r* = ((I - P) w) . r0`.
With `r0 = c w` this is `c |(I - P) w|^2`, because `I - P` is symmetric and equal to its own square. The reading before adaptation is `c |w|^2`.
(d) `r*` lies in the orthogonal complement of the column space, which has dimension `m - rank(Phi)`. On that space the audit `w` and the audit `(I - P) w` read the same, so the distinct readings form a space of that dimension. A basis of the complement gives `m - rank(Phi)` audits whose readings do not change at all.

The fact in (a) is the normal equations of least squares. It is textbook material.

Remarks, each checked by the script.

- **Weights.** If adaptation minimises a weighted sum of squares `r^T W r`, then `Phi^T W r* = 0`, and the blind audits are the vectors `W Phi u`.
- **Stationary points.** If the residual is a differentiable function `r(theta)` and adaptation stops at a stationary point of `|r(theta)|^2`, then `J^T r* = 0` for the Jacobian `J` there, and audits in the column space of `J` read zero. Parts (c) and (d) are not claimed for this case.
- **Before convergence.** Each step of gradient descent on half the squared norm, `|r|^2 / 2`, with a positive step size at most the reciprocal of the largest eigenvalue of `Phi^T Phi` leaves the outside part of `r` exactly unchanged and strictly shrinks the inside part.
  The reading of an audit in the column space is bounded by the size of that inside part, so an alarm that falls during adaptation is expected whether or not the true gap closes.
- **What is left to check.** The squared norm splits exactly: `|r0|^2 = |P r0|^2 + |r*|^2`. The total `|r*|^2` is the sum of the squared readings of the surviving audits of part (d), taken in an orthonormal basis.
  For uncorrelated noise of width `s` its expected value is `(m - rank(Phi)) s^2`, because the trace of `I - P` is `m - rank(Phi)`. A leak `g` adds `|(I - P) g|^2`. The script checks the split and the trace.
  Comparing `|r*|^2` with that expected value is the classical goodness-of-fit test with reduced degrees of freedom (`source claim`: textbook least squares). A single audit sees a left-out effect only along its own direction. This total sees it along every outside direction.
- **Rank-deficient `Phi`.** The residual `r*` is unique. The minimiser is not, so an outside quantity `c . theta` is fixed only for `c` in the row space. Smallest case: `Phi = [[1, 1]]`, `r0 = [2]`. Both `theta = (1, 1)` and `theta = (2, 0)` give a zero residual, and `c = (1, 0)` reads 1 and 2.

**Contract 4.** (a) An audit verdict is recorded before adaptation and is bound to the state it was computed on. (b) An alarm that clears after adaptation is not evidence that the gap closed. (c) An audit counts after adaptation only by its outside part.
With `Phi` known, the squared sine `|(I - P) w|^2 / |w|^2` is computed from `w` and `Phi` alone. It needs no knowledge of the true gap.

### 6.2 Evidence

The script works in exact rational arithmetic. It checks parts (a), (b) and (d), and the general reading in (c), on 200 full-rank and 100 rank-deficient instances. It checks the squared sine on 100 more, the weighted form on 100, the stationary-point form on 60 and the gradient steps on 60.
The statements of Claim 9 and Falsifier 6 have their own checks. On 150 instances (96 with rank-deficient `Phi`, seed 20261121) they cover the cost, the outside part, the old falsifier and the `0 < x < 2` rule with both ties. They then cover several anchors on 100 instances (seed 20261122) and revisions on 100 (seed 20261123).
The old falsifier fires on 136 of the 150, and in each of those the outside part is unchanged and the total residual rose. Each check has a must-fail control that runs it on a corrupted input.

**Record C (`source claim`).** Recorded in the hub plan (`siliconcordat/.github` issue 5) and not reproduced here: a first run held on 1,500 exact rational instances. The same statement was then demonstrated on a table of 14 binned points committed in `Foundation-0/gravity` at commit 8f96c4b2.
The hub plan states both results in words. The figures below come from the runs themselves, which are not published.
A line was fitted with the table's own weights, and families of rank 1 to 4 were then absorbed by exact least squares. Each audit matched to a family member read exactly zero from the rank where that member entered, and was nonzero before. A probe outside every family kept a nonzero reading: 0.277 before, then 0.0402, 0.0302, 0.0170 and 0.0037.

Limits of that demonstration. It shows a statement about the audit and nothing about the physics in that repository. Its first test of outside anchors was weak, and a stronger one follows below.
Tuning one parameter lowered the fitted table's misfit, a weighted sum of squared residuals, from 30.486 to 25.89. Of the two outside checks that the repository ties to that parameter, one moved from 0.634 to 0.751. It had three degrees of freedom and was already near its floor, so "the outside check did not improve" carries little weight for it.
The other improved from 7.876 to 5.393, and by the module's own description it shares its sample with the fitted table, so it is not independent. These two anchors do not show that adaptation harms outside anchors.

A sample-disjoint anchor exists in the same repository: the KiDS-1000 lensing table at 1 Mpc (`KIDS_WL_ALL_1000KPC`, 4 points), predicted from the same relation. The probe in `Foundation-0/gravity` draft pull request 30 found this anchor, and an outside check reproduced it.
That probe fitted `d_s` in steps of 0.01 and reported a chi-squared of 75.5 at 0.94. The figures below use steps of 0.005 and were reproduced again for this document at commit 8f96c4b2 with the command in Section 11. With `d_s` fixed at 1 the anchor's chi-squared is 31.5.
At the adapted `d_s` of 0.945 it is 69.9, while the fitted table's misfit falls from 30.49 to 25.89. The acceleration scale `a0` is refitted at each `d_s`, and moves from 1.18e-10 to 1.25e-10. The anchor already misfits at `d_s` of 1, so this shows that adaptation moved the fit away from a sample-disjoint anchor. It does not show that `d_s` of 1 is right.

### 6.3 A Correction on Early Warning

An earlier form of the rule said that a collective audit warns before any single residual fails only when the leak is spread over many residuals. That is wrong for an audit matched to the leak.

**Claim 11 (`verified`).** Take a leak in one residual, an audit that reads that residual with threshold `z s`, and a single check with tolerance `T` on every residual, where `s` is the noise width and `z s < T`. On every noise draw in which no residual reaches `T` in size by noise alone, the audit fires at a leak size strictly smaller than the single check does.

*Proof.* With noise `e` on the leaking residual, the audit fires from leak size `max(0, z s - e)` and the single check from `T - e`. The other residuals do not change. The first size is smaller because `z s < T` and `e < T`.

**Record D (`source claim`).** A simulation whose outcome the hub plan states in words. The figures here come from the run itself, which is not published. It used 64 residuals, 2,000 noise draws and `z = 1.645`.
For a matched audit the collective test warned first for every leak shape tried, a one-residual leak included, at every tolerance of 3 noise widths or more. At `T = 4 s` the single check needed, by medians, 2.39 times the leak size for a one-residual leak and 8.44 times for a leak in all 64.
For a plain sum over all residuals, which does not know the leak's shape, the rule holds with a different threshold than first stated. The collective test warned first from a leak spread over 9, 6, 5, 4 and 3 residuals at tolerances of 3, 3.5, 4, 4.5 and 6 noise widths. The formula first stated gave no flip at 3 and then 24, 12, 9 and 5.
The quantity that matters is the leak's component along the audit direction, not the leak's own norm. That is part (c) of Claim 10 read before adaptation.

## 7. The Object Underneath: The Closure Defect

### 7.1 Definitions

Take a finite system with states `X` and a deterministic step `T: X -> X`. A quotient is a map `phi: X -> Q` onto a smaller set of abstract states. A specification is a set `S` of allowed abstract steps, pairs in `Q x Q`. The image of the system is `Im = {(phi(x), phi(T(x)))}` over all `x`.

- The quotient is **closed** when states with equal image have successors with equal image: `phi(x) = phi(y)` implies `phi(T(x)) = phi(T(y))`. Then `Im` is the graph of a function on `Q`, and a specification can describe the image exactly.
- A **fork** is a pair `x, y` with `phi(x) = phi(y)` and `phi(T(x)) != phi(T(y))`. A **missing step** is a state `x` with `(phi(x), phi(T(x)))` not in `S`.
- The **closure defect** of a quotient with its specification is the set of its forks and missing steps.

For a Markov chain, closure of a partition is lumpability (`source claim`: Kemeny and Snell, 1960). A system with several moves per state is covered by one step map per move. The definitions and proofs below apply to each map.

### 7.2 Two Consequences

**Claim 12 (`verified`).**

- (a) A failure has a refutation of two steps. If the quotient is not closed there is a fork, and checking a fork takes two concrete steps whatever the size of `X`. If the specification omits a real step, one concrete step shows it.
- (b) Closure has no certificate shorter than looking at every state. Let `Q` have at least two elements and every class of `phi` at least two states. Let a deterministic checker know `phi` in full, receive any certificate, and learn `T` only by evaluating it. If it accepts some closed system without evaluating `T` at a state `x0`, it also accepts a system that is not closed.
- (c) If the quotient is not closed, every deterministic specification, one abstract successor per abstract state, has a missing step.

*Proof.* (a) The negation of the definition is the existence of a fork. Verifying one evaluates `T(x)` and `T(y)`.
(b) Let `T` be closed and accepted without evaluating `T(x0)`. Pick `z` with `phi(z) != phi(T(x0))` and let `T'` equal `T` except `T'(x0) = z`. Pick `y != x0` in the class of `x0`. Closure of `T` gives `phi(T'(y)) = phi(T(y)) = phi(T(x0)) != phi(T'(x0))`, so `x0, y` is a fork of `T'`.
The checker sees the same answers on `T'` as on `T`, so it accepts `T'`. This is a standard adversary argument.
The nearest published bound found is for another property: testing whether an operation given as an oracle is associative needs on the order of the square of the set's size in queries (`source claim`: Rajagopalan and Schulman, as cited by Le Gall and Yoshida, 2011).
(c) At a fork the two successors have different images. A deterministic specification allows one of them at most.

Part (b) is about a checker that treats the step as a black box. A proof about the text of the rules that define `T` is another kind of certificate and is outside this statement.
The script runs all 256 deterministic systems on four states under the quotient into two classes of two. 64 are closed and 192 are not. Each of the 192 has a fork verified in two steps and no deterministic specification without a missing step. Each of the 64 has exactly one.
For each closed system, each of its 4 states and each of the 15 proper subsets of states, a system that is not closed agrees with it everywhere the checker looked.

### 7.3 Polarity

Let some states be goals, let the abstract goals contain the image of every goal, and let each step cost 1. Write `d(x)` for the fewest concrete steps from `x` to a goal and `d_S(q)` for the fewest abstract steps from `q` to an abstract goal using `S`.

**Claim 13 (`verified`).**

- (a) If the specification allows at least what the system does, `Im` is inside `S`, then `d_S(phi(x)) <= d(x)` for every `x`. Any lower bound certified in the quotient is a lower bound for the system. Adding more abstract steps keeps it valid and can only lower it.
- (b) If the system allows a step the specification lacks, the certificate proves nothing about the system. Whenever a bound from the quotient exceeds the true distance at a state, some real step on a shortest route from that state is a missing step.

*Proof.* (a) Map a shortest concrete route from `x` through `phi`. Every step lands in `Im`, hence in `S`, and the route ends in an abstract goal. So the abstract distance is at most the route's length. More steps in `S` give more routes to minimise over.
(b) If every step of that shortest route had an abstract step, the argument of (a) would bound the abstract distance by the route's length.

That a relaxation which keeps every real move gives a valid lower bound is long known in heuristic search and in model checking by abstraction (`source claim`: Pearl, 1984, and Clarke, Grumberg and Long, 1994).
The script draws 60 random systems on six states with three abstract states and runs all 512 specifications against each. The 694 cases with `Im` inside `S` give no invalid bound. Of the 30,026 cases with a missing step, 14,720 give at least one invalid bound, 31,680 invalid state bounds in all. Each is refuted by one real step on a real shortest route.

With part (c) of Claim 12 this gives the rule for a quotient that is not closed. A deterministic specification on it is void. A specification that lists every image step stays sound and pays in looseness.

### 7.4 Evidence: Route Replay

A lower bound `h` on the keys still to play can be replayed on a real winning route of `n` keys. At each state `s_t` it must satisfy `h(s_t) <= n - t`, it must drop by at most 1 per key if it is claimed to be consistent, and it must be 0 at the goal. One state that breaks a condition is a short refutation. Passing certifies nothing, because the replay sees only states on the routes.

**Record E (`source claim`).** From the test file of the route-replay pull request for `ahrazzle/soko` named in Section 8, at commit 8cbac818. That file was run again for this document under `python3 -O -B -W error`, and its 9 tests pass.

- A drafted quotient for switching between pieces tracks only the active piece and which pieces are off their goals. For 19 of the 316 keys of a record route, the concrete step has no edge in that quotient. Each is a missing step. One-key boards show the cause: a key by one piece moves an inactive piece onto a goal or off it, and the quotient does not track where the pieces stand.
- Used as a bound, that quotient's exact distance drops by 2 at four of those keys. The other 15 keys with no edge do not break the value conditions, so the edge check finds more than the value check.
- The repository's shipped bounds show no violation on 66 catalogued routes and 3,063 keys.

Also part of Record E, from a second reviewer's probe: no drop larger than 1 on 15,592 further legal steps off the routes, a count the hub plan records. The probe also met 313 successor states that the bound could not evaluate, each reached after a hero dies. Section 8 names the issue that records them.

### 7.5 The Four Contracts as Closure Conditions

**Claim 14 (`hypothesis`).** Each contract is the closure condition for one quotient. The reading is useful only if it predicts a defect class before one is found. It is stated here so that it can fail.

| Contract | States | Quotient | A fork is |
| --- | --- | --- | --- |
| 1 | submissions | the decoded typed values and the measured bytes | two submissions with one meaning and two verdicts |
| 2 | candidates | the oracle's verdict | two candidates with one verdict and two grades |
| 3 | a candidate together with the oracle's hidden sample | the candidate alone | one candidate, two samples and two replies |
| 4 | residuals before adaptation | the residual after adaptation, `(I - P) r0` | two gaps with one reading after adaptation |

Row 4 is Claim 10 (c) restated. Rows 1 to 3 are readings, not theorems. In row 3 an exact oracle has no hidden sample, so it has no fork of this kind.

### 7.6 Predictions Made From the Reading

Claim 14 and the contracts are worth keeping only if they predict. Each prediction below was written before the code it concerns was read. For the first one the order rests on the author's word. The other two were pushed to this repository in commit 5616b59 before the check, so the push time of that commit is their timestamp.
A second reader who had not made the predictions scored them from the code. A miss stays on this list. The score so far is one partial hit and two misses.

**Prediction 1, scored: a miss.** The layer-3 loader checks each adapter's certificate alone. The norm of a sum of updates is not a function of the norms of its parts, so the per-adapter certificate is a quotient that is not closed under stacking. A deterministic rule on such a quotient is void. So the stack check was predicted to be missing or unsound.
It is neither. The loader bounds a stack of `N` adapters by `N` times the sum of the parts, which is the Cauchy-Schwarz worst case. That is the other branch Section 7.3 allows: a specification that keeps every possible image stays sound and pays in looseness.
The price was then measured (`source claim`, reproducer in the issue named in Section 8). Each adapter in a stack of `N` gets the joint bound divided by `N` squared, where orthogonal adapters would need only the bound divided by `N`. A composed certificate cannot relax the rule.
Scored strictly, the reading named the place where a rule had to choose between two branches. It did not say which branch the code took.

**Prediction 2, scored: a partial hit (Contracts 2 and 3).** Stage 3 of the layer-3 loader runs what its source calls verifier-owned deterministic canary checks before an adapter is activated. Predicted: the canary prompts and expected results are a fixed list that whoever builds an adapter can read, and a Stage 3 pass is recorded with no statement of its oracle class.
A small fixed list is a sampled oracle. Once it is known, an adapter can be fitted to it, which is Claim 7. Known when this was written: the repository ships a file named `schemas/verifier-canaries.json`, and the mount routine refuses canaries that an adapter supplies.
It is a hit if both parts hold on current main. It is a miss if the canaries are hidden from the builder, or are drawn fresh for each mount from a set the builder cannot list, or if the receipt names the pass as a wiring test and not as evidence about the adapter.
Outcome at commit e3899d3e (`source claim`, with file and line in the issue named in Section 8). Both parts hold for the path the command-line entry point uses. The suite is one file of nine prompts with string rules, run at temperature 0 with a fixed seed, with nothing sampled or held back. Agent tools may read its directory. The mount receipt records a digest and counts and no oracle class.
It is scored partial and not a full hit because the source also holds a runner for a sealed suite. Nothing wires that runner in and no document mentions it, so which suite a deployment uses is not known from the repository. No adapter was fitted to the suite.

**Prediction 3, scored: a miss (Contract 1, clause 4).** R4 was stated for Python flags. Its analogue in Rust is the build profile. A `debug_assert!` and the check for integer overflow exist in a debug build and are removed in a release build by default.
Predicted: at least one gate written in Rust in the five layers has a `debug_assert!` on a validation path, or does unchecked arithmetic or a narrowing cast on an integer parsed from a submission while its release profile leaves overflow checks off.
It is a hit if one such site can change a verdict or wrap on a value the submitter chooses. It is a miss if no such site is found in the Rust code of the five layers. Nothing was known about that code when this was written beyond the fact that layer 5 prints floats from Rust.
Outcome (`source claim`, read at layer-5 commit 52ce017 and not built). Only layer 5 holds Rust. Its `Cargo.toml` sets no release profile, so overflow checks are off in a release build. But the code has no `debug_assert!`. The one unchecked subtraction on integers a submitter chooses, the two ends of an edit span, sits behind an explicit range test that runs first. No site was found that can wrap.

## 8. What Each Layer Could Adopt

Every entry in the third column is a `hypothesis`. None is merged into a default branch. State on 2026-11-20: every item named is open, except that the two `mcproof` fixes in the matrix are merged into a feature branch and not into main.
Each issue or pull request is named once in this document. The matrix names the fix branches it measured. This table names the rest.

| Contract | Layer or repository | What it could adopt | Open record |
| --- | --- | --- | --- |
| 1, clause 2 | L3 `siliconcordat/warp` | Refuse a bundle whose adapter file was not hashed, unless the operator opts out. | issue 10, with draft pull request 14 |
| 1, clause 5 | L3 `siliconcordat/warp` | Compare the path the server lists with the path that was hashed. Hash before the server starts. | issue 11 |
| 1, clause 5 | L3 `siliconcordat/warp` | Read flags and the base digest from the running process. Mark anything that was not measured as declared. | issue 12 |
| 1, clause 5 | L3 `siliconcordat/warp`, L2 `siliconcordat/weft` | Recompute the certificate numbers from the tensors of the file to be served, in exact integers. Require `alpha` equal to rank. | issue 13, with a rational checker for the spectral form drafted as pull request 7 in this repository |
| Section 7 | L3 `siliconcordat/warp` | Compute the joint numbers of a stack from its concatenated factors, in place of the worst-case rule and a declared composed certificate. | issue 15 |
| 2 and 3 | L3 `siliconcordat/warp` | Say in the mount receipt what a canary pass shows. Wire the sealed canary runner, or draw each mount's canaries from a pool only the verifier holds. | issue 16 |
| 1, clause 3 | L5 `siliconcordat/mde`, with L4 and L3 | No floats inside a hashed body. Scales as an integer numerator over a power of two. One file of test vectors run by every layer. | issue 7 |
| 1, clause 5 | L4 `siliconcordat/exo` | Scales with a denominator of 1024, rounded down. | issue 7 there |
| 1, clause 5 | L4 `siliconcordat/exo` | An outcome other than pending carries a digest that resolves to a ledger receipt. | issue 8 there |
| 1, clauses 1 to 3 | L2 `siliconcordat/weft` | A strict header reader: duplicate keys, overlaps, gaps and a length that disagrees with type and shape are rejected. | issue 9, fix measured in the matrix |
| 1, clauses 2 and 3 | `Proven-Commons/mcproof` | Full-string matches for digests and rationals. Reject a certificate that names no recognized status. | issues 8 and 9 there, fixes measured in the matrix |
| 1, clauses 2 and 3 | `ahrazzle/soko` | The same two fixes, and must-fail controls one millionth past each exact bound. | issues 65, 66 and 67, fixes measured in the matrix |
| 1, clauses 2 and 3 | `ahrazzle/soko`, `Proven-Commons/mcproof` | Check the type of a field before its value: a flag is a boolean and a count is a non-negative integer. A certificate marked verified with no witness fails whether or not it names a floor. | issue 74 in `soko`, issue 13 in `mcproof` |
| 1, clause 3 | `Foundation-0/quotient-lp-bounds` | One accepted spelling of a rational in the second checker, in lowest terms and in ASCII digits. | issue 1 there |
| 1, relation R5 | `ahrazzle/soko`, `Proven-Commons/mcproof`, `Foundation-0/quotient-lp-bounds` | One fixture per check that only that check rejects, with the test matching the full rule name. The deletion loop then tests that the fixture set is complete. | issue 75 in `soko`, issue 14 in `mcproof`, issue 2 in `quotient-lp-bounds` |
| 1, relation R5 | `ahrazzle/soko` | Make every listed must-fail control run the checker on a corrupted input. One control in a prover receipt is true by construction. | issue 77 |
| 1, clause 4 | `aska-physical/fibral-rigidity` | Checks that raise, in place of bare asserts. A bound recorded in the certificate. | the fix measured in the matrix |
| 1, clause 4 | `aska-physical/cfrp-masts` | The same change for its five bare asserts, so that a certificate written under `python3 -O` cannot record a claim the plain run rejects. | issue 3 there |
| 2 | `Proven-Commons/mcproof`, then L4 | Record the oracle gap per family in every repair-loop receipt. Do not stop a loop on an oracle whose recorded gap is above a registered threshold. | issue 12 there |
| 3 | `Moissanite-Labs/weft-loom`, then L4 | Finish the registered comparison of feedback detail. A sharper one would give every arm the same room to think, under its own preregistration. Write the oracle class into the receipt format. | draft pull request 38 |
| 4 | L1 `siliconcordat/loom`, L4 | Bind each audit verdict to the digest of the state before adaptation. Report the squared sine of each audit against the adjustable directions. | none yet |
| Section 7 | `ahrazzle/soko` | Replay every shipped bound on every catalogued route in CI. Expose per-state values from the native engine so they can be replayed too. | issue 71, with draft pull request 72 |
| Section 7 | `ahrazzle/soko` | Give the operator-counting bound a stated result for a state that can no longer be won, in place of an error about a matrix. | issue 76 |
| Section 7 | `ahrazzle/soko` | Keep the record that compares the published floors for one room with move sums on reachable positions. It does not settle what those floors count. | draft pull request 73 |
| all | L1 `siliconcordat/loom` | This document, the harness and its suite. | this change |

## 9. Falsification Conditions

Claims 1, 5, 10, 11, 12 and 13 are theorems and cannot be refuted by an observation. What can be refuted is that each contract earns its cost on real gates. An observation of any of the following counts against the contract named.

1. **Harmless violations dominate (Contract 1).** Of the violations the harness reports on real gates for R1, for R2 on required evidence, and for R3 on rejected inputs, fewer than half are confirmed as defects by the gate's owner once the reproducer is read. Then the relations mostly flag intended behaviour.
2. **The gap does not cost (Contract 2).** With early stopping switched off for the two families whose recorded gap is high, grader passes at the last turn do not rise. Then a false stop was not what the loop lost, and recording the gap earns no routing rule.
3. **Detail does not speed repair (Contract 3).** In the preregistered experiment, the arm that returns signed exact amounts does not repair in fewer rounds than the arm that returns only the failed constraint and its place, by the paired test registered there. Claim 5 still holds. Claim 8 is then dropped.
   The first registered run does not decide this. For its one model the rule gave "not decided", and its arms differed in how often replies reasoned in the open as well as in the feedback text.
   The record names a sharper design that gives every arm the same room to think. That design needs its own preregistration and has not been run.
4. **A mislabelled class (Contracts 2 and 3).** A loop fed full detail from a gate recorded as exact outputs an accepted artifact that the specification's owner shows to be false. Then the classes cannot be assigned reliably in practice, whatever the theorem says.
5. **The latch does not bite (Contract 4).** In a real adaptive loop, an audit whose squared sine against the adjustable directions is below 0.05 keeps a reading after adaptation that tracks an independently measured gap. Then the loop is far from linear or far from a stationary point, and Claim 10 does not describe it.
6. **Feeding the anchor back works (Claim 9).** A proposer adapted on an anchor's failures is judged on fresh anchors of the same kind, drawn after adaptation and never shown to it. Each fresh anchor `b` is counted by its outside part, `((I - P) b) . r`, as Contract 4 (c) says. If the size of that count falls after absorbing, the gap outside the adjustable directions closed, and the routing rule costs progress.
   A raw reading that falls is not enough. In the linear model absorbing leaves every outside count exactly unchanged.
   An earlier wording said that fresh anchors passing after adaptation meant that absorbing had closed the real gap. That inference is false in the linear model of Section 6.1. Absorbing a failed anchor by the least change moves the residual only inside the column space, so the outside part is exactly unchanged. Yet fresh anchors that resemble the absorbed one mostly read smaller.
   The script shows this on 136 of 150 instances. The defect was found through the two-loop study in `Foundation-0/continuum` draft pull request 3 and our second-pass check of it.
7. **Replay has no power (Section 7).** An invalid bound is found in a shipped checker and no catalogued route visits a state that shows it. Then route replay is too weak a test for that bound, and closure has to be argued from the rules.
8. **A defect outside the reading (Claim 14).** A gate defect is found in the stack that is neither a fork nor a missing step under any quotient its owner would name. Then the closure reading is dropped.

## 10. Limits and Prior Work

No statement in this document is claimed as new. The parts are known under these names (`source claim` for each).

- A checker that needs only a witness and a short check: certifying algorithms (McConnell, Mehlhorn, Naher and Schweitzer, 2011).
- A consumer that checks a supplied proof against its own safety policy: proof-carrying code (Necula, 1997). The policy there is the pinned rules here.
- Relations between runs in place of an oracle: metamorphic testing (Chen, Cheung and Yiu, 1998).
- Each condition shown to decide the outcome alone: modified condition/decision coverage (Chilenski and Miller, 1994).
- Deleting each rejection statement of a verifier and counting the deletions that no test notices: refusal-site mutation testing (Hill, 2026).
- Signing only what was measured: measured boot and remote attestation (Trusted Computing Group), and build provenance written by the build platform and not by its tenant (SLSA).
- No floats inside hashed JSON: the JSON Canonicalization Scheme, RFC 8785, pins one number format, and the Matrix specification forbids floats in canonical JSON.
- Residuals orthogonal to the regressors, and tests for misspecification built from them: least squares, and the specification tests of Ramsey (1969).
- The cost of one linear restriction on a least-squares fit: restricted least squares, in econometrics texts such as Greene, Econometric Analysis.
- Reuse of held-out data: adaptive data analysis (Dwork, Feldman, Hardt, Pitassi, Reingold and Roth, 2015).
- Quotients of a chain that keep the dynamics: lumpability (Kemeny and Snell, 1960).

Three packagings were not found as stated. A first search was one or two queries each. A second search by a separate reader ran eleven to fourteen queries each, in the vocabularies of several fields. Its verdict was the same for all three: every ingredient is known, and the packaged rule was not found.
That is the whole of the statement. A search that finds nothing does not show that nothing exists. Hill (2026) was opened and checked again for this document. The other entries are taken from the search notes.

| Packaging | Queries tried | Nearest work found |
| --- | --- | --- |
| The latch as a rule for adaptive loops: judge before adapting, void later audits for absorbed directions, count surviving audits by rank | "residual diagnostics invalid after adaptive fitting optimizer removes misspecification signal". "adaptive controller masks fault from residual-based fault detection". "halt learning when proxy metric and held-out anchor diverge". "two-loop learning, separate verification and validation channels, halt parameter adaptation on misspecification" | Ramsey (1969). Dwork and others (2015). Ljung, System Identification (1999), on residual analysis. Cheng and others (2018), where weighting derived from the data removed most of a measured signal. Bayarri and Berger (2000), on checks weakened by using the data twice. From the second search: the count of residual degrees of freedom in least squares, the redundancy count used for gross-error tests in data reconciliation, and reports that an adaptive controller can hide a fault from residual-based detection |
| The omission relation as a required test for gates that check proof certificates | "metamorphic testing of proof checkers certificate verifiers removing fields from witness must not turn reject into accept" | Chen, Cheung and Yiu (1998). Metamorphic testing of compilers for zero-knowledge proofs (2025). From the second search: Hill (2026) measures the deletion form of R5 and does not state the omission relation. Chen and Furia (2018) test the opposite direction, that an equivalent variant of an accepted program stays accepted |
| A return policy indexed by oracle class and written into the receipt format | "verifier feedback granularity binary verdict vs structured counterexample adaptive data analysis holdout leakage budget feedback policy by oracle type" | Dwork and others (2015). Blum and Hardt (2015). Counterexample-guided synthesis (Solar-Lezama and others, 2006). Counterexample-guided abstraction refinement (Clarke and others, 2000). From the second search: Jha and Seshia (2015) classify synthesis oracles by the kind of counterexample they return. No table by oracle class was found, and no source for the rule that an anchor returns nothing |

Limits.

- The relations are necessary conditions. A gate that keeps all five can still accept a false claim, and none of them reaches clause 5 of Contract 1.
- The snapshot is one day, eighteen rows, and adapters that are not published. Sampled cells show what was run and no more.
- The oracle gap is counted on 48 validation items per arm, against one grader. A grader can be wrong too.
- Claim 5 is about soundness. It says nothing about speed, and nothing about whether the specification is the right one.
- The exact status of Claim 9 is for the noiseless linear model. With noise, or for the reading of one anchor, revising the specification can raise the error. Claim 9 as a rule for real loops is untested.
- Claim 10 is exact for a residual that is linear in the adjustable parameters and for a least-squares minimiser. For other losses only the stationary-point remark is offered.
- Claims 12 and 13 are for finite systems given by one or more step maps, with unit step cost. Part (b) of Claim 12 is about a checker that evaluates the step as a black box.
- The harness reads JSON artifacts and Python interpreter flags. It assumes a rejected fixture is rejected for its content. A fixture rejected only because a value has the wrong type can be reported as a re-spelling that passes. The reproducer shows the pair.

## 11. Check It

```bash
python3 -B -W error -m unittest -v scripts/verify_gate_contracts.py
python3 -O -B -W error -m unittest -v scripts/verify_gate_contracts.py
python3 -B -W error scripts/gatecheck.py --self-test
python3 -B scripts/verify_gate_contracts.py --report
```

Last lines of the first command. The second prints the same apart from the time.

```text
Ran 26 tests in 9.500s

OK
```

Output of the self-test:

```text
leaky {'R1': 'fail 5', 'R2': 'fail 9', 'R3': 'fail 11', 'R4': 'fail 2', 'R5': 'fail 2'}
strict {'R1': 'pass 0', 'R2': 'pass 0', 'R3': 'pass 0', 'R4': 'pass 0', 'R5': 'pass 0'}
SELF-TEST OK
```

Output of the report:

```text
Contract 1, toy gates: {'leaky': {'R1': 5, 'R2': 9, 'R3': 11, 'R4': 2, 'R5': 2}, 'leaky_runs': 907, 'strict_runs': 751}
  harness sabotages that must go red: 32
Contract 4, latch census: {'full_rank': 200, 'rank_deficient': 100, 'boundary': 100, 'boundary_strictly_between_0_and_1': 100, 'weighted': 100}
  stationary-point instances: 60  gradient-descent instances: 60
Claim 9, one anchor absorbed (seed 20261121): {'instances': 150, 'rank_deficient': 96, 'old_falsifier_fired': 136, 'classes': {'helps': 366, 'hurts': 683, 'tie_at_0': 150, 'tie_at_2': 150}}
  several anchors (seed 20261122): 100  revisions (seed 20261123): 100
Contract 3, exact gate under feedback: loops run 472392  loops that ended in an accept 266328  false accepts 0
  unsound gates exploited without feedback: 37
  sampled oracle, (samples, committed false passes, false passes after one detailed answer): (20, 1, 20)
Closure census: {'systems': 256, 'closed': 64, 'not_closed': 192, 'one_state_changes_tried': 256, 'subsets_fooled': 960}
Polarity census: {'systems': 60, 'specs_allowing_more': 694, 'specs_allowing_less': 30026, 'unsound_bounds': 31680, 'void_specs': 14720, 'refuted_by_one_step': 31680}
Thousandths as 32-bit floats (above, below, equal, n/1024 exact): (503, 489, 8, 1025)
```

The count behind Claim 4, from a clone of `Proven-Commons/mcproof` at commit 62164d63:

```python
import json, collections
for f in ("validation_repair_b0.json", "validation_repair_p2b.json"):
    with open("compile/artifacts/evaluation/repair_loop/" + f) as fh:
        d = json.load(fh)
    items = []
    def walk(o):
        if isinstance(o, dict):
            if "inference_certified" in o and "passed" in o:
                items.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    c = collections.Counter((r["family"], r["inference_certified"], r["passed"]) for r in items)
    print(f, sorted(c.items()))
```

```text
validation_repair_b0.json [(('A', False, False), 11), (('A', True, True), 1), (('B', False, False), 3), (('B', True, False), 4), (('B', True, True), 5), (('C', False, False), 1), (('C', True, False), 11), (('D', False, False), 10), (('D', True, True), 2)]
validation_repair_p2b.json [(('A', False, False), 12), (('B', False, False), 8), (('B', True, False), 4), (('C', False, False), 2), (('C', True, False), 10), (('D', False, False), 12)]
```

A triple reads family, oracle pass, grader pass. The first file is the bare model and the second is the adapter.

The added anchor of Record C, from a clone of `Foundation-0/gravity` at commit 8f96c4b2. Save the script below as `kids_check.py`, outside the clone, and run:

```bash
git clone https://github.com/Foundation-0/gravity.git
git -C gravity checkout 8f96c4b2
python3 -I -B kids_check.py gravity
```

```python
import math, sys
sys.path.insert(0, sys.argv[1])
import wave3_empirical_audit as w
def sparc(ds, a0):
    return sum(((lo - w.pred_log10_gobs(lb, ds, a0)) / (sd / math.sqrt(n))) ** 2
               for lb, lo, sd, n in w.SPARC_RAR_BINS)
def kids(ds, a0):
    r, c = 1000.0 * w.KPC, 0.0
    for lm, v, e in w.KIDS_WL_ALL_1000KPC:
        gb = w.G * 10 ** lm * w.M_SUN / r ** 2
        vp = math.sqrt(10 ** w.pred_log10_gobs(math.log10(gb), ds, a0) * r) / 1e3
        c += ((v - vp) / e) ** 2
    return c
free = min((sparc(d / 1000, a * 1e-12), d / 1000, a * 1e-12) for d in range(800, 1101, 5) for a in range(80, 161))
fixed = min((sparc(1.0, a * 1e-12), 1.0, a * 1e-12) for a in range(80, 161))
for tag, (c, ds, a0) in (("d_s fixed at 1", fixed), ("d_s free", free)):
    print(tag, "d_s", ds, "a0", a0, "sparc", round(c, 2), "kids", round(kids(ds, a0), 1))
```

```text
d_s fixed at 1 d_s 1.0 a0 1.18e-10 sparc 30.49 kids 31.5
d_s free d_s 0.945 a0 1.25e-10 sparc 25.89 kids 69.9
```

The script fits `d_s` and `a0` to the 14 binned points of the table with the table's own weights, over `d_s` from 0.8 to 1.1 in steps of 0.005 and `a0` from 0.8e-10 to 1.6e-10 in steps of 1e-12. It then reads the chi-squared of the 4 lensing points at the fitted values.
