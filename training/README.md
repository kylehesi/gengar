# Öğrenci modeli eğitimi (Qwen3.5 4B, Kaggle)

Öğretmen (Qwen3.5 9B, düşünme açık) Gengar görevlerini çözer; yalnızca **doğrulanmış** çözümler
eğitim verisi olur. Öğrenci (Qwen3.5 4B) bu verilerle LoRA ile eğitilir. Hedef: Gengar görevlerinde
9B'ye yakın başarı, ~2 kat hız ve VRAM'de daha geniş bağlam payı.

## 1. Veri üretimi (bilgisayarda, gece)
```
evals\gece_veri_uret.cmd          (çift tıklayın; yarıda kalırsa tekrar çift tıklayın, kaldığı yerden devam eder)
```
İlerleme: `data\gen_log.txt`. Çıktı: `data\trajectories\gen_*.jsonl`.

## 2. Eğitim verisine dönüştürme
```
uv run python evals\export_sft.py "data\trajectories\gen_*seed5000*.jsonl" --out data\sft
```
Çıktı: `data\sft\gengar_sft_train.jsonl`, `data\sft\gengar_sft_val.jsonl`. İstatistiklerde "Düşünce içeren
örnek" en az %75 olmalı (Unsloth önerisi; Qwen3.5'in düşünme yeteneği korunsun).
Ölçüm dökümleri (dev/test) asla eğitime girmez; dönüştürücü yalnızca `purpose=train` kayıtları alır.

## 3. Kaggle'da eğitim
1. kaggle.com → Datasets → **New Dataset** → `data\sft` içindeki iki `.jsonl` dosyasını yükleyin
   (ad örn. `gengar-sft`).
2. Code → **New Notebook** → File → Import Notebook → `training\gengar_qwen35_4b_kaggle.ipynb`.
3. Sağ panel: **Accelerator: GPU T4 x2** (ya da P100), **Internet: On**, **Add Input** → `gengar-sft`.
4. Hücreleri sırayla çalıştırın. Model iki T4'e bölünür (`device_map="balanced"`); tek T4'te 16-bit
   model + 6k token eğitim sığmadı. Yine de bellek hatası (CUDA out of memory) alırsanız
   Run → Restart, 2. hücrede `LOAD_IN_4BIT = True` yapıp 2. hücreden itibaren yeniden çalıştırın.
5. Bitince sağ panel → **Output** → `gengar_gguf/` içindeki `.gguf` dosyasını indirin.

Not defteri `training\build_notebook.py` dosyasından üretilir; değişiklik o dosyada yapılır:
`uv run python training\build_notebook.py`.

Ölçülen veri: örnek başına ortalama ~4.900 token (sabit kısım: sistem promptu + 18 araç ≈ 4.050),
%99'u 8.192 token altında.

## 4. Ollama'ya aktarma (bilgisayarda)
```
mkdir data\models
(indirilen .gguf dosyasını data\models\gengar-qwen35-4b.Q4_K_M.gguf adıyla koyun)
ollama create gengar-4b -f training\Modelfile.gengar-4b
```
Sonra `config\settings.toml`'daki `student` profiliyle ölçüm:
```
uv run python evals\bench2.py student --split test --tag egitimli
```

## Karşılaştırma planı (test seti)
| Model | Ne ölçülür |
|---|---|
| Qwen3.5 9B (öğretmen, mevcut varsayılan) | üst sınır |
| Qwen3.5 4B (eğitimsiz) | öğrencinin başlangıcı |
| Qwen3.5 4B + Gengar LoRA | eğitimin etkisi |
