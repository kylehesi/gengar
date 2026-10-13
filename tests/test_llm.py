"""LLM istemcisi testleri. Gerçek modele gitmez; litellm.completion taklit edilir."""

from types import SimpleNamespace as NS

import pytest

from gengar.config import load_settings
from gengar.llm import LLMClient, LLMError
from gengar.llm.client import _get_litellm


def chunk(content=None, thinking=None, tokens=None):
    choices = [] if content is None and thinking is None else [
        NS(delta=NS(content=content, reasoning_content=thinking))
    ]
    usage = NS(completion_tokens=tokens) if tokens else None
    return NS(choices=choices, usage=usage)


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def fake_completion(monkeypatch):
    """litellm.completion'ı, verilen parçaları döndüren sahte bir fonksiyonla değiştirir."""
    litellm = _get_litellm()
    calls = []

    def install(chunks=(), error=None):
        def completion(**kwargs):
            calls.append(kwargs)
            if error:
                raise error
            return iter(chunks)

        monkeypatch.setattr(litellm, "completion", completion)
        return calls

    return install


def test_stream_yields_thinking_and_text(settings, fake_completion):
    fake_completion([
        chunk(thinking="hmm"),
        chunk(content="Mer"),
        chunk(content="haba"),
        chunk(tokens=7),
    ])
    client = LLMClient(settings, "local")

    deltas = list(client.stream_chat([{"role": "user", "content": "selam"}]))

    assert [(d.kind, d.text) for d in deltas] == [
        ("thinking", "hmm"), ("text", "Mer"), ("text", "haba"),
    ]
    assert client.last_stats.output_tokens == 7
    assert client.last_stats.profile == "local"


def test_local_request_args(settings, fake_completion):
    calls = fake_completion([chunk(content="ok")])
    client = LLMClient(settings, "local")

    assert client.complete([]) == "ok"

    args = calls[0]
    assert args["model"] == "ollama_chat/qwen3:8b"
    assert args["api_base"] == settings.ollama_host
    assert args["reasoning_effort"] == "none"
    assert args["stream"] is True
    assert args["num_ctx"] == 8192  # profil options'ları iletiliyor


def test_think_override(settings, fake_completion):
    calls = fake_completion([chunk(content="ok")])
    client = LLMClient(settings, "local")
    assert not client.thinking_enabled

    client.reasoning_override = "medium"
    client.complete([])

    assert client.thinking_enabled
    assert calls[0]["reasoning_effort"] == "medium"


def test_api_profile_has_no_api_base(settings, fake_completion, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    calls = fake_completion([chunk(content="ok")])

    LLMClient(settings, "gemini").complete([])

    assert "api_base" not in calls[0]
    assert "reasoning_effort" not in calls[0]


def test_missing_key_rejected_and_old_profile_kept(settings, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = LLMClient(settings, "local")

    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        client.use("gemini")
    assert client.profile.name == "local"


def test_unknown_profile(settings):
    with pytest.raises(LLMError, match="profil yok"):
        LLMClient(settings, "yok-boyle-bir-sey")


def test_connection_error_is_translated(settings, fake_completion):
    litellm = _get_litellm()
    fake_completion(error=litellm.APIConnectionError("refused", "ollama", "qwen3:8b"))
    client = LLMClient(settings, "local")

    with pytest.raises(LLMError, match="Ollama'ya bağlanılamadı"):
        client.complete([])
    assert client.last_stats is None


def test_transient_api_errors_are_retried(settings, monkeypatch):
    from gengar.llm import client as client_mod

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(client_mod, "RETRY_DELAYS", (0, 0))
    litellm = _get_litellm()
    attempts = []

    def completion(**kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise litellm.ServiceUnavailableError("503 high demand", "gemini", "x")
        return iter([chunk(content="tamam")])

    monkeypatch.setattr(litellm, "completion", completion)
    assert LLMClient(settings, "gemini").complete([]) == "tamam"
    assert len(attempts) == 3


def test_retries_give_up_with_friendly_message(settings, monkeypatch):
    from gengar.llm import client as client_mod

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(client_mod, "RETRY_DELAYS", (0, 0))
    litellm = _get_litellm()

    def completion(**kwargs):
        raise litellm.ServiceUnavailableError("503", "gemini", "x")

    monkeypatch.setattr(litellm, "completion", completion)
    with pytest.raises(LLMError, match="yoğun"):
        LLMClient(settings, "gemini").complete([])


def test_rate_limit_waits_for_suggested_delay(settings, monkeypatch):
    from gengar.llm import client as client_mod

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    slept = []
    monkeypatch.setattr(client_mod.time, "sleep", slept.append)
    litellm = _get_litellm()
    attempts = []

    def completion(**kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise litellm.RateLimitError('quota... Please retry in 51.6s. "retryDelay": "51s"', "gemini", "x")
        return iter([chunk(content="ok")])

    monkeypatch.setattr(litellm, "completion", completion)
    deltas = list(LLMClient(settings, "gemini").stream_chat([]))
    assert slept == [pytest.approx(52.6)]
    assert deltas[0].kind == "status" and "53 sn" in deltas[0].text
    assert deltas[-1].text == "ok"


def test_rpm_paces_requests(settings, fake_completion, monkeypatch):
    from gengar.llm import client as client_mod

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    fake_completion([chunk(content="ok")])
    clock = [1000.0]
    slept = []
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: slept.append(s) or clock.__setitem__(0, clock[0] + s))

    c = LLMClient(settings, "gemini")  # settings.toml: rpm = 5 → 12 sn aralık
    assert c.profile.rpm == 5
    list(c.stream_chat([]))
    clock[0] += 3
    deltas = list(c.stream_chat([]))
    assert slept == [pytest.approx(9)]
    assert deltas[0].kind == "status" and "dakikada 5 istek" in deltas[0].text


def test_local_errors_are_not_retried(settings, monkeypatch):
    litellm = _get_litellm()
    attempts = []

    def completion(**kwargs):
        attempts.append(1)
        raise litellm.ServiceUnavailableError("down", "ollama", "x")

    monkeypatch.setattr(litellm, "completion", completion)
    with pytest.raises(LLMError):
        LLMClient(settings, "local").complete([])
    assert len(attempts) == 1


def test_rate_limit_is_translated(settings, fake_completion, monkeypatch):
    from gengar.llm import client as client_mod

    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)
    litellm = _get_litellm()
    fake_completion(error=litellm.RateLimitError("429", "gemini", "x"))

    with pytest.raises(LLMError, match="limit"):
        LLMClient(settings, "gemini").complete([])
