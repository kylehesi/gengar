"""Tek arayüzle yerel (Ollama) ve API modelleriyle konuşan istemci.

LiteLLM'in üstünde ince bir katman: profil seçimi, akışlı (stream) yanıt,
istatistik toplama ve hataları kullanıcıya anlaşılır Türkçe mesajlara çevirme.
"""

from __future__ import annotations

import json
import os
import re
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

# API sağlayıcısı geçici hata verirse (yoğunluk, zaman aşımı) bu aralıklarla tekrar dene (sn).
RETRY_DELAYS = (2.0, 5.0)


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
    """Akıştan gelen bir parça: yanıt metni, modelin düşünme metni ya da durum bilgisi
    (örn. "sağlayıcı limiti, 20 sn bekleniyor"; modele geri gönderilmez)."""

    kind: Literal["text", "thinking", "status"]
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
            # Yanıt tek parçada geldiyse (örn. sadece araç çağrısı) hız anlamsız olur.
            if gen_time > 0.25:
                parts.append(f"{self.output_tokens / gen_time:.0f} tok/sn")
        return " · ".join(parts)


@dataclass(frozen=True)
class ToolCall:
    """Modelin istediği bir araç çağrısı. `arguments` JSON metnidir."""

    id: str
    name: str
    arguments: str

    def parsed_args(self) -> dict[str, Any]:
        """Argümanları sözlüğe çevirir; geçersiz JSON'da ValueError."""
        if not self.arguments.strip():
            return {}
        args = json.loads(self.arguments)
        if not isinstance(args, dict):
            raise ValueError("argümanlar bir JSON nesnesi olmalı")
        return args

    def to_message(self) -> dict[str, Any]:
        return {"id": self.id, "type": "function",
                "function": {"name": self.name, "arguments": self.arguments}}


