# READ run v1 — Preregistration Amendment 09

**Status: pending review. Not an approved amendment.**

Amendment date: 2026-09-01. Replaces Amendment 05 §2's plateau-selection rule
with a more robust reading of the same underlying test. Amendments 02–08 stand.

The frozen preregistration is not modified. `PREREGISTRATION.md`,
`preregistration.v1.json`, and `training-config.v1.json` retain the exact SHA-256
digests pinned in `read_run/contracts.py`.

## 0. Disclosure

Written with TRAV's extended probe at 5,774 of 9,376 updates, its last completed
screening checkpoint at U=5,500. **TRAV currently has no valid plateau reading
under this amendment's own rule** — the one candidate checkpoint it produced
under the old rule (4,500) is immediately broken by the two checkpoints that
follow it (5,000: +5.07pp; 5,500: +3.11pp), so as of this writing TRAV has not
plateaued by any standard. This amendment is deliberately committed before that
is resolved. DIRECT's complete curve (9,376 updates, finished earlier) is
already fully known and is used below as worked evidence, not as data this
amendment was tuned to produce a preferred answer from — its reading is stated
in §2 before its consequence for DIRECT is drawn out in §3.

## 1. What Amendment 05 §2 got wrong

Amendment 05 §2 selected the **first** checkpoint at which an arm had left
uniform and two consecutive 500-update intervals each failed to increase
accuracy by more than 1.00pp. Applied to TRAV, it fired at update 4,500:

| U | acc | ΔA vs prior checkpoint |
|---|---|---|
| 4,000 | 82.21% | −0.4448pp |
| **4,500** | 83.19% | **+0.9786pp** |
| 5,000 | 88.26% | +5.0712pp |
| 5,500 | 91.37% | +3.11pp |

The fire came within **0.0214 percentage points of its own threshold** — 11
correct episodes out of 1,124; a twelfth would have produced 1.0676pp and the
rule would not have fired. TRAV then gained 5.07pp and 3.11pp over the following
two checkpoints. That is a demonstrated false positive, not a suspected one: the
rule caught two small intervals inside a noisy upward climb and reported them as
a settled arm.

The failure is structural, not a fluke of this one run. A two-consecutive-
interval test evaluated at the *first* point it passes has no protection against
being satisfied by chance in the middle of continued improvement — it only takes
one lucky pair.

## 2. The corrected rule

Selection moves from **first-qualifying** to the start of the **final unbroken
run of qualifying checkpoints that extends to the end of the arm's measured
range**. Precisely:

Let an arm's *measured range* be its evaluated checkpoints in chronological
order, `U_1 < U_2 < ... < U_n` (the most recent, `U_n`, being the last checkpoint
completed so far). Checkpoint `U_i` (for `i >= 3`) is **qualifying** when:

- the arm has left uniform at `U_i` (Amendment 04 §4 criterion (L),
  `L(U_i) <= 2.34`, together with the Amendment 04 §5 learner-gate floors), and
- `acc(U_i) - acc(U_{i-1}) <= 1.00` pp, and
- `acc(U_{i-1}) - acc(U_{i-2}) <= 1.00` pp.

**The arm's plateau point is the smallest qualifying `U_i` such that every
checkpoint from `U_i` to `U_n` is also qualifying, provided that run contains at
least 3 checkpoints** (equivalently, spans at least 1,000 updates from `U_i` to
`U_n`; see the correction below). Equivalently: walk backward from the most
recent checkpoint; the plateau point is the start of the unbroken qualifying
streak that reaches the end, if that streak is long enough to be evidence of
settling rather than a short coincidence.

**If no such `U_i` exists — the most recent checkpoint is not qualifying, the
qualifying streak reaching it is empty, or that streak is shorter than the
3-checkpoint minimum — the arm has not plateaued within its measured range**,
and Amendment 04 §4's extension rule applies: the probe is extended and the
test re-applied to the longer range, never extrapolated. This is TRAV's present
state.

### Why not simply the last element of the qualifying set

A simpler reading — "last-qualifying" as merely the most recent checkpoint at
which the pairwise test independently passes, without requiring the streak to
hold unbroken to the end — was considered and rejected. It degenerates for any
arm that settles into a low, non-spiking improvement rate and never spikes
again: such an arm continues to satisfy the pairwise test at *every* subsequent
checkpoint, so its "last qualifying checkpoint" becomes whichever checkpoint the
probe happened to be stopped at, rather than any property of where the arm
actually settled.

DIRECT's own curve demonstrates this concretely. Under the simpler reading its
plateau point is **9,376** — its very last measured checkpoint, an artifact of
how far this diagnostic happened to be run, since it exhibits no more large
jumps anywhere from 7,500 onward:

