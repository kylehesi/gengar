"""Hazır (açık) veri setlerini Gengar'ın eğitim biçimine çevirir (3. aşama, INCELENECEK 9).

Neden: yalnızca kendi ürettiğimiz veriyle eğitilen model bizim işlerde iyileşip genel araç çağırmayı, araç
gerekmediğini anlamayı ve Türkçe sohbeti unutabilir (felaket unutma, INCELENECEK 8). Genel veri karıştırmak bunu
önler; etkisi BFCL alt kümesiyle (evals/bfcl.py) önce/sonra ölçülür.

Çıktı biçimi export_sft.py ile aynı: {"messages": [...], "tools": [...], "meta": {"source": ...}}; asistan araç
çağrıları OpenAI biçiminde `tool_calls`, araç sonuçları `tool` rolünde.

Kaynaklar (ön inceleme ve lisanslar: docs/OPEN_ISSUES.md 9). Satırlar HF satır arayüzünden JSONL olarak alınır;
indirme kullanıcının onayına bağlı (boyutlar orada).
- toucan       Agent-Ark/Toucan-1.5M (SFT)      çok adımlı araç kullanımı; `tool_call`/`tool_response` rolleri
- when2call    nvidia/When2Call (train_sft)     araç ÇAĞIRMAMA: eksik bilgiyi sormak, "yapamam" demek
- xlam_irrel   MadeAgents/xlam-irrelevance-7.5k araç çağırmama; asistan cevabı YOK → needs_reply (öğretmen yazar)
- tr_calls     atasoglu/turkish-function-calling-20k  Türkçe istekten araç çağrısı
- tr_xlam      bilalabic/turkish-tool-calling   xLAM'ın Türkçe çevirisi (sistem mesajı Türkçe)
- aya_tr       CohereLabs/aya_dataset (Türkçe)  genel Türkçe sohbet
- code         bigcode/self-oss-instruct-sc2-exec-filter-50k   kod
"""

from __future__ import annotations

import ast
import difflib
import json
import re
from collections.abc import Callable, Iterable
from typing import Any

Example = dict[str, Any]

# --- araç şemaları -----------------------------------------------------------------------------------------

_PY_TYPES = {"str": "string", "string": "string", "int": "integer", "integer": "integer", "float": "number",
             "number": "number", "bool": "boolean", "boolean": "boolean", "list": "array", "array": "array",
             "tuple": "array", "dict": "object", "object": "object"}


def py_type(t: str) -> dict:
    """Python tarzı tip adını JSON Schema'ya çevirir: "str, optional" → string, "List[int]" → int dizisi."""
    t = re.sub(r",?\s*optional\b", "", str(t), flags=re.IGNORECASE).strip()
    m = re.fullmatch(r"(?:typing\.)?(?:List|list|Tuple|tuple|Set|set)\[(.+)\]", t)
    if m:
        return {"type": "array", "items": py_type(m.group(1).split(",")[0])}
    if re.fullmatch(r"(?:typing\.)?(?:Dict|dict)\[.+\]", t):
        return {"type": "object"}
    if t.lower() in ("any", ""):
        return {}
    return {"type": _PY_TYPES.get(t.lower(), "string")}


def _is_optional(spec: dict) -> bool:
    return "optional" in str(spec.get("type", "")).lower()


def _param(spec: dict) -> dict:
    out = py_type(spec.get("type", "")) if isinstance(spec.get("type"), str) else {}
    if spec.get("description"):
        out["description"] = spec["description"]
    for key in ("enum", "items", "properties"):
        if key in spec and key not in out:
            out[key] = spec[key]
    if "default" in spec and spec["default"] not in ("", None):
        out["default"] = spec["default"]
    return out


def schema_from_params(params: dict) -> dict:
    """xLAM/When2Call parametreleri → JSON Schema. İki biçim var:
    - düz sözlük {ad: {type, description, default}} (xLAM): "optional" yazmayan zorunludur;
    - {"type": "dict", "properties": {...}, "required": [...]} (When2Call, BFCL benzeri)."""
    if "properties" in params and isinstance(params["properties"], dict):
        props = params["properties"]
        required = params.get("required")
    else:
        props = params
        required = None
    if required is None:
        required = [k for k, v in props.items() if isinstance(v, dict) and not _is_optional(v)]
    return {"type": "object", "properties": {k: _param(v) for k, v in props.items() if isinstance(v, dict)},
            "required": [r for r in required if r in props]}


def openai_tool(fn: dict | str) -> dict:
    """Her biçimdeki araç tanımını {"type": "function", "function": {...}} biçimine getirir."""
    if isinstance(fn, str):
        fn = json.loads(fn)
    if fn.get("type") == "function" and "function" in fn:
        fn = fn["function"]
    params = fn.get("parameters") or {}
    is_schema = params.get("type") == "object" and all(
        isinstance(v, dict) and not _is_optional(v) and str(v.get("type", "")) in _PY_TYPES.values()
        for v in params.get("properties", {}).values())
    return {"type": "function", "function": {
        "name": fn["name"], "description": fn.get("description", ""),
        "parameters": params if is_schema else schema_from_params(params)}}


def _tools(value: Any) -> list[dict]:
    items = json.loads(value) if isinstance(value, str) else (value or [])
    return [openai_tool(t) for t in items]


def _call(i: int, name: str, arguments: Any) -> dict:
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return {"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": arguments}}


# --- dönüştürücüler (satır → örnek; kullanılamayan satırda None) --------------------------------------------

