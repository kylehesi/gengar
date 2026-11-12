# Training the student model (Qwen3.5 4B on Kaggle)

> Turkish original: [`docs/tr/EGITIM.md`](../docs/tr/EGITIM.md).

The teacher (Qwen3.5 9B, thinking on) solves Gengar tasks; only **verified** solutions become training data. The
student (Qwen3.5 4B) is fine-tuned on this data with LoRA. Goal: close to 9B success on Gengar tasks, ~2× the
speed, more VRAM headroom for context. Background: [ARCHITECTURE §11](../docs/ARCHITECTURE.md#11-distillation-and-training).

## 1. Data generation (on the PC, overnight)
```
evals\gece_veri_uret.cmd          (double-click; if interrupted, double-click again — it resumes)
```
Progress: `data\gen_log.txt`. Output: `data\trajectories\gen_*.jsonl`.

## 2. Conversion to training data
```
uv run python evals\export_sft.py "data\trajectories\gen_*seed5000*.jsonl" --out data\sft
```
Output: `data\sft\gengar_sft_train.jsonl`, `data\sft\gengar_sft_val.jsonl`. In the statistics, "examples with
reasoning" should be at least 75% (Unsloth's recommendation, so Qwen3.5 keeps its thinking ability).
Benchmark trajectories (dev/test) never enter training; the converter only takes `purpose=train` records.

### Public data in the mix (not yet downloaded)
[`training/public_mix.py`](public_mix.py) converts rows of seven public datasets into the same format, so the
student does not forget general tool calling and Turkish: Toucan, When2Call, xLAM-irrelevance, two Turkish
tool-calling sets, the Turkish part of Aya, and self-oss-instruct.
- Each converter turns one row into one example, or `None` if the row cannot be used. Toucan's
  `tool_call`/`tool_response` roles become `tool_calls` + `tool` messages. Python type names (`str, optional`,
  `List[int]`) become JSON Schema.
- xLAM-irrelevance has no assistant reply. Its examples are marked `needs_reply`: the teacher writes the
  no-tool answer, as in data generation.
- `bfcl_leaks()` finds training questions that are the same as, or very close to, the BFCL subset
  (`evals/bfcl.py`). Drop them before training, or the "after" number is inflated.
- The datasets, licences, sizes and proposed samples are in [OPEN_ISSUES 9](../docs/OPEN_ISSUES.md).
- [`training/fetch_public.py`](fetch_public.py) downloads the raw rows (approved 2026-11-12) into
  `data/public/<key>.jsonl` through the row API, 100 rows per request. For Toucan (4,000 of 119k rows), the
  Turkish xLAM translation (5,000) and self-oss-instruct (2,000), pages are chosen with a fixed seed instead of
  downloading everything. If interrupted, run it again: finished sets are skipped and a half-done one continues.
  It does not convert anything.

## 3. Training on Kaggle
1. kaggle.com → Datasets → **New Dataset** → upload the two `.jsonl` files from `data\sft` (e.g. `gengar-sft`).
2. Code → **New Notebook** → File → Import Notebook → `training\gengar_qwen35_4b_kaggle.ipynb`.
3. Right panel: **Accelerator: GPU T4 x2** (or P100), **Internet: On**, **Add Input** → `gengar-sft`.
4. Because it takes hours, run it in the background with **Save Version → Save & Run All** (the browser can be
   closed; outputs are saved permanently). The model is split unevenly across the two T4s (more layers on GPU 0);
   cell 3 should show ~6 GB on GPU 0 and ~3 GB on GPU 1. If you still get a memory error (CUDA out of memory), set
   `LOAD_IN_4BIT = True` in cell 2 and run again. A checkpoint is saved every 10 steps.
5. When finished: right panel → **Output** → download the `.gguf` file in `gengar_gguf/`.

The notebook is generated from `training\build_notebook.py`; make changes there:
`uv run python training\build_notebook.py`.

Measured data: ~4,900 tokens per example on average (fixed part: system prompt + 18 tools ≈ 4,050); 93% fit in
6,144 tokens.

## 4. Import into Ollama (on the PC)
```
mkdir data\models
(put the downloaded .gguf file at data\models\gengar-qwen35-4b.Q4_K_M.gguf)
ollama create gengar-4b -f training\Modelfile.gengar-4b
```
Then measure with the `student` profile in `config\settings.toml`:
```
uv run python evals\bench2.py student --split test --tag trained
```

## Comparison plan (test set)
| Model | What it measures |
|---|---|
| Qwen3.5 9B (teacher, current default) | the upper bound |
| Qwen3.5 4B (untrained) | the student's starting point |
| Qwen3.5 4B + Gengar LoRA | the effect of training |
