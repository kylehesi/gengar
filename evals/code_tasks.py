"""Kod görevleri değerlendirmesi (Faz 5): aynı 3 görev farklı modellerde.

Kullanım:  uv run python evals/code_tasks.py <profil> [--think]
  örn.     uv run python evals/code_tasks.py local --think
           uv run python evals/code_tasks.py gemini

Görevler: A) asal sayı toplamı (1060), B) hatalı modülü testler geçene kadar düzeltme,
C) CSV + pandas ile ortalama (çalışma alanında olmalı). Sonuçlar otomatik doğrulanır.
Onaylar otomatik: silme/durdurma/kayıt defteri gibi tehlikeli komutlar hayır, gerisi evet.
Faz 8'de genel değerlendirme altyapısına taşınacak.
"""

import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(errors="replace")

from gengar.config import load_env, load_settings
from gengar.core import Agent, AuditLog, Conversation, PermissionPolicy, render_system_prompt
from gengar.llm import LLMClient
from gengar.tools import Risk, default_registry
from gengar.ui.repl import Repl

STATS = '''"""Basit istatistik fonksiyonları."""


def mean(values):
    """Aritmetik ortalama."""
    return sum(values) / (len(values) - 1)


def median(values):
    """Ortanca değer."""
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return s[n // 2]


def value_range(values):
    """En büyük ile en küçük değer arasındaki fark."""
    return max(values) - min(values)
'''

TESTS = '''from stats import mean, median, value_range

assert mean([2, 4, 6]) == 4, f"mean([2,4,6]) = {mean([2, 4, 6])}, beklenen 4"
assert mean([5]) == 5, "tek elemanlı ortalama"
assert median([3, 1, 2]) == 2, "tek sayıda eleman"
assert median([4, 1, 3, 2]) == 2.5, f"median([4,1,3,2]) = {median([4, 1, 3, 2])}, beklenen 2.5"
assert value_range([3, 9, 1]) == 8
print("TÜM TESTLER GEÇTİ")
'''


import re

DANGEROUS = re.compile(r"Remove-Item|\brm\b|\bdel\b|rmdir|Format-Volume|Stop-|shutdown|Restart-|\breg\b|"
                       r"Set-ItemProperty|Uninstall|Clear-", re.IGNORECASE)


class AutoRepl(Repl):
    def confirm(self, tool, summary, risk, can_grant):
        # Gerçek kullanıma yakın: tehlikeli görünen komutlar dışında her şeyi onayla.
        ok = not DANGEROUS.search(summary)
        answer = "yes" if ok else "no"
        first = summary.strip().splitlines()[0] if summary.strip() else ""
        self.print(f"[ONAY {risk.label}] {tool.name}: {first[:100]!r} -> {answer}")
        return answer

    def on_tool_end(self, call, output, ok):
        super().on_tool_end(call, output if len(output) < 500 else output[:500] + " …", ok)


def main():
    profile = next((a for a in sys.argv[1:] if not a.startswith("--")), "local")
    load_env()
    s = load_settings()
    ws = s.workspace
    client = LLMClient(s, profile)
    if "--think" in sys.argv:
        client.reasoning_override = "medium"

    # Görev B'nin hatalı dosyalarını her seferinde baştan oluştur
    bug = ws / "bugfix"
    shutil.rmtree(bug, ignore_errors=True)
    bug.mkdir(parents=True)
    (bug / "stats.py").write_text(STATS, encoding="utf-8")
    (bug / "test_stats.py").write_text(TESTS, encoding="utf-8")

    tasks = [
        ("A", "1'den 100'e kadar olan asal sayıları bulan ve toplamlarını yazdıran bir Python programı yaz, "
              "çalıştır ve sonucu söyle."),
        ("B", f"{bug} klasöründeki test_stats.py testleri başarısız oluyor. Testleri çalıştır, "
              "stats.py içindeki hataları düzelt ve testler geçene kadar devam et. Test dosyasını değiştirme."),
        ("C", "notlar adında bir proje klasörü oluştur. İçine 5 öğrencinin adını ve notunu içeren notlar.csv "
              "dosyası yaz. Sonra pandas kullanarak not ortalamasını hesaplayan bir program yaz, çalıştır ve "
              "ortalamayı söyle."),
    ]
    results = {}
    t_all = time.perf_counter()
    for key, task in tasks:
        agent = Agent(client, default_registry(s), PermissionPolicy("normal"), AuditLog(s.log_dir),
                      Conversation(render_system_prompt(s.system_prompt_path, workspace=ws),
                                   s.max_history_messages),
                      max_steps=s.max_steps)
        repl = AutoRepl(s, agent)
        print(f"\n========== [{key}] {task}")
        t = time.perf_counter()
        repl.ask(task)
        elapsed = time.perf_counter() - t
        steps = sum(1 for m in agent.conversation.history if m["role"] == "assistant")
        final = next((m["content"] for m in reversed(agent.conversation.history)
                      if m["role"] == "assistant" and m.get("content")), "")
        results[key] = (elapsed, steps, final)

    # --- doğrulama ---
    print("\n================ SONUÇ", profile, "(think)" if "--think" in sys.argv else "")
    a_ok = "1060" in results["A"][2]
    venv_py = s.sandbox_venv / "Scripts" / "python.exe"
    r = subprocess.run([str(venv_py), "test_stats.py"], cwd=bug, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    b_ok = r.returncode == 0 and "GEÇTİ" in r.stdout and (bug / "test_stats.py").read_text(encoding="utf-8") == TESTS
    csv = next(iter(ws.rglob("notlar.csv")), None)
    c_ok, c_note = False, "notlar.csv yok"
    if csv:
        import csv as csvmod
        raw = csv.read_bytes()
        text = raw.decode("utf-16") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-8-sig", "replace")
        rows = list(csvmod.reader(text.splitlines()))
        nums = []
        for row in rows[1:]:
            for cell in row:
                try:
                    nums.append(float(cell))
                    break
                except ValueError:
                    pass
        if nums:
            avg = sum(nums) / len(nums)
            c_note = f"gerçek ortalama {avg:g}"
            c_ok = any(f"{avg:{f}}".rstrip("0").rstrip(".") in results["C"][2].replace(",", ".")
                       for f in (".0f", ".1f", ".2f", "g"))
    for key, ok, note in (("A", a_ok, "1060 bekleniyor"), ("B", b_ok, r.stdout.strip()[-60:] or r.stderr.strip()[-120:]),
                          ("C", c_ok, c_note)):
        el, steps, _ = results[key]
        print(f"{key}: {'BAŞARILI' if ok else 'BAŞARISIZ':10} {el:6.1f} sn  {steps:2} adım  ({note})")
    print(f"TOPLAM {time.perf_counter() - t_all:.1f} sn")


main()
