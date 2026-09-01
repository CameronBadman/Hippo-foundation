# READ run v1 — provenance of the coverage-to-accuracy prediction

Written 2026-09-01, before any further run. This note exists so that a striking
agreement between two measurements cannot later be mistaken for a stronger claim
than its provenance supports.

## The ordering, which is the whole point

**The coverage figures were measured and committed before any accuracy existed.**
They are gate 7 of the P0 report at `audit/read-run-p0.v1.passed.json`, canonical
digest `sha256:715a12e0358cd6cd4b486f574961968dc8b000d2ce5a64e07be0e5f6abbd46e6`,
evaluated 2026-08-31, and that digest is bound into all 30 E1 training receipts
and into code freeze `sha256:07d18b39…`. At the moment they were recorded no
model had been trained, no checkpoint existed, and no accuracy had been computed
on any split.

DIRECT target-in-pool coverage at the selected budget B = 128, over the 2,000
official screening episodes per gamma bucket:

| Stratum | episodes | coverage at B=128 |
|---|---|---|
| `hops_2_4` | 1,518 | 100.00% |
| `hops_5` | 412 | 26.21% |
| `hops_6_plus` | 70 | **0.00%** |

Identical across all five gamma buckets, which is the structural gamma-invariance
Amendment 02 §3 records: pool construction never reads `query_similarity_ppm`.

## The subsequent observation

The diagnostic learnability probe then scored DIRECT on the same screening
domain. At update 5,500, proof-valid exact-set accuracy over non-abstain
episodes:

| Stratum | episodes scored | accuracy | coverage |
|---|---|---|---|
| `hops_2_4` | 1,124 | 86.48% | 100.00% |
| `hops_5` | 322 | 13.98% | 26.21% |
| `hops_6_plus` | 54 | **0.00%** | **0.00%** |

Accuracy tracks coverage. Where the structural pool reaches the target at every
episode, DIRECT answers most of them. Where it reaches roughly a quarter, DIRECT
answers roughly half of what it can see. Where it reaches none at any
preregistered budget, DIRECT answers exactly none.

The `hops_6_plus` cell is the sharpest of the three: 0.00% predicted and 0.00%
observed, on a mechanism — the BFS pool cannot reach a 6-hop target within 128
examined edges — that was derived structurally rather than fitted.

### Why the denominators differ

Coverage is computed over all 2,000 screening episodes; accuracy is computed over
non-abstain episodes only, which are 75% of each bucket by construction. The
per-stratum non-abstain counts (1,124 / 322 / 54) are not exactly 75% of the
per-stratum totals (1,518 / 412 / 70), because ABSTAIN is matched across degree,
path length, candidate count, gamma and difficulty rather than across BFS hop
distance. The two tables describe the same episodes under different filters and
their rows are aligned by stratum, not by count.

## What this is, and what it is not

**It is a confirmed prediction on one seed of screening data.** Model seed 1729,
gamma = 0, screening split, a single non-preregistered diagnostic run, one
checkpoint. Nothing here carries a decision rule.

**It is not yet a claim.** It becomes one only if E1-v2 reproduces it across
three model seeds, on data generated from a new master seed, under the
preregistered reporting of Amendment 02. Until then it is recorded as an
observation whose ordering happens to be clean, not as a result.

**It is not a comparison between the arms.** TRAV's deep-stratum numbers are not
quoted here and no gap is computed. Amendment 02 §6 forbids reading a
`hops_5` or `hops_6_plus` difference as a scoring result, because DIRECT has no
visibility there and any difference would measure abstention behaviour rather
than the comparison the experiment is about.

**The falsifier is stated so the prediction can fail.** If E1-v2 shows DIRECT
scoring materially above zero at `hops_6_plus`, or shows `hops_5` accuracy
unrelated to its measured coverage, this observation is wrong and is reported as
having failed. A prediction that cannot fail is not evidence.
