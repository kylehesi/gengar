# Changelog

All notable changes to Gengar. The version is bumped on every commit: patch +1 for each change, minor +1 for a
bigger milestone. Turkish design notes: [`docs/tr/MIMARI.md`](docs/tr/MIMARI.md); English:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

| Version | Date | Summary |
|---|---|---|
| [0.0.7](#007---2026-10-29) | 2026-10-29 | A denied action is not asked again in the same request with a different tool |
| [0.0.6](#006---2026-10-29) | 2026-10-29 | Fewer unnecessary questions: a system prompt rule, replay-tested; same pass rate, 18% faster on the affected tasks |
| [0.0.5](#005---2026-10-29) | 2026-10-29 | "Announce and stop" fix: up to two nudges per turn, also after tool use; replay-tested on a real session |
| [0.0.4](#004---2026-10-27) | 2026-10-27 | `save_skill` removed (prefix 3,525 tokens); A/B benchmark: same pass rate, 10% faster; `save_answer` approval shows the real target |
| [0.0.3](#003---2026-10-26) | 2026-10-26 | Fixed prompt prefix 4,611 → 3,685 tokens (−20%), measured with the model's own template |
| [0.0.2](#002---2026-10-26) | 2026-10-26 | Thinking off by default; `auto` thinks only on the first step of hard requests and after a failure |
| [0.0.1](#001---2026-10-12--2026-10-26) | 2026-10-12 – 2026-10-26 | First version: agent, 21 tools, safety layers, memory, benchmark, training pipeline |

## [0.0.7] - 2026-10-29

### Fixed
- **A denied action is no longer asked again in another form.** After the user denied a deletion, the model
  often tried the same deletion with a different tool (`Remove-Item` denied → `delete_files`, 5 of 6 tries when
  a session was replayed), and the user had to deny it again. The repeat guard only stops identical calls. Now,
  once the user denies something in a request, any new call in that request that needs approval is refused
  without asking, and the model is told to say what was not done and ask how to proceed. Reads still run;
  tools the user allowed for the session still run; the next request starts fresh.

### Notes
- Benchmark on `safety_denied`, `safety_injection`, `file_delete`: 6/7. The new rule never fired there (with the
  current tools the model stops after the first denial), so it is a safety net for the replayed case.

## [0.0.6] - 2026-10-29

### Highlights
- **Gengar asks fewer unnecessary questions.** For "create a folder on the Desktop and split it by month" the
  model used to ask "What should the folder be called?" without doing anything. Replaying that request: it now
  starts working 6 of 6 times (before: 3 of 6).

### Changed
- System prompt rule: details with a sensible default (name, format, location) are chosen by the model, which
  then says what it chose; the requested action is done instead of asking "shall I?", since risky actions get
  an approval prompt anyway. Questions are kept for requests that could mean clearly different things.
  Prefix: 3,525 → 3,623 tokens.
- The claim check also recognises the third-person forms the model sometimes uses about itself ("Metni
  klasöre kaydetti."), but not look-alikes such as "kesildi".

### Notes
- Necessary questions are kept: with two matching folders and a delete request, the model still asks which
  one 6 of 6 times, with the old and the new prompt.
- End-to-end benchmark on the affected families (38 tasks): 32/38 before and after, 623 s → 508 s (−18%),
  44 → 33 tool calls. No extra tool use in tasks that need none.
- Not fixed on purpose: "…I'll save it. Ready?" appeared in one task among 1,766 logged stopping points.
- Found while testing: after the user denies a deletion, the model often retries it with a different tool
  (`Remove-Item` denied → `delete_files`), and the user is asked again. Fixed in the next version.
- New open issue: the model sometimes writes to `Yapilacaklar` instead of the existing `Yapılacaklar` folder.

## [0.0.5] - 2026-10-29

### Highlights
- **The model no longer leaves the user with an announced but undone step as easily.** In a real session it
  said "I'll add the month subfolders:" and stopped three times; the user had to ask "so add them?". Replaying
  that session up to each stop, the nudge now makes the model call a tool 6 of 6 times.

### Changed
- The "do it now" nudge can fire twice per turn instead of once. The model often started working after the
  first nudge, then announced and stopped again on the next step.
- Announcements are also caught after tools were used ("Klasör oluşturuldu. Şimdi alt klasörleri ekleyeceğim:").
- The detector looks at the last sentence only and knows more Turkish forms: "kontrol edeyim", "bakalım"
  (-eyim/-ayım, -elim/-alım). Negatives ("yapmayacağım"), offers ("isterseniz yapayım") and requests for
  information ("bana söyle, kaydedeyim") are not announcements. Tried on 1,644 logged stopping points before
  the code changed: 13 matches, 12 real announcements.
- If the model still announces and stops after two nudges, the answer ends with a note that the task may not
  be finished.
- Nudges and unfinished turns are recorded in the audit log (`nudge`, `unfinished`), so real use can be
  measured.

### Notes
- A "stronger" second nudge ("you announced again; if you cannot do it, tell the user") was tested and
  rejected: 3/6 tool calls versus 6/6 for repeating the same nudge. The model took the way out it was offered.
- Targeted benchmark (`memory_fact`, `web_version`, `file_rename_ext`, `file_folder_size`): 9/12; the nudge
  fired once, in a passing task. The three failures are unrelated model errors.
- Docs: the safeguard table now names `_think_next_step` (it still said `_escalate`).

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
