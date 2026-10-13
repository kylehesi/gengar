"""Eğitim verisi üretici (4. aşama): öğretmen model görevleri çözer, sadece doğrulananlar saklanır.

Kullanım:
  uv run python evals/generate.py [profil] [--per-family N] [--seed S] [--mode on|auto|off]
                                  [--only aile,...] [--resume DOSYA] [--max-hours H]
  örn.  uv run python evals/generate.py local35 --per-family 20 --mode on

Kurallar (veri hijyeni):
- Yalnızca testte bulunan aileler (test_only) HİÇ kullanılmaz.
- Ölçüm v2 tohum 1000 kullanır; üretim varsayılan olarak 5000'den başlar, yani ölçüm görevleri
  eğitime girmez.
- Her görevin dökümü (başarılı/başarısız) data/trajectories/gen_*.jsonl dosyasına yazılır;
  eğitim için `ok=true` olanlar seçilir (bkz. evals/export_sft.py).
- --resume ile yarıda kalan bir üretim kaldığı yerden devam eder (biten görevler atlanır).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(errors="replace", line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent))

from families import all_families  # noqa: E402
from framework import PROJECT_ROOT, TRAJ_ROOT, build_tasks, gengar_commit, run_task  # noqa: E402
from gengar.config import load_env, load_settings  # noqa: E402
from gengar.llm import LLMClient  # noqa: E402

GEN_ROOT = PROJECT_ROOT / "data" / "gen"


def main() -> None:
    ap = argparse.ArgumentParser(description="Gengar eğitim verisi üretici")
    ap.add_argument("profile", nargs="?", default=None)
    ap.add_argument("--per-family", type=int, default=20)
    ap.add_argument("--seed", type=int, default=5000)
    ap.add_argument("--mode", choices=["off", "on", "auto"], default="on", help="öğretmenin düşünme modu")
    ap.add_argument("--only", default="")
    ap.add_argument("--resume", default="", help="devam edilecek gen_*.jsonl dosyası")
    ap.add_argument("--max-hours", type=float, default=0, help="bu süre dolunca dur (0: sınırsız)")
    args = ap.parse_args()
    if args.seed == 1000:
        sys.exit("Tohum 1000 ölçüm setine ait; eğitim verisi için başka bir tohum kullanın.")

    load_env()
    settings = replace(load_settings(), think=args.mode)
    profile = args.profile or settings.default_profile
    client = LLMClient(settings, profile)

    families = [f for f in all_families() if not f.test_only]
    only = [x for x in args.only.split(",") if x]
    if only:
        families = [f for f in families if f.name in only or f.category in only]
    tasks = build_tasks(families, seed=args.seed, base=GEN_ROOT, instances=args.per_family)

    TRAJ_ROOT.mkdir(parents=True, exist_ok=True)
    out = Path(args.resume) if args.resume else \
        TRAJ_ROOT / f"gen_{datetime.now():%Y%m%d_%H%M%S}_{profile}_think-{args.mode}_seed{args.seed}.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(line)["task_id"] for line in out.read_text(encoding="utf-8").splitlines() if line}
    # Aileleri karıştırarak sırala: üretim yarıda kalırsa bile her aileden örnek olsun.
    tasks.sort(key=lambda t: (int(t.id.rsplit("_", 1)[1]), t.family))
    todo = [t for t in tasks if t.id not in done]

    meta = {"purpose": "train", "profile": profile, "model": client.profile.model, "think": args.mode,
            "seed": args.seed, "commit": gengar_commit(), "date": datetime.now().isoformat(timespec="seconds"),
            "num_ctx": client.profile.options.get("num_ctx")}
    print(f"Veri üretimi: {len(families)} aile × {args.per_family} = {len(tasks)} görev "
          f"({len(done)} zaten bitmiş), öğretmen {client.profile.model} think={args.mode}\nÇıktı: {out}\n")

    start = time.time()
    ok = sum(1 for line in out.read_text(encoding="utf-8").splitlines() if line and json.loads(line)["ok"]) \
        if out.exists() else 0
    for i, t in enumerate(todo, 1):
        if args.max_hours and time.time() - start > args.max_hours * 3600:
            print(f"\n{args.max_hours} saat doldu, durduruluyor. Devam için: --resume {out}")
            break
        r = run_task(t, settings, client, out, meta)
        ok += r.ok
        elapsed = time.time() - start
        eta = elapsed / i * (len(todo) - i) / 60
        print(f"[{i}/{len(todo)}] {'✅' if r.ok else '❌'} {t.id:28} {r.seconds:5.1f} sn | "
              f"toplam doğrulanmış {ok} | kalan ~{eta:.0f} dk")

    total = sum(1 for line in out.read_text(encoding="utf-8").splitlines() if line) if out.exists() else 0
    print(f"\nBitti: {total} döküm, {ok} doğrulanmış (eğitime uygun). Dosya: {out}")


if __name__ == "__main__":
    main()
