"""Alt süreçler Gengar'la birlikte kapanıyor mu (Windows Job Object, INCELENECEK 6).

Gerçek süreçlerle: pencere açmayan, uyuyan küçük Python süreçleri. Her test kendi job'unu kurar ve kapatır
(Gengar'ın kendi job'larına dokunmaz; onlar kapanırsa testi çalıştıran süreçlerin çocukları da giderdi).
"""

import subprocess
import sys
import time

import psutil

from gengar.tools import jobs

# Venv'deki python.exe asıl yorumlayıcıyı alt süreç olarak başlatan bir yönlendirici; testte ağaç belli olsun diye
# doğrudan asıl yorumlayıcı kullanılır (çocuk → torun, araya yönlendirici girmez).
PYTHON = getattr(sys, "_base_executable", sys.executable)
# Çocuk bir torun başlatır, torunun PID'ini yazar ve uyur.
PARENT = ("import subprocess, sys, time; "
          "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
          "print(c.pid, flush=True); time.sleep(60)")


def _gone(pid: int, wait: float = 5.0) -> bool:
    end = time.time() + wait
    while time.time() < end:
        if not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
            return True
        time.sleep(0.1)
    return False


def test_tree_job_kills_child_and_grandchild():
    job = jobs.Job(tree=True)
    proc = subprocess.Popen([PYTHON, "-c", PARENT], stdout=subprocess.PIPE, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert job.add(proc)  # torun başlamadan önce eklendi: torun da job'da doğar
    grandchild = int(proc.stdout.readline())
    job.close()  # Gengar'ın ölmesiyle aynı şey: son tutamaç kapanır
    assert proc.wait(timeout=5) is not None
    assert _gone(grandchild)


def test_direct_job_spares_what_the_child_opened():
    # run_powershell: Start-Process ile açılan uygulama Gengar kapanınca kapanmasın.
    job = jobs.Job(tree=False)
    proc = subprocess.Popen([PYTHON, "-c", PARENT], stdout=subprocess.PIPE, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert job.add(proc)
    grandchild = int(proc.stdout.readline())
    try:
        job.close()
        assert proc.wait(timeout=5) is not None
        assert psutil.pid_exists(grandchild) and not _gone(grandchild, wait=0.5)
    finally:
        psutil.Process(grandchild).kill()


def test_adopt_never_raises():
    class NotStarted:
        _handle = None

    assert jobs.adopt(NotStarted(), tree=True) is False
