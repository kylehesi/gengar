"""Kaggle eğitim not defterini (gengar_qwen35_4b_kaggle.ipynb) üretir.

Hücreler burada okunabilir hâlde tutulur; not defteri bu dosyadan üretilir:
  uv run python training/build_notebook.py
"""

import json
from pathlib import Path

CELLS: list[tuple[str, str]] = []


def md(text: str) -> None:
    CELLS.append(("markdown", text.strip("\n")))


def code(text: str) -> None:
    CELLS.append(("code", text.strip("\n")))


md("""
# Gengar — Qwen3.5 4B öğrenci modeli eğitimi (Kaggle)

**Amaç:** Qwen3.5 9B öğretmen modelin Gengar görevlerindeki *doğrulanmış* çözümleriyle Qwen3.5 4B'yi
eğitmek (LoRA). Hedef: Gengar görevlerinde 9B'ye yakın başarı, ~2 kat hız.

**Kaggle ayarları (sağ panel → Session options):**
1. **Accelerator:** GPU T4 x2 (ya da GPU P100)
2. **Internet:** On (telefon doğrulaması gerekir)
3. **Input:** `gengar_sft_train.jsonl` ve `gengar_sft_val.jsonl` dosyalarını içeren bir Kaggle Dataset ekleyin
   (Datasets → New Dataset → dosyaları yükleyin → bu not defterine "Add Input").

Sonra hücreleri sırayla çalıştırın. Eğitim bittiğinde çıktılar `/kaggle/working` altında olur
(sağ panel → Output); `gengar_gguf/` klasöründeki `.gguf` dosyasını indirin.
""")

md("## 1. Kurulum\nUnsloth'un resmi Qwen3.5 not defterindeki sürümler. (~3-5 dk)")
code("""
!pip install -q uv
!uv pip install -q --system --upgrade --no-deps "tokenizers>=0.22.0,<=0.23.0" trl==0.22.2 unsloth unsloth_zoo
!uv pip install -q --system transformers==5.2.0
!unsloth install-kernels
!uv pip install -q --system --no-deps --upgrade "torchao>=0.16.0"
# Kaggle'da hazır gelmeyen bağımlılıklar (Colab'da var; --no-deps kurulum bunları getirmiyor).
!uv pip install -q --system bitsandbytes peft accelerate datasets
""")

md("## 2. Ayarlar")
code("""
import glob, json, os
# Bellek parçalanmasını azaltır; torch yüklenmeden önce ayarlanmalı.
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

MODEL = "unsloth/Qwen3.5-4B"
# Qwen3.5'in sözlüğü çok büyük (~248k token): uzun örneklerde çıktı olasılık tablosu GB'larca yer tutuyor.
# Kaggle T4 x2'de 8192 bellek hatası verdi (deneme turu, 2026-10-13); 6144 örneklerin ~%93'ünü kapsıyor.
MAX_LEN = 6144
# Yedek plan: iki GPU'ya bölmeye rağmen bellek yetmezse True yapın (4-bit QLoRA; Unsloth Qwen3.5 için
# önermiyor, kalite biraz düşebilir ama ~6 GB yer açar).
LOAD_IN_4BIT = False
EPOCHS = 2
LEARNING_RATE = 2e-4
LORA_R = 16
BATCH = 1
GRAD_ACCUM = 8          # etkin batch = BATCH * GRAD_ACCUM
SEED = 3407
OUT = "/kaggle/working"

train_path = (glob.glob("/kaggle/input/**/gengar_sft_train.jsonl", recursive=True) or ["gengar_sft_train.jsonl"])[0]
val_path = (glob.glob("/kaggle/input/**/gengar_sft_val.jsonl", recursive=True) or ["gengar_sft_val.jsonl"])[0]
print("Eğitim verisi:", train_path)
print("Doğrulama verisi:", val_path)
""")

