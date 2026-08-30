# Hippocampus Foundation — One-Week READ Run

## Preregistration v1

**Frozen:** 2026-08-31 (2026-08-30T15:35:42Z), before the READ-run
generator was written.

**Held-out seed commitment:**
`sha256:6183dc36b8a9fededaee99db385013d33785bc75de531937e65115d6d770c663`

The 32-byte seed preimage is stored only in ignored private storage. The
commitment is over the exact raw 32 bytes. Dataset seeds are derived with
domain-separated SHA-256 from the preimage, split name, paired-world index,
and gamma bucket. Revealing or changing the preimage before the final report
voids the run.

**Prior legitimate baseline:** unmeasured. Hippocampus-1.0 produced six nulls
on tasks that could not test the hypothesis. Hippo-9, hippo-qwen-2 and
Hippo-wik results are invalid because of label leakage. Phase 0 v4.4 is
parked, not deleted.

---

## 1. Question

Does learned graph traversal beat a direct no-traversal scorer at equal
examined-edge budget, and does the gap depend on how path-dependent the task
is?

This is the load-bearing claim. If a direct scorer matches traversal, every
downstream question — shared READ/WRITE trunks, curricula, MoE, and real-graph
tiers — is moot.

## 2. Definitions

**Gamma (greedy-wrongness).** Over all steps on a valid path to the target,
the fraction at which the unique highest query-similarity neighbour is not on
any valid path. Gamma is the difficulty axis. Hop count is secondary. The
generator must avoid query-similarity ties at the maximum. Measured gamma is
computed from the emitted graph and the independent oracle, not copied from a
requested setting.

**Exact-set accuracy.** Credit only when the complete assertion set is exactly
correct and the recorded traversal is valid. Non-abstaining targets are
uniform over the 15 non-empty subsets of four assertions. ABSTAIN is a separate
outcome and occupies exactly 25% of every split and gamma bucket. Exact-set
accuracy conditional on non-abstention and ABSTAIN accuracy are always reported
separately; the primary exact-set number cannot be inflated by abstaining.

**Examined-edge budget B.** The number of distinct edge actions whose scores
are computed. Re-scoring an edge counts again and is prohibited by the
preregistered harness. Both arms must consume exactly B scores; padding or
dummy scores do not count. The main-sweep B is selected by the budget sweep
below before screening accuracy is inspected.

**Unit of analysis.** One query episode in one procedurally generated closed
world. Base worlds are paired across gamma buckets, while train, screening,
and final-held-out world families are mutually disjoint.

**Prediction time and available information.** The model receives only the
serialized visible episode, router seed, and B. Target identity, assertion
labels, valid routes, teacher actions, measured gamma, split derivation
material, and oracle state are unavailable to both arms.

## 3. Hypothesis

Exact-set accuracy of TRAV exceeds DIRECT by a margin that increases with
gamma.

## 4. Arms

| Arm | Description |
| --- | --- |
| TRAV | Traversal controller, approximately 10M trainable parameters, with pointer scoring over the currently visible frontier. It adaptively chooses which node to expand next. |
| DIRECT | No-traversal scorer with the same observation and candidate encoders. Starting from the same router seed as TRAV, the harness expands breadth-first until exactly B distinct edges have been exposed. All B edges are scored jointly in one shot; no score may depend on a previously selected endpoint. BFS ordering is structural and cannot read query similarity, labels, target identity, valid routes, or gamma. |

Training data, optimizer, update count, model seeds, and each selected B are
identical between arms. Candidate and observation encoders are identical.
Trainable parameter counts must differ by less than 1%. Any arm-specific data,
schedule, early stopping, candidate construction, or scoring allowance voids
the comparison.

## 5. Budget selection and decision rule

The Day-3 screening sweep uses:

- B in {16, 32, 64, 128};
- gamma in {0, 0.4};
- one preregistered model seed;
- both arms, for 16 total runs.

The main-sweep budget is the smallest candidate B for which DIRECT's
target-in-pool coverage is greater than 90% at gamma=0. Coverage alone selects
B. The selection is recorded before any screening accuracy aggregate is
opened. If no candidate exceeds 90%, the main sweep does not run and the result
is reported as a design failure. Accuracy-at-budget for every Day-3 run is a
secondary result and all 16 runs are reported.

The primary decision is set before any number is seen:

- **Negative control.** At gamma=0 the mean arm gap must be at most one
  percentage point in absolute value. Otherwise the harness is wrong and the
  run is void regardless of higher-gamma results.
- **Positive.** The gamma=0 control passes, the mean gamma=0.4 gap is at least
  five percentage points, and `min(TRAV) > max(DIRECT)` over the three model
  seeds at gamma=0.4.
- **Null.** The absolute mean gap is at most two percentage points at every
  gamma.
- **Inconclusive.** Anything between. It is reported as inconclusive, not
  reframed.

With three seeds per arm, complete seed-range separation is the one-sided exact
permutation event with p = 1 / C(6, 3) = 0.05. The full curve and every seed are
reported in all four cases. The five-point threshold is a preregistered
judgement threshold and will not move.

## 6. Data and splits

All data are local procedural closed worlds. No external corpus, Wikidata, or
Hugging Face payload is used.

- 64–256 nodes;
- 8–16 typed relations;
- valid target-path length 2–6;
- complete worlds, so absence genuinely means false and VERIFIED_FALSE
  negatives are constructible;
- ABSTAIN at exactly 25%, matched across degree, path length, candidate count,
  gamma, and difficulty;