class _ToolCallBuffer:
    """Akışta parça parça gelen araç çağrılarını birleştirir.

    OpenAI tarzı sağlayıcılar bir çağrıyı parçalara böler (ilk parçada id+ad,
    sonrakilerde argüman devamı, hepsi aynı `index` ile). Ollama ise çağrıyı
    tek parçada ve argümanları sözlük olarak gönderir. İkisini de destekler.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._by_index: dict[int, dict[str, Any]] = {}

    def add(self, tc: Any) -> None:
        idx = getattr(tc, "index", None)
        tc_id = getattr(tc, "id", None) or None
        fn = getattr(tc, "function", None)
        name = getattr(fn, "name", None) if fn else None
        args = getattr(fn, "arguments", None) if fn else None
        if isinstance(args, dict):
            args = json.dumps(args, ensure_ascii=False)

        cur = self._by_index.get(idx) if idx is not None else None
        if cur is None and idx is None and self.calls and not tc_id and not name:
            cur = self.calls[-1]  # index'siz devam parçası
        if cur is None or (tc_id and cur["id"] and tc_id != cur["id"]):
            cur = {"id": tc_id, "name": "", "arguments": ""}
            self.calls.append(cur)
            if idx is not None:
                self._by_index[idx] = cur
        if tc_id and not cur["id"]:
            cur["id"] = tc_id
        if name and not cur["name"]:
            cur["name"] = name
        if args:
            cur["arguments"] += args

    def finish(self) -> list[ToolCall]:
        return [
            ToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments=c["arguments"])
            for i, c in enumerate(self.calls)
            if c["name"]
        ]


class LLMClient:
    def __init__(self, settings: Settings, profile: str | None = None):
        self.settings = settings
        self.profile = self._check(profile or settings.default_profile)
        self.reasoning_override: str | None = None  # /think ile oturum boyunca değişir
        self.last_stats: Stats | None = None
        self.last_tool_calls: list[ToolCall] = []
        self.last_finish_reason: str | None = None
        self._last_request: dict[str, float] = {}  # profil → son istek zamanı (rpm için)

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

    @property
    def context_tokens(self) -> int | None:
        """Modelin bağlam penceresi; bilinmiyorsa None (API modelleri için genelde çok büyük)."""
        n = self.profile.options.get("num_ctx")
        return int(n) if n else None

    @property
    def timeout(self) -> float:
        """Modelden hiç veri gelmeden beklenecek en uzun süre (yerel modelde daha uzun, bkz. settings.toml)."""
        return self.settings.local_timeout if self.profile.is_local else self.settings.timeout

    def _request_args(self, messages: list[dict], tools: list[dict] | None,
                      json_mode: bool = False) -> dict[str, Any]:
        args: dict[str, Any] = {
            **self.profile.options,
            "model": self.profile.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "timeout": self.timeout,
        }
        if self.profile.is_local:
            args["api_base"] = self.settings.ollama_host
        if self.reasoning_effort is not None:
            args["reasoning_effort"] = self.reasoning_effort
        if tools:
            args["tools"] = tools
        if json_mode:
            args["response_format"] = {"type": "json_object"}  # Ollama'da format=json olur
        return args

    def stream_chat(self, messages: list[dict], tools: list[dict] | None = None,
                    json_mode: bool = False) -> Iterator[Delta]:
        """Yanıtı parça parça üretir. Bitince `last_stats` ve `last_tool_calls` dolar."""
        litellm = _get_litellm()
        self.last_stats = None
        self.last_tool_calls = []
        # "length": yanıt bağlam/uzunluk sınırında kesildi (yarım araç çağrısı hiç gelmez, cevap boş görünür).
        self.last_finish_reason: str | None = None
        yield from self._pace()
        start = time.perf_counter()
        first: float | None = None
        tokens: int | None = None
        calls = _ToolCallBuffer()

        for attempt in range(len(RETRY_DELAYS) + 1):
            self._last_request[self.profile.name] = time.monotonic()
            try:
                for chunk in litellm.completion(**self._request_args(messages, tools, json_mode)):
                    usage = getattr(chunk, "usage", None)
                    if usage and getattr(usage, "completion_tokens", None):
                        tokens = usage.completion_tokens
                    if not chunk.choices:
                        continue
                    finish = getattr(chunk.choices[0], "finish_reason", None)  # her parçada/sağlayıcıda olmayabilir
                    if finish:
                        self.last_finish_reason = finish
                    delta = chunk.choices[0].delta
                    thinking = getattr(delta, "reasoning_content", None)
                    text = getattr(delta, "content", None)
                    tool_calls = getattr(delta, "tool_calls", None) or []
                    if (thinking or text or tool_calls) and first is None:
                        first = time.perf_counter() - start
                    for tc in tool_calls:
                        calls.add(tc)
                    if thinking:
                        yield Delta("thinking", thinking)
                    if text:
                        yield Delta("text", text)
                break
            except Exception as e:  # LiteLLM sağlayıcıya göre çok çeşitli hatalar fırlatıyor
                # Henüz hiçbir şey üretilmediyse ve hata geçiciyse (yoğunluk, limit, zaman aşımı) bekle, tekrar dene.
                if first is None and attempt < len(RETRY_DELAYS) and _is_transient(e, self.profile):
                    delay = _retry_after(e)
                    if delay is not None:
                        yield Delta("status", f"sağlayıcı istek limiti doldu, {delay:.0f} sn bekleniyor…")
                    else:
                        delay = RETRY_DELAYS[attempt]
                        yield Delta("status", f"sağlayıcı yanıt vermedi, {delay:.0f} sn sonra tekrar deneniyor…")
                    time.sleep(delay)
                    continue
                raise _translate(e, self.profile, self.settings) from e

        self.last_tool_calls = calls.finish()
        self.last_stats = Stats(self.profile.name, time.perf_counter() - start, first, tokens)

    def _pace(self) -> Iterator[Delta]:
        """Profilde `rpm` (dakikada istek) sınırı varsa istekleri aralıklandır.

        Ücretsiz API katmanları dakikada çok az isteğe izin veriyor (örn. Gemini: 5);
        bir agent görevi kolayca 5-10 istek attığından, hata almak yerine önceden beklemek
        daha öngörülebilir.
        """
        if not self.profile.rpm:
            return
        last = self._last_request.get(self.profile.name)
        if last is None:
            return
        wait = last + 60 / self.profile.rpm - time.monotonic()
        if wait > 0.5:
            yield Delta("status", f"{self.profile.name} dakikada {self.profile.rpm} istek sınırı: "
                                  f"{wait:.0f} sn bekleniyor…")
            time.sleep(wait)

    def complete(self, messages: list[dict], json_mode: bool = False) -> str:
        """Akışsız kısayol: tüm yanıt metnini tek seferde döndürür."""
        return "".join(d.text for d in self.stream_chat(messages, json_mode=json_mode) if d.kind == "text")


def _unwrap(e: Exception) -> Exception:
    """LiteLLM bazı hataları 'akış ortasında hata' içine sarar; asıl hatayı çıkar."""
    return getattr(e, "original_exception", None) or e


MAX_RETRY_AFTER = 65.0


def _retry_after(e: Exception) -> float | None:
    """Limit hatasında sağlayıcının önerdiği bekleme süresi ("retry in 51.6s" / "retryDelay": "51s")."""
    litellm = _get_litellm()
    if not isinstance(_unwrap(e), litellm.RateLimitError) and not isinstance(e, litellm.RateLimitError):
        return None
    m = re.search(r"retry in (\d+(?:\.\d+)?)s|\"retryDelay\":\s*\"(\d+(?:\.\d+)?)s\"", str(_unwrap(e)))
    seconds = float(m.group(1) or m.group(2)) + 1 if m else 20.0
    return min(seconds, MAX_RETRY_AFTER)


def _is_transient(e: Exception, profile: Profile) -> bool:
    """Tekrar denemeye değer, geçici bir hata mı? (sağlayıcı yoğun, zaman aşımı, 5xx)"""
    litellm = _get_litellm()
    inner = _unwrap(e)
    if profile.is_local:
        # Ollama kapalıysa (bağlantı hatası) beklemek işe yaramaz; ama model yüklenirken/değişirken
        # verdiği 5xx hataları geçicidir.
        server_side = (litellm.ServiceUnavailableError, litellm.InternalServerError)
        connection = isinstance(e, litellm.APIConnectionError) and not isinstance(e, server_side)
        return not connection and (isinstance(e, server_side) or isinstance(inner, server_side))
    return isinstance(e, (litellm.ServiceUnavailableError, litellm.InternalServerError, litellm.Timeout)) \
        or isinstance(inner, (litellm.ServiceUnavailableError, litellm.InternalServerError,
                              litellm.Timeout, litellm.RateLimitError))


def _translate(e: Exception, profile: Profile, settings: Settings) -> LLMError:
    """LiteLLM hatasını kullanıcının anlayacağı bir mesaja çevir."""
    litellm = _get_litellm()
    name = profile.name
    e = _unwrap(e)

    if isinstance(e, litellm.ServiceUnavailableError) or isinstance(e, litellm.InternalServerError):
        if profile.is_local:
            return LLMError(f"[{name}] Ollama hata verdi (tekrar denendi): {str(e)[:200]}. Model yükleniyor ya da "
                            f"VRAM yetmiyor olabilir; biraz sonra tekrar deneyin.")
        return LLMError(f"[{name}] Sağlayıcı şu an yoğun ya da hata veriyor (tekrar denendi). "
                        f"Biraz sonra deneyin ya da /model ile başka profile geçin.")
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
        limit = settings.local_timeout if profile.is_local else settings.timeout
        return LLMError(f"[{name}] Model {limit:.0f} sn boyunca hiç veri göndermedi, istek kesildi. Çok uzun bir "
                        f"cevap ya da dosya içeriği yazıyor olabilir: isteği bölün (örn. önce ilk yarısını "
                        f"kaydet) ya da settings.toml'daki {'local_timeout' if profile.is_local else 'timeout'} "
                        f"değerini artırın. İstek sohbette duruyor; 'tekrar dene' diyebilirsiniz.")
    if isinstance(e, litellm.APIConnectionError):
        if profile.is_local:
            return LLMError(f"[{name}] Ollama'ya bağlanılamadı ({settings.ollama_host}). Ollama açık mı?")
        return LLMError(f"[{name}] Sağlayıcıya bağlanılamadı. İnternet bağlantısını kontrol edin.")
    return LLMError(f"[{name}] Beklenmeyen hata: {type(e).__name__}: {e}")
