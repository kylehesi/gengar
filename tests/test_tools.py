import json

import pytest

from gengar.core.audit import AuditLog
from gengar.core.permissions import PermissionPolicy
from gengar.tools import Risk, ToolError, default_registry
from gengar.tools import files
from gengar.tools.base import truncate
from gengar.tools.powershell import classify, rewrite_chains, run_powershell


# --- PowerShell risk sınıflandırma ---------------------------------------

@pytest.mark.parametrize("cmd", [
    "Get-Process",
    "Get-ChildItem C:\\Users -Recurse | Where-Object { $_.Length -gt 1MB } | Sort-Object Length",
    "Get-Service | Select-Object Name, Status | Format-Table",
    "(Get-Date).Year",
    "ls ~\\Desktop",
    "Get-NetIPAddress -AddressFamily IPv4; whoami",
    "Get-ItemProperty 'HKCU:\\Control Panel\\Desktop' | Select-Object WallPaper",
    "Test-Path C:\\Windows",
    "Get-PSDrive C | Select-Object @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}",
    "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory | ForEach-Object { $_ / 1GB }",
    "ollama --version",
    "git.exe --version",
    "Get-Process | Sort-Object -Property WS -Descending | Select-Object -First 5 | Select-Object Name, WS | "
    "ForEach-Object { $_.Name + ' ' + [math]::Round($_.WS / 1MB, 2) + ' MB' }",
])
def test_read_only_commands(cmd):
    assert classify(cmd) == Risk.READ


@pytest.mark.parametrize("cmd", [
    "Remove-Item C:\\temp\\x.txt",
    "Get-ChildItem *.log | Remove-Item",
    "Get-ChildItem | Where-Object { Remove-Item $_ }",
    "Get-Process > procs.txt",
    "Get-Date; Stop-Computer",
    "Write-Output \"$(Remove-Item x)\"",
    "[IO.File]::Delete('x')",
    "[math]::Round(1); [IO.File]::Delete('x')",
    "(Get-Item x).Delete()",
    "ls | % Delete",
    "ls | ForEach-Object -MemberName Delete",
    "ls | ForEach-Object { Remove-Item $_ }",
    "& notepad.exe",
    "iex 'Remove-Item x'",
    "Set-ItemProperty HKCU:\\x -Name y -Value 1",
    "shutdown /s",
    "reg delete HKCU\\Software\\X /f",
    "ollama --version; Remove-Item x",
    ".\\kotu.exe --version",
    "ollama rm qwen3:8b --version",
    "",
])
def test_risky_commands_need_confirmation(cmd):
    assert classify(cmd) == Risk.SYSTEM


def test_run_powershell_utf8_and_exit_code():
    out = run_powershell("Write-Output 'Gengar çalışıyor ğüşöı'; exit 3")
    assert "exit code: 3" in out
    assert "Gengar çalışıyor ğüşöı" in out


def test_run_powershell_stderr_is_plain_text():
    out = run_powershell("Get-Item C:\\yok\\dosya.txt")
    assert "--- stderr ---" in out
    assert "Cannot find path" in out or "bulunamıyor" in out
    assert "CLIXML" not in out and "<S " not in out
    assert "At line:" not in out


@pytest.mark.parametrize("cmd, expected", [
    ("cd x && python t.py", "cd x; if ($?) { python t.py }"),
    ("a && b && c", "a; if ($?) { b; if ($?) { c } }"),
    ("a || b", "a; if (-not $?) { b }"),
    ("Write-Output 'a && b'", "Write-Output 'a && b'"),  # tırnak içi değişmez
    ("Get-Date", "Get-Date"),
])
def test_rewrite_chains(cmd, expected):
    assert rewrite_chains(cmd) == expected


def test_chains_actually_work_in_powershell_51():
    out = run_powershell("Write-Output bir && Write-Output iki")
    assert "bir" in out and "iki" in out and "exit code: 0" in out
    out = run_powershell("Get-Item C:\\yok\\yok.txt && Write-Output calismamali")
    assert "calismamali" not in out.split("--- stderr ---")[0]


def test_redirection_writes_utf8(tmp_path):
    f = tmp_path / "x.csv"
    run_powershell(f"echo 'Ad,Not' > '{f}'; echo 'Ayşe,90' >> '{f}'")
    data = f.read_bytes()
    assert not data.startswith(b"\xff\xfe")  # UTF-16 değil
    assert "Ayşe,90" in data.decode("utf-8-sig")


def test_run_powershell_timeout():
    out = run_powershell("Start-Sleep -Seconds 10", timeout=1)
    assert "durduruldu" in out


# --- dosya araçları ------------------------------------------------------

def test_write_read_edit_roundtrip(tmp_path):
    f = tmp_path / "alt" / "not.txt"
    assert "oluşturuldu" in files.write_file(str(f), "bir\niki\nüç\n")
    out = files.read_file(str(f))
    assert out.splitlines()[1:] == ["bir", "iki", "üç"]  # numarasız içerik, başlık ayrı satırda
    assert "2\tiki" in files.read_file(str(f), line_numbers=True)
    files.edit_file(str(f), "iki", "İKİ")
    assert f.read_text(encoding="utf-8") == "bir\nİKİ\nüç\n"


