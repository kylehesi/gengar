"""BFCL alt kümesi: genel araç çağırma ve "felaket unutma" ölçümü (INCELENECEK 8).

Kendi ölçüm setlerimiz yalnızca Gengar'ın araçlarını ölçüyor. Model yalnızca Gengar verisiyle eğitilirse bizim
işlerde iyileşip geri kalan her şeyde kötüleşebilir (catastrophic forgetting). Berkeley Function Calling
Leaderboard'un (BFCL, Apache-2.0) bir alt kümesi bunu gösterir: hiç görmediği araçlarla doğru çağrı yapabiliyor mu,
araç gerekmediğini anlayabiliyor mu (irrelevance)? Eğitimden ÖNCE ve SONRA aynı alt kümeyle ölçülür.

- Veri sabit bir commit'ten indirilir (COMMIT): "önce" ve "sonra" aynı sorularla ölçülsün.
- Kategoriler: tek çağrı (simple_python, live_simple), birkaç araç arasından seçim (multiple), aynı anda birden çok
  çağrı (parallel, parallel_multiple), araç çağırmamak (irrelevance, live_irrelevance). "live" sorular gerçek
  kullanıcılardan; diğerleri yazılmış.
- Kontrol, BFCL'in AST denetiminin sadeleştirilmiş hali: işlev adı, beklenmeyen parametre olmaması, zorunlu
  parametrelerin varlığı ve her değerin kabul edilen değerlerden biri olması (metinde büyük/küçük harf, boşluk
  ve noktalama yok sayılır; tam sayı ondalık yerine geçer). Paralel çağrılarda sıra önemsiz.
- Gengar'ın sistem promptu ve araçları KULLANILMAZ: model yalnızca sorunun kendi araçlarını görür (BFCL'in
  yerel araç çağırma, "FC", kurulumu). Düşünme Gengar'ın varsayılanı gibi kapalı.

Kullanım:
    uv run python evals/bfcl.py local35 --tag once           # ~260 soru
    uv run python evals/bfcl.py local35 --per-cat 5 --tag deneme
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from framework import RESULTS, gengar_commit  # noqa: E402
from gengar.config import PROJECT_ROOT, load_env, load_settings  # noqa: E402
from gengar.llm import LLMClient, LLMError  # noqa: E402

COMMIT = "f7cf7359b7ac615a0b294831c5ba2bc95ee4a000"  # 2025-12-17, "[BFCL] Multiple Dataset Fix ..."
BASE_URL = (f"https://raw.githubusercontent.com/ShishirPatil/gorilla/{COMMIT}/"
            "berkeley-function-call-leaderboard/bfcl_eval/data")
DATA = PROJECT_ROOT / "data" / "bfcl" / COMMIT[:8]
RUNS = PROJECT_ROOT / "data" / "bfcl" / "runs"

# Kategori → kaç soru (sabit tohumla seçilir). Toplam 260.
SUBSET = {"simple_python": 40, "multiple": 40, "parallel": 30, "parallel_multiple": 30, "live_simple": 40,
          "irrelevance": 40, "live_irrelevance": 40}
NO_CALL = {"irrelevance", "live_irrelevance"}  # doğru cevap: hiç araç çağırmamak


# --- veri -------------------------------------------------------------------------------------------------

def _files(cat: str) -> list[str]:
    names = [f"BFCL_v4_{cat}.json"]
    if cat not in NO_CALL:
        names.append(f"possible_answer/BFCL_v4_{cat}.json")
    return names


def fetch(cats: list[str]) -> None:
    """Eksik dosyaları sabit commit'ten indirir (data/bfcl/, gitignore)."""
    for cat in cats:
        for name in _files(cat):
            target = DATA / name
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"indiriliyor: {name}")
            with urllib.request.urlopen(f"{BASE_URL}/{name}", timeout=60) as r:
                target.write_bytes(r.read())


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class Item:
    id: str
    category: str
    messages: list[dict]
    functions: list[dict]
    truth: list[dict] | None  # [{işlev: {parametre: [kabul edilen değerler]}}]; NO_CALL'da None


def load(cat: str, n: int | None, seed: int = 0, data: Path = DATA) -> list[Item]:
    questions = _jsonl(data / f"BFCL_v4_{cat}.json")
    answers = {} if cat in NO_CALL else {a["id"]: a["ground_truth"]
                                          for a in _jsonl(data / "possible_answer" / f"BFCL_v4_{cat}.json")}
    if n is not None and n < len(questions):
        # Kategori adına bağlı sabit tohum: bir kategorinin sayısı değişse de diğerlerinin soruları değişmez.
        questions = random.Random(f"{seed}-{cat}").sample(questions, n)
    items = [Item(q["id"], cat, q["question"][0], q["function"], answers.get(q["id"])) for q in questions]
    return sorted(items, key=lambda it: int(re.sub(r"\D", "", it.id.rsplit("_", 1)[-1]) or 0))


