"""Ayarları (config/settings.toml) ve gizli anahtarları (.env) yükler."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.toml"
ENV_PATH = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class Profile:
    """Seçilebilir bir model: yerel (Ollama) ya da bir API sağlayıcısı."""

    name: str
    model: str
    description: str = ""
    key_env: str | None = None

    @property
    def is_local(self) -> bool:
        return self.model.startswith("ollama")

    def has_key(self) -> bool:
        if self.key_env is None:
            return True
        return bool(os.environ.get(self.key_env, "").strip())


@dataclass(frozen=True)
class Settings:
    profiles: dict[str, Profile]
    default_profile: str
    ollama_host: str
    required_models: list[str]
    raw: dict = field(repr=False)


def load_env(path: Path = ENV_PATH) -> None:
    """Basit .env okuyucu (KEY=VALUE satırları).

    Ortamda zaten tanımlı olan değişkenleri ezmez; böylece sistem ortam
    değişkeni .env dosyasından önceliklidir.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if key and value:
            os.environ.setdefault(key, value)


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    llm = raw.get("llm", {})
    profiles = {
        name: Profile(
            name=name,
            model=p["model"],
            description=p.get("description", ""),
            key_env=p.get("key_env"),
        )
        for name, p in llm.get("profiles", {}).items()
    }
    default = llm.get("default", "local")
    if default not in profiles:
        raise ValueError(f"settings.toml: varsayılan profil '{default}' tanımlı değil")

    ollama = raw.get("ollama", {})
    return Settings(
        profiles=profiles,
        default_profile=default,
        ollama_host=ollama.get("host", "http://localhost:11434").rstrip("/"),
        required_models=list(ollama.get("required_models", [])),
        raw=raw,
    )
