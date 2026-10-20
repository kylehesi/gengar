"""Araç gerekmeyen görev aileleri: havuz ayrımı (sızıntı yok), araç sınırı ve doğrulayıcılar."""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

from families import notool  # noqa: E402
from framework import Task, apply_tool_limit, build_tasks  # noqa: E402


def prompts(tasks):
    return {t.prompt for t in tasks if t.family != "notool_chat"}


def test_bench_and_train_questions_never_overlap(tmp_path):
    bench = build_tasks(notool.FAMILIES, seed=1000, base=tmp_path / "b", instances=20, purpose="bench")
    train = build_tasks(notool.FAMILIES, seed=5000, base=tmp_path / "t", instances=20, purpose="train")
    assert prompts(bench) and prompts(train)
    assert not prompts(bench) & prompts(train)  # aynı soru hem ölçümde hem eğitimde olamaz


def test_all_tasks_forbid_tools(tmp_path):
    tasks = build_tasks(notool.FAMILIES, seed=1000, base=tmp_path)
    assert tasks and all(t.max_tools == 0 for t in tasks)


def test_tool_limit():
    task = Task("x", "f", "c", "soru", lambda a: (True, "tamam"), max_tools=0)
    assert apply_tool_limit(task, True, "tamam", []) == (True, "tamam")
    ok, note = apply_tool_limit(task, True, "tamam", ["system_info"])
    assert not ok and "gereksiz araç" in note and "system_info" in note
    free = Task("y", "f", "c", "soru", lambda a: (True, "tamam"))  # sınırsız (mevcut aileler)
    assert apply_tool_limit(free, True, "tamam", ["a", "b", "c"]) == (True, "tamam")


@pytest.mark.parametrize("answer, ok", [
    ("Recursion, bir fonksiyonun kendini çağırmasıdır; sonsuza gitmemesi için bir durma koşulu gerekir.", True),
    ("Recursion bir fonksiyonun kendini çağırmasıdır.", False),  # durma koşulu yok
    ("", False),
])
def test_keyword_groups(answer, ok):
    check = notool._keywords(notool.EXPLAIN[0][1])
    assert check(answer)[0] is ok


def test_prompt_info_checks():
    now = datetime.now()
    assert notool._weekday(f"Bugün {notool.DAYS_TR[now.weekday()].capitalize()}.")[0]
    assert notool._year(f"{now.year} yılındayız.")[0]
    assert notool._clock(f"Saat {now:%H:%M}.")[0]
    assert not notool._clock("Saat 99:99.")[0]
