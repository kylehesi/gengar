"""Doğrulanmış dökümleri eğitim verisine (SFT, sohbet + araçlar biçimi) çevirir.

Kullanım:
  uv run python evals/export_sft.py data/trajectories/gen_*.jsonl [--out data/sft] [--val 0.05]

Çıktı (her satır bir örnek):
  {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", "tool_calls": [...]},
                {"role": "tool", ...}, ...], "tools": [...], "meta": {...}}
Bu biçim TRL/Unsloth'un sohbet şablonuyla (Qwen araç çağırma biçimi) doğrudan kullanılır.
Eğitimde kayıp yalnızca asistan mesajlarından hesaplanmalı (train_on_responses_only).

Seçim kuralları:
- Yalnızca doğrulanmış (ok=true) ve hatasız görevler.
- Gengar'ın araya girdiği oturumlar ("[Gengar] ..." uyarıları, engellenen tekrarlar) atılır:
  model temiz örneklerden öğrenmeli. Hata alıp kendi düzelten oturumlar kalır.
- Her oturum ayrı örnek; aynı içerikli örnekler tekilleştirilir.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

ROOT = Path(__file__).resolve().parent.parent


def clean_session(session: dict, keep_reasoning: bool = True) -> dict | None:
    messages = session["messages"]
    if not messages or messages[-1]["role"] != "assistant" or not (messages[-1].get("content") or "").strip():
        return None  # son cevap yoksa örnek eksik
    for m in messages:
        content = m.get("content") or ""
        if m["role"] == "user" and content.startswith("[Gengar]"):
            return None
        if m["role"] == "tool" and content.startswith("Not executed:"):
            return None
    out = [{"role": "system", "content": session["system"]}]
    for m in messages:
        msg = {"role": m["role"], "content": m.get("content") or ""}
        if m.get("_reasoning") and keep_reasoning:
            # Qwen sohbet şablonu bunu <think>...</think> olarak yazar. Unsloth: Qwen3.5'in düşünme
            # yeteneğini korumak için örneklerin en az %75'i düşünce içermeli.
            msg["reasoning_content"] = m["_reasoning"]
        if m.get("tool_calls"):
            msg["tool_calls"] = [{"type": "function", "id": tc["id"], "function": {
                "name": tc["function"]["name"],
                # Qwen sohbet şablonu argümanları JSON nesnesi olarak bekliyor
                "arguments": json.loads(tc["function"]["arguments"] or "{}")}} for tc in m["tool_calls"]]
        if m["role"] == "tool":
            msg["tool_call_id"] = m.get("tool_call_id", "")
            msg["name"] = m.get("name", "")
        out.append(msg)
    return {"messages": out, "tools": session["tools"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default=str(ROOT / "data" / "sft"))
    ap.add_argument("--val", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-reasoning", action="store_true", help="düşünce metinlerini çıkar")
    args = ap.parse_args()

    paths = [p for pattern in args.files for p in glob.glob(pattern)]
    examples, seen, stats = [], set(), Counter()
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            stats["görev"] += 1
            if rec.get("purpose") != "train":
                stats["eğitim amaçlı değil (ölçüm dökümü)"] += 1
                continue
            if not rec["ok"] or rec.get("error"):
                stats["doğrulanmamış"] += 1
                continue
            for i, session in enumerate(rec["sessions"]):
                ex = clean_session(session, keep_reasoning=not args.no_reasoning)
                if ex is None:
                    stats["oturum atıldı (uyarı/eksik)"] += 1
                    continue
                key = hashlib.sha1(json.dumps(ex["messages"][1:], ensure_ascii=False, sort_keys=True)
                                   .encode()).hexdigest()
                if key in seen:
                    stats["tekrar"] += 1
                    continue
                seen.add(key)
                ex["meta"] = {"task_id": rec["task_id"], "family": rec["family"], "category": rec["category"],
                              "session": i, "teacher": rec.get("model"), "think": rec.get("think")}
                examples.append(ex)
                stats["örnek"] += 1

    random.Random(args.seed).shuffle(examples)
    n_val = max(1, int(len(examples) * args.val)) if examples else 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", examples[n_val:]), ("val", examples[:n_val])):
        with (out / f"gengar_sft_{name}.jsonl").open("w", encoding="utf-8") as f:
            for ex in part:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    chars = [len(json.dumps(ex, ensure_ascii=False)) for ex in examples]
    print("İstatistik:", dict(stats))
    print(f"Örnek: {len(examples)} (eğitim {len(examples) - n_val}, doğrulama {n_val})")
    if chars:
        print(f"Örnek başına ~{sum(chars) / len(chars) / 3:.0f} token (kaba tahmin), "
              f"en uzun ~{max(chars) / 3:.0f}, toplam ~{sum(chars) / 3 / 1e6:.1f}M token")
    with_reasoning = sum(any(m.get("reasoning_content") for m in ex["messages"]) for ex in examples)
    if examples:
        print(f"Düşünce içeren örnek: {with_reasoning}/{len(examples)} (%{100 * with_reasoning / len(examples):.0f}; "
              "Unsloth önerisi en az %75)")
    print("Aile dağılımı:", dict(Counter(ex["meta"]["family"] for ex in examples).most_common()))
    print(f"Çıktı: {out}")


if __name__ == "__main__":
    main()
