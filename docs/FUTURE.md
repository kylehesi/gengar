# Planned for later

> Turkish original: [`docs/tr/ILERIDE.md`](tr/ILERIDE.md).

Features postponed for now because there is no budget. To be discussed again before deciding.

## 1. Hybrid mode (local model + API fallback)

**Idea:** tasks always start with the local model (Qwen3.5 9B); only when the local model gets stuck is the task
handed over to a strong API model. This keeps the cost very low.

**Hand-over conditions (proposal):**
- The local model was stopped for repeating the same failing step (repeat guard)
- The step limit was reached
- The empty-answer safeguard fired and still no answer came
- The user explicitly asked with an `/api` command
- (Optional) The request was classified as "complex" (`core/router.py`)

**Required safeguards:**
- **Budget limit:** a monthly maximum in `settings.toml` (e.g. `$2`). Gengar computes the cost of each request from
  the token counts LiteLLM returns, warns when close to the limit and stops when it is exceeded.
- **Privacy consent:** when handing a task to an API, warn "this conversation (including files read) will be sent
  to this provider" and ask for consent; can be remembered for the session.
- Handed-over tasks are logged in the audit log with provider, tokens and cost.

**Existing infrastructure:** LiteLLM profiles, retries, 429 back-off and `rpm` pacing already exist
(`llm/client.py`). Missing: the hand-over logic, the cost counter, the privacy consent.

## 2. Choosing an API (comparison of 2026-10-13)

Assumption: an average Gengar task ≈ 20,000 input + 1,000 output tokens (tool definitions, system prompt, 3–5
requests). Prices change; check again before deciding.

| | Claude Haiku 5.5 | DeepSeek V4 Flash | OpenRouter (free) | Gemini (free) |
|---|---|---|---|---|
| Price (per 1M tokens in/out) | $0.10 / $0.50 | ~$0.14 / $0.28 (sources disagree) | $0 | $0 |
| Per task | ~$0.0025 | ~$0.003 | $0 | $0 |
| 1,000 tasks | ~$2.5 | ~$3 | — | — |
| Limits | practically none | practically none | 50 requests/day (~15 tasks); 1,000 with a one-off $10 top-up | 5 requests/minute, frequent 503s |
| Reliability | high | medium-high | low (models change without notice) | low (all requests returned 503 on 2026-10-13) |
| Data privacy | API data is not used for training by default | data stored in China (may need justification under Turkish data-protection law) | some free providers may log | free-tier content may be used for product development |
| Needed | account + credit | account + credit | account | existing key |

**Pros / cons summary**
- **Claude Haiku 5.5:** the cheapest paid option, strong at tool use, no limit problems. Needs prepayment; data
  goes to a US company. (Note: this comparison was drafted with the help of an AI assistant made by Anthropic;
  the decision should rest on measurements.)
- **DeepSeek V4 Flash:** similarly cheap, strong at code. Prices and model names change often; data in China.
- **OpenRouter free:** no cost, but the daily limit is not enough for real use; results are not reproducible.
- **Gemini free:** already available, but 5 requests/minute and frequent outages; not a reliable fallback.

**Recommendation (not decided):** local first + Claude Haiku 5.5 when needed, Gemini as a free backup. Before
deciding, run the same benchmark with the candidate and compare it with the local model (the whole set with
Haiku 5.5 ≈ $0.06).

**Sources:** DeepSeek V4 prices (siliconflow.com, benchlm.ai), OpenRouter free API comparison
(openrouter.ai/blog), OpenRouter limits (truefoundry.com), Gemini free tier (agentdeals.dev, yingtu.ai), Claude
prices from Anthropic's current model table.

## 3. Other postponed items

- **Menu UI (Textual):** the terminal (cmd) interface is used for now.
- **Real code isolation:** `run_python` runs in a separate virtual environment, but with the user's permissions;
  real isolation with Windows Sandbox or Docker.
- **Voice (speech ↔ text), understanding screenshots, image generation.**
