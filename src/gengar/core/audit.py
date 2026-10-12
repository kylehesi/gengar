"""Denetim kaydı (audit log): Gengar'ın yaptığı/denediği her eylem logs/ altına yazılır.

Biçim JSON Lines: her satır bir olay. Günlük dosya: logs/audit-YYYY-MM-DD.jsonl
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_LOGGED_OUTPUT = 2000


class AuditLog:
    def __init__(self, directory: Path):
        self.directory = directory
        self.session = uuid.uuid4().hex[:8]

    @property
    def path(self) -> Path:
        return self.directory / f"audit-{datetime.now():%Y-%m-%d}.jsonl"

    def record(self, event: str, **fields: Any) -> None:
        entry = {"ts": datetime.now().isoformat(timespec="seconds"), "session": self.session,
                 "event": event, **fields}
        if isinstance(entry.get("output"), str) and len(entry["output"]) > MAX_LOGGED_OUTPUT:
            entry["output"] = entry["output"][:MAX_LOGGED_OUTPUT] + " ...[kesildi]"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass  # log yazılamaması asistanı durdurmamalı
