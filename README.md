# Gengar

**A Windows desktop assistant that actually does things on your computer — powered by a small local language
model.**

Gengar runs a local LLM (Qwen3.5 9B via [Ollama](https://ollama.com)) or a cloud model through an API. Instead of
guessing, it uses tools: it reads system information, opens and closes apps, changes settings, reads and writes
files, runs PowerShell and Python, searches the web for things it doesn't know and remembers what it learns.
Every action goes through a risk-based permission layer and is written to an audit log.

> Final-year capstone project (Information Systems and Technologies). Work in progress — it is being developed
> step by step, and every step is measured. The interface and the assistant's replies are in Turkish; the
> documentation is in English (Turkish originals in [`docs/tr/`](docs/tr/)).

## Why it's interesting

The core idea: **make a small, free model strong through the system around it.** A 4–9B model on an 8 GB laptop
GPU makes mistakes a large cloud model doesn't — it stops before acting, gives empty answers, repeats failing
commands, claims work it didn't do. Gengar's agent loop has a targeted safeguard for each of these, and every
safeguard came from a failure that was observed and then measured.

| | |
|---|---|
| **Runs locally** | Qwen3.5 9B on an RTX 4060 Laptop (8 GB): 16k context, ~32 tokens/s, no internet or API key needed |
| **21 tools** | system info, apps, settings, UI automation, files, Recycle Bin delete/restore, PowerShell, Python sandbox, web search, official version lookup, memory |
| **Safety in layers** | risk levels → PowerShell command classifier → permission modes → a guard that protects Gengar's own folder → undoable deletion → audit log |
| **Learns** | remembers facts about the user and saves reusable "skills" after solving hard tasks (semantic search with bge-m3) |
| **Measured** | an automatically verified benchmark (100+ tasks, dev/test split) drives every change |
| **Distillation** | the 9B teacher generates verified training data to fine-tune a faster 4B student (LoRA on Kaggle) |

## Results so far

| Benchmark | Score |
|---|---|
| v1 (24 tasks) — Qwen3 8B → Qwen3.5 9B + 16k context | 21/24 → **24/24**, 766 s → 358 s |
| v2 test (53 never-tuned-on tasks) — Qwen3.5 9B, before → after the dev iterations | 45/53 → **51/53** |
| v2 test — untrained Qwen3.5 4B | 46/53, **1.6× faster** than 9B |
| "Save your earlier answer to a file" — with / without the turn hint (ablation) | **4/5** / 0/5 |

Details, and what each number taught us: [docs/ARCHITECTURE.md §10](docs/ARCHITECTURE.md#10-evaluation).

## How it was built

Gengar grew in small, runnable steps. Each step was tested, measured, and committed before the next one.

1. **Foundations (phases 0–2).** Project skeleton and `gengar doctor`; an LLM layer that talks to local and API
   models through one interface (LiteLLM); the agent loop with a permission system and an audit log.
2. **Windows and research tools (phases 3–4).** Dedicated tools for system info, apps, settings and UI automation
   replaced free-form PowerShell — the 8B model had been misreading command output and inventing numbers. Web
   search and page reading with relevance ranking (BM25).
3. **Code agent and memory (phases 5–6).** Python in an isolated virtual environment, a write → run → fix loop;
   long-term memory and a Voyager-style skill library with a measured similarity threshold.
4. **Measuring instead of guessing.** A 24-task benchmark, then a 103-task benchmark with a dev/test split. Model
   choice (Qwen3 8B → Qwen3.5 9B), a 16k context via KV-cache compression, and safeguards for the failure modes
   the benchmark exposed. Fixes made on dev raised the untouched test score from 45/53 to 51/53.
5. **Distillation pipeline.** The teacher solved 780 generated tasks overnight; 735 were verified and became 755
   training examples. A Kaggle notebook fine-tunes Qwen3.5 4B with 16-bit LoRA. (The first full run ran out of GPU
   memory; the notebook has been fixed and the run is pending.)
6. **Real-use fixes.** Each problem found while using Gengar was reproduced, measured, and then fixed:
   - deletions go to the Recycle Bin and can be restored;
   - chats are saved automatically and can be reopened;
   - long answers can be saved to a file without the model retyping them.
   - An incident where a long save timed out was traced to three causes: a silence timeout, a context-limit
     truncation, and a request being dropped from the history after an error.

The full story, with the reasoning behind every design decision, is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Known open problems: [docs/OPEN_ISSUES.md](docs/OPEN_ISSUES.md).

## Quick start (Windows)

Requirements: [uv](https://docs.astral.sh/uv/), Python 3.12+, [Ollama](https://ollama.com), ~8 GB of VRAM for the
default model.

```powershell
winget install astral-sh.uv
winget install Python.Python.3.12
winget install Ollama.Ollama
ollama pull qwen3.5:9b
ollama pull bge-m3
```

For a 16k context on 8 GB of VRAM, set these user environment variables and restart Ollama (otherwise use
`num_ctx = 8192` in `config/settings.toml`): `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`.

In the project folder:

```powershell
uv sync
copy .env.example .env      # optional: API keys for cloud profiles
uv run gengar doctor        # checks that everything is ready
uv run gengar               # start chatting (or double-click gengar.cmd)
```

Example requests (in Turkish or English): "How much free space is on C:?", "Open Notepad", "Set the volume to
30", "Switch to dark mode", "What's the latest Python version?", "Read this file and summarise it".

### Chat commands

| Command | |
|---|---|
| `/model [name]` | list profiles / switch model (local or API) |
| `/think on\|off\|auto` | thinking mode |
| `/mode normal\|strict\|trust` | permission mode |
| `/memory`, `/remember`, `/skills`, `/skill`, `/learn`, `/forget` | memory and skills |
| `/chats`, `/open <no>`, `/pin <no>`, `/unpin <no>`, `/export [no]`, `/new` | chat history |
| `/help`, `/exit` | |

Confirmation prompts: `e` yes, `h` no, `o` allow for this session. Every action is logged to
`logs/audit-YYYY-MM-DD.jsonl`.

## Project structure

| Path | Contents |
|---|---|
| `src/gengar/core/` | agent loop, conversation, permissions, audit log, routers, chat history |
| `src/gengar/llm/` | model client (local and API through LiteLLM) |
| `src/gengar/tools/` | tools and the guard |
| `src/gengar/memory/` | facts, skills, embeddings, automatic learning |
| `src/gengar/ui/` | terminal UI |
| `config/` | settings and the system prompt |
| `evals/` | benchmark, task families, training-data generation and export |
| `training/` | Kaggle fine-tuning notebook and Ollama import ([training/README.md](training/README.md)) |
| `tests/` | 314 automated tests (`uv run pytest`) |
| `docs/` | [architecture](docs/ARCHITECTURE.md), [open issues](docs/OPEN_ISSUES.md), [future plans](docs/FUTURE.md) |

## Roadmap

- [x] Phase 0–6: setup, LLM layer, agent loop, Windows tools, research, code agent, memory and learning
- [x] Benchmark with a dev/test split; teacher data generation
- [ ] Train the 4B student and compare it with the teacher and the untrained 4B
- [ ] Shorten the ~5,000-token fixed prompt (faster inference and training)
- [ ] Hybrid mode: local first, API fallback with a budget limit ([docs/FUTURE.md](docs/FUTURE.md))
- [ ] Menu UI (postponed; the terminal UI is used for now)

## License

[MIT](LICENSE) © 2026 Emir
