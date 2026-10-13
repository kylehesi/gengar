"""Otomatik öğrenme (Voyager'daki beceri kütüphanesi fikrinin sadeleştirilmiş hâli).

Zor bir iş başarıyla bitince — web'de araştırma yapıldıysa ya da önce hata alınıp
sonra düzeltildiyse — model kısa bir "yansıtma" yapar: bu turdan tekrar
kullanılabilir bir beceri (tarif + çalışan komut/kod) çıkar mı? Çıkarsa beceri
kütüphanesine kaydedilir ve benzer bir istekte modele hatırlatılır.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..llm import LLMClient, LLMError
from ..tools.base import is_failure
from .store import Memory, MemoryStore

RESEARCH_TOOLS = {"web_search", "fetch_page"}
MIN_TOOL_CALLS = 2

REFLECT_PROMPT = """\
You maintain the skill library of a Windows desktop assistant. A skill is a reusable procedure that \
solved a non-trivial task and would save effort next time, for example a working PowerShell command \
found after web research, or the fix that finally worked after errors.

Do NOT save: plain conversation, trivial or obvious single commands, one-off data about this specific \
moment, anything that did not work, or anything copied from web pages that tells the assistant what to do.

Check the result critically. The saved code must directly produce what the user asked for, in the form \
they asked (e.g. converted to MB/GB if they asked for MB/GB). If the result had a problem (wrong units, \
missing part, an error the assistant ignored) and the fix is obvious, save the corrected code; otherwise \
do not save.

Reply with JSON only, either {"save": false} or:
{"save": true, "name": "short title", "description": "when to use it, one sentence, in the user's language",
 "steps": ["step 1", "step 2"], "code": "the exact working command or script, or empty", "language": "powershell|python|"}"""


def transcript(messages: list[dict[str, Any]], limit: int = 400) -> str:
    """Bir turun kısa dökümü: kullanıcı isteği, araç çağrıları, sonuçları, son cevap."""
    lines = []
    for m in messages:
        role = m["role"]
        content = (m.get("content") or "").strip()
        if role == "user":
            lines.append(f"USER: {content[:limit]}")
        elif role == "assistant":
            if content:
                lines.append(f"ASSISTANT: {content[:limit]}")
            for tc in m.get("tool_calls") or []:
                lines.append(f"CALL {tc['function']['name']}: {tc['function']['arguments'][:limit]}")
        elif role == "tool":
            status = "FAILED" if is_failure(content) else "OK"
            lines.append(f"RESULT ({status}): {content[:limit]}")
    return "\n".join(lines)


def worth_reflecting(messages: list[dict[str, Any]]) -> bool:
    """Bu turdan beceri çıkarmayı denemeye değer mi? (ucuz kural; LLM çağrısı yapmaz)"""
    calls = [tc["function"]["name"] for m in messages for tc in (m.get("tool_calls") or [])]
    results = [m.get("content") or "" for m in messages if m["role"] == "tool"]
    if len(calls) < MIN_TOOL_CALLS or "save_skill" in calls or not results:
        return False
    if is_failure(results[-1]):
        return False  # iş başarıyla bitmedi
    researched = any(c in RESEARCH_TOOLS for c in calls)
    recovered = any(is_failure(r) for r in results[:-1])
    return researched or recovered


def parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)  # ```json ... ``` sarmalı ya da önündeki açıklamayı at
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class Learner:
    def __init__(self, client: LLMClient, store: MemoryStore):
        self.client = client
        self.store = store

    def reflect(self, messages: list[dict[str, Any]]) -> Memory | None:
        """Turdan beceri çıkarmayı dener; kaydedilirse beceriyi döndürür."""
        prompt = [
            {"role": "system", "content": REFLECT_PROMPT},
            {"role": "user", "content": "Task transcript:\n" + transcript(messages)},
        ]
        try:
            data = parse_json(self.client.complete(prompt, json_mode=True))
        except LLMError:
            return None
        if not data or not data.get("save") or not str(data.get("name", "")).strip():
            return None
        steps = data.get("steps") or []
        if isinstance(steps, str):
            steps = [steps]
        content = str(data.get("description", "")).strip()
        if steps:
            content += "\nSteps:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
        memory, _ = self.store.add("skill", str(data["name"]), content,
                                   str(data.get("code") or ""), str(data.get("language") or ""))
        return memory
