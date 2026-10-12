import json

import pytest

from gengar.core.audit import AuditLog
from gengar.core.permissions import PermissionPolicy
from gengar.tools import Risk, ToolError, default_registry
from gengar.tools import files
from gengar.tools.base import truncate
from gengar.tools.powershell import classify, run_powershell


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


def test_run_powershell_timeout():
    out = run_powershell("Start-Sleep -Seconds 10", timeout=1)
    assert "durduruldu" in out


# --- dosya araçları ------------------------------------------------------

def test_write_read_edit_roundtrip(tmp_path):
    f = tmp_path / "alt" / "not.txt"
    assert "oluşturuldu" in files.write_file(str(f), "bir\niki\nüç\n")
    assert "2\tiki" in files.read_file(str(f))
    files.edit_file(str(f), "iki", "İKİ")
    assert f.read_text(encoding="utf-8") == "bir\nİKİ\nüç\n"


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
