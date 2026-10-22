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
