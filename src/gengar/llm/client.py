"""Tek arayüzle yerel (Ollama) ve API modelleriyle konuşan istemci.

LiteLLM'in üstünde ince bir katman: profil seçimi, akışlı (stream) yanıt,
istatistik toplama ve hataları kullanıcıya anlaşılır Türkçe mesajlara çevirme.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from ..config import Profile, Settings

# LiteLLM açılışta model fiyat listesini internetten çekmeye çalışır; paketle
# gelen yerel kopyayı kullansın ki internetsiz de hızlı açılsın.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

_litellm: Any = None
_import_lock = threading.Lock()


def _get_litellm() -> Any:
    """LiteLLM'i ilk ihtiyaçta yükler (içe aktarması birkaç saniye sürüyor)."""
    global _litellm
    with _import_lock:
        if _litellm is None:
            import litellm

            litellm.drop_params = True  # sağlayıcının desteklemediği parametreleri sessizce at
            litellm.suppress_debug_info = True
            _litellm = litellm
    return _litellm


def warm_up() -> None:
    """LiteLLM'i arka planda yükle; kullanıcı ilk mesajı yazarken hazır olsun."""
    threading.Thread(target=_get_litellm, daemon=True).start()


class LLMError(Exception):
    """Kullanıcıya gösterilebilecek, açıklamalı model hatası."""


@dataclass(frozen=True)
class Delta:
    """Akıştan gelen bir parça: yanıt metni ya da modelin düşünme metni."""

    kind: Literal["text", "thinking"]
    text: str


@dataclass(frozen=True)
class Stats:
    profile: str
    elapsed: float
    first_token: float | None
    output_tokens: int | None

    def summary(self) -> str:
        parts = [self.profile]
        if self.first_token is not None:
            parts.append(f"ilk token {self.first_token:.1f} sn")
        parts.append(f"{self.elapsed:.1f} sn")
        if self.output_tokens:
            parts.append(f"{self.output_tokens} token")
            gen_time = self.elapsed - (self.first_token or 0)
            if gen_time > 0:
                parts.append(f"{self.output_tokens / gen_time:.0f} tok/sn")
        return " · ".join(parts)


class LLMClient:
    def __init__(self, settings: Settings, profile: str | None = None):
        self.settings = settings
        self.profile = self._check(profile or settings.default_profile)
        self.reasoning_override: str | None = None  # /think ile oturum boyunca değişir
        self.last_stats: Stats | None = None

    def _check(self, name: str) -> Profile:
        profile = self.settings.profiles.get(name)
        if profile is None:
            names = ", ".join(self.settings.profiles)
            raise LLMError(f"'{name}' diye bir profil yok. Seçenekler: {names}")
        if not profile.has_key():
            raise LLMError(
                f"'{name}' profili için {profile.key_env} gerekli. "
                f".env dosyasına ekleyip Gengar'ı yeniden başlatın."
            )
        return profile

    def use(self, name: str) -> Profile:
        """Profili değiştir; geçersizse LLMError fırlatır ve eskisi kalır."""
        self.profile = self._check(name)
        return self.profile

    @property
    def reasoning_effort(self) -> str | None:
        return self.reasoning_override or self.profile.reasoning_effort

    @property
    def thinking_enabled(self) -> bool:
        return self.reasoning_effort not in (None, "none")

    def _request_args(self, messages: list[dict]) -> dict[str, Any]:
        args: dict[str, Any] = {
            **self.profile.options,
            "model": self.profile.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "timeout": self.settings.timeout,
        }
        if self.profile.is_local:
            args["api_base"] = self.settings.ollama_host
        if self.reasoning_effort is not None:
            args["reasoning_effort"] = self.reasoning_effort
        return args

    def stream_chat(self, messages: list[dict]) -> Iterator[Delta]:
        """Yanıtı parça parça üretir. Bitince `last_stats` dolar."""
        litellm = _get_litellm()
        self.last_stats = None
        start = time.perf_counter()
        first: float | None = None
        tokens: int | None = None

        try:
            for chunk in litellm.completion(**self._request_args(messages)):
                usage = getattr(chunk, "usage", None)
                if usage and getattr(usage, "completion_tokens", None):
                    tokens = usage.completion_tokens
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                thinking = getattr(delta, "reasoning_content", None)
                text = getattr(delta, "content", None)
                if (thinking or text) and first is None:
                    first = time.perf_counter() - start
                if thinking:
                    yield Delta("thinking", thinking)
                if text:
                    yield Delta("text", text)
        except Exception as e:  # LiteLLM sağlayıcıya göre çok çeşitli hatalar fırlatıyor
            raise _translate(e, self.profile, self.settings) from e

        self.last_stats = Stats(self.profile.name, time.perf_counter() - start, first, tokens)

    def complete(self, messages: list[dict]) -> str:
        """Akışsız kısayol: tüm yanıt metnini tek seferde döndürür."""
        return "".join(d.text for d in self.stream_chat(messages) if d.kind == "text")


def _translate(e: Exception, profile: Profile, settings: Settings) -> LLMError:
    """LiteLLM hatasını kullanıcının anlayacağı bir mesaja çevir."""
    litellm = _get_litellm()
    name = profile.name

    if isinstance(e, litellm.AuthenticationError):
        return LLMError(f"[{name}] API anahtarı geçersiz ({profile.key_env}).")
    if isinstance(e, litellm.RateLimitError):
        return LLMError(f"[{name}] Kullanım/hız limiti aşıldı. Biraz bekleyin ya da /model ile başka profile geçin.")
    if isinstance(e, litellm.ContextWindowExceededError):
        return LLMError(f"[{name}] Sohbet modelin bağlamına sığmıyor. /clear ile yeni sohbet başlatın.")
    if isinstance(e, litellm.NotFoundError):
        if profile.is_local:
            model = profile.model.split("/", 1)[1]
            return LLMError(f"[{name}] Model indirilmemiş. Çalıştırın: ollama pull {model}")
        return LLMError(f"[{name}] Model bulunamadı: {profile.model} (settings.toml'u kontrol edin)")
    if isinstance(e, litellm.Timeout):
        return LLMError(f"[{name}] Yanıt {settings.timeout:.0f} sn içinde gelmedi.")
    if isinstance(e, litellm.APIConnectionError):
        if profile.is_local:
            return LLMError(f"[{name}] Ollama'ya bağlanılamadı ({settings.ollama_host}). Ollama açık mı?")
        return LLMError(f"[{name}] Sağlayıcıya bağlanılamadı. İnternet bağlantısını kontrol edin.")
    return LLMError(f"[{name}] Beklenmeyen hata: {type(e).__name__}: {e}")
