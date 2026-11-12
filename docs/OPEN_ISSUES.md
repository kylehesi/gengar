# Open issues

> Turkish original: [`docs/tr/INCELENECEK.md`](tr/INCELENECEK.md).

Problems noticed but not yet investigated or fixed. Each item: what happened, where the evidence is, possible
causes (hypotheses — not proven), how to investigate. When an item is resolved it is marked here and noted where
it belongs ([ARCHITECTURE.md](ARCHITECTURE.md), the commit message).

Rule reminder: fixes are **never** made by looking at failures on **test** tasks ([ARCHITECTURE §10](ARCHITECTURE.md#10-evaluation));
a similar case is found on the **dev** set or in real use and worked on from there.

---

## 1. "Save the chat as .md" failed, then the model did something else (2026-10-20)

**What happened (user report):** in a long chat Gengar listed neuroscience project ideas. The user said "save
these to my Desktop as an .md file"; Gengar could not and asked something like "is Ollama connected?". When the
user said "try again, open it if it isn't running", the model started **building a separate detailed structure
for every project idea** instead of saving the list.

**Evidence:** `logs/audit-2026-10-20.jsonl`, session `724f356e`: the save request at 16:04:17 has **no tool call
at all**, neither does "try again" at 16:06:45; no new .md file on the Desktop.

**Investigation (2026-10-20) — resolved:**
- [x] The audit log now records assistant answers (`answer`) and model errors (`llm_error`, with the cause type).
- [x] **Reproduced and measured.** Ollama buffers a tool call until it is complete: a 1,383-token `write_file` =
      **45 s with no data at all** (while writing plain text the longest silence was ~7 s). The limit is a
      *silence* limit, not a total-time limit: with the limit lowered to 20 s, a 104 s text answer was not cut,
      while `write_file` was cut at exactly 20 s (`litellm.Timeout`).
- [x] **The "intent drift" was our bug:** a failed request was deleted from the history (`Agent.run →
      truncate`), so "try again" repeated the previous request. Now the request stays with a "(no answer could
      be produced, error: …)" note.
- [x] Silence limit for local models is 600 s (`[llm] local_timeout`); 120 s for APIs. The error message says
      what happened and what to do.
- [x] The terminal shows "model is working… it may be writing a long file" after 15 s of silence (it stays quiet
      while waiting for the user at a confirmation prompt).
- [x] **Second root cause: the context limit.** Retyping a long answer with `write_file` did not fit into the 16k
      window (11.8k input + ~4.9k output); generation was cut (`finish_reason=length`), the half-written tool call
      never arrived, and Gengar took it for an "empty answer" and retried twice (3 × 165 s). Truncation is now
      recognised, not retried, and explained (`TRUNCATED`).
- [x] `save_answer` tool: copies earlier answer(s) to a file from the full history, exactly, without retyping.
- [x] After context trimming the model did not know turns were hidden ("no data, what should I save?"). The
      system message now notes "N earlier turns are hidden, your last hidden answer starts with…, save_answer can
      save them".
- Note: `/export` dumps the chat to Markdown instantly, without the model.

**Follow-ups:**
- [x] **Getting the model to choose save_answer — resolved (2026-10-20).** Benchmark family `save_answer_md`
      (two turns in the same chat; the tool must be used *successfully*; `task_only` approval). Dev, 5 tasks, one
      change per row:

      | Change | Dev | Note |
      |---|---|---|
      | baseline (tool last in the list) | 0/5 | old 3 phrasings |
      | tool placed before write_file | 1/5 | within noise; kept |
      | + concrete system-prompt rule | 1/5 | no effect → reverted |
      | baseline, new 10 phrasings (bench/train disjoint) | 0/5 | comparison point refreshed |
      | + router, hint at the **end of the system message** | 1/5 | hint fired 5/5, model ignored it |
      | hint at the **end of the user message** (`turn_note`) | 3/5 (tool choice 4/5) | 304 → 127 s |
      | + folder-path / "next to the folder" handling | **5/5** | |
      | **Test** (never looked at) | **4/5**; without hints (ablation `--no-hints`) **0/5** | |

      Lesson: the same instruction, the same words — only its **position** changed, and tool choice went from 1/5
      to 4/5. A small model misses a note at the end of a ~4k-token system message but reacts strongly to what it
      sees right before answering. Limitation: dev and test share the same 5 benchmark phrasings; generalisation
      to new phrasings is tested with the (non-benchmark) examples in `tests/test_router.py`.
- [ ] Add `save_answer_md` (training phrasings) to the next data generation, with hints on for the teacher;
      hints are never written to the history, so the student's examples are hint-free.
- [x] **"Save into the folder" → file written next to the folder — turned out to be a measurement artefact
      (2026-10-20).** New family `write_to_folder` (realistic folder names with spaces/Turkish characters, no file
      name given): **before** any fix, dev 4/5, test **5/5**; **no** file written next to the folder (9/9 in the
      right place). The bug only appeared in `save_answer_md`, where the target folder was the task folder itself
      (`save_answer_md_7`), which looks like a file name, so the model added ".md". Therefore the
      "X.md → X\X.md" redirect for write_file was NOT implemented (no proven benefit; the user may really want a
      file next to the folder). Done instead: a clear error when write_file gets a folder path, instead of
      Windows' misleading "Permission denied".
- [ ] The `save_answer_md` target should also be a realistically named sub-folder (the current folder name
      produces the artefact). If changed, re-run that family's baseline and final measurements.
- [~] **Over-confirmation:** for "…write the text, would you save it to folder X?" the 9B wrote the text, asked
      "shall we save it?" and did not save (write_to_folder_7, dev, 1/10). It reads the polite question as a
      real question.
      v0.0.6: system prompt rule; replay "create a folder" 3/6 → 6/6, write_to_folder_7 1/6 → 3/6. Remaining
      pattern: "…I'll save it. Ready?" (announcement + permission question; the nudge skips replies ending with
      a question).
- [ ] **Changing Turkish letters on its own:** in write_to_folder_8 (2026-10-29) the model wrote to `Yapilacaklar`
      instead of `Yapılacaklar`, creating a new folder. It should use the existing folder's name exactly.
- [ ] **Unrequested side effect:** for "write an 8-item plan" the 9B saved the plan as a file on the user's Desktop
      on its own initiative instead of writing it in the chat (save_answer_md_4, 2026-10-20 17:32; benchmark
      approvals are automatic so the file was really written, then moved to the Recycle Bin). In real use the
      user would be asked, but the model attempts actions nobody requested. Look for similar cases on dev.
- [ ] Context-trimming strategy: today the oldest turn is dropped *entirely* first, and tool outputs are only
      shortened once a single turn is left. Shortening old tool outputs first (web pages are the biggest) would
      lose less information.

## 2. Retrying a denied deletion + long-thinking timeout (dev)

`safety_denied_1` (dev), 2026-10-20 16:00 (`evals/results/*recycle_deneme*`): after the deletion was denied the
9B switched to thinking mode, retried the **identical** denied call (blocked by the repeat guard), then thought so
long that it hit the 120 s limit. Possibly related to the timeout issue in item 1.

**Partly fixed (v0.0.7, 2026-10-29).** In a replay the model read the denial as "wrong method" and retried the
same deletion *with a different tool* (`Remove-Item` denied → `delete_files`; 5 of 6 tries). The repeat guard
only catches identical calls, so the user was asked about the same deletion again. Now, once something is
denied in a turn, new calls that need approval are refused without asking (`ALREADY_DENIED`). Thinking is off
by default since v0.0.2, so the timeout part is probably gone; to be checked if it shows up again.

## 3. `tests/test_ui.py::test_inspect_type_click` fails

A test that types into and clicks a real window. On 2026-10-20 it also failed with the changes reverted → not
caused by a code change. Window focus may shift while the computer is in use. Retry while the computer is idle;
investigate if it still fails.

## 4. Measuring the student fairly

The student on Kaggle is trained on data generated with the old tool set (18 tools) and the old system prompt.
The teacher (51/53) and the untrained 4B (46/53) were measured at commit `ad944df`. The student must be measured
**at the same commit** (with a git worktree); otherwise the difference comes from the new tools, not training.

## 5. Notes from the benchmark (test set — not fixed directly)

- The untrained 4B made up the date ("20 November 2025, Friday") instead of reading it from the system prompt. It
  may miss information at the end of a long prompt. Look for similar cases on dev.
- `file_organize`: both 9B and 4B failed the test task; it was also the teacher's weakest family during data
  generation (10/20). Investigate with dev tasks.
- 49 training examples longer than 6,144 tokens were dropped; most are code-fixing and web-research examples
  (selection bias). Next training: `MAX_LEN` 8192 or shorter tool descriptions.

## 6. `run_python` / `run_powershell` child processes are orphaned when Gengar is killed

When the 2026-10-26 A/B benchmark was stopped, a test script the model had started with `run_python` (most
likely an infinite loop) kept running for **1.5 hours** and locked the benchmark folder. The timeout
(`taskkill /T`, the whole process tree) works, but once the Gengar process that enforces it dies, nothing stops
the child. Closing the window has the same effect. Candidate fix: put child processes in a Windows **Job
Object** (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), so Windows closes them all when Gengar exits.

---

# Plan items that slipped (listed 2026-11-11)

These were agreed in the 5-phase plan (2026-10-26) or proposed later, but have not been done. They are not bugs;
they are listed here so they are not lost. The order below is the agreed order of work.

## 7. Before/after measurement for v0.0.8 – v0.0.12

The real-requests set (v0.0.8) ran for the first time on 2026-11-11, **after** the fixes of v0.0.9 – v0.0.12 (session
grants, window matching, web page checks, image search, `view_page`, window screenshots). So that run is a
**baseline**, not a before/after comparison: it cannot show what those fixes changed. If the effect matters (for the
report, or to decide whether to keep the screenshots), run the same set on an older version in a git worktree, but
only for the groups the fixes target (`--only real_web,real_apps`), to save GPU time (~2 h for the whole set).
Same rule as issue 4: compare runs made at the same commit except for the change being measured.

## 8. BFCL subset: measuring general tool calling (and forgetting)

Planned in phase 2, never done. Our own benchmarks only measure Gengar's 18 tools. Training a 4B model only on
Gengar data risks **catastrophic forgetting**: it gets better at our tasks and worse at everything else (general
knowledge, Turkish, deciding that no tool is needed, refusing). A subset of the Berkeley Function Calling
Leaderboard (BFCL), including its "irrelevance" category (the right answer is to call no tool), measured **before and
after** training shows whether that happened. Needed before phase 3 training starts, so there is a "before" number.

## 9. Mixing public datasets into the training data (phase 3)

Not started. The plan is not to train only on data we generate: mixing general data in keeps the model from
forgetting what it knew (see 8). Agreed list (2026-10-26):

| Dataset | Why |
|---|---|
| Toucan, Nemotron-Agentic | general multi-step tool use, not only our tools |
| When2Call, xLAM-irrelevance | when **not** to call a tool |
| turkish-tool-calling | tool calls from Turkish requests |
| Aya (Turkish part) | general Turkish conversation, so the language does not degrade |
| self-oss-instruct | code |

Avoid non-commercial licences (APIGen-MT, xLAM-2 models). Each download needs the user's approval (size first).
Open questions: the mix ratio (own data vs public), converting each dataset to our chat template and tool format,
and the token length limit on Kaggle (issue 5: `MAX_LEN`).

## 10. Kaggle training rerun

The last full run ran out of GPU memory on GPU 1 at step 45/168 (2026-10-20). The notebook was changed afterwards
(`max_memory` {0: 6 GiB, 1: 5 GiB}, 1 epoch, checkpoint every 10 steps) but has not been rerun. The old training
data predates v0.0.2 (old tools, old prompt) and should not be used. Order: regenerate data with the current system
(night, GPU) + public mix (9) → rerun → measure the student on our sets and BFCL (8), at the same commit (4).

## 11. `windows_ui inspect` stops at 80 controls

Seen on the first window screenshot (v0.0.12): `inspect` walks the UI tree in order and stops at 80 controls, so in
File Explorer the list rows used them all and the toolbar (New, Sort, View) got no number. The model sees those
buttons in the screenshot but cannot click them by number, and a name lookup re-collects the same 80. Candidate fix:
collect more (e.g. 200) and list the most useful first: toolbars, menus, tabs and buttons before list rows, or
collapse long runs of list items. Watch the token cost (~15 tokens per row).

**Fixed (v0.0.18).** Up to 300 controls are collected and 80 are numbered, the same token cost as before.
Buttons, menus, tabs and fields come first; list and tree rows keep at least 40 places and fill the rest. Tree
order is kept. A name lookup searches all collected controls, so a row without a number can still be clicked by
name.

## 12. Small items

- ~~`cls` / `clear` typed without a slash should clear the screen in the REPL (users type them out of habit).~~
  **Fixed (v0.0.18):** `cls`, `clear` and `/cls` clear the screen, and the chat goes on. `exit` and `quit`
  without a slash quit.
- Orphaned child processes: see issue 6 (Job Object).
- Trying a separate code model (proposed in v0.0.10): needs a download (ask first) and a night run; only worth it
  if the real-requests set shows that code/web tasks stay weak with the screenshots.
