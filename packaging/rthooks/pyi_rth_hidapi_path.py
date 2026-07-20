# Runtime hook: preload hidapi.dll by absolute path BEFORE any app imports.
#
# PyInstaller 6 onedir places the DLL under sys._MEIPASS (_internal).
# hidapi.py (CFFI) only does ffi.dlopen("hidapi.dll") with a bare name, which
# fails on Windows unless the DLL was already loaded via absolute path.

import ctypes
import os
import sys


def _abs(path: str) -> str:
    return os.path.abspath(path)


def _enable(directory: str) -> None:
    directory = _abs(directory)
    if not os.path.isdir(directory):
        return
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(directory)
        except OSError:
            pass
    path_env = os.environ.get("PATH", "")
    if directory.lower() not in path_env.lower().split(os.pathsep):
        os.environ["PATH"] = directory + (os.pathsep + path_env if path_env else "")


def _preload(dll_path: str) -> bool:
    dll_path = _abs(dll_path)
    if not os.path.isfile(dll_path):
        return False
    _enable(os.path.dirname(dll_path))
    try:
        ctypes.WinDLL(dll_path)
        return True
    except OSError:
        return False


candidates = []
meipass = getattr(sys, "_MEIPASS", None)
exe_dir = os.path.dirname(_abs(sys.executable))

if meipass:
    meipass = _abs(meipass)
    candidates.extend(
        [
            os.path.join(meipass, "hidapi.dll"),
            os.path.join(meipass, "pydualsense", "hidapi.dll"),
            os.path.join(meipass, "libhidapi-0.dll"),
        ]
    )
    _enable(meipass)
    _enable(os.path.join(meipass, "pydualsense"))

candidates.extend(
    [
        os.path.join(exe_dir, "hidapi.dll"),
        os.path.join(exe_dir, "_internal", "hidapi.dll"),
        os.path.join(exe_dir, "_internal", "pydualsense", "hidapi.dll"),
        os.path.join(exe_dir, "pydualsense", "hidapi.dll"),
    ]
)
_enable(exe_dir)
_enable(os.path.join(exe_dir, "_internal"))
_enable(os.path.join(exe_dir, "_internal", "pydualsense"))

for path in candidates:
    if _preload(path):
        break