| U | acc | ΔA |
|---|---|---|
| 7,500 | 86.03% | −1.60pp |
| 8,000 | 86.74% | +0.71pp |
| 8,500 | 87.19% | +0.44pp |
| 9,000 | 87.28% | +0.09pp |
| 9,376 | 87.81% | +0.53pp (376-update window) |

Every one of these intervals independently satisfies the pairwise test, so under
the simple reading the plateau point is pushed to the end of measurement no
matter how far that measurement happens to run — inflating the shared budget for
a reason that has nothing to do with the arm's convergence and everything to do
with an experimenter's stopping decision. A rule with that property is not safe
to preregister: it would let "run the probe longer" quietly become "select a
larger budget," which is the same category of problem the Amendment 06 ceiling
exists to prevent from the opposite direction.

The unbroken-streak definition does not have this defect. It asks only whether
the arm has been sitting in a settled regime continuously up to the present,
which is a property of the curve's shape and is stable to how much further the
probe happens to run past the point where settling began.

### Correction: a minimum run length, added while TRAV is still unresolved

§2 as first written had a residual hole. An unbroken run is only evidence of
settling if there is enough of it — a run of exactly two checkpoints reaching
the end of measurement is the 4,500 false positive again in a different shape,
since two qualifying checkpoints is exactly what §2's per-checkpoint test
already requires as a minimum to fire even once. Requiring the run to *reach the
end* fixed the "broken and resumed" failure mode; it did nothing about a run
that is merely short.

**Added: an unbroken qualifying run must contain at least 3 checkpoints**
(equivalently, span at least 1,000 updates from its first checkpoint to the
most recent) to be read as a plateau. A run of 1 or 2 checkpoints reaching the
end of the measured range does not qualify, and Amendment 04 §4's extension
rule applies exactly as it does for no run at all.

This is stated now, while TRAV's outcome under it is unknown, for the same
reason the rest of this amendment was: resolving it after TRAV produces a
run would make the minimum a fact about that run rather than a rule. Applied
identically to both arms — DIRECT is rechecked, not exempted:

| | run | checkpoints | span |
|---|---|---|---|
| DIRECT | `{7500, 8000, 8500, 9000, 9376}` | 5 | 1,876 updates |

DIRECT clears the minimum by a wide margin either way it is stated (5 ≥ 3
checkpoints; 1,876 ≥ 1,000 updates), so this addition changes nothing for
DIRECT and costs nothing to state. Its purpose is entirely prospective, for
whatever run TRAV eventually produces.

## 3. Applied to both arms

**DIRECT**, under §2: the qualifying checkpoints in its full range are
`{7500, 8000, 8500, 9000, 9376}`, an unbroken run of 5 checkpoints spanning
1,876 updates, clearing the minimum-run-length correction with margin. Its
plateau point is **7,500** — unchanged from Amendment 05's reading, because
DIRECT's case is exactly the one both definitions were designed to agree on: a
real, sustained settling rather than a lucky pair.

**TRAV**, under §2: no unbroken qualifying run currently reaches its last
measured checkpoint (5,500). TRAV **has not plateaued** within its measured
range as of this writing. Its probe continues to 9,376 per the existing
extension; if no unbroken run reaching that point exists either, it extends
further under Amendment 04 §4 within the Amendment 06 ceiling of 15,000. If it
reaches 15,000 without ever producing such a run, Amendment 07 §3's stop clause
applies.

This rule is stated identically for both arms before either arm's outcome under
it is known for certain — DIRECT's answer happens to be computable now only
because its probe already finished; TRAV's is not yet computable by
construction.

## 4. Shared budget

Unchanged in form from Amendment 05 §3:

```
update_count = max(plateau_DIRECT, plateau_TRAV)
```

read under §2's corrected definition rather than Amendment 05's. On present
evidence this is `max(7500, plateau_TRAV)`, with `plateau_TRAV` unresolved.

## 5. What this does not change

No decision rule, threshold, arm definition, metric, seed, or the gamma=0
negative control changes. This amendment changes only which checkpoint a
preregistered convergence test reads off an unchanged curve. Amendment 04 §5's
learner-gate thresholds, Amendment 04 §6's rejection of per-run early stopping,
Amendment 06's extension ceiling, and Amendment 07's void taxonomy and stop
clause all stand exactly as committed.

`training_authorized` in Phase 0, Phase 1, and Phase 2 artifacts remains
mechanically `false`, pinned by `tests/test_no_training_surface.py`.