def test_write_file_fixes_flat_escaped_newlines(tmp_path):
    f = tmp_path / "r.txt"
    files.write_file(str(f), "RAM: 16 GB\\nDisk: 1300 GB\\nPil: %90")
    assert f.read_text(encoding="utf-8").splitlines() == ["RAM: 16 GB", "Disk: 1300 GB", "Pil: %90"]
    g = tmp_path / "kod.py"
    files.write_file(str(g), "print('a\\nb')\nprint(1)\n")  # gerçek satır sonu varsa dokunma
    assert "print('a\\nb')" in g.read_text(encoding="utf-8")


def test_edit_requires_unique_match(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x x", encoding="utf-8")
    with pytest.raises(ToolError, match="2 kez"):
        files.edit_file(str(f), "x", "y")
    with pytest.raises(ToolError, match="bulunamadı"):
        files.edit_file(str(f), "z", "y")


def test_read_missing_and_binary(tmp_path):
    with pytest.raises(ToolError, match="dosya yok"):
        files.read_file(str(tmp_path / "yok.txt"))
    b = tmp_path / "b.bin"
    b.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ToolError, match="binary"):
        files.read_file(str(b))


def test_list_and_find(tmp_path):
    (tmp_path / "klasor").mkdir()
    (tmp_path / "klasor" / "rapor.pdf").write_bytes(b"%PDF")
    assert "<DIR>" in files.list_directory(str(tmp_path))
    assert "rapor.pdf" in files.find_files("**/*.pdf", str(tmp_path))
    assert "eşleşen bir şey yok" in files.find_files("**/*.docx", str(tmp_path))


def test_writing_to_windows_folder_is_system_risk(tmp_path):
    assert files.write_risk({"path": "C:\\Windows\\gengar.txt"}) == Risk.SYSTEM
    assert files.write_risk({"path": str(tmp_path / "x.txt")}) == Risk.WRITE


# --- kayıt, izin, log ----------------------------------------------------

def test_registry_schemas_and_bad_args():
    reg = default_registry()
    names = {s["function"]["name"] for s in reg.schemas()}
    assert {"run_powershell", "read_file", "write_file", "edit_file"} <= names
    with pytest.raises(ToolError, match="geçersiz argüman"):
        reg.get("read_file").run({"yol": "x"})


def test_truncate_keeps_head_and_tail():
    text = "A" * 9000 + "SON"
    out = truncate(text, 1000)
    assert out.startswith("A") and out.endswith("SON")
    assert "kesildi" in out


def test_permission_modes():
    p = PermissionPolicy("normal")
    assert not p.needs_confirmation("read_file", Risk.READ)
    assert p.needs_confirmation("write_file", Risk.WRITE)
    p.grant_for_session("write_file")
    assert not p.needs_confirmation("write_file", Risk.WRITE)
    assert p.needs_confirmation("run_powershell", Risk.SYSTEM)
    assert not PermissionPolicy.can_grant_for_session(Risk.SYSTEM)

    assert PermissionPolicy("strict").needs_confirmation("read_file", Risk.READ)
    assert not PermissionPolicy("trust").needs_confirmation("x", Risk.SYSTEM)
    with pytest.raises(ValueError):
        PermissionPolicy("yolo")


def test_audit_log(tmp_path):
    log = AuditLog(tmp_path)
    log.record("tool", tool="run_powershell", output="x" * 5000)
    entry = json.loads(log.path.read_text(encoding="utf-8").strip())
    assert entry["tool"] == "run_powershell"
    assert entry["session"] == log.session
    assert len(entry["output"]) < 2100


# --- klasör yoluna yazma ----------------------------------------------------------------------------
# Not: "X.md" → "X\X.md" yönlendirmesi bilerek YOK: write_to_folder ölçümünde (gerçekçi klasör adları)
# model 9/9 doğru yazdı; "klasörün yanına" hatası save_answer_md'nin dosya adı gibi görünen görev
# klasörlerinden (save_answer_md_7) kaynaklanan bir ölçüm artefaktıydı.

def test_write_to_folder_path_gives_clear_error(tmp_path):
    folder = tmp_path / "Çalışma Planı"
    folder.mkdir()
    with pytest.raises(ToolError, match="bir klasör, dosya değil"):
        files.write_file(str(folder), "içerik")
    assert list(folder.iterdir()) == []


def test_sibling_file_is_written_where_asked(tmp_path):
    (tmp_path / "Notlar").mkdir()
    files.write_file(str(tmp_path / "Notlar.md"), "yeni")      # kullanıcı yanına istemiş olabilir
    assert (tmp_path / "Notlar.md").read_text(encoding="utf-8") == "yeni"