md("""
## 3. Model
16-bit LoRA (Unsloth: Qwen3.5'te 4-bit QLoRA önerilmiyor). T4'te bf16 yok; otomatik fp16 kullanılır.

**İki GPU:** 16-bit 4B model tek T4'te (~15 GB) ~9 GB tutuyor; uzun örneklerde eğitim belleği yetmedi
(deneme turu, 2026-10-13). `device_map="balanced"` modelin katmanlarını iki T4'e böler (Unsloth'un
belgelenmiş yöntemi); her kartta ~4.5 GB model kalır, gerisi eğitime.
""")
code("""
import torch
from unsloth import FastLanguageModel, is_bf16_supported

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL,
    max_seq_length = MAX_LEN,
    load_in_4bit = LOAD_IN_4BIT,
    load_in_16bit = not LOAD_IN_4BIT,
    full_finetuning = False,
    device_map = "balanced" if torch.cuda.device_count() > 1 else None,
)
model = FastLanguageModel.get_peft_model(
    model,
    r = LORA_R,
    lora_alpha = LORA_R,
    lora_dropout = 0,
    bias = "none",
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing = "unsloth",   # uzun bağlam için şart
    random_state = SEED,
)
# Görsel model işlemcisi (processor) dönebilir; sohbet şablonu için metin tokenizer'ı kullanılır.
tok = getattr(tokenizer, "tokenizer", tokenizer)
print("GPU:", torch.cuda.device_count(), "x", torch.cuda.get_device_name(0), "| bf16:", is_bf16_supported())
for i in range(torch.cuda.device_count()):
    print(f"  GPU {i}: {torch.cuda.memory_allocated(i) / 1e9:.1f} GB model")
""")

md("""
## 4. Veri: sohbet şablonuna dönüştürme
Her örnek: sistem promptu + 18 araç tanımı + kullanıcı isteği + modelin araç çağrıları, araç sonuçları
ve son cevap. Düşünce metinleri (`reasoning_content`) şablonda `<think>...</think>` olarak yazılır.
""")
code("""
from datasets import Dataset

def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def render(ex):
    return tok.apply_chat_template(ex["messages"], tools=ex["tools"], tokenize=False)

raw_train, raw_val = load(train_path), load(val_path)
texts_train = [render(ex) for ex in raw_train]
texts_val = [render(ex) for ex in raw_val]
lengths = [len(tok(t).input_ids) for t in texts_train]
keep = [i for i, n in enumerate(lengths) if n <= MAX_LEN]
print(f"Eğitim: {len(raw_train)} örnek, token ortalama {sum(lengths)/len(lengths):.0f}, en uzun {max(lengths)}")
print(f"MAX_LEN={MAX_LEN} sınırına sığan: {len(keep)} ({len(raw_train) - len(keep)} örnek çıkarıldı)")

train_ds = Dataset.from_dict({"text": [texts_train[i] for i in keep]})
val_ds = Dataset.from_dict({"text": [t for t in texts_val if len(tok(t).input_ids) <= MAX_LEN]})

# Şablonun araç çağrısı ve düşünceyi doğru yazdığını gözle kontrol edin:
sample = texts_train[keep[0]]
i = sample.find("<|im_start|>assistant")
print(sample[i:i + 1500])
""")

md("""
## 5. Eğitici
Kayıp yalnızca **asistan** mesajlarından hesaplanır (`train_on_responses_only`): model kullanıcı
isteklerini ve araç çıktılarını değil, kendi kararlarını (araç çağrıları, düşünce, cevap) öğrenir.
Qwen şablonunda araç sonuçları da `user` rolünde yazıldığı için onlar da maskelenir.
""")
code("""
from trl import SFTTrainer, SFTConfig
from unsloth.chat_templates import train_on_responses_only

trainer = SFTTrainer(
    model = model,
    tokenizer = tok,
    train_dataset = train_ds,
    eval_dataset = val_ds,
    args = SFTConfig(
        dataset_text_field = "text",
        max_length = MAX_LEN,
        packing = False,
        per_device_train_batch_size = BATCH,
        per_device_eval_batch_size = 1,   # varsayılan 8: doğrulama adımında 8 uzun örnek belleği taşırır
        gradient_accumulation_steps = GRAD_ACCUM,
        num_train_epochs = EPOCHS,
        learning_rate = LEARNING_RATE,
        lr_scheduler_type = "cosine",
        warmup_steps = 3,
        logging_steps = 1,       # her adımda çıktı: ilk adım uzun sürdüğünde "takıldı mı" belli olsun
        eval_strategy = "steps",
        eval_steps = 25,
        save_strategy = "steps",
        save_steps = 50,
        save_total_limit = 2,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        fp16 = not is_bf16_supported(),
        bf16 = is_bf16_supported(),
        seed = SEED,
        output_dir = f"{OUT}/checkpoints",
        report_to = "none",
    ),
)
trainer = train_on_responses_only(
    trainer,
    instruction_part = "<|im_start|>user\\n",
    response_part = "<|im_start|>assistant\\n",
)

# Maskelemeyi kontrol: eğitilen (etiketi -100 olmayan) kısım asistan mesajları olmalı.
labels = trainer.train_dataset[0]["labels"]
trained = tok.decode([t for t, l in zip(trainer.train_dataset[0]["input_ids"], labels) if l != -100])
print(f"Eğitilen token oranı: {sum(l != -100 for l in labels) / len(labels):.0%}")
print(trained[:800])
""")