def toucan(row: dict) -> Example | None:
    """`assistant` metni + ardından gelen `tool_call`'lar tek asistan mesajı olur; `tool_response` → `tool`."""
    msgs = json.loads(row["messages"]) if isinstance(row["messages"], str) else row["messages"]
    out: list[dict] = []
    pending: list[str] = []  # cevap bekleyen çağrı kimlikleri (sırayla)
    n = 0
    for m in msgs:
        role, content = m.get("role"), m.get("content") or ""
        if role in ("user", "system"):
            out.append({"role": role, "content": content})
        elif role == "assistant":
            out.append({"role": "assistant", "content": content})
        elif role == "tool_call":
            try:
                c = ast.literal_eval(content) if isinstance(content, str) else content
            except (ValueError, SyntaxError):
                return None
            if not out or out[-1]["role"] != "assistant":
                out.append({"role": "assistant", "content": ""})
            n += 1
            out[-1].setdefault("tool_calls", []).append(_call(n, c["name"], c.get("arguments", "{}")))
            pending.append(f"call_{n}")
        elif role == "tool_response":
            if not pending:
                return None
            out.append({"role": "tool", "tool_call_id": pending.pop(0), "content": content})
        else:
            return None
    if pending or not out or out[-1]["role"] != "assistant" or out[-1].get("tool_calls"):
        return None  # yarım kalmış akış: son söz asistanın metni olmalı
    return {"messages": out, "tools": _tools(row["tools"]), "meta": {"source": "toucan",
                                                                      "subset": row.get("subset_name", "")}}


def when2call(row: dict) -> Example | None:
    msgs = [{"role": m["role"], "content": m["content"]} for m in row["messages"]]
    if not msgs or msgs[-1]["role"] != "assistant" or "<TOOLCALL>" in msgs[-1]["content"]:
        return None  # train_sft'de yalnızca çağırmama örnekleri beklenir
    return {"messages": msgs, "tools": _tools(row["tools"]), "meta": {"source": "when2call"}}


def xlam_irrelevance(row: dict) -> Example | None:
    """Asistan cevabı yok (answers = []): öğretmen model araç çağırmadan cevap yazacak (needs_reply)."""
    if json.loads(row["answers"]) if isinstance(row["answers"], str) else row["answers"]:
        return None
    return {"messages": [{"role": "user", "content": row["query"]}], "tools": _tools(row["tools"]),
            "meta": {"source": "xlam_irrelevance", "needs_reply": True}}


def tr_calls(row: dict) -> Example | None:
    answers = json.loads(row["answers"]) if isinstance(row["answers"], str) else row["answers"]
    if not answers:
        return None
    calls = [_call(i, a["function"]["name"], a["function"].get("arguments", "{}")) for i, a in enumerate(answers, 1)]
    return {"messages": [{"role": "user", "content": row["query"]},
                         {"role": "assistant", "content": "", "tool_calls": calls}],
            "tools": _tools(row["tools"]), "meta": {"source": "tr_calls"}}


def tr_xlam(row: dict) -> Example | None:
    out, n = [], 0
    for m in row["messages"]:
        msg = {"role": m["role"], "content": m.get("content") or ""}
        if m.get("tool_calls"):
            msg["tool_calls"] = []
            for tc in m["tool_calls"]:
                n += 1
                msg["tool_calls"].append(_call(n, tc["function"]["name"], tc["function"].get("arguments", "{}")))
        if m["role"] == "tool":
            msg["tool_call_id"] = m.get("tool_call_id") or f"call_{n}"
        out.append(msg)
    if not any(m["role"] == "assistant" for m in out):
        return None
    return {"messages": out, "tools": _tools(row["tools"]), "meta": {"source": "tr_xlam"}}


def aya_tr(row: dict) -> Example | None:
    if row.get("language") != "Turkish" and row.get("language_code") != "tur":
        return None
    return {"messages": [{"role": "user", "content": row["inputs"]}, {"role": "assistant", "content": row["targets"]}],
            "tools": [], "meta": {"source": "aya_tr"}}


def code(row: dict) -> Example | None:
    return {"messages": [{"role": "user", "content": row["instruction"]},
                         {"role": "assistant", "content": row["response"]}], "tools": [], "meta": {"source": "code"}}


CONVERTERS: dict[str, Callable[[dict], Example | None]] = {
    "toucan": toucan, "when2call": when2call, "xlam_irrel": xlam_irrelevance, "tr_calls": tr_calls,
    "tr_xlam": tr_xlam, "aya_tr": aya_tr, "code": code,
}


# --- BFCL sızıntı kontrolü -----------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def first_user(ex: Example) -> str:
    return next((m["content"] for m in ex["messages"] if m["role"] == "user"), "")


def bfcl_leaks(examples: Iterable[Example], questions: Iterable[str], ratio: float = 0.9) -> list[int]:
    """BFCL sorularıyla aynı ya da çok benzer (difflib oranı ≥ ratio) ilk kullanıcı mesajı olan örneklerin sırası.

    Eğitim verisinde BFCL sorusu varsa "sonra" ölçümü şişer. Hız için önce kelime örtüşmesiyle aday elenir.
    """
    qs = [(_norm(q), set(_norm(q).split())) for q in questions]
    hits = []
    for i, ex in enumerate(examples):
        t = _norm(first_user(ex))
        words = set(t.split())
        for q, qw in qs:
            if t == q:
                hits.append(i)
                break
            if not words or len(words & qw) / max(len(words | qw), 1) < 0.5:
                continue
            if difflib.SequenceMatcher(None, t, q).ratio() >= ratio:
                hits.append(i)
                break
    return hits
