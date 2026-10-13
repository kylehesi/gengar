"""Ölçüm altyapısının (evals/) kendi testleri: doğrulamalar boş cevapla geçmemeli, üretim tekrarlanabilir olmalı."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

from families import code, compound, files  # noqa: E402
from framework import build_tasks, near, numbers, split_for  # noqa: E402

LOCAL_FAMILIES = [*files.FAMILIES, *code.FAMILIES,
                  *[f for f in compound.FAMILIES if f.category in ("multi", "safety")]]


@pytest.mark.parametrize("text, expected", [
    ("1.346,7 GB", 1346.7), ("1346.7", 1346.7), ("15,7 GB", 15.7), ("%52", 52.0), ("1.060", 1060.0),
])
def test_numbers(text, expected):
    assert expected in numbers(text)


def test_near():
    assert near("boş alan 1.333,8 GB", 1333.8, 0.5)
    assert not near("boş alan 13 GB", 1333.8, 2)


def test_split_is_stable_and_balanced():
    ids = [f"aile_{i}" for i in range(200)]
    splits = [split_for(i) for i in ids]
    assert splits == [split_for(i) for i in ids]
    assert 70 < splits.count("dev") < 130


def test_local_checks_fail_on_empty_answer(tmp_path):
    tasks = build_tasks(LOCAL_FAMILIES, base=tmp_path / "b")
    for t in tasks:
        ok, note = t.check("")
        assert ok is False, (t.id, note)


def test_generation_is_reproducible(tmp_path):
    a = [t.prompt for t in build_tasks(files.FAMILIES, seed=7, base=tmp_path / "a")]
    b = [t.prompt for t in build_tasks(files.FAMILIES, seed=7, base=tmp_path / "b")]
    c = [t.prompt for t in build_tasks(files.FAMILIES, seed=8, base=tmp_path / "c")]
    norm = lambda ps, d: [p.replace(str(tmp_path / d), "<root>") for p in ps]
    assert norm(a, "a") == norm(b, "b")
    assert norm(a, "a") != norm(c, "c")


def test_correct_actions_pass(tmp_path):
    """Doğru işi yapınca doğrulama geçmeli (birkaç aile için elle)."""
    t = next(t for t in build_tasks([f for f in files.FAMILIES if f.name == "file_rename_ext"], base=tmp_path)
             if t.id.endswith("_0"))
    for p in t.root.glob("*.txt"):
        p.rename(p.with_suffix(".md"))
    assert t.check("tamam")[0]

    t = build_tasks([f for f in files.FAMILIES if f.name == "file_delete"], base=tmp_path / "d")[0]
    for p in t.root.glob("*.tmp"):
        p.unlink()
    assert t.check("silindi")[0]
