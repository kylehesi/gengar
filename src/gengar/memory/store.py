"""Kalıcı hafıza: kullanıcı bilgileri (fact) ve öğrenilmiş beceriler (skill), SQLite'ta.

Neden ayrı bir vektör veritabanı (ChromaDB vb.) değil: kayıt sayısı yüzlerle
binler arasında; vektörler SQLite'ta ikili (float32) saklanıp tam tarama ile
karşılaştırılıyor (1000 kayıt ≈ birkaç ms). Ek bağımlılık ve sunucu gerekmiyor.

Embedding alınamazsa (Ollama kapalı vb.) kelime örtüşmesine göre arama yapılır.
"""

from __future__ import annotations

import sqlite3
from array import array
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ..tools.web import _stems
from .embeddings import Embedder, dot

Kind = Literal["fact", "skill"]

# Bu benzerliğin üstündeki yeni kayıt, eskisinin güncellenmiş hâli sayılır (çift kayıt olmasın).
DUPLICATE_SCORE = 0.92

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    embedding BLOB
);
"""


@dataclass
class Memory:
    id: int
    kind: str
    title: str
    content: str
    code: str = ""
    language: str = ""
    created: str = ""
    uses: int = 0
    score: float = 0.0

    def search_text(self) -> str:
        """Embedding'i alınacak metin: beceride ad + ne zaman kullanılır + adımların başı."""
        if self.kind == "skill":
            return f"{self.title}\n{self.content[:400]}"
        return self.content


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _pack(v: list[float] | None) -> bytes | None:
    return array("f", v).tobytes() if v else None


def _unpack(b: bytes | None) -> list[float] | None:
    if not b:
        return None
    a = array("f")
    a.frombytes(b)
    return a.tolist()


class MemoryStore:
    def __init__(self, path: Path, embedder: Embedder | None):
        self.path = path
        self.embedder = embedder
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- yazma ------------------------------------------------------------

    def _embed_one(self, text: str) -> list[float] | None:
        vectors = self.embedder.embed([text]) if self.embedder else None
        return vectors[0] if vectors else None

    def add(self, kind: Kind, title: str, content: str, code: str = "", language: str = "") -> tuple[Memory, bool]:
        """Kaydı ekler; çok benzer bir kayıt varsa onu günceller. (kayıt, yeni mi?) döner."""
        mem = Memory(0, kind, title.strip(), content.strip(), code.strip(), language.strip())
        vector = self._embed_one(mem.search_text())
        existing = self._best_match(kind, vector, mem.search_text())
        if existing and existing.score >= DUPLICATE_SCORE:
            self.db.execute(
                "UPDATE memories SET title=?, content=?, code=?, language=?, updated=?, embedding=? WHERE id=?",
                (mem.title, mem.content, mem.code, mem.language, _now(), _pack(vector), existing.id))
            self.db.commit()
            return self.get(existing.id), False
        cur = self.db.execute(
            "INSERT INTO memories (kind, title, content, code, language, created, updated, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, mem.title, mem.content, mem.code, mem.language, _now(), _now(), _pack(vector)))
        self.db.commit()
        return self.get(cur.lastrowid), True

    def delete(self, memory_id: int) -> bool:
        cur = self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self.db.commit()
        return cur.rowcount > 0

    def mark_used(self, ids: list[int]) -> None:
        if ids:
            self.db.executemany("UPDATE memories SET uses = uses + 1 WHERE id=?", [(i,) for i in ids])
            self.db.commit()

    # --- okuma ------------------------------------------------------------

    def _row(self, r: sqlite3.Row, score: float = 0.0) -> Memory:
        return Memory(r["id"], r["kind"], r["title"], r["content"], r["code"], r["language"],
                      r["created"], r["uses"], score)

    def get(self, memory_id: int) -> Memory | None:
        r = self.db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._row(r) if r else None

    def all(self, kind: Kind | None = None) -> list[Memory]:
        q, args = "SELECT * FROM memories", ()
        if kind:
            q, args = q + " WHERE kind=?", (kind,)
        return [self._row(r) for r in self.db.execute(q + " ORDER BY id", args)]

    def search(self, query: str, kind: Kind | None = None, k: int = 5, min_score: float = 0.0) -> list[Memory]:
        """Sorguya en benzer kayıtlar (anlamsal; embedding yoksa kelime örtüşmesi)."""
        if not query.strip():
            return []
        ranked = self._rank(kind, self._embed_one(query), query)
        return [m for m in ranked if m.score >= min_score][:k]

    def _best_match(self, kind: Kind, vector: list[float] | None, text: str) -> Memory | None:
        ranked = self._rank(kind, vector, text)
        return ranked[0] if ranked else None

    def _rank(self, kind: Kind | None, vector: list[float] | None, text: str) -> list[Memory]:
        q, args = "SELECT * FROM memories", ()
        if kind:
            q, args = q + " WHERE kind=?", (kind,)
        rows = self.db.execute(q, args).fetchall()
        query_stems = set(_stems(text))
        scored = []
        for r in rows:
            emb = _unpack(r["embedding"])
            if vector and emb and len(emb) == len(vector):
                score = dot(vector, emb)
            else:
                # Kelime yedeği: sorgudaki köklerin kayıtta geçme oranı.
                mem = self._row(r)
                stems = set(_stems(mem.search_text()))
                score = len(query_stems & stems) / len(query_stems) if query_stems else 0.0
            scored.append(self._row(r, score))
        return sorted(scored, key=lambda m: -m.score)

    def close(self) -> None:
        self.db.close()
