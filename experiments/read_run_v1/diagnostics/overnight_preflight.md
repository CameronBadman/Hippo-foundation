# Overnight preflight — recorded before any work

Recorded 2026-09-02, at T+0 of the overnight task.

## The two running processes (NOT killed)

| PID | elapsed | what it is |
|---|---|---|
| 263203 | 12:40 | `tail -F` on probe-TRAV-ext.{out,err}, probe-DIRECT.out, probe-timing.log |
| 832968 | 08:03 | `tail -F` on probe-TRAV-checkpoint.{out,err}, probe-timing.log |

Both are **read-only log followers**, not compute. They consume no GPU and no
measurable CPU. They are left running. No new work needs to be scheduled around
them: the machine is otherwise idle.

## What they were watching has already finished

    2026-09-01T11:03:36Z end TRAV-ext        exit=0 seconds=26024
    2026-09-01T15:44:33Z end TRAV-checkpoint exit=0 seconds=26328

Both PID files under `private/read-run-v1/diagnostics/` are **stale**
(70884, 264080 — neither process exists). They are left in place as the record
of what ran; `stop_run.sh` refuses non-read-run PIDs so a stale file is inert.

## Machine state at T+0

| | |
|---|---|
| HEAD | `1f70055` (γ=0 diagnostic CLEAN) |
| tree | clean except untracked `CLAUDE.md`, `debug/` |
| disk | 301 G free of 807 G (61% used) |
| GPU | RTX 5070 Ti, 3% util, 1268/16303 MiB, 40 W, 48 °C |
| load | 0.46 over 32 cores |

Full GPU and CPU are available for the night.
