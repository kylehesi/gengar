# Real-requests benchmark

24 tasks adapted from the author's own Gengar requests in October 2026: short, slangy, misspelled and
multi-turn, the way the assistant is really used. The synthetic families in `evals/families/` are written in
clean sentences; this set checks whether the model also copes with real wording.

- Fixtures and automatic checks: [`evals/families/real.py`](../families/real.py)
- Tests for the checks (no model needed): [`tests/test_real_family.py`](../../tests/test_real_family.py)
- Design notes: [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md#real-requests-set-v008)

## Request texts are local

The request texts are personal, so they are **not in the repository**. They live in
`evals/real/private/prompts.json` (git-ignored), a JSON object that maps each family name in `real.py` to a
list of requests (several requests: one chat, turn by turn). `{root}` is replaced by the task folder. Without
this file the suite does not run.

## Running

```powershell
uv run python evals/bench2.py local35 --suite real --split all --list
uv run python evals/bench2.py local35 --suite real --split all --repeat 3
uv run python evals/bench2.py local35 --suite real --only real_cs2_launch   # launches the real game
```

A full run takes a long time and keeps the GPU busy, and app tasks open and close windows. Run it when
the computer is not in use.

## Rules

- Tune on `dev` only; `test` is for reporting.
- These trajectories are never training data.
- Nothing outside the task folder is written: writing tasks use `task_only` approval. App tasks close only
  the windows that opened during the task.
