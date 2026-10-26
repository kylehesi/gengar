"""Kod ajanı araçlarının testleri: metin arama ve ayrı sanal ortamda Python çalıştırma."""

import pytest

from gengar.tools import ToolError
from gengar.tools.code import PythonSandbox, make_tools, search_text


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    root = tmp_path_factory.mktemp("code")
    box = PythonSandbox(root / "workspace", root / "venv")
    box.ensure()  # sanal ortamı bir kez oluştur (birkaç saniye)
    return box


@pytest.fixture(scope="module")
def run(sandbox):
    tool = {t.name: t for t in make_tools(sandbox)}["run_python"]
    return lambda **args: tool.run(args)


def test_runs_code_in_separate_venv(run, sandbox):
    out = run(code="import sys; print('merhaba'); print(sys.prefix)")
    assert out.startswith("exit code: 0")
    assert "merhaba" in out
    assert str(sandbox.venv_dir) in out  # Gengar'ın ortamı değil, sandbox


def test_traceback_is_returned(run):
    out = run(code="def f():\n    return 1 / 0\nf()")
    assert "exit code: 1" in out
    assert "ZeroDivisionError" in out and "--- stderr ---" in out


def test_runs_file_with_args_and_cwd(run, sandbox):
    project = sandbox.workspace / "proje"
    project.mkdir(parents=True, exist_ok=True)
    (project / "main.py").write_text("import sys, pathlib\nprint(sys.argv[1:], pathlib.Path.cwd().name)",
                                     encoding="utf-8")
    out = run(file="main.py", args=["a", "ğ"], cwd=str(project))
    assert "['a', 'ğ'] proje" in out


def test_timeout_kills(run):
    out = run(code="import time; time.sleep(30)", timeout=1)
    assert "killed" in out


def test_code_or_file_required(run):
    with pytest.raises(ToolError, match="ya `code` ya da `file`"):
        run()


@pytest.mark.parametrize("bad", ["--index-url=http://kotu", "requests; rm -rf", "../yerel"])
def test_rejects_weird_package_names(sandbox, bad):
    with pytest.raises(ToolError, match="geçersiz paket"):
        sandbox.install([bad])


def test_accepts_normal_package_specs(sandbox, monkeypatch):
    seen = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: seen.append(cmd) or
                        type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    sandbox.install(["requests", "numpy==2.1.0", "pandas>=2", "uvicorn[standard]"])
    assert seen and "requests" in seen[0]


def test_python_in_powershell_uses_sandbox(sandbox):
    from gengar.tools import powershell

    tool = powershell.make_tool(lambda: str(sandbox.ensure().parent))
    out = tool.run({"command": 'python -c "import sys; print(sys.prefix)"'})
    assert "exit code: 0" in out
    assert str(sandbox.venv_dir) in out


def test_literal_newlines_are_repaired(run):
    out = run(code="x = 2\\nfor i in range(3):\\n    x += i\\nprint('sonuc', x)")
    assert "sonuc 5" in out and "were fixed" in out


def test_valid_code_with_backslash_n_in_string_is_untouched():
    from gengar.tools.code import repair_code

    code = "print('a\\nb')"
    assert repair_code(code) == (code, False)


def test_windows_path_escape_gets_hint(run, sandbox):
    out = run(code="open('C:\\gengar\\data\\bench\\out\\x.txt', 'w')")
    assert "--- hint ---" in out and "raw string" in out


def test_missing_module_gets_hint(run):
    out = run(code="import yok_boyle_bir_paket_123")
    assert "packages=" in out


def test_relative_paths_use_working_dir(tmp_path):
    from gengar.tools import base, files

    old = base.working_dir()
    try:
        base.set_working_dir(tmp_path / "ws")
        files.write_file("proje/a.txt", "x")
        assert (tmp_path / "ws" / "proje" / "a.txt").read_text() == "x"
    finally:
        base.set_working_dir(old)


# --- metin arama -------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def hesapla(x):\n    return x * 2\n\nprint(hesapla(3))\n",
                                             encoding="utf-8")
    (tmp_path / "src" / "notlar.txt").write_text("hesapla fonksiyonu burada\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.py").write_text("def hesapla(): pass\n", encoding="utf-8")
    (tmp_path / "resim.bin").write_bytes(b"\0hesapla")
    return tmp_path


def test_search_text_finds_with_line_numbers(project):
    out = search_text("def hesapla", str(project))
    assert "app.py:1: def hesapla(x):" in out
    assert "node_modules" not in out  # gereksiz klasörler atlanır


def test_search_text_glob_and_case(project):
    out = search_text("HESAPLA", str(project), glob="*.txt")
    assert "notlar.txt:1" in out and "app.py" not in out
    assert "No matches" in search_text("HESAPLA", str(project), glob="*.txt", ignore_case=False)


def test_search_text_invalid_regex_falls_back_to_literal(project):
    (project / "src" / "a.py").write_text("x = liste[0\n", encoding="utf-8")
    assert "a.py:1" in search_text("liste[0", str(project))


def test_code_can_import_modules_from_cwd(run, sandbox):
    # Model kodu `code` ile verip cwd'yi görev klasörü yapınca o klasördeki modülü import edebilmeli
    # (önceden kod .runs içinde çalıştığı için ModuleNotFoundError veriyordu).
    project = sandbox.workspace / "gorev"
    project.mkdir(parents=True, exist_ok=True)
    (project / "cozum.py").write_text("def topla(a, b):\n    return a + b\n", encoding="utf-8")
    out = run(code="import cozum\nprint(cozum.topla(2, 3))", cwd=str(project))
    assert out.startswith("exit code: 0") and "5" in out
