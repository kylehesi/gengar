from pathlib import Path

from gengar.config import Profile, load_env, load_settings
from gengar.doctor import normalize_model


def test_default_settings_load():
    s = load_settings()
    assert s.default_profile in s.profiles
    assert s.profiles["local"].is_local
    assert not s.profiles["gemini"].is_local


def test_load_env_does_not_override(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# yorum\nGENGAR_A=dosya\nGENGAR_B='tirnakli'\nBOS=\n", encoding="utf-8")
    monkeypatch.setenv("GENGAR_A", "ortam")
    monkeypatch.delenv("GENGAR_B", raising=False)
    monkeypatch.delenv("BOS", raising=False)

    load_env(env)

    import os
    assert os.environ["GENGAR_A"] == "ortam"
    assert os.environ["GENGAR_B"] == "tirnakli"
    assert "BOS" not in os.environ


def test_has_key(monkeypatch):
    p = Profile(name="x", model="gemini/x", key_env="GENGAR_TEST_KEY")
    monkeypatch.delenv("GENGAR_TEST_KEY", raising=False)
    assert not p.has_key()
    monkeypatch.setenv("GENGAR_TEST_KEY", "abc")
    assert p.has_key()


def test_normalize_model():
    assert normalize_model("bge-m3") == "bge-m3:latest"
    assert normalize_model("qwen3:8b") == "qwen3:8b"