# --- araç şeması ------------------------------------------------------------------------------------------

_TYPES = {"dict": "object", "float": "number", "tuple": "array", "integer": "integer", "string": "string",
          "boolean": "boolean", "array": "array", "object": "object", "number": "number"}


def to_schema(node: Any) -> Any:
    """BFCL'in Python tipli şemasını JSON Schema'ya çevirir (dict→object, float→number, tuple→array, any→serbest)."""
    if isinstance(node, list):
        return [to_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "type" and isinstance(v, str):
            if v == "any":
                continue  # tip kısıtı yok
            out[k] = _TYPES.get(v, v)
        elif k == "properties" and isinstance(v, dict):
            out[k] = {name: to_schema(p) for name, p in v.items()}
        else:
            out[k] = to_schema(v)
    return out


def safe_name(name: str) -> str:
    """OpenAI uyumlu araç adı ("math.factorial" → "math_factorial"); BFCL'deki BFCL FC kurulumu da böyle yapar."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def tools_for(functions: list[dict]) -> tuple[list[dict], dict[str, str]]:
    tools, names = [], {}
    for f in functions:
        name = safe_name(f["name"])
        names[name] = f["name"]
        tools.append({"type": "function", "function": {
            "name": name, "description": f.get("description", ""),
            "parameters": to_schema(f.get("parameters", {"type": "object", "properties": {}}))}})
    return tools, names


# --- kontrol ----------------------------------------------------------------------------------------------

def _norm(s: str) -> str:
    # BFCL'in metin standardizasyonu: boşluk ve , . / - _ * ^ yok sayılır, küçük harf, ' → "
    return re.sub(r"[ ,./\-_*^]", "", s).lower().replace("'", '"')


def _same(v: Any, a: Any) -> bool:
    """Modelin değeri v, kabul edilen tek bir değer a ile eşleşiyor mu?"""
    if isinstance(a, bool) or isinstance(v, bool):
        return isinstance(a, bool) and isinstance(v, bool) and a == v
    if isinstance(a, (int, float)) and isinstance(v, (int, float)):
        return float(a) == float(v) and not (isinstance(a, int) and isinstance(v, float) and not v.is_integer())
    if isinstance(a, str) and isinstance(v, str):
        return _norm(a) == _norm(v)
    if isinstance(a, list) and isinstance(v, list):
        return len(a) == len(v) and all(_same(x, y) for x, y in zip(v, a, strict=True))
    if isinstance(a, dict) and isinstance(v, dict):
        # İç içe sözlükte her anahtarın değeri yine bir kabul listesi (BFCL biçimi).
        return params_ok(v, a)[0]
    return False


def _value_ok(value: Any, allowed: list) -> bool:
    return any(_same(value, a) for a in allowed if a != "")


def params_ok(args: dict, expected: dict) -> tuple[bool, str]:
    extra = [k for k in args if k not in expected]
    if extra:
        return False, f"beklenmeyen parametre: {', '.join(extra)}"
    for k, allowed in expected.items():
        allowed = allowed if isinstance(allowed, list) else [allowed]
        if not allowed:
            # Birkaç live sorusunda kabul listesi boş ([]): olduğu gibi okunursa hiçbir cevap geçemez. Liste tipli
            # parametrenin boş olduğu anlamında yorumlanır: verilmemiş ya da boş liste.
            allowed = ["", []]
        if k not in args:
            if "" not in allowed:
                return False, f"eksik parametre: {k}"
        elif not _value_ok(args[k], allowed):
            return False, f"{k}={json.dumps(args[k], ensure_ascii=False)[:60]} kabul edilenlerden değil"
    return True, ""


def call_ok(name: str, args: dict, expected: dict) -> tuple[bool, str]:
    want = next(iter(expected))
    if name != want:
        return False, f"işlev {name}, beklenen {want}"
    return params_ok(args, expected[want])


def check(item: Item, calls: list[tuple[str, dict]]) -> tuple[bool, str]:
    """calls: (asıl işlev adı, argümanlar). Paralelde sıra önemsiz (her beklenen çağrıya bir model çağrısı)."""
    if item.category in NO_CALL:
        return (not calls, "araç çağırmadı" if not calls else f"gereksiz çağrı: {calls[0][0]}")
    truth = item.truth or []
    if len(calls) != len(truth):
        return False, f"{len(calls)} çağrı, beklenen {len(truth)}"

    first_reason = ""

    def assign(i: int, used: set[int]) -> bool:
        nonlocal first_reason
        if i == len(truth):
            return True
        for j, (name, args) in enumerate(calls):
            if j in used:
                continue
            ok, why = call_ok(name, args, truth[i])
            if ok and assign(i + 1, used | {j}):
                return True
            first_reason = first_reason or why
        return False

    return (True, "doğru") if assign(0, set()) else (False, first_reason or "eşleşmedi")


# --- çalıştırma -------------------------------------------------------------------------------------------

def ask(client: LLMClient, item: Item) -> tuple[list[tuple[str, dict]], str, str]:
    """Modele sorar: (çağrılar, cevap metni, hata)."""
    tools, names = tools_for(item.functions)
    text = []
    try:
        for delta in client.stream_chat(item.messages, tools):
            if delta.kind == "text":
                text.append(delta.text)
    except LLMError as e:
        return [], "", str(e)
    calls = []
    for tc in client.last_tool_calls:
        try:
            args = tc.parsed_args()
        except ValueError:
            return [], "".join(text), f"geçersiz argüman JSON'u: {tc.arguments[:80]}"
        calls.append((names.get(tc.name, tc.name), args))
    return calls, "".join(text), ""


def run(client: LLMClient, items: list[Item], traj: Path | None = None) -> list[dict]:
    rows = []
    for i, item in enumerate(items, 1):
        start = time.perf_counter()
        calls, text, error = ask(client, item)
        ok, note = (False, error) if error else check(item, calls)
        row = {"id": item.id, "category": item.category, "ok": ok, "note": note,
               "seconds": round(time.perf_counter() - start, 1), "calls": [[n, a] for n, a in calls],
               "text": text[:300]}
        rows.append(row)
        print(f"[{i}/{len(items)}] {'✅' if ok else '❌'} {item.id:28} {row['seconds']:5.1f} sn  {note}")
        if traj:
            with traj.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**row, "messages": item.messages}, ensure_ascii=False) + "\n")
    return rows


def summarize(rows: list[dict]) -> dict[str, Any]:
    cats = {}
    for cat in SUBSET:
        rs = [r for r in rows if r["category"] == cat]
        if rs:
            cats[cat] = {"passed": sum(r["ok"] for r in rs), "total": len(rs)}
    call = [r for r in rows if r["category"] not in NO_CALL]
    nocall = [r for r in rows if r["category"] in NO_CALL]
    return {
        "categories": cats,
        # İki ayrı beceri: doğru çağrı yapmak ve gerekmeyince çağırmamak. Ortalama, ikisini eşit tartar.
        "call_accuracy": round(sum(r["ok"] for r in call) / len(call), 3) if call else None,
        "no_call_accuracy": round(sum(r["ok"] for r in nocall) / len(nocall), 3) if nocall else None,
        "passed": sum(r["ok"] for r in rows), "total": len(rows),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="BFCL alt kümesi (genel araç çağırma / unutma ölçümü)")
    ap.add_argument("profile", nargs="?", help="settings.toml profili (varsayılan: default_profile)")
    ap.add_argument("--tag", default="", help="sonuç dosyası etiketi (örn. once, sonra)")
    ap.add_argument("--per-cat", type=int, default=None, help="her kategoriden kaç soru (varsayılan: SUBSET)")
    ap.add_argument("--only", default="", help="virgülle kategoriler")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    cats = [c for c in SUBSET if not args.only or c in args.only.split(",")]
    fetch(cats)
    items = [it for c in cats for it in load(c, args.per_cat or SUBSET[c], args.seed)]

    load_env()
    settings = load_settings()
    client = LLMClient(settings, args.profile or settings.default_profile)
    if settings.think == "off":
        client.reasoning_override = "none"  # Gengar'ın varsayılanı gibi
    label = f"bfcl_{client.profile.name}{'_' + args.tag if args.tag else ''}"
    RUNS.mkdir(parents=True, exist_ok=True)
    traj = RUNS / f"{datetime.now():%Y%m%d_%H%M%S}_{label}.jsonl"
    print(f"BFCL alt kümesi ({COMMIT[:8]}): {len(items)} soru, model {client.profile.model}\nDöküm: {traj}\n")

    rows = run(client, items, traj)
    summary = summarize(rows)
    print(f"\n=== {label}: {summary['passed']}/{summary['total']}  çağrı doğruluğu {summary['call_accuracy']}  "
          f"çağırmama doğruluğu {summary['no_call_accuracy']}")
    for cat, s in summary["categories"].items():
        print(f"  {cat:18} {s['passed']}/{s['total']}")
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d_%H%M%S}_{label}.json"
    out.write_text(json.dumps({"profile": client.profile.name, "model": client.profile.model, "bfcl_commit": COMMIT,
                               "seed": args.seed, "think": settings.think, "commit": gengar_commit(),
                               "date": datetime.now().isoformat(timespec="seconds"), **summary, "results": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSonuç: {out}")


if __name__ == "__main__":
    main()
