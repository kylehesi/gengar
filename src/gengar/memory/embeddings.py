"""Metni vektöre çevirme (embedding): Ollama + bge-m3.

bge-m3 CPU'da çalıştırılır (num_gpu=0). GPU'ya yüklenirse 8 GB VRAM'de Qwen3'ü
dışarı itiyor ve sohbet modeli her mesajda yeniden yükleniyor. CPU'da ilk yükleme
~2.5 sn, sonraki her çağrı ~0.05 sn (ölçüm: RTX 4060 Laptop, i5-13500H).
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request


class Embedder:
    def __init__(self, host: str, model: str = "bge-m3", on_cpu: bool = True, timeout: float = 60):
        self.host = host.rstrip("/")
        self.model = model
        self.on_cpu = on_cpu
        self.timeout = timeout
        self.available = True  # bir kez başarısız olursa oturum boyunca kelime aramasına düşülür

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Normalize edilmiş vektörler; Ollama/model yoksa None (çağıran kelime aramasına düşer)."""
        if not self.available or not texts:
            return None
        body = {"model": self.model, "input": texts, "keep_alive": "30m",
                "options": {"num_gpu": 0} if self.on_cpu else {}}
        req = urllib.request.Request(f"{self.host}/api/embed", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                vectors = json.load(r)["embeddings"]
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            self.available = False
            return None
        return [normalize(v) for v in vectors]


def normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def dot(a: list[float], b: list[float]) -> float:
    """Normalize vektörlerde iç çarpım = kosinüs benzerliği."""
    return sum(x * y for x, y in zip(a, b))
