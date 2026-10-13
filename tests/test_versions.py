"""Sürüm kontrol aracı testleri: internete çıkmaz, resmi API cevapları taklit edilir."""

import urllib.error

import pytest

from gengar.tools import versions


@pytest.fixture
def fake(monkeypatch):
    responses = {}

    def get_json(url):
        for key, value in responses.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"beklenmeyen adres: {url}")

    monkeypatch.setattr(versions, "_get_json", get_json)
    monkeypatch.setattr(versions, "local_version", lambda cmd, name: ("2.55.0", f"{cmd} --version"))
    return responses


def test_github_latest_and_update_available(fake):
    fake["git-for-windows/git/releases/latest"] = {"tag_name": "v2.56.0.windows.1"}
    out = versions.software_version("git")
    assert "installed 2.55.0" in out and "latest stable: 2.56.0" in out
    assert "update available (2.55.0 → 2.56.0)" in out


def test_up_to_date(fake):
    fake["ollama/ollama/releases/latest"] = {"tag_name": "v2.55.0"}
    assert "status: up to date" in versions.software_version("Ollama")


def test_falls_back_to_tags_without_prereleases(fake):
    fake["releases/latest"] = urllib.error.HTTPError("u", 404, "yok", {}, None)
    fake["golang/go/tags"] = [{"name": "go1.30rc1"}, {"name": "go1.29.3"}, {"name": "go1.29.10"},
                              {"name": "weekly"}]
    assert "latest stable: 1.29.10" in versions.software_version("go")


def test_python_ignores_prereleases_and_picks_max(fake):
    fake["python.org"] = [{"name": "Python 3.14.8"}, {"name": "Python 3.15.0"}, {"name": "Python 3.9.25"},
                          {"name": "Python 3.16.0a1"}]
    assert "latest stable: 3.15.0" in versions.software_version("python")


def test_node_lts(fake):
    fake["nodejs.org"] = [{"version": "v26.11.1", "lts": False}, {"version": "v24.21.0", "lts": "Krypton"}]
    out = versions.software_version("nodejs")
    assert "latest stable: 24.21.0 (LTS 'Krypton'; en yeni Current: 26.11.1)" in out


def test_unknown_program_suggests_web(fake, monkeypatch):
    monkeypatch.setattr(versions, "local_version", lambda cmd, name: (None, ""))
    out = versions.software_version("Photoshop")
    assert "not found" in out and "web_search" in out


def test_network_error_is_reported_not_raised(fake):
    fake["git-for-windows"] = urllib.error.URLError("çevrimdışı")
    out = versions.software_version("git")
    assert "latest stable: unknown" in out and "installed 2.55.0" in out
