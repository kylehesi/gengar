"""Ölçüm altyapısının (evals/) kendi testleri: doğrulamalar boş cevapla geçmemeli, üretim tekrarlanabilir olmalı."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

from families import code, compound, files  # noqa: E402
from framework import QuietRepl, build_tasks, inside_task, near, numbers, split_for  # noqa: E402

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


def test_export_keeps_clean_sessions_only():
    from export_sft import clean_session

    tc = {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}
    good = {"system": "SYS", "tools": [{"x": 1}], "messages": [
        {"role": "user", "content": "oku"},
        {"role": "assistant", "content": "", "tool_calls": [tc]},
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "Error: dosya yok"},
        {"role": "assistant", "content": "", "tool_calls": [tc]},
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "merhaba"},
        {"role": "assistant", "content": "Dosyada 'merhaba' yazıyor."}]}
    ex = clean_session(good)
    assert ex["messages"][0] == {"role": "system", "content": "SYS"}
    assert ex["messages"][2]["tool_calls"][0]["function"]["arguments"] == {"path": "a.txt"}  # nesne olarak
    assert ex["tools"] == [{"x": 1}]

    nudged = {**good, "messages": good["messages"][:-1] + [
        {"role": "user", "content": "[Gengar] Your last reply was empty..."},
        {"role": "assistant", "content": "Dosyada merhaba yazıyor.", "_reasoning": "boş cevap vermişim"}]}
    ex = clean_session(nudged)
    assert ex["salvaged"]
    assert [m["role"] for m in ex["messages"]][-2:] == ["tool", "assistant"]  # uyarı ayıklandı
    assert "reasoning_content" not in ex["messages"][-1]  # uyarıya atıf yapan düşünce atıldı

    announced = {**good, "messages": [good["messages"][0],
                                      {"role": "assistant", "content": "Önce dosyayı okuyacağım."},
                                      {"role": "user", "content": "[Gengar] Do it now: ..."},
                                      *good["messages"][1:]]}
    roles = [m["role"] for m in clean_session(announced)["messages"]]
    assert roles[:3] == ["system", "user", "assistant"] and "Önce" not in clean_session(announced)["messages"][2]["content"]
    # Turda iki dürtme: ikisinin duyuru mesajı da ayıklanmalı.
    twice = {**good, "messages": [good["messages"][0],
                                  {"role": "assistant", "content": "Önce dosyayı okuyacağım."},
                                  {"role": "user", "content": "[Gengar] Do it now: ..."},
                                  {"role": "assistant", "content": "Şimdi dosyayı okuyacağım:"},
                                  {"role": "user", "content": "[Gengar] Do it now: ..."},
                                  *good["messages"][1:]]}
    texts = [m.get("content") or "" for m in clean_session(twice)["messages"]]
    assert not any("okuyacağım" in t for t in texts)

    blocked = {**good, "messages": good["messages"][:2] + [
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "Not executed: ..."}]
        + good["messages"][3:]}
    assert clean_session(blocked) is None
    no_answer = {**good, "messages": good["messages"][:-1]}
    assert clean_session(no_answer) is None

    thought = {**good, "messages": good["messages"][:-1] + [
        {"role": "assistant", "content": "Dosyada 'merhaba' yazıyor.", "_reasoning": "dosyayı okudum"}]}
    assert clean_session(thought)["messages"][-1]["reasoning_content"] == "dosyayı okudum"
    assert "reasoning_content" not in clean_session(thought, keep_reasoning=False)["messages"][-1]


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


def test_build_tasks_reports_locked_leftovers(tmp_path):
    # 2026-11-11: --repeat çöktü; görevlerin hafıza veritabanları açık kalmıştı, Windows silemedi.
    base = tmp_path / "bench"
    (base / "_hafiza").mkdir(parents=True)
    locked = (base / "_hafiza" / "x.db").open("w")
    try:
        with pytest.raises(RuntimeError, match="kilitli dosyalar"):
            build_tasks([files.FAMILIES[0]], base=base)
    finally:
        locked.close()
    assert build_tasks([files.FAMILIES[0]], base=base)  # kilit kalkınca çalışır


def test_result_from_record():
    from framework import result_from_record

    rec = {"task_id": "t_0", "family": "f", "category": "c", "split": "dev", "difficulty": 1, "ok": True,
           "note": "tamam", "seconds": 3.5, "error": "", "rep": 2,
           "sessions": [{"messages": [
               {"role": "user", "content": "x"},
               {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "read_file"}}]},
               {"role": "tool", "content": "..."},
               {"role": "assistant", "content": " bitti "}]}]}
    r = result_from_record(rec)
    assert (r.id, r.rep, r.ok, r.tools, r.tool_calls, r.steps, r.answer) == \
        ("t_0", 2, True, ["read_file"], 1, 2, "bitti")


ROOT = Path(r"C:\gengar\data\bench2\real_x_0")


@pytest.mark.parametrize("summary,ok", [
    (r"C:\gengar\data\bench2\real_x_0\notlar.txt", True),
    # klasörün kendisi (eskiden sondaki ayraç arandığı için reddediliyordu)
    (r'New-Item -ItemType Directory -Path "C:\gengar\data\bench2\real_x_0" -Force', True),
    # Python kaynağında çift ters eğik çizgi
    ('base = "C:\\\\gengar\\\\data\\\\bench2\\\\real_x_0"\nos.makedirs(base + "\\\\Ocak")', True),
    # değişkene atanan yol
    ('$parent = "C:\\gengar\\data\\bench2\\real_x_0"; Rename-Item "$parent\\Kasım" "November"', True),
    ("C:/gengar/data/bench2/real_x_0/a.md", True),
    # adresler ve kaçış dizileri yol sayılmaz
    ('html = "<link href=\'https://fonts.googleapis.com/css2\'>"\nopen(r"C:\\gengar\\data\\bench2\\real_x_0\\i.html", "w")', True),
    ('print("Plan:\\n1. gün")\nopen(r"C:\\gengar\\data\\bench2\\real_x_0\\p.txt", "w")', True),
    ('print("İ:\\n")\nopen(r"C:\\gengar\\data\\bench2\\real_x_0\\p.txt", "w")', True),
    # klasörün YANI, dışı, yol yok, ev klasörü, dışarı çıkan yol
    (r"C:\gengar\data\bench2\real_x_0.txt", False),
    (r"C:\gengar\data\bench2\real_x_00\a.txt", False),
    (r"C:\Users\kyle\Desktop\a.txt", False),
    (r'Copy-Item "C:\gengar\data\bench2\real_x_0\a.txt" "C:\Users\kyle\Desktop"', False),
    ("print(1 + 1)", False),
    (r'New-Item "$env:USERPROFILE\Desktop\x"; dir "C:\gengar\data\bench2\real_x_0"', False),
    (r'os.path.expanduser("~"); r"C:\gengar\data\bench2\real_x_0"', False),
    (r"C:\gengar\data\bench2\real_x_0\..\..\..\Desktop", False),
])
def test_inside_task(summary, ok):
    assert inside_task(ROOT, summary) is ok


class _Tool:
    def __init__(self, name):
        self.name = name


def _repl(approval):
    r = QuietRepl.__new__(QuietRepl)  # Repl kurulumu (ekran, ayarlar) gerekmiyor
    r.approval, r.root = approval, ROOT
    return r


def test_task_apps_allows_vscode_window_only():
    r = _repl("task_apps")
    assert r.confirm(_Tool("apps"), "aç: Visual Studio Code", None, False) == "yes"
    assert r.confirm(_Tool("windows_ui"), "focus pencere='Visual Studio Code'", None, False) == "yes"
    assert r.confirm(_Tool("windows_ui"), "type pencere='' metin='<h1>Hello</h1>'", None, False) == "yes"
    assert r.confirm(_Tool("windows_ui"), "type pencere='Discord' metin='selam'", None, False) == "no"
    assert r.confirm(_Tool("write_file"), r"C:\gengar\data\bench2\real_x_0\index.html (40 karakter)",
                     None, False) == "yes"
    assert _repl("task_only").confirm(_Tool("windows_ui"), "focus pencere='Visual Studio Code'", None, False) == "no"