- 150,000 train episodes per gamma bucket;
- 2,000 Day-3 screening episodes per gamma bucket;
- 15,000 final-held-out episodes per gamma bucket;
- gamma in {0, 0.1, 0.2, 0.3, 0.4};
- three main-sweep model seeds: 1729, 2718, and 3141;
- teacher supervision is the complete set of actions at each step that can
  still reach the target, never one arbitrarily selected shortest path.

Screening worlds are generated independently and are not train subsamples.
World-family identifiers may not overlap across train, screening, or final
holdout. The final holdout is generated and opened once, only after generator,
oracle, model code, training configuration, selected B, thresholds, update
count, and reporting code are frozen. Day-3 observations may diagnose an
independently established infrastructure failure, but any code or configuration
change after an accuracy is observed requires a new preregistration version and
a newly committed held-out seed.

## 7. P0 gates

No model training starts until all seven gates pass. These gates use locally
generated train/screen audit material and never open the final holdout.

1. **Gamma measured, not declared.** Empirical gamma must be within 0.03 of the
   requested setting in every split and bucket. The checker recomputes valid
   paths independently.
2. **Gold-swap noninterference.** Change the hidden target while holding the
   visible episode fixed and assert byte identity for every model-visible
   artifact: graph tensors, seeds, masks, budgets, padding, and serialization
   order.
3. **Shortcut probes at chance.** Separate preregistered lookup probes use only
   degree, candidate count, candidate position, serialization order, or episode
   length. They are fit on the first 120,000 canonically ordered training
   episodes and evaluated on the remaining 30,000 in each gamma bucket. For
   non-abstaining examples, chance is 1/15 and `n=22,500`; for binary ABSTAIN
   prediction, majority chance is 75% and `n=30,000`. For every feature and
   bucket, the one-sided 95% Wilson upper confidence bound may exceed the
   corresponding chance rate by at most one percentage point. Results for the
   two strata are reported separately.
4. **DiRe control.** For each connected audit episode, remove one indispensable
   route edge while preserving endpoint-local features, nuisance marginals,
   candidate assertion distribution, and serialization size. The operational
   answer becomes ABSTAIN. A nuisance-only shortcut probe trained on connected
   episodes must recover the original non-empty assertion set on the
   disconnected variants no better than the gate-3 conditional chance bound.
5. **Dual oracle agreement.** The generator and an independently implemented
   oracle must agree record-for-record on reachability, all valid next actions,
   target assertion set, ABSTAIN status, and measured gamma.
6. **Double execution.** Regenerate under perturbed locale, timezone, working
   directory, and Python hash seed. Public dataset bytes must be identical.
7. **DIRECT-pool invariance.** For every paired episode and every candidate B,
   DIRECT's structural BFS target-in-pool indicator must be exactly identical
   across all gamma buckets. Aggregate coverage is reported at every gamma. Any
   per-episode difference or decline means pool construction is contaminated
   and voids the run.

A gate failure is fixed at the generator or harness and rerun from that point.
Gates 2 and 3 are the mechanical checks that would have caught all three known
historical leakage failures.

## 8. Schedule

| Day | Work |
| --- | --- |
| 1 | Generator, independent oracle, complete teacher-route derivation, measured gamma |
| 2 | P0 gates 1–7; freeze generator, oracle, model, training, and reporting configuration |
| 3 | Full 16-run B sweep; commit the coverage-selected B before opening accuracy summaries |
| 4–6 | Main sweep: five gamma values × two arms × three seeds = 30 runs |
| 7 | Complete the full report, integrity checks, and release; no slack remains |

Days 3–7 are treated as five execution/reporting days. There is no rescue day.

## 9. Out of scope

WRITE and all mutation operations; the shared-trunk claim; MoE; curriculum
scheduling; real-graph tiers; text encoders; reinforcement learning; LLM
judges; and the twelve-hypothesis ledger.

Cut from Phase 0 v4.4 specifically:

- ContractNLI, EvidenceBench, and SocialIQA cannot answer this question.
- The 131.73-GiB Wikimedia mirror is unnecessary; canonical dumps can remain
  publisher-hosted and publisher-hashed.
- An OCI custody runner, three-key ceremony, and encrypted quarantine index do
  not create independence against a solo researcher who controls every role.

## 10. Integrity commitments

1. This document and its seed commitment are frozen before the READ-run
   generator is written.
2. Final-held-out worlds derive only from the committed seed preimage and
   documented domain separation.
3. Every run is reported, including broken runs, unless independently
   diagnosed as an infrastructure failure. The diagnosis is recorded before a
   replacement run.
4. No threshold, metric, arm definition, pool rule, or decision rule changes
   after any accuracy is seen.
5. Holdout labels, oracle internals, measured gamma, teacher routes, and target
   identity cannot enter model features, model selection, threshold selection,
   or budget selection.

## 11. Stop conditions

Report a negative or limited result without changing the metric, weakening
DIRECT, dropping seeds, or adding a rescue arm if:

- DIRECT matches TRAV at high gamma;
- the gamma=0 negative control fails;
- any P0 gate fails and cannot be fixed at the generator;
- no candidate B exceeds 90% target-in-pool coverage at gamma=0;
- the effect exists but falls below the preregistered threshold.

## 12. Lessons carried forward

- Hashing code is not execution evidence. *(v4.4)*
- Label removal does not make a membership index public-safe. *(v4.4)*
- An audit layer that has never audited a result is not evidence either.
- A task that requires only one binding cannot test an accumulation hypothesis.
  *(1.0)*
