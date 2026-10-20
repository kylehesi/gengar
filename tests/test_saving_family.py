"""save_answer_md ailesi ve çerçevenin çok turlu sohbet / zorunlu araç özellikleri."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

from families import saving  # noqa: E402
from framework import Task, apply_tool_limit, build_tasks  # noqa: E402


def test_tasks_are_two_turn_same_chat_and_require_save_answer(tmp_path):
    tasks = build_tasks(saving.FAMILIES, seed=1000, base=tmp_path)
    assert tasks
    for t in tasks:
        assert isinstance(t.prompt, list) and len(t.prompt) == 2
        assert t.same_chat and t.require_tools == ("save_answer",)
        assert str(t.root) in t.prompt[1]  # kaydet isteği görev klasörünü gösteriyor


def test_bench_and_train_topics_never_overlap(tmp_path):
    bench = build_tasks(saving.FAMILIES, seed=1000, base=tmp_path / "b", instances=20, purpose="bench")
    train = build_tasks(saving.FAMILIES, seed=5000, base=tmp_path / "t", instances=20, purpose="train")
    first = lambda ts: {t.prompt[0] for t in ts}  # noqa: E731
    assert first(bench) and first(train) and not first(bench) & first(train)


def test_require_tools():
    task = Task("x", "f", "c", ["yaz", "kaydet"], lambda a: (True, "tamam"), require_tools=("save_answer",))
    assert apply_tool_limit(task, True, "tamam", ["save_answer"]) == (True, "tamam")
    ok, note = apply_tool_limit(task, True, "tamam", ["write_file"])
    assert not ok and "save_answer" in note and "write_file" in note


def test_check_needs_file_with_topic(tmp_path):
    task = build_tasks(saving.FAMILIES, seed=1000, base=tmp_path)[0]
    assert task.check("kaydettim") == (False, "dosya oluşmadı")
    keyword = next(k for p, k in saving.TOPICS if p == task.prompt[0])
    (task.root / "liste.md").write_text(f"# Plan\n{keyword}\n" + "madde açıklaması\n" * 40, encoding="utf-8")
    assert task.check("kaydettim")[0]