md("""
## 6. Eğitim
**İlk adım 10-15 dakika sürebilir:** Qwen3.5'in hibrit mimarisi için GPU çekirdekleri ilk adımda derlenir
(Unsloth: "özellikle T4'te yavaş"). İlerleme çubuğu bir süre `0/…` durabilir; durdurmayın.
Sonraki adımlar çok daha hızlıdır. Toplam süre örnek sayısına göre 1-4 saat.
""")
code("""
import time
start = time.time()
stats = trainer.train()
peak = ", ".join(f"GPU{i} {torch.cuda.max_memory_allocated(i) / 1e9:.1f} GB" for i in range(torch.cuda.device_count()))
print(f"Süre: {(time.time() - start) / 60:.0f} dk | en yüksek bellek: {peak}")
print(stats)
""")

md("## 7. Hızlı deneme\nDoğrulama setinden bir isteği modele verip ilk adımını (araç çağrısı) görelim.")
code("""
FastLanguageModel.for_inference(model)
ex = raw_val[0]
prompt_msgs = [m for m in ex["messages"] if m["role"] in ("system", "user")][:2]
prompt = tok.apply_chat_template(prompt_msgs, tools=ex["tools"], tokenize=False, add_generation_prompt=True)
inputs = tok(prompt, return_tensors="pt").to("cuda")
out = model.generate(**inputs, max_new_tokens=512, temperature=0.6, top_p=0.95, do_sample=True)
print("İSTEK:", prompt_msgs[-1]["content"])
print("MODEL:", tok.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=False))
""")

md("""
## 8. Kaydetme
- `gengar_lora/`: LoRA ağırlıkları (küçük; yeniden eğitmeden denemeler için)
- `gengar_gguf/`: Ollama'da kullanılacak **GGUF** (q4_k_m, ~2.5-3 GB). llama.cpp derlendiği için ~10-20 dk sürer.
""")
code("""
model.save_pretrained(f"{OUT}/gengar_lora")
tok.save_pretrained(f"{OUT}/gengar_lora")
model.save_pretrained_gguf(f"{OUT}/gengar_gguf", tok, quantization_method = "q4_k_m")
!ls -la {OUT}/gengar_gguf
""")

md("""
## Sonraki adım (bilgisayarda)
İndirdiğiniz `.gguf` dosyasını `C:\\gengar\\data\\models\\` altına koyun; Gengar'a Ollama modeli olarak
eklemek için `training/README.md`'deki adımları izleyin. Sonra öğrenciyi ölçüm setinin **test**
bölümünde öğretmenle karşılaştırırız.
""")


def build(path: Path) -> None:
    nb = {"nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                       "language_info": {"name": "python"},
                       "kaggle": {"accelerator": "gpu", "isInternetEnabled": True}},
          "cells": []}
    for i, (kind, src) in enumerate(CELLS):
        cell = {"cell_type": kind, "id": f"c{i:02d}", "metadata": {}, "source": src.splitlines(keepends=True)}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        nb["cells"].append(cell)
    path.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{path} ({len(CELLS)} hücre)")


if __name__ == "__main__":
    build(Path(__file__).parent / "gengar_qwen35_4b_kaggle.ipynb")
