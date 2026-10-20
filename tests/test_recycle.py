"""Geri dönüşüm kutusuna silme ve geri yükleme."""

import os
import struct
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gengar.tools import ToolError, guard, recycle


def info_v2(path: str, size: int, when: datetime) -> bytes:
    ft = int((when - datetime(1601, 1, 1, tzinfo=timezone.utc)).total_seconds() * 10_000_000)
    text = path + "\0"
    return struct.pack("<qqqi", 2, size, ft, len(text)) + text.encode("utf-16-le")


def test_parse_info_v2_and_v1():
    when = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    path, deleted, size = recycle.parse_info(info_v2(r"C:\Users\kyle\Desktop\not.txt", 1234, when))
    assert (path, size) == (r"C:\Users\kyle\Desktop\not.txt", 1234)
    assert abs(deleted - when.astimezone().replace(tzinfo=None)) < timedelta(seconds=1)

    v1 = struct.pack("<qqq", 1, 10, 0) + r"D:\a.txt".encode("utf-16-le").ljust(520, b"\0")
    assert recycle.parse_info(v1)[0] == r"D:\a.txt"


@pytest.fixture
def no_guard(monkeypatch):
    monkeypatch.setattr(guard, "_root", None)
    monkeypatch.setattr(guard, "_scratch", [])


@pytest.fixture
def home_dir(no_guard):
    # Ev klasörü: AppData altındaki pytest geçici klasörü Claude masaüstü uygulamasında sanallaştırılabiliyor.
    d = Path.home() / f".gengar_test_{uuid.uuid4().hex[:8]}"
    d.mkdir()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def test_delete_goes_to_recycle_bin_and_restores(home_dir):
    f = home_dir / "silinecek.txt"
    f.write_text("merhaba", encoding="utf-8")

    out = recycle.delete_files([str(f)])
    assert not f.exists() and "Geri dönüşüm kutusuna" in out
    listing = recycle.restore_files()
    assert str(f) in listing

    assert "✓" in recycle.restore_files([str(f)])
    assert f.read_text(encoding="utf-8") == "merhaba"
    assert str(f) not in recycle.restore_files()  # fiş de temizlendi


def test_restore_never_overwrites(home_dir):
    f = home_dir / "a.txt"
    f.write_text("eski", encoding="utf-8")
    recycle.delete_files([str(f)])
    f.write_text("yeni", encoding="utf-8")
    assert "üzerine yazılmadı" in recycle.restore_files([str(f)])
    assert f.read_text(encoding="utf-8") == "yeni"
    f.unlink()
    recycle.restore_files([str(f)])  # kutuyu temiz bırak


def test_refuses_when_item_would_be_deleted_permanently(home_dir, monkeypatch):
    f = home_dir / "buyuk.bin"
    f.write_bytes(b"x" * 2048)
    monkeypatch.setattr(recycle, "_bin_settings", lambda anchor: (True, 1024))  # kutu sınırı 1 KB
    with pytest.raises(ToolError, match="Hiçbir şey silinmedi"):
        recycle.delete_files([str(f)])
    assert f.exists()

    monkeypatch.setattr(recycle, "_bin_settings", lambda anchor: (False, None))  # kutu kapalı
    with pytest.raises(ToolError, match="kapalı"):
        recycle.delete_files([str(f)])
    assert f.exists()


def test_task_folders_are_deleted_permanently(tmp_path, monkeypatch):
    root = tmp_path / "gengar"
    task = root / "data" / "bench2" / "t1"
    task.mkdir(parents=True)
    (task / "gecici.tmp").write_text("x")
    monkeypatch.setattr(guard, "_root", None)
    guard.configure(root, [root / "data" / "workspace", root / "data" / "bench2"])
    out = recycle.delete_files([str(task / "gecici.tmp")])
    assert "Kalıcı silindi" in out and not (task / "gecici.tmp").exists()


def test_guard_blocks_deleting_gengar(tmp_path, monkeypatch):
    root = tmp_path / "gengar"
    (root / "src").mkdir(parents=True)
    monkeypatch.setattr(guard, "_root", None)
    guard.configure(root, [root / "data" / "workspace"])
    assert guard.check("delete_files", {"paths": [str(root / "src")]})
    assert guard.check("delete_files", {"paths": [str(root / "data" / "workspace" / "a.txt")]}) is None


def test_missing_path_deletes_nothing(home_dir):
    f = home_dir / "var.txt"
    f.write_text("x")
    with pytest.raises(ToolError, match="bulunamadı"):
        recycle.delete_files([str(f), str(home_dir / "yok.txt")])
    assert f.exists()


def test_risk_levels():
    tool = {t.name: t for t in recycle.TOOLS}
    assert tool["delete_files"].risk_for({"paths": [r"C:\Users\kyle\Desktop\a.txt"]}).name == "WRITE"
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    assert tool["delete_files"].risk_for({"paths": [rf"{windir}\a.txt"]}).name == "SYSTEM"
    assert tool["restore_files"].risk_for({}).name == "READ"
