# Changelog

All notable changes to Gengar. The version is bumped on every commit: patch +1 for each change, minor +1 for a
bigger milestone. Turkish design notes: [`docs/tr/MIMARI.md`](docs/tr/MIMARI.md); English:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

| Version | Date | Summary |
|---|---|---|
| [0.0.22](#0022---2026-11-12) | 2026-11-12 | The "announced but did not do it" nudge no longer misses answers that end with an emoji |
| [0.0.21](#0021---2026-11-12) | 2026-11-12 | Open issues: survey of the public datasets for the training mix (exact sets, licences, sizes, proposed samples); nothing downloaded |
| [0.0.20](#0020---2026-11-12) | 2026-11-12 | BFCL subset harness: general tool calling and forgetting, measured before and after training |
| [0.0.19](#0019---2026-11-12) | 2026-11-12 | Child processes of `run_python` and `run_powershell` end when Gengar ends (Windows Job Object) |
| [0.0.18](#0018---2026-11-12) | 2026-11-12 | `inspect` numbers toolbars before long lists; `cls`/`clear` clear the screen |
| [0.0.17](#0017---2026-11-12) | 2026-11-12 | Wikipedia opens again in `fetch_page`: Wikimedia sites get a User-Agent that names Gengar, as their policy asks |
| [0.0.16](#0016---2026-11-12) | 2026-11-12 | Gengar fixes from the first real-requests run: web search no longer fails on `wt.wikipedia.org`, `create_folders`, VS Code and browser names, `save_answer` keeps .txt |
| [0.0.15](#0015---2026-11-12) | 2026-11-12 | Benchmark fixes from the first real-requests run: deletion checks no longer need the Recycle Bin; the task-folder approval rule understands every way a path is written |
| [0.0.14](#0014---2026-11-11) | 2026-11-11 | Benchmark: `--repeat` no longer crashes between repeats (memory databases are closed); `--resume` continues a broken run |
| [0.0.13](#0013---2026-11-11) | 2026-11-11 | Open issues: plan items that slipped (BFCL, public data mix, Kaggle rerun, before/after measurement, 80-control limit) |
| [0.0.12](#0012---2026-11-07) | 2026-11-07 | Eyes for window work: `windows_ui inspect` returns a screenshot with each control's number drawn on it; window screenshots go to local models only |
| [0.0.11](#0011---2026-11-07) | 2026-11-07 | The model's eyes: `view_page` renders a web page in headless Edge and shows the model a screenshot; Gengar asks it to look before finishing |
| [0.0.10](#0010---2026-11-07) | 2026-11-07 | Web pages: broken images are reported to the model, real images via `web_search(images=true)`, design and PDF hints; 30 steps for window tasks |
| [0.0.9](#009---2026-11-07) | 2026-11-07 | "Allow for this session" now really stops the questions; critical actions are still asked; `windows_ui` finds windows reliably |
| [0.0.8](#008---2026-11-07) | 2026-11-07 | Real-requests benchmark: 24 tasks from real use, request texts kept local; `--repeat`, `--suite` |
| [0.0.7](#007---2026-10-29) | 2026-10-29 | A denied action is not asked again in the same request with a different tool |
| [0.0.6](#006---2026-10-29) | 2026-10-29 | Fewer unnecessary questions: a system prompt rule, replay-tested; same pass rate, 18% faster on the affected tasks |
| [0.0.5](#005---2026-10-29) | 2026-10-29 | "Announce and stop" fix: up to two nudges per turn, also after tool use; replay-tested on a real session |
| [0.0.4](#004---2026-10-27) | 2026-10-27 | `save_skill` removed (prefix 3,525 tokens); A/B benchmark: same pass rate, 10% faster; `save_answer` approval shows the real target |
| [0.0.3](#003---2026-10-26) | 2026-10-26 | Fixed prompt prefix 4,611 → 3,685 tokens (−20%), measured with the model's own template |
| [0.0.2](#002---2026-10-26) | 2026-10-26 | Thinking off by default; `auto` thinks only on the first step of hard requests and after a failure |
| [0.0.1](#001---2026-10-12--2026-10-26) | 2026-10-12 – 2026-10-26 | First version: agent, 21 tools, safety layers, memory, benchmark, training pipeline |

## [0.0.22] - 2026-11-12

### Fixed
- **The "do it now" nudge missed announcements that end with an emoji.** In the second real-requests run (dev
  task `real_vscode_slang`, 3/3 in the first run) the model answered "Tamam kardeşim, VS Code'ı açıp Python
  yapalım! 🐍💜" ("sure, let's open VS Code and do some Python") and called no tool. The detector checks only
  the last sentence, and it took "🐍💜" to be that sentence. Parts without letters no longer count as
  sentences.
- Checked on the 1,630 distinct stopping answers in the recorded trajectories: 3 decisions changed, all from
  "no" to "yes".
  - Two were real announcements: this one, and "I will save your birthday as 14 March 🎂", where nothing was
    saved.
  - One was conversational ("let's start with this! 🎉"). Without the emoji the old rule would have caught it
    too.

## [0.0.21] - 2026-11-12

### Changed
- Open issue 9 (public data in the training mix) now holds a survey taken from the Hugging Face API. Nothing
  was downloaded. For each dataset it lists:
  - the exact name, licence, size and format;
  - a proposed sample and how to get it.

  Without Aya the downloads come to about 200 MB. Toucan is sampled through the row API instead of downloading
  its 21.8 GB. Nemotron-Agentic (5.8 GB, no row API) is skipped for now. The Turkish part of Aya is gated and
  needs the user's Hugging Face login.
- Two steps were added to the plan: a BFCL leak check of the training questions before training, and a
  proposed ratio of about 30 % public data.

### Notes
- No code changes. Waiting for the user's approval before any download.

## [0.0.20] - 2026-11-12

### Added
- **[`evals/bfcl.py`](evals/bfcl.py): a subset of the Berkeley Function Calling Leaderboard** (open issue 8).
  Our own sets only measure Gengar's tools. Training on Gengar data alone risks catastrophic forgetting:
  better at our tasks, worse at general tool calling and at seeing that no tool fits. This subset measures
  that before and after training.
  - 260 questions in 7 categories:
    - one call (`simple_python`, `live_simple`);
    - choosing among functions (`multiple`);
    - several calls at once (`parallel`, `parallel_multiple`);
    - not calling a tool (`irrelevance`, `live_irrelevance`).
  - The data is downloaded from one pinned commit of the BFCL repository (Apache-2.0) into `data/bfcl/`
    (git-ignored). Questions are sampled with a fixed seed per category, so "before" and "after" see the same
    questions.
  - The model sees only each question's functions, not Gengar's prompt or tools, and thinking is off. Dotted
    names (`math.factorial`) are sent as `math_factorial` and mapped back.
  - The check is a simplified version of BFCL's AST check: function name, no unexpected parameters, required
    parameters present, and every value among the accepted ones (strings ignore case, spaces and
    punctuation; an integer counts as a float). Parallel calls may come in any order. Call accuracy and
    no-call accuracy are reported separately. Results go to `evals/results/*_bfcl_*.json`, trajectories to
    `data/bfcl/runs/`.
- `tests/test_bfcl.py` tests the schema conversion, the check and the run loop with a fake model. It also
  passes the ground truth of every question in these categories through the check. That test found
  `live_simple` answers with an empty accepted list (`[]`) for a parameter. Read literally, nothing could
  pass, so `[]` now means "omitted or an empty list".

### Notes
- Not run on the model yet: the GPU is busy with the second real-requests run. Next: the "before" numbers for
  `local35` (teacher) and `base4b` (untrained student).

## [0.0.19] - 2026-11-12

### Fixed
- **Scripts started by the model outlived Gengar** (open issue 6). The timeout kills the whole process tree,
  but only while Gengar runs. On 2026-10-26 a script with an endless loop ran for 1.5 hours after the
  benchmark was stopped and locked the benchmark folder. Closing the window had the same effect.
  - New [`tools/jobs.py`](src/gengar/tools/jobs.py): child processes go into a Windows Job Object with
    `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Windows closes the job when Gengar exits or dies, and its processes
    with it.
  - `run_python` uses a whole-tree job. The venv's `python.exe` is a launcher that starts the real
    interpreter as a child, so covering only the direct child would have missed the script.
  - `run_powershell` covers only `powershell.exe` itself (`SILENT_BREAKAWAY_OK`). Apps it opens with
    `Start-Process` stay open, so closing Gengar never closes a window the user asked for, with its unsaved
    work.
  - If a process cannot be added (very old Windows), the tool still runs; only this guarantee is missing.

### Added
- `tests/test_jobs.py` uses real processes (small sleeping Python processes, no windows). Closing a tree job
  ends the child and the grandchild. Closing a direct job ends the child, and the grandchild survives.
- Checked end to end by hand: a process started an endless loop through `jobs.adopt` and was then killed
  with `taskkill /F` (not the tree). The loop and its children were gone.

## [0.0.18] - 2026-11-12

### Fixed
- **`windows_ui inspect` gave no number to a toolbar under a long list** (open issue 11). It walked the UI
  tree in order and stopped at 80 controls. In File Explorer the file rows used all 80, so New, Sort and View
  could not be clicked by number, though the model saw them in the screenshot. A name lookup collected the
  same 80, so it could not find them either. Now:
  - `inspect` collects up to 300 controls (still within 4 s) and numbers 80, the same token cost as before;
  - buttons, menus, tabs and fields come first; list and tree rows keep at least 40 places and fill the rest;
  - tree order is kept;
  - the output says how many controls have no number;
  - a name lookup searches all collected controls; if a name matches several, the error marks the ones
    without a number.

### Added
- REPL: `cls` and `clear` typed without a slash clear the screen, and the chat goes on (open issue 12). They
  used to be sent to the model as a question. `/cls` does the same; `/clear` still starts a new chat. `exit`
  and `quit` without a slash quit.

### Notes
- Made while the second real-requests run was on the GPU. Only tests with fake windows were run, so that no
  test window would get mixed into the benchmark's app tasks.

## [0.0.17] - 2026-11-12

### Fixed
- **`fetch_page` got HTTP 403 from Wikipedia (tr and en) in 7 of 69 runs** of the first real-requests run.
  The model then turned to old or wrong sources and once made up facts (`real_fossil`). The request used a
  browser-like User-Agent with "Gengar/0.1" at the end. The Wikimedia User-Agent policy asks automated
  clients to name themselves with contact information, and Wikimedia refuses browser look-alikes. On
  Wikimedia sites (Wikipedia, Commons, Wikidata, Wiktionary and the other projects) `fetch_page` now sends
  `Gengar/<version> (https://github.com/kylehesi/gengar)`, as the Commons image search already did. Other
  sites are unchanged. Checked once by hand: the page that failed in the benchmark opens.

### Notes
- The 403s from Bulbapedia, Fandom and pokestats.gg (test tasks) are bot protection on those sites. They are
  left alone.

## [0.0.16] - 2026-11-12

Gengar bugs found in the dev failures of the first real-requests run (2026-11-11).

### Fixed
- **`web_search` failed in 7 of 69 runs** with a certificate error from `wt.wikipedia.org`.
  - ddgs's "auto" search asks Wikipedia first and takes the language from the region. With the default
    region `wt-wt` (no region) that is `wt.wikipedia.org`, which does not exist.
  - When no engine returned results, ddgs raised that last error and the whole search failed. Most engines
    return nothing to automated clients, and which ones work changes from minute to minute.
  - For `wt-wt` the search now uses all enabled engines except Wikipedia; Wikipedia pages still come back
    through the other engines.
- **The second search attempt never did anything.** It used the "bing" backend, but ddgs 9.x disabled Bing
  and silently falls back to "auto" for an unknown name. The same search ran twice. The second attempt now
  uses region `us-en`, and it also runs after "no results" (before, "no results" ended the search at once).
- **"vs code" and "vscode" did not find VS Code** (the Start menu name is "Visual Studio Code"). Both are
  aliases now. `apps installed` uses aliases too, so `installed vscode` finds it.

### Added
- **`create_folders`:** creates many folders (with parents) in one call. In "split it into month folders"
  the model had no folder tool. It wrote 12 empty, extensionless *files* with `write_file`, one call each,
  and hit the 15-step limit. Every path is shown in the approval prompt, and a path under Windows or
  Program Files makes the call critical, as with `write_file`. There are 19 tools now.
- **`write_file` refuses an empty file without an extension** (except dot names like `.gitkeep`). The error
  points to `create_folders`.
- **`apps open tarayıcı` / `browser`** opens the first installed browser, in order: Chrome, Edge, Firefox,
  Opera, Brave, Vivaldi. As an alias it would have matched Chrome and Edge together, and the answer
  "several apps match" makes the model ask. In the request "open chrome, or whatever there is, don't ask",
  it asked in 2 of 3 runs.

### Changed
- `save_answer` keeps a .txt extension when it redirects "X.txt" into the folder X (`X\kayit.txt`).
  Before, it always wrote `kayit.md`, though the user had asked for a Notepad file.

## [0.0.15] - 2026-11-12

### Highlights
- **First real-requests run (2026-11-11): 26/69 (38%), dev 10/33, test 16/36.** Reading every dev failure
  sorted them into model skill gaps, Gengar bugs (fixed in the next versions) and two **measurement bugs**,
  fixed here. Both made correct work fail, so the dev score was lower than the model's real result.

### Fixed
- `real_delete_turkish` and `real_recreate_english` could never pass. Their checks required the deleted
  folders to be in the Recycle Bin, but `delete_files` deletes task folders under `data/bench2` permanently,
  so benchmarks do not fill the bin. Two correct runs failed this way. The checks now require that
  `delete_files` succeeded (`require_tools`); in the user's own folders that tool always uses the Recycle Bin.
  Deleting with `Remove-Item` still fails.
- The `task_only` approval rule denied actions inside the task folder (6 runs). It looked for
  `<task folder>\` in the approval text, so it denied:
  - the task folder itself (`New-Item … real_hello_vscode_0`);
  - paths in Python source written with double backslashes (`"C:\\gengar\\…"`);
  - a folder kept in a variable and used later (`"$parent\X"`).

  After one denial Gengar refuses the rest of the request, so a single wrong denial ended the run. The new
  rule, `inside_task`, requires every absolute path in the approval text to be the task folder or inside it.
  URLs are removed first (`https://fonts…` looked like the drive path `s:\fonts`). A drive letter must follow
  a separator, so escapes in code (`"Plan:\n"`, `"İ:\n"`) are not paths. Paths next to the folder
  (`…\task_0.txt`), `..` and home-folder references (`$env:USERPROFILE`, `expanduser`, `~\`) are denied.
  Replaying all 302 tool calls of the run, 30 decisions changed, all from "no" to "yes", all inside the task
  folder; none changed the other way.
- `real_hello_vscode` asks for writing live in VS Code, but its approval denied `windows_ui`, so the model
  could not focus or type into the editor. `task_apps` now also allows `windows_ui` in VS Code windows (and
  the last-used window), and nowhere else.

### Changed
- Result files of the real-requests set (`evals/results/*_real_*.json`) no longer store the model's answers.
  The answers can repeat the user's own words, and result files go into the public repository. Full answers
  stay in the local trajectory (`data/trajectories`, git-ignored). The first run's result file was stored
  this way.

### Added
- Tests for `inside_task` (16 cases) and the `task_apps` window rule; the deletion tests check
  `require_tools` instead of the Recycle Bin.

## [0.0.14] - 2026-11-11

### Fixed
- `bench2 --repeat` crashed when the second repeat started. This is the first real-requests run (2026-11-11);
  the crash came after all 23 tasks of repeat 1. Each task opens its own memory database
  (`data/bench2/_hafiza/*.db`), and `run_task` never closed it. Windows does not delete open files, so
  rebuilding the task folders for the next repeat failed with `FileExistsError`. A single run never noticed,
  because the folders are only rebuilt at the start. `run_task` now closes the memory database of every agent it
  built.
- `build_tasks` gives a clear error naming the locked files if old files cannot be removed, instead of a
  `FileExistsError` or, worse, mixing old files into new tasks.

### Added
- `bench2 --resume FILE.jsonl` continues a broken run: task+repeat pairs already in the trajectory file are
  skipped and new runs are appended to the same file. The final summary covers old and new runs. Repeat 1 of
  the first real-requests run was kept this way, so its 23 tasks did not have to run again.

## [0.0.13] - 2026-11-11

### Changed
- `docs/OPEN_ISSUES.md` (and the Turkish `docs/tr/INCELENECEK.md`) now list plan items that were agreed but not
  done, in the agreed order of work. These are issues 7–12:
  - a before/after measurement for v0.0.8 – v0.0.12 (the first real-requests run is a baseline);
  - a BFCL subset to measure general tool calling and catastrophic forgetting before and after training;
  - mixing public datasets into the training data;
  - the Kaggle rerun;
  - the 80-control limit of `windows_ui inspect`;
  - small items (`cls`/`clear`, trying a code model).

### Notes
- No code changes.

## [0.0.12] - 2026-11-07

### Highlights
- **The model can see the windows it operates.** Until now `inspect` gave only a list of controls. A list cannot
  show icons without names, which of several "Play" buttons is which, or which tab is open, and window requests
  failed far more often than anything else (39% of `windows_ui` calls in the 2026-11-07 session). Now `inspect`
  also returns a screenshot of the window, with each control's `[number]` drawn on it (Set-of-Mark prompting).
  The model can match what it sees to the number it clicks, and look again after a click to check the result.

### Added
- `winapi.capture_window`: window screenshot without Pillow, entirely in ctypes and the standard library.
  - `PrintWindow` with `PW_RENDERFULLCONTENT`, so a window covered by another one is captured too. If that
    fails, the visible screen area is copied.
  - Halftone scaling with `StretchBlt` to at most 1280 px.
  - Boxes and number labels drawn with GDI. The labels sit at the top-right corner: in the first try they sat
    top-left and covered the start of the text ("6ownloads").
  - PNG encoded with `zlib`.
  - The thread is set to per-monitor DPI awareness, so control positions match the image at 125% scaling.
  - About 0.05 s for an Explorer window. A minimized window gets the list and "No screenshot: the window is
    minimized".
- `ToolResult.private`: window screenshots can show anything on the user's screen, so they are only sent to a
  local model. An API profile gets the text list and a note instead.
- `base.save_screen`: one place for saving screenshots (`data/screens/`, newest 40). Names are never reused, so a
  message in the history cannot end up pointing at a newer image.

### Fixed
- `test_registry_order_and_size` still expected 17 tools after `view_page` was added in 0.0.11. The test ran
  only now; the expected count is 18.

### Notes
- The screenshot showed a gap in `inspect`: it stops at 80 controls in tree order, so in Explorer the toolbar
  (New, Sort, View) gets no number. Not fixed yet.
- Not measured on the model yet (the GPU is busy).

## [0.0.11] - 2026-11-07

### Highlights
- **The model can see the pages it writes.** It used to write HTML and never see the result, then call a page with
  13 broken images and a template gradient "great". Qwen3.5 9B can read images, so the new `view_page` tool
  renders the page in a headless browser and puts the screenshot in front of the model, together with what went
  wrong while loading. If the model writes a web page and tries to finish without looking at it, Gengar asks it
  once to look and fix what it sees.

### Added
- `view_page` (`tools/pageview.py`): renders an `.html` file or an http(s) URL in headless Edge (throw-away
  profile, `--disable-gpu`) over the Chrome DevTools Protocol, using aiohttp's websocket client (no new package).
  - Desktop 1280 × 800 or phone 390 × 844; long pages come in parts of 1,800 px (`part=2`, …).
  - The JPEG is scaled in the browser: 960 × 1350 px on desktop, roughly 1,300 image tokens.
  - Reports images that do not load (local ones too), failed requests, JavaScript errors, and sideways
    scrolling with the first element that sticks out.
  - Screenshots are kept in `data/screens/` (the newest 40).
  - Risk: read; a local-network URL is critical, as with `fetch_page`.
  - On the graffiti page from 0.0.10: 1.9 s, 13 broken images found.
- `ToolResult`: a tool result that carries images. It is a `str` subclass, so logging and failure checks are
  unchanged.
- The conversation sends images to the model in a user message right after the tool results. OpenAI-style
  providers do not accept images inside a tool result, and tool results must follow the call without a gap.
  - LiteLLM converts this into Ollama's `images` field; checked on the request body.
  - Only the 2 newest images of the current turn are sent, and they count against the context budget.
  - The history (and so the training data) keeps only the file path.
- Profile option `vision = true` (local35, base4b, gemini). Profiles without it get the text diagnosis only,
  with a note that the screenshot was not attached.
- `[agent] review_pages = true`: a turn that wrote an `.html` file without looking at it gets one
  "look at it with view_page before you finish" message. It works like the check for unbacked "created"
  claims.

### Changed
- The web hint now says to look at the page with `view_page` before answering.
- The document hint says how to install the library: `packages=["fpdf2"]`. The old wording ("packages: fpdf2,
  …") read as if they were already installed. They are not, in the `run_python` sandbox or in Gengar's own
  environment.

### Notes
- Not measured on the model yet: the GPU is busy. The next night run should compare the web tasks of the
  real-requests set before and after.
- The tool schema adds about 200 tokens to the fixed prefix.

## [0.0.10] - 2026-11-07

### Highlights
- **The model now sees when its web page is broken.** Asked to turn a guide into a website "with real
  pictures, not AI slop", the model put 13 invented Unsplash URLs into the page (all 13 return 404), used the
  most common template gradient, and praised its "real photos". Nothing had told it the images were broken, and
  it had no way to find real ones. Now `write_file` / `edit_file` try every image of an `.html` file and report
  the ones that do not load (on that page: 13 of 13, in 1.6 s), and `web_search(images=true)` returns real,
  freely licensed images that load.

### Added
- `tools/pagecheck.py`: image check for written web pages (`<img src>` and CSS `url(...)`, remote URLs in
  parallel, local files next to the page). No warning when no address can be reached (offline). Local-network
  addresses are never requested.
- `web_search(images=true)`: free images from Wikimedia Commons with a working URL, size, licence and author.
  Words are matched in the file title (`intitle:`), image files only; a plain search for "graffiti" returned a
  pyramid first. Wikimedia requires a User-Agent with contact information, so it names the project's GitHub page.
- Turn hints for this turn only (not stored in the history, so not in training data):
  - a request to build or change a web page gets a short design brief: real images only; no purple gradients,
    glowing text, emoji icons or a card for everything; colours and a typeface that suit the topic;
  - a request for a PDF, Word, Excel or PowerPoint file gets "you can create it with `run_python` (fpdf2,
    python-docx, openpyxl, python-pptx)" and how to get Turkish characters into a PDF. The model had answered
    "a PDF cannot be created in a text-based system" and written a .txt file.

### Changed
- Step limit: a turn that uses `windows_ui` may take 30 steps instead of 15 (`[agent] ui_max_steps`). Three
  window requests had hit the limit; window work needs look → click → look again.
- System prompt: in Turkish "dosya" often means a folder (the user asked for a "dosya" named Graffiti with a
  PDF inside; the model wrote a file called Graffiti.txt).

### Fixed
- A REPL test ran a real PowerShell command, so writing it created an empty `C:\x\Plan` folder on this PC.
  The test now uses a command that writes nothing. An older test that checked the confirmation prompt never
  looked at the prompt text (the choices go to the input line, not the screen), so it could not fail; it now
  reads the input line.

### Notes
- Not measured on the benchmark yet (the GPU is busy). The real-requests set has web-page tasks
  (`real_hello_vscode`, `real_bio_page`, `real_deslop`); they now get the web hint.
- Fixed prefix: about +20 tokens (the "dosya" rule and the `images` parameter); not re-measured.
- What the system cannot fix is taste. Planned next step: let the model look at a screenshot of its own page
  (Qwen3.5 9B can read images) and fix what it sees.

## [0.0.9] - 2026-11-07

### Highlights
- **"Allow for this session" now does what it says.** In a real session the user allowed `windows_ui` for the
  session while the model focused a browser window, and was then asked again for every click and keystroke of
  the same tool (16 times). The grant only covered "change" actions; clicks, typing, commands and running
  Python were "system" actions, which were always asked and never offered the session option.
- **Window control fails much less often.** `windows_ui` was the weakest tool in real use: 39% of its calls failed
  (every other tool 0–10%). 11 of the 14 errors in the latest session would no longer occur.

### Changed
- New risk level `CRITICAL` for actions that are hard to undo: permanent deletion (`Remove-Item`, `rm`, `del`,
  `[IO.File]::Delete`, `shutil.rmtree`, `os.remove`), writing to Windows / Program Files / Gengar's own files,
  the registry, shutdown/restart, killing processes, forced app close, requests to the local network, and Python
  code that starts other programs (`subprocess`, `os.system`). These are asked **every time**.
- A session grant now covers a tool's `WRITE` and `SYSTEM` actions (clicks, commands, Python). The prompt says
  so: `[o]turum boyunca windows_ui için sorma`; after granting, Gengar says that critical actions will still be
  asked. `/izin` lists the grants, `/izin sıfırla` revokes them.
- `windows_ui` window matching:
  - Titles are normalised before matching: invisible characters are removed (Edge puts a zero-width space in
    "Microsoft Edge", so that name never matched) and all dash types become `-`.
  - Without `window`, the last-used window is taken (the model forgot it 6 times in one session).
  - A window is still found by a title it had earlier (the title changes when a page loads).
  - Common names map to processes (`edge` → `msedge.exe`), all words of the name may appear separately, and
    when several windows match, the last-used one wins.

### Added
- `evals/error_report.py`: tool error rates and the most frequent error patterns from the audit log (benchmark
  calls excluded), with `--since`, `--tool`, `--examples`. This report found the `windows_ui` problem.

### Notes
- Fixed prefix: the `window` parameter description grew by a few tokens ("omit to reuse the last window");
  not re-measured, since the GPU is busy.
- `test_recycle::test_delete_goes_to_recycle_bin_and_restores` failed once in a combined run and passed 3 of 3
  alone; it uses the real Recycle Bin.

## [0.0.8] - 2026-11-07

### Highlights
- **A benchmark built from real use.** 24 tasks adapted from the author's own October requests: short, slangy,
  misspelled, multi-turn ("you didn't open it.", "what about estoya?"). Each task recreates the situation where
  Gengar failed or nearly failed (apps not opened, an unnecessary question, a typo not understood, a long
  answer not saved, a config value changed in the wrong file, deleting in the wrong folder) and checks the
  outcome automatically. Not run yet; the first run (3 repeats) is planned for when the GPU is free.

### Added
- `evals/families/real.py`: fixtures and checks for the 24 tasks (apps, folders, saving, information, ideas,
  web page). App tasks look only at windows opened during the task and close only those (`AppWatch`). Writing
  tasks are limited to the task folder. Launching the real game is opt-in. Split by hand, balanced per group:
  11 dev, 12 test.
- The request texts are **not** in the repository: they stay in `evals/real/private/prompts.json`
  (git-ignored). `evals/real/README.md` describes the format.
- `bench2.py --suite real` selects the set; `--repeat N` runs every task N times, rebuilding its files each time,
  and prints how many repeats each task passed. `compare_runs.py` keeps repeats apart.
- Framework: `Task.setup` (runs just before the task), `Task.multi_answer` (the check sees every turn's answer),
  `opt_in` tasks, fixed `Family.split`, and `task_apps` approval (opening apps allowed, writes only in the task
  folder).
- `tests/test_real_family.py`: every check is tested against hand-made right and wrong outcomes, without a model.

### Notes
- These tests found a measurement bug before the first run: on Windows `write_text` writes CRLF line endings,
  so the check saw an untouched config file as "changed".
- The set is measurement only: it is too small to train on, and its trajectories are never exported as training
  data (`export_sft` reads only `purpose=train`).

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
