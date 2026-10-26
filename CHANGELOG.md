# Changelog

All notable changes to Gengar. The version is bumped on every commit: patch +1 for each change, minor +1 for a
bigger milestone. Turkish design notes: [`docs/tr/MIMARI.md`](docs/tr/MIMARI.md); English:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

| Version | Date | Summary |
|---|---|---|
| [0.0.4](#004---2026-10-27) | 2026-10-27 | `save_skill` removed (prefix 3,525 tokens); A/B benchmark: same pass rate, 10% faster; `save_answer` approval shows the real target |
| [0.0.3](#003---2026-10-26) | 2026-10-26 | Fixed prompt prefix 4,611 → 3,685 tokens (−20%), measured with the model's own template |
| [0.0.2](#002---2026-10-26) | 2026-10-26 | Thinking off by default; `auto` thinks only on the first step of hard requests and after a failure |
| [0.0.1](#001---2026-10-12--2026-10-26) | 2026-10-12 – 2026-10-26 | First version: agent, 21 tools, safety layers, memory, benchmark, training pipeline |

## [0.0.4] - 2026-10-27

### Highlights
- **The shorter prompt was measured with an A/B benchmark:** 135 tasks, same seed, thinking off, old prompt
  (v0.0.2, separate git worktree) vs new prompt. Passed 121 vs 119: within noise (21 tasks changed result,
  10 in each direction ±1). Total time 2,340 s → 2,113 s (−10%), tool calls 272 → 253.

### Added
- `evals/compare_runs.py`: compares two benchmark runs task by task (pass rate, time, tool usage per tool,
  tasks that changed result). A run split into several parts can be given as one glob.

### Removed
- `save_skill` tool. It was never called in 1,227 logged tasks; skills are still saved automatically by the
  learner (`memory/learn.py`). The fixed prefix drops from 3,685 to 3,525 tokens (−24% since v0.0.2).

### Fixed
- The `save_answer` confirmation summary shows where the file will really be written (`answer_target`), not
  the raw path from the model. For a folder path or "folder.md" next to a folder, the tool writes inside the
  folder; the benchmark's `task_only` rule read the raw path and denied these calls. `save_answer_md`:
  5/10 → 8/10.

### Notes
- With the shorter prompt the model chose Python more often than PowerShell (`run_python` 36 → 52,
  `run_powershell` 18 → 8) with no change in pass rate.
- New open issue: if Gengar is killed, `run_python` / `run_powershell` child processes keep running (one
  test script ran for 1.5 h). Candidate fix: a Windows Job Object.

## [0.0.3] - 2026-10-26

### Highlights
- **The fixed part of every request is 20% shorter:** system prompt plus tool definitions went from 4,611 to
  3,685 tokens. This prefix is re-read at the start of every new chat and makes up most of every training
  example.

### Changed
- System prompt regrouped and de-duplicated: 1,098 → 842 tokens. Choosing between tools stays in the system
  prompt; each rule is stated once (unit conversion, Recycle Bin deletion and "no unverified claims" each
  appeared twice).
- Tool descriptions shortened: 1,277 → 938 tokens. Usage hints already covered by the system prompt were
  removed from the tools. Hints added because of measured failures (the Turkish synonyms in `settings`, the
  `save_answer` wording) were kept.
- Self-explanatory parameter descriptions removed: 638 → 307 tokens.

### Added
- `evals/prefix_tokens.py`: measures the real prefix size with Ollama (`prompt_eval_count`). It reports the
  system prompt, tool text, parameter text and the tool "skeleton" separately.

### Notes
- The skeleton (tool and parameter names, types, the template's "how to call" header) is 1,598 tokens and does
  not shrink with shorter text. Going further means fewer tools or parameters.
- Not measured on the benchmark yet; a teacher run on dev/test is planned to check that tool choice did not
  get worse.

## [0.0.2] - 2026-10-26

### Highlights
- **Thinking mode is off by default.** On Qwen3.5 9B, thinking made the same task types 2–4× slower without
  reducing tool errors (11% vs 10%), and about half of the requests with thinking on came back empty.

### Changed
- `auto` thinking mode redesigned. It now thinks only on the first step of code, research, comparison or analysis
  requests, and on the single step after a tool failure. It no longer stays on for every step of a request.
- The "request longer than 160 characters" rule was removed; its length mostly came from file paths, and it
  caused 17 of 20 thinking triggers. Words that also appear in simple requests (test, error, report, plan,
  "write to file", why…) and the "several and/then" rule were removed as well.

### Notes
- The new `auto` mode is not measured yet; an `off` / `on` / `auto` comparison on the same tasks is planned.

## [0.0.1] - 2026-10-12 – 2026-10-26

First version, developed step by step. The full story and the reasoning behind each decision is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Highlights
- A Windows desktop assistant that runs a local model (Qwen3.5 9B via Ollama) or an API model.
- 21 tools: system info, apps, settings, UI automation, files, Recycle Bin delete/restore, `save_answer`,
  PowerShell, a Python sandbox, web search, official version lookup, memory.
- Safety in layers: risk levels, PowerShell classifier, permission modes, a guard for Gengar's own folder, undoable
  deletion, audit log.
- Benchmark with a dev/test split: test score 45/53 → 51/53 from system improvements alone.
- Distillation pipeline: 780 teacher tasks → 735 verified → 755 training examples; Kaggle LoRA notebook.

### Added (latest)
- Chat history: automatic saving, `/chats`, `/open`, `/pin`, `/unpin`, `/export`, `/new`.
- `save_answer` tool and a turn-hint router; on the test set 4/5 with hints, 0/5 without.
- No-tool and "save into folder" benchmark families; `bench2.py --no-hints` for ablations.

### Fixed (latest)
- `run_python`: modules in the working folder can be imported (23 of 26 import errors had the correct folder).
- `edit_file`: whitespace-tolerant matching with indentation taken from the file; copied `read_file` headers and
  line numbers are stripped; when nothing matches, the most similar lines are shown. Replaying real failures:
  7 of 11 now succeed.
- `edit_file` no longer silently converts Windows (CRLF) files to LF.
- Local model silence timeout raised to 600 s (Ollama buffers tool calls); context-limit truncation is recognised;
  a request is no longer dropped from the history after a model error.
