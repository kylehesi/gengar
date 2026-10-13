"""Hafıza: kullanıcı bilgileri, beceri kütüphanesi ve otomatik öğrenme (Faz 6).

Akış:
  1. Her kullanıcı mesajında ilgili bilgiler ve beceriler bulunup sistem
     promptuna eklenir (model `recall` çağırmayı unutsa bile görür).
  2. Model `remember` ile kullanıcı hakkında kalıcı bilgi, `save_skill` ile
     beceri kaydedebilir.
  3. Zor bir iş başarıyla bitince `Learner` turdan otomatik beceri çıkarmayı dener.
"""

from __future__ import annotations

import re
from typing import Any

from ..tools.base import Risk, Tool, ToolError
from .embeddings import Embedder
from .learn import Learner, worth_reflecting
from .store import Memory, MemoryStore

_REMEMBER = re.compile(r"\b(hatırla|hatirla|unutma|aklında tut|aklında bulundur|remember)\b", re.IGNORECASE)
_REMEMBER_PHRASE = re.compile(
    r"(lütfen\s+)?(bunu|bunları|şunu)?\s*(hatırla|hatirla|unutma|aklında tut|aklında bulundur|remember( this| that)?)"
    r"(\s+lütfen)?[.!]*", re.IGNORECASE)

# Bilgi sayısı bunu geçmezse hepsi her mesajda verilir (kullanıcı bilgileri genelde hep ilgilidir).
ALL_FACTS_LIMIT = 8
MAX_CODE_CHARS = 800


class MemorySystem:
    def __init__(self, store: MemoryStore, learner: Learner | None = None,
                 skill_min_score: float = 0.47, fact_min_score: float = 0.45, auto_learn: bool = True):
        self.store = store
        self.learner = learner
        self.skill_min_score = skill_min_score
        self.fact_min_score = fact_min_score
        self.auto_learn = auto_learn and learner is not None

    # --- her mesajda verilen bağlam ----------------------------------------

    def context_for(self, query: str) -> str:
        facts = self.store.all("fact")
        if len(facts) > ALL_FACTS_LIMIT:
            facts = self.store.search(query, "fact", k=5, min_score=self.fact_min_score)
        skills = self.store.search(query, "skill", k=2, min_score=self.skill_min_score)
        self.store.mark_used([s.id for s in skills])

        parts = []
        if facts:
            parts.append("What you remember about the user (from earlier sessions):\n"
                         + "\n".join(f"- {f.content}" for f in facts))
        if skills:
            parts.append("Skills you learned earlier that may fit this request. Reuse them if they "
                         "match, adapt them to the request, and still verify the result:\n"
                         + "\n\n".join(format_skill(s) for s in skills))
        return "\n\n".join(parts)

    # --- açık "hatırla" istekleri -------------------------------------------------

    @staticmethod
    def explicit_fact(user_text: str) -> str | None:
        """Kullanıcı açıkça "hatırla/unutma" dediyse hafızaya yazılacak cümle; yoksa None.

        Küçük modeller "kaydettim" deyip `remember` aracını çağırmayabiliyor (ölçümde gözlendi);
        açık isteği kaçırmamak için Gengar bunu kendisi kaydeder.
        """
        if not _REMEMBER.search(user_text):
            return None
        fact = _REMEMBER_PHRASE.sub("", user_text).strip(" .,!;:-")
        return fact if len(fact.split()) >= 3 else None

    # --- otomatik öğrenme -----------------------------------------------------

    def after_turn(self, messages: list[dict[str, Any]]) -> Memory | None:
        if not self.auto_learn or not worth_reflecting(messages):
            return None
        return self.learner.reflect(messages)

    def learn_now(self, messages: list[dict[str, Any]]) -> Memory | None:
        """/learn komutu: kurala bakmadan yansıtma yap."""
        return self.learner.reflect(messages) if self.learner else None

    # --- araçlar ------------------------------------------------------------

    def tools(self) -> list[Tool]:
        store = self.store

        def remember(fact: str) -> str:
            if not fact.strip():
                raise ToolError("hatırlanacak bilgi boş")
            mem, new = store.add("fact", fact[:80], fact)
            return f"{'Saved' if new else 'Updated'} memory #{mem.id}: {mem.content}"

        def recall(query: str) -> str:
            hits = store.search(query, k=5, min_score=0.35)
            if not hits:
                return f"Nothing in memory about '{query}'."
            return "\n\n".join(f"[{m.kind} #{m.id}, score {m.score:.2f}]\n"
                               + (format_skill(m) if m.kind == "skill" else m.content) for m in hits)

        def save_skill(name: str, description: str, steps: list[str] | None = None,
                       code: str = "", language: str = "") -> str:
            if not name.strip() or not description.strip():
                raise ToolError("beceri için ad (name) ve açıklama (description) gerekli")
            content = description.strip()
            if steps:
                content += "\nSteps:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
            mem, new = store.add("skill", name, content, code, language)
            return f"{'Saved' if new else 'Updated'} skill #{mem.id}: {mem.title}"

        return [
            Tool(
                name="remember",
                description=("Save a lasting fact or preference about the user or their setup for future "
                             "sessions (e.g. 'Projects are in D:\\Projeler', 'Prefers short answers'). "
                             "Use it when the user tells you such a fact or asks you to remember something."),
                parameters={"type": "object", "properties": {
                    "fact": {"type": "string", "description": "One self-contained sentence."}},
                    "required": ["fact"]},
                risk=Risk.READ, func=remember, describe=lambda a: str(a.get("fact", "")),
            ),
            Tool(
                name="recall",
                description="Search your long-term memory (user facts and learned skills).",
                parameters={"type": "object", "properties": {"query": {"type": "string"}},
                            "required": ["query"]},
                risk=Risk.READ, func=recall, describe=lambda a: str(a.get("query", "")),
            ),
            Tool(
                name="save_skill",
                description=("Save a reusable procedure after you solved a non-trivial task (especially "
                             "after research or fixing errors), so you can reuse it next time."),
                parameters={"type": "object", "properties": {
                    "name": {"type": "string", "description": "Short title."},
                    "description": {"type": "string", "description": "When to use it."},
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "code": {"type": "string", "description": "Exact working command/script, if any."},
                    "language": {"type": "string", "enum": ["powershell", "python", ""]}},
                    "required": ["name", "description"]},
                risk=Risk.READ, func=save_skill, describe=lambda a: str(a.get("name", "")),
            ),
        ]


def format_skill(s: Memory) -> str:
    text = f"### {s.title} (skill #{s.id})\n{s.content}"
    if s.code:
        code = s.code if len(s.code) <= MAX_CODE_CHARS else s.code[:MAX_CODE_CHARS] + "\n# ...(truncated)"
        text += f"\nCode ({s.language or 'text'}):\n```\n{code}\n```"
    return text


__all__ = ["Embedder", "Learner", "Memory", "MemoryStore", "MemorySystem", "format_skill"]
