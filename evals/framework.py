"""Ölçüm v2 altyapısı: görev aileleri, dev/test bölünmesi, çalıştırma ve tam döküm kaydı.

Kavramlar
- Aile (Family): bir görev türü. `make(rng, root)` sahte dosyaları kurar ve bir Task döndürür.
  Aynı aileden farklı tohumlarla (seed) farklı görevler üretilir; 3. aşamada eğitim verisi de
  aynı ailelerden, ölçümde kullanılmayan tohumlarla üretilecek.
- Bölünme: her görev "dev" (ayar yaparken bakılır) ya da "test" (sadece rapor). `test_only`
  aileler hiç dev/eğitimde görünmez: eğitilen modelin görmediği iş türlerini ölçmek için.
- Döküm (trajectory): her çalıştırmanın sistem mesajı, araç şemaları, tüm mesajlar ve doğrulama
  sonucu JSONL olarak kaydedilir (data/trajectories). Doğrulanmış dökümler eğitim verisidir.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import subprocess
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from gengar.app import build_agent
from gengar.config import PROJECT_ROOT, Settings
from gengar.llm import LLMClient, LLMError
from gengar.ui.repl import Repl

BENCH_ROOT = PROJECT_ROOT / "data" / "bench2"
TRAJ_ROOT = PROJECT_ROOT / "data" / "trajectories"
RESULTS = PROJECT_ROOT / "evals" / "results"

DANGEROUS = re.compile(r"delete_files|Remove-Item|\brm\b|\bdel\b|rmdir|Format-Volume|Stop-|shutdown|Restart-|\breg\b|"
                       r"Set-ItemProperty|Uninstall|Clear-|apps.*kapat|winget", re.IGNORECASE)

Check = Callable[[str], tuple[bool, str]]


# --- görev ----------------------------------------------------------------------

@dataclass
class Task:
    id: str
    family: str
    category: str
    prompt: str | list[str]          # liste: ortak hafızayla ardışık oturumlar
    check: Check
    split: str = "dev"
    difficulty: int = 1              # 1 kolay, 2 orta, 3 zor (çok adımlı)
    # Onay politikası: "auto" (tehlikeli görünen hayır), "trust" (hepsi evet),
    # "deny" (hepsi hayır), ya da görev klasörü içindeki silmelere izin veren "sandbox".
    approval: str = "auto"
    memory: bool = False
    cleanup: Callable[[], None] | None = None
    root: Path | None = None
    # En fazla kaç araç çağrısına izin var? None: sınır yok. 0: araç gerekmeyen görev (notool ailesi);
    # cevap doğru olsa bile araç çağrıldıysa başarısız sayılır.
    max_tools: int | None = None


@dataclass
class Family:
    name: str
    category: str
    make: Callable[[random.Random, Path], Task]
    instances: int = 2
    test_only: bool = False


def variant(rng: random.Random, options: list | tuple):
    """Ailenin ana varyantını örnek sırasına göre seçer (aynı soru tekrar etmesin diye)."""
    return options[getattr(rng, "instance", 0) % len(options)]


def split_for(task_id: str) -> str:
    """Görev kimliğinden kararlı bölünme: yaklaşık yarısı dev, yarısı test."""
    return "dev" if int(hashlib.sha1(task_id.encode()).hexdigest(), 16) % 2 == 0 else "test"


def build_tasks(families: list[Family], seed: int = 1000, base: Path = BENCH_ROOT,
                instances: int | None = None, purpose: str = "bench") -> list[Task]:
    """Ailelerden görevleri üretir. `instances` verilirse her aileden o kadar örnek (veri üretimi için).

    purpose: "bench" (ölçüm) ya da "train" (eğitim verisi üretimi). Sabit soru listesinden seçen
    aileler (örn. notool) bununla listeyi ikiye ayırır: ölçüm soruları asla eğitim verisine girmez.
    """
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    tasks = []
    for fam in families:
        for i in range(instances if instances is not None else fam.instances):
            task_id = f"{fam.name}_{i}"
            rng = random.Random(f"{seed}:{task_id}")
            rng.instance = i + seed  # variant() için; farklı tohumlar farklı varyant sırası verir
            rng.purpose = purpose
            root = base / task_id
            root.mkdir(parents=True)
            t = fam.make(rng, root)
            t.id, t.family, t.category, t.root = task_id, fam.name, fam.category, root
            t.split = "test" if fam.test_only else split_for(task_id)
            tasks.append(t)
    return tasks


# --- doğrulama yardımcıları ------------------------------------------------------------

def numbers(text: str) -> list[float]:
    """Metindeki sayılar (Türkçe ondalık virgül ve binlik nokta dahil, her iki yorum)."""
    out = []
    for m in re.findall(r"\d[\d.,]*", text):
        s = m.rstrip(".,")
        cand = s
        if "," in s and "." in s:
            cand = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s:
            cand = s.replace(",", ".") if len(s.split(",")[-1]) != 3 else s.replace(",", "")
        try:
            out.append(float(cand))
        except ValueError:
            pass
        # Belirsiz biçimler iki türlü de yorumlanır: "1.060" (binlik nokta) ve "195,584" (ondalık virgül).
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
            out.append(float(s.replace(".", "")))
        if re.fullmatch(r"\d+,\d{3}", s):
            out.append(float(s.replace(",", ".")))
    return out


def near(text: str, truth: float, tol: float) -> bool:
    return any(abs(n - truth) <= tol for n in numbers(text))


def has(text: str, *words: str) -> bool:
    t = text.lower()
    return all(w.lower() in t for w in words)


def read(path: Path) -> str | None:
    if not path.exists():
        return None
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "gengar-bench"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def gengar_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
                              text=True).stdout.strip()
    except OSError:
        return "?"


# --- çalıştırma -----------------------------------------------------------------------

class QuietRepl(Repl):
    """Ekrana az şey basar; onayları görevin politikasına göre otomatik verir."""

    def __init__(self, *a, approval: str = "auto", root: Path | None = None, **kw):
        super().__init__(*a, **kw)
        self.approval = approval
        self.root = root

    def confirm(self, tool, summary, risk, can_grant):
        if self.approval == "trust":
            return "yes"
        if self.approval == "deny":
            return "no"
        if self.approval == "sandbox" and self.root and str(self.root).lower() in summary.lower():
            return "yes"  # görev klasörüyle sınırlı silme vb.
        return "no" if DANGEROUS.search(f"{tool.name} {summary}") else "yes"

    def on_delta(self, delta):
        if delta.kind == "status":
            super().on_delta(delta)

    def on_step_end(self, stats):
        pass

    def on_tool_start(self, call, summary, risk):
        self.print(f"    » {call.name} {summary.splitlines()[0][:110] if summary else ''}")

    def on_tool_end(self, call, output, ok):
        if not ok:
            self.print(f"      ✗ {output.splitlines()[0][:110] if output else ''}")


@dataclass
class Result:
    id: str
    family: str
    category: str
    split: str
    difficulty: int
    ok: bool
    note: str
    seconds: float
    tool_calls: int
    steps: int
    error: str = ""
    answer: str = ""
    tools: list[str] = field(default_factory=list)


def run_task(task: Task, settings: Settings, client: LLMClient, traj_file: Path | None,
             meta: dict[str, Any]) -> Result:
    # Hafıza gerçek kullanımdaki gibi hep açık (araç seti aynı olsun), ama her görevin kendi boş
    # hafıza dosyası var: görevler birbirini etkilemez. Hafıza görevlerinde oturumlar bu dosyayı paylaşır.
    # Dosya görev klasörünün DIŞINDA: içeride olsaydı dosya sayma/taşıma görevlerine karışıyordu.
    s = replace(settings, memory_db=task.root.parent / "_hafiza" / f"{task.id}.db")
    prompts = task.prompt if isinstance(task.prompt, list) else [task.prompt]
    start = time.perf_counter()
    answer, error, calls, steps, tools, sessions = "", "", 0, 0, [], []
    for p in prompts:
        agent = build_agent(s, client, memory=True,
                            permission_mode="trust" if task.approval == "trust" else "normal")
        if agent.memory:
            agent.memory.auto_learn = False  # ölçüm sırasında beceri öğrenme kapalı (görevler birbirini etkilemesin)
        repl = QuietRepl(s, agent, approval=task.approval, root=task.root)
        try:
            answer = agent.run(p, repl) or ""
        except LLMError as e:
            error = str(e)
        except Exception as e:  # ölçüm devam etsin
            error = f"{type(e).__name__}: {e}"
        hist = agent.conversation.history
        calls += sum(len(m.get("tool_calls") or []) for m in hist)
        steps += sum(1 for m in hist if m["role"] == "assistant")
        tools += [tc["function"]["name"] for m in hist for tc in (m.get("tool_calls") or [])]
        sessions.append({"system": agent.conversation.system_message, "tools": agent.tools.schemas(),
                         "messages": hist})
    elapsed = time.perf_counter() - start
    try:
        ok, note = task.check(answer)
    except Exception as e:
        ok, note = False, f"doğrulama hatası: {type(e).__name__}: {e}"
    ok, note = apply_tool_limit(task, bool(ok), str(note), tools)
    if error:
        ok = False
    if task.cleanup:
        try:
            task.cleanup()
        except Exception:
            pass
    result = Result(task.id, task.family, task.category, task.split, task.difficulty, bool(ok), str(note),
                    round(elapsed, 1), calls, steps, error, answer.strip()[:400], tools)
    if traj_file:
        record = {**meta, "task_id": task.id, "family": task.family, "category": task.category,
                  "split": task.split, "difficulty": task.difficulty, "ok": result.ok, "note": result.note,
                  "seconds": result.seconds, "error": error, "sessions": sessions}
        with traj_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return result


def apply_tool_limit(task: Task, ok: bool, note: str, tools: list[str]) -> tuple[bool, str]:
    """Görevin araç sınırı aşıldıysa (örn. araç gerekmeyen soruda araç çağrıldıysa) başarısız say."""
    if task.max_tools is not None and len(tools) > task.max_tools:
        return False, f"gereksiz araç ({len(tools)} > {task.max_tools}): {', '.join(tools)} | {note}"
    return ok, note


def summarize(results: list[Result], label: str) -> dict[str, Any]:
    def block(rs: list[Result]) -> str:
        return f"{sum(r.ok for r in rs)}/{len(rs)}" if rs else "-"

    print(f"\n=== {label}: {sum(r.ok for r in results)}/{len(results)} başarılı "
          f"(%{100 * sum(r.ok for r in results) / max(len(results), 1):.0f}), "
          f"toplam {sum(r.seconds for r in results):.0f} sn")
    for split in ("dev", "test"):
        rs = [r for r in results if r.split == split]
        if rs:
            print(f"  {split:5} {block(rs)}")
    cats = sorted({r.category for r in results})
    for c in cats:
        rs = [r for r in results if r.category == c]
        print(f"  {c:9} {block(rs):7} " + " ".join(f"{'✅' if r.ok else '❌'}{r.family}" for r in rs))
    for d in (1, 2, 3):
        rs = [r for r in results if r.difficulty == d]
        if rs:
            print(f"  zorluk {d}: {block(rs)}")
    return {"passed": sum(r.ok for r in results), "total": len(results)}


def save_results(results: list[Result], label: str, meta: dict[str, Any]) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d_%H%M%S}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', label)}.json"
    out.write_text(json.dumps({**meta, "label": label, "passed": sum(r.ok for r in results),
                               "total": len(results), "seconds": round(sum(r.seconds for r in results), 1),
                               "results": [r.__dict__ for r in results]}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return out
