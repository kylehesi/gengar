"""Gengar ölçüm seti v2: görev aileleri, dev/test bölünmesi, tam döküm kaydı.

Kullanım:
  uv run python evals/bench2.py [profil] [--split dev|test|all] [--mode off|on|auto] [--only aile|kategori,...]
                                [--tag not] [--list]
  örn.  uv run python evals/bench2.py local35 --split dev
        uv run python evals/bench2.py local35 --split test --tag aday1

Kurallar: prompt/sistem ayarlarken sadece dev sonuçlarına bakılır; test seti yalnızca rapor içindir.
Her çalıştırmanın dökümü data/trajectories/<zaman>_<etiket>.jsonl dosyasına yazılır.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(errors="replace", line_buffering=True)  # arka planda çalışırken ilerleme hemen görünsün
sys.path.insert(0, str(Path(__file__).parent))

from families import all_families  # noqa: E402
from framework import TRAJ_ROOT, build_tasks, gengar_commit, run_task, save_results, summarize  # noqa: E402
from gengar.config import load_env, load_settings  # noqa: E402
from gengar.llm import LLMClient  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Gengar ölçüm seti v2")
    ap.add_argument("profile", nargs="?", default=None, help="settings.toml profil adı (varsayılan: default)")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--mode", choices=["off", "on", "auto"], default=None, help="düşünme modu (varsayılan: ayar)")
    ap.add_argument("--only", default="", help="virgülle ayrılmış aile/kategori/görev adları")
    ap.add_argument("--tag", default="")
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--list", action="store_true", help="görevleri listele, çalıştırma")
    args = ap.parse_args()

    load_env()
    settings = load_settings()
    if args.mode:
        settings = replace(settings, think=args.mode)
    profile = args.profile or settings.default_profile

    tasks = build_tasks(all_families(), seed=args.seed)
    only = [x for x in args.only.split(",") if x]
    tasks = [t for t in tasks if (args.split == "all" or t.split == args.split)
             and (not only or t.id in only or t.family in only or t.category in only)]

    if args.list:
        for t in tasks:
            p = t.prompt if isinstance(t.prompt, str) else " → ".join(t.prompt)
            print(f"[{t.split:4}] [{t.category:8}] z{t.difficulty} {t.id:24} {p[:110]}")
        print(f"\n{len(tasks)} görev")
        return

    client = LLMClient(settings, profile)
    label = f"v2 {args.split} {profile} think={settings.think}{' ' + args.tag if args.tag else ''}"
    meta = {"profile": profile, "model": client.profile.model, "think": settings.think, "split": args.split,
            "seed": args.seed, "commit": gengar_commit(), "date": datetime.now().isoformat(timespec="seconds"),
            "num_ctx": client.profile.options.get("num_ctx")}
    TRAJ_ROOT.mkdir(parents=True, exist_ok=True)
    traj = TRAJ_ROOT / f"{datetime.now():%Y%m%d_%H%M%S}_{args.split}_{profile}{'_' + args.tag if args.tag else ''}.jsonl"
    print(f"Ölçüm v2: {label} — {len(tasks)} görev, model {client.profile.model}\nDöküm: {traj}\n")

    results = []
    for i, t in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] [{t.category}/{t.id}] z{t.difficulty}")
        r = run_task(t, settings, client, traj, meta)
        results.append(r)
        print(f"  {'✅' if r.ok else '❌'} {r.seconds:5.1f} sn, {r.tool_calls} araç | {r.note[:120]}"
              + (f" | HATA: {r.error[:100]}" if r.error else ""))

    summarize(results, label)
    out = save_results(results, label, meta)
    print(f"\nSonuç: {out}\nDöküm: {traj}")


if __name__ == "__main__":
    main()
