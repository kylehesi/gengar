"""Gengar'ın kendi klasörünün korunması, "yaptım" iddiası kontrolü ve klasör arama (2026-10-13 olayı)."""

import pytest

from gengar.core import Agent, AuditLog, Conversation, PermissionPolicy
from gengar.core.agent import CLAIMED, _claims_change
from gengar.tools import Risk, Tool, ToolRegistry, files, guard

from fakes import RecordingUI, ScriptedClient, call

ROOT = r"C:\gengar"


@pytest.fixture
def protected(monkeypatch, tmp_path):
    root = tmp_path / "gengar"
    for d in ("src", "data/workspace", "data/bench2/t1", "data/sft"):
        (root / d).mkdir(parents=True)
    monkeypatch.setattr(guard, "_root", None)
    monkeypatch.setattr(guard, "_scratch", [])
    guard.configure(root, [root / "data" / "workspace", root / "data" / "bench2"])
    return root


def ps(command, cwd=None):
    return guard.check("run_powershell", {"command": command, **({"cwd": cwd} if cwd else {})})


def test_blocks_deleting_gengar_files(protected):
    r = str(protected)
    # Olaydaki gerçek komutun özü: çalışma alanı serbest, ama kurulumun geri kalanı değil.
    assert ps(f'Remove-Item "{r}\\src" -Recurse -Force')
    assert ps(f'Remove-Item {r}\\data\\sft\\x.jsonl -Force')
    assert ps(f'$root = "{r}"; Remove-Item "$root\\src" -Recurse')  # kurulum kökü değişkende
    assert ps(f'Get-ChildItem {r}\\data -Recurse | Remove-Item')     # korunan şeyleri içeren üst klasör
    assert ps(f'[IO.File]::Delete("{r}\\src\\a.py")')
    assert ps('Remove-Item ..\\..\\src -Recurse')                      # çalışma alanından yukarı çıkma
    assert ps('Remove-Item src -Recurse', cwd=r)                       # cwd kurulum kökü


def test_allows_scratch_and_user_folders(protected):
    r = str(protected)
    assert ps(f'Remove-Item "{r}\\data\\workspace\\.runs\\*" -Force') is None
    assert ps(f'Remove-Item {r}\\data\\bench2\\t1\\a.tmp') is None
    assert ps('Remove-Item .runs\\* -Force') is None                  # göreli: çalışma alanı içinde
    assert ps(r'Remove-Item "C:\Users\kyle\Desktop\çalışma programı\Ekim 2026" -Recurse') is None
    assert ps(f'Get-ChildItem {r}\\src -Recurse') is None              # okuma serbest


def test_python_deletes_are_checked(protected):
    r = str(protected).replace("\\", "\\\\")
    code = f'import os\nfor f in os.listdir("{r}\\\\src"):\n    os.remove(f)'
    assert guard.check("run_python", {"code": code})
    assert guard.check("run_python", {"code": f'import shutil\nshutil.rmtree(r"{protected}")'})
    assert guard.check("run_python", {"code": f'open(r"{protected}\\src\\a.py", "w").write("")'})
    assert guard.check("run_python", {"code": f'print(open(r"{protected}\\src\\a.py").read())'}) is None
    ws = protected / "data" / "workspace"
    assert guard.check("run_python", {"code": f'import os\nos.remove(r"{ws}\\a.txt")'}) is None


def test_python_file_argument_is_read(protected, monkeypatch):
    script = protected / "data" / "workspace" / "sil.py"
    script.write_text(f'import shutil\nshutil.rmtree(r"{protected}\\src")', encoding="utf-8")
    monkeypatch.setattr("gengar.tools.base._working_dir", protected / "data" / "workspace")
    assert guard.check("run_python", {"file": "sil.py"})


