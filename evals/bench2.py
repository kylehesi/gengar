"""Gengar ölçüm seti v2: görev aileleri, dev/test bölünmesi, tam döküm kaydı.

Kullanım:
  uv run python evals/bench2.py [profil] [--split dev|test|all] [--mode off|on|auto] [--only aile|kategori,...]
                                [--tag not] [--list] [--suite base|real] [--repeat N]
  örn.  uv run python evals/bench2.py local35 --split dev
        uv run python evals/bench2.py local35 --split test --tag aday1
        uv run python evals/bench2.py local35 --suite real --split all --repeat 3

--suite real: gerçek istekler seti (evals/real/README.md); metinleri evals/real/private/prompts.json'da, yerelde.
--repeat N: her görev N kez koşulur (her tekrarda başlangıç durumu yeniden kurulur); sonunda görev başına
  "kaç tekrarda geçti" yazılır. Tek koşuda görevlerin ~%15'i rastlantıyla değişiyor.

Kurallar: prompt/sistem ayarlarken sadece dev sonuçlarına bakılır; test seti yalnızca rapor içindir.
Her çalıştırmanın dökümü data/trajectories/<zaman>_<etiket>.jsonl dosyasına yazılır.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(errors="replace", line_buffering=True)  # arka planda çalışırken ilerleme hemen görünsün
sys.path.insert(0, str(Path(__file__).parent))

from families import all_families, real  # noqa: E402
from framework import (TRAJ_ROOT, build_tasks, gengar_commit, result_from_record, run_task,  # noqa: E402
                       save_results, summarize)
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
    ap.add_argument("--suite", choices=["base", "real"], default="base",
                    help="base: sentetik görev aileleri; real: gerçek istekler seti")
    ap.add_argument("--repeat", type=int, default=1, help="her görevi kaç kez koş")
    ap.add_argument("--resume", default="",
                    help="yarıda kalan ölçümün döküm dosyası (.jsonl): bitmiş görev+tekrarlar atlanır, aynı dosyaya eklenir")
    ap.add_argument("--no-hints", action="store_true",
                    help="tur ipuçlarını kapat (ablasyon: ipucunun etkisini ölçmek için)")
    args = ap.parse_args()

    load_env()
    settings = load_settings()
    if args.mode:
        settings = replace(settings, think=args.mode)
    if args.no_hints:
        settings = replace(settings, turn_hints=False)
    profile = args.profile or settings.default_profile

    if args.suite == "real" and not real.prompts_available():
        sys.exit(f"Gerçek istek metinleri yok: {real.PROMPTS_FILE}\nBkz. evals/real/README.md")
    families = real.FAMILIES if args.suite == "real" else all_families()
    only = [x for x in args.only.split(",") if x]

    def select() -> list:
        # Görevler (ve sahte dosyaları) her tekrarda yeniden kurulur: önceki koşunun bıraktıkları karışmasın.
        tasks = build_tasks(families, seed=args.seed)
        return [t for t in tasks if (args.split == "all" or t.split == args.split)
                and (not only or t.id in only or t.family in only or t.category in only)
                and (not t.opt_in or t.id in only or t.family in only)]

    tasks = select()

    if args.list:
        for t in tasks:
            p = t.prompt if isinstance(t.prompt, str) else " → ".join(t.prompt)
            print(f"[{t.split:4}] [{t.category:8}] z{t.difficulty} {t.id:24} {p[:110]}")
        print(f"\n{len(tasks)} görev")
        return

    client = LLMClient(settings, profile)
    suite = "" if args.suite == "base" else f" {args.suite}"
    label = f"v2{suite} {args.split} {profile} think={settings.think}{' ' + args.tag if args.tag else ''}"
    meta = {"profile": profile, "model": client.profile.model, "think": settings.think, "split": args.split,
            "seed": args.seed, "commit": gengar_commit(), "date": datetime.now().isoformat(timespec="seconds"),
            "num_ctx": client.profile.options.get("num_ctx"), "turn_hints": settings.turn_hints,
            "suite": args.suite, "repeat": args.repeat}
    TRAJ_ROOT.mkdir(parents=True, exist_ok=True)
    traj = TRAJ_ROOT / f"{datetime.now():%Y%m%d_%H%M%S}_{args.split}_{profile}{'_' + args.tag if args.tag else ''}.jsonl"
    results = []
    if args.resume:
        traj = Path(args.resume)
        records = [json.loads(line) for line in traj.read_text(encoding="utf-8").splitlines() if line.strip()]
        results = [result_from_record(r) for r in records]
        print(f"Devam: {len(results)} koşu zaten bitmiş ({traj.name})")
    done = {(r.id, r.rep) for r in results}
    times = f" × {args.repeat} tekrar" if args.repeat > 1 else ""
    print(f"Ölçüm v2: {label} — {len(tasks)} görev{times}, model {client.profile.model}\nDöküm: {traj}\n")

    for rep in range(args.repeat):
        if all((t.id, rep) in done for t in tasks):
            continue
        if rep:
            tasks = select()
        for i, t in enumerate(tasks, 1):
            if (t.id, rep) in done:
                continue
            tag = f"{rep + 1}. tekrar, " if args.repeat > 1 else ""
            print(f"[{tag}{i}/{len(tasks)}] [{t.category}/{t.id}] z{t.difficulty}")
            r = run_task(t, settings, client, traj, meta, rep=rep)
            results.append(r)
            print(f"  {'✅' if r.ok else '❌'} {r.seconds:5.1f} sn, {r.tool_calls} araç | {r.note[:120]}"
                  + (f" | HATA: {r.error[:100]}" if r.error else ""))

    summarize(results, label)
    if args.repeat > 1:
        print("\nGörev başına (geçen / tekrar):")
        for tid in dict.fromkeys(r.id for r in results):
            rs = [r for r in results if r.id == tid]
            print(f"  {sum(r.ok for r in rs)}/{len(rs)}  {tid}")
    out = save_results(results, label, meta)
    print(f"\nSonuç: {out}\nDöküm: {traj}")


if __name__ == "__main__":
    main()
