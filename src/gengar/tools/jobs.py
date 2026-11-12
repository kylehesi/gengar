"""Alt süreçler Gengar'la birlikte kapansın: Windows Job Object.

Neden: `run_python` / `run_powershell` zaman aşımında süreç ağacını `taskkill /T` ile kapatıyor; ama bunu yapan
Gengar'ın kendisi ölürse (pencere kapatıldı, ölçüm durduruldu) kimse durdurmuyor. 2026-10-26'da modelin başlattığı
sonsuz döngülü bir betik ölçüm durdurulduktan sonra 1,5 saat çalıştı ve ölçüm klasörünü kilitledi (INCELENECEK 6).

Job Object'e konan süreçler, job'un son tutamacı kapanınca (Gengar çıkınca ya da ölünce Windows kapatır)
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE ile birlikte sonlandırılır. İki tür job var:
- tree=True (run_python): sürecin açtığı her şey de job'da. Venv'deki python.exe asıl yorumlayıcıyı ALT süreç
  olarak başlatan bir yönlendirici; yalnızca doğrudan çocuk kapsansaydı asıl betik kurtulurdu.
- tree=False (run_powershell): yalnızca powershell.exe'nin kendisi. Onun açtığı uygulamalar (Start-Process
  notepad) job dışında kalır (SILENT_BREAKAWAY): kullanıcının açtırdığı bir pencere Gengar kapanınca kaydedilmemiş
  işiyle birlikte gitmesin.
"""

from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x1000


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                                                  "OtherBytes")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
_kernel32.CreateJobObjectW.restype = wintypes.HANDLE
_kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_kernel32.SetInformationJobObject.restype = wintypes.BOOL
_kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


class Job:
    """Kapanınca (close ya da Gengar'ın ölmesi) içindeki süreçleri sonlandıran Windows job'u."""

    def __init__(self, tree: bool = True):
        self.handle = _kernel32.CreateJobObjectW(None, None)  # devralınamaz: alt süreçler tutamacı taşımaz
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW başarısız")
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | (
            0 if tree else JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK)
        if not _kernel32.SetInformationJobObject(self.handle, JobObjectExtendedLimitInformation,
                                                 ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            self.close()
            raise OSError(err, "SetInformationJobObject başarısız")

    def add(self, proc: subprocess.Popen) -> bool:
        """Süreci job'a koyar. Başaramazsa False (süreç yine çalışır; yalnızca bu güvence olmaz)."""
        handle = getattr(proc, "_handle", None)
        return bool(self.handle and handle and _kernel32.AssignProcessToJobObject(self.handle, int(handle)))

    def close(self) -> None:
        if self.handle:
            _kernel32.CloseHandle(self.handle)
            self.handle = None


_jobs: dict[bool, Job] = {}


def adopt(proc: subprocess.Popen, tree: bool) -> bool:
    """Alt süreci Gengar'ın job'una koyar; Gengar çıkınca Windows onu da kapatır.

    Job'lar Gengar'ın ömrü boyunca açık kalır (hiç kapatılmaz): tutamaç süreç bitince Windows tarafından
    kapatılır. Hata olursa (örn. çok eski Windows) sessizce False: araç yine çalışır, zaman aşımı yine geçerli.
    """
    try:
        if tree not in _jobs:
            _jobs[tree] = Job(tree)
        return _jobs[tree].add(proc)
    except OSError:
        return False
