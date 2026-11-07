"""Gerçek kullanımdaki araç hatalarının dökümü: hangi araç ne sıklıkla, hangi hatayla başarısız oluyor?

Denetim kaydını (logs/audit-*.jsonl) okur. Ölçüm ve veri üretimi çağrıları (data\\bench2, data\\gen yolları)
varsayılan olarak hariç tutulur; reddedilen/korunan çağrılar hata sayılmaz. Hata metinlerindeki sayılar ve
tırnak içleri kalıba çevrilir, böylece aynı hatanın farklı örnekleri tek satırda toplanır.

    uv run python evals/error_report.py                 # bütün kayıtlar
    uv run python evals/error_report.py --since 2026-11-01 --tool windows_ui --examples 3
    uv run python evals/error_report.py --include-bench

2026-11-07: bu döküm windows_ui'nin %39 hata oranını gösterdi (diğer araçlar %0-10); düzeltme v0.0.9'da.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DECISIONS = {"denied", "after_denial", "protected"}


def is_bench(event: dict) -> bool:
    args = json.dumps(event.get("args"), ensure_ascii=False).lower()
    return "bench2" in args or "data\\\\gen\\\\" in args or "data/gen/" in args


def pattern(output: str) -> str:
    text = re.sub(r"\d+", "N", output.replace("\n", " "))
    return re.sub(r"'[^']*'", "'…'", text)[:100]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default="", help="bu tarihten (YYYY-AA-GG) itibaren")
    ap.add_argument("--tool", default="", help="yalnızca bu araç")
    ap.add_argument("--include-bench", action="store_true", help="ölçüm/veri üretimi çağrılarını da say")
    ap.add_argument("--top", type=int, default=20, help="kaç hata kalıbı gösterilsin")
    ap.add_argument("--examples", type=int, default=0, help="her kalıp için kaç örnek çağrı gösterilsin")
    args = ap.parse_args()

    total, errors = collections.Counter(), collections.Counter()
    patterns: collections.Counter = collections.Counter()
    examples: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for path in sorted(glob.glob(str(ROOT / "logs" / "audit-*.jsonl"))):
        if args.since and Path(path).stem.removeprefix("audit-") < args.since:
            continue
        for line in open(path, encoding="utf-8"):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("event") != "tool" or e.get("decision") in SKIP_DECISIONS:
                continue
            tool = e.get("tool", "?")
            if (args.tool and tool != args.tool) or (not args.include_bench and is_bench(e)):
                continue
            total[tool] += 1
            if e.get("ok") is False:
                errors[tool] += 1
                key = (tool, pattern(e.get("output") or ""))
                patterns[key] += 1
                if len(examples[key]) < args.examples:
                    examples[key].append(f"{e.get('ts', '')}  {json.dumps(e.get('args'), ensure_ascii=False)[:160]}")

    if not total:
        print("Kayıt yok.")
        return
    print("araç               hata / toplam")
    for tool, n in sorted(total.items(), key=lambda kv: -errors[kv[0]] / kv[1]):
        bar = "█" * round(20 * errors[tool] / n)
        print(f"  {tool:16s} {errors[tool]:4d} / {n:<5d} %{100 * errors[tool] / n:3.0f} {bar}")
    print(f"\nen sık {args.top} hata kalıbı ('blocked repeat': aynı çağrı tekrarlandığı için durduruldu):")
    for (tool, text), n in patterns.most_common(args.top):
        print(f"  {n:3d}  {tool:14s} {text}")
        for ex in examples[(tool, text)]:
            print(f"         ↳ {ex}")


if __name__ == "__main__":
    main()
