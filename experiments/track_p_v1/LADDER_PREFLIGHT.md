# Track P — model-free ladder and the gate that fixed K

Record of `scripts/read_run_v3_policy_ladder.py`, run 2026-09-03 on
`experiments/track_p_v1/diagnostics/policy_ladder_v3.json` (2,000 episodes
per cell, γ = 0.4, seed label `track-p-v3-policy-ladder`, 30 workers). No
model existed when the gates and the K rule were written into the script's
docstring; this file reads the result against them.

## The rule, as written before the run

K is the **smallest K passing gates 1–3**; gate 4 must hold at every K.

1. *The hard-coded stop is a real decision.* `stop_aware` must fail to
   register both targets on ≥ 10 % of gated hard-cell episodes (fraction
   ≤ 0.90, Wilson upper < 0.95).
2. *There is room to order.* median(`blind_exhaust` expansions) −
   median(oracle expansions) ≥ 2 on the hard cell.
3. *The easy cell stays a sanity rung.* Generation success ≥ 0.5 at that K and
   the exhausted walker route-complete on every gated easy episode.
4. *The two coverage implementations agree.* `route_coverage_v3.route_complete`
   equals "both target routes decodable from the examined set" on every policy
   and episode, zero disagreements.

Gate 1 reads the **walk-based** quantity (`targets_registered`), for the reason
recorded in `docs/DESIGN_NOTES_READ_PATH_SUCCESSOR.md` §2.23: set-based
coverage can credit a stop policy with a target whose final edge entered the
examined set through an expansion at another depth. Both quantities are in the
JSON; on this run they differ by at most 0.4 pp on any policy.

## Result

| K | gate 1 | gate 2 | gate 3 | gate 4 | stop_aware registers both (hard) | Wilson upper | room (hard) | easy gen |
|---|---|---|---|---|---|---|---|---|
| 1 | pass | pass | pass | pass | 0.873 | 0.889 | 2 | 1.000 |
| 2 | pass | pass | pass | pass | 0.799 | 0.820 | 2 | 1.000 |
| 4 | pass | pass | pass | pass | 0.758 | 0.786 | 2 | 0.814 |

**Chosen K = 1.** Gate 4: zero disagreements at every K and on K = 0.

K = 2 and K = 4 also pass every gate and are stronger versions of the same
test; they are not run in Track P, by the rule, and are the obvious next cell
if K = 1 reads band A.

## The reference numbers Track P is read against (hard cell, K = 1, n = 1,080)

| policy | registers both targets | expansions (median / p75) | expansions at RC (median) | overhead after RC | only targets registered | distractor endpoints reached |
|---|---|---|---|---|---|---|
| blind_exhaust | 1.000 | 6 / 10 | 6 | 0.43 | 0.000 | 1.00 |
| similarity_exhaust | 1.000 | 6 / 10 | 5 | 1.63 | 0.000 | 1.00 |
| bfs_two_stop | 0.844 | 6 / 10 | 5 | 0 | 0.166 | 0.84 |
| stop_aware | 0.873 | 5 / 8 | 4 | 0 | 0.231 | 0.77 |
| oracle | 1.000 | 4 / 6 | 4 | 0 | — | — |

Easy cell, K = 1, n = 1,122: blind_exhaust 5 expansions at RC 1.000;
stop_aware registers both on 0.771 at 4 expansions; oracle 4.

Generation success: hard K = 1 0.722 (v2 baseline 0.826), easy K = 1 1.000.
Gated stratum `hops_2_4`, non-abstain, as in Track O's ladder; median query
length in the stratum is 4 on both cells.

## What the numbers say, before any model exists

- **K = 0 is the diagnosis confirmed.** On v2 data `stop_aware` registers both
  targets on 100 % of episodes and the room is 0 (easy) or 1 (hard): nothing to
  learn about stopping, one expansion to learn about ordering.
- **At K = 1 the stop is a decision and the ordering has room.** The best
  hand-coded policy is right 87 % of the time at a median of 5 expansions; the
  oracle needs 4; exhaustion needs 6 and is always right. A learned walk that
  reads band A has to be right *and* cheaper than 5 — it cannot buy
  completeness by exhausting.
- **The trees are small.** Median 6 expansions to exhaustion, p75 10. The
  whole contest is over one or two expansions per episode; per-seed paired
  comparisons on ~1,000 episodes are what make that readable, which is what
  the preregistration's paired-proportion rule is for.
- **Set-versus-registration disagreement is rare but real**: 0.2–0.4 % of
  stopping-policy episodes. Small enough not to move a band, large enough that
  a label defined on the wrong one would be unexplainable by any structural
  feature.

## Provenance

- Generator: `generator_v3.py` at K = 1 (`deg6_len8_v4_rep-k1`,
  `deg3_len6_v8-k1`), whose K = 0 output is byte-identical to `generator_v2`
  (`tests/test_read_run_generator_v3.py::test_k0_reproduces_v2_byte_for_byte`).
- Policies: `policies_v3.py`; `blind_exhaust` cross-checked against the
  v1-era `relation_walker_examined_set` at unlimited budget
  (`tests/test_read_run_policies_v3.py`).
- The JSON holds aggregates only; the hidden-field scan on it is clean.
- Touches no holdout; generates in memory under the `test-fixture` split.