def test_writes_to_gengar_need_confirmation_each_time(protected):
    assert files.write_risk({"path": str(protected / "src" / "a.py")}) == Risk.SYSTEM
    assert files.write_risk({"path": str(protected / "data" / "workspace" / "a.py")}) == Risk.WRITE


def echo(text: str = "") -> str:
    return f"echo: {text}"


def make_agent(steps, tmp_path):
    tools = [
        Tool("run_powershell", "PS", {"type": "object", "properties": {"command": {"type": "string"}}},
             Risk.SYSTEM, lambda command: "exit code: 0\nsilindi"),
        Tool("echo", "Echo.", {"type": "object", "properties": {"text": {"type": "string"}}}, Risk.READ, echo),
        Tool("write", "Write.", {"type": "object", "properties": {"text": {"type": "string"}}}, Risk.WRITE, echo),
    ]
    client = ScriptedClient(steps)
    agent = Agent(client, ToolRegistry(tools), PermissionPolicy("trust"), AuditLog(tmp_path),
                  Conversation("SYS"), max_steps=5)
    return agent, client


def test_agent_refuses_protected_delete_even_in_trust_mode(protected, tmp_path):
    cmd = f'Remove-Item "{protected}\\src" -Recurse'
    agent, _ = make_agent([("", [call("run_powershell", command=cmd)]), ("Silemedim.", [])], tmp_path)
    ui = RecordingUI()
    agent.run("türkçe dosyaları sil", ui)
    out = agent.conversation.history[2]["content"]
    assert out.startswith("Not executed:") and "protected" in out
    assert not any(e[0] == "start" for e in ui.events)  # araç hiç çalışmadı


@pytest.mark.parametrize("text", [
    "Programı oluşturdum ve klasöre kaydettim.",
    "Türkçe klasörler silindi.",
    "Kurs planını dosyaya yazdım.",
    "I've created the plan file.",
])
def test_claims(text):
    assert _claims_change(text)


@pytest.mark.parametrize("text", [
    "Klasör silinmedi; onay vermediniz.",
    "Dosya oluşturulamadı.",
    "İşte programı yazdım:\n1. gün ...",   # sohbette yazılan metin, dosya iddiası değil
    "Bilgisayarınızda 16 GB RAM var.",
])
def test_not_claims(text):
    assert not _claims_change(text)


def test_unbacked_claim_gets_one_nudge(tmp_path):
    agent, client = make_agent([
        ("Programı oluşturdum.", []),
        ("", [call("write", text="plan")]),
        ("Programı plan.txt dosyasına kaydettim.", []),
    ], tmp_path)
    answer = agent.run("kurs programı yaz", RecordingUI())
    assert answer.strip() == "Programı plan.txt dosyasına kaydettim."
    assert client.requests[1][-1] == {"role": "user", "content": CLAIMED}


def test_claim_after_real_write_is_not_nudged(tmp_path):
    agent, client = make_agent([("", [call("write", text="x")]), ("Dosyayı oluşturdum.", [])], tmp_path)
    assert agent.run("yaz", RecordingUI()).strip() == "Dosyayı oluşturdum."
    assert len(client.requests) == 2


def test_claim_nudge_only_once(tmp_path):
    agent, client = make_agent([("Oluşturdum.", []), ("Oluşturdum.", [])], tmp_path)
    assert agent.run("yap", RecordingUI()).strip() == "Oluşturdum."
    assert len(client.requests) == 2


def test_find_files_finds_folder_and_skips_appdata(tmp_path):
    (tmp_path / "Desktop" / "çalışma programı" / "October 2026").mkdir(parents=True)
    (tmp_path / "AppData" / "Local" / "çalışma programı").mkdir(parents=True)
    out = files.find_files("**/Çalışma Programı", str(tmp_path))
    found = out.splitlines()
    assert len(found) == 1 and "Desktop" in found[0]  # AppData altındaki aynı adlı klasör atlandı
    assert "October 2026" in files.find_files("**/october*", str(tmp_path))
