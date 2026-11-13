"""Launch and gracefully stop only the instrumented, isolated game."""
from contextlib import contextmanager
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import subprocess
import sys
import uuid
import zipfile

from movie_format import validate
from session_lock import exclusive

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "lab/kr1-test"
EXE = LAB / "game/Kingdom Rush.exe"


def validate_environment(movie=None):
    with zipfile.ZipFile(EXE) as archive:
        embedded = archive.read("tas_lab.lua")
        config = json.loads(archive.read("tas_config.json"))
    runtime_hash = hashlib.sha256(embedded).hexdigest()
    if hashlib.sha256((ROOT / "runtime/tas_lab.lua").read_bytes()).hexdigest() != runtime_hash:
        raise ValueError("Runtime changed; close the test game and run tools/instrument.py")
    if movie is not None:
        validate(movie)
        for key, expected in (("game_sha256", config["game_sha256"]),
                              ("seed", config["seed"]), ("runtime_sha256", runtime_hash)):
            if movie.get(key) != expected:
                raise ValueError(f"Movie {key} does not match the installed instrumentation")
        if abs(movie["dt"] - config["dt"]) > 1e-14:
            raise ValueError("Movie timestep mismatch")
    return config


@contextmanager
def owned_process():
    """Pin the PID to a handle and verify its image before any lifecycle action."""
    if not (LAB / "pid.json").exists():
        yield None
        return
    if os.name != "nt":
        raise RuntimeError("The game launcher requires Windows")
    info = json.loads((LAB / "pid.json").read_text(encoding="utf-8"))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, info["pid"])
    if not handle:
        if ctypes.get_last_error() != 87:
            raise ctypes.WinError(ctypes.get_last_error())
        yield None
        return
    try:
        if kernel.WaitForSingleObject(handle, 0) == 0:
            yield None
            return
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        if Path(buffer.value).resolve() != EXE.resolve():
            # Reused PID belongs to another program. Never control it.
            yield None
            return
        yield (kernel, handle, info)
    finally:
        kernel.CloseHandle(handle)


@exclusive
def stop_owned():
    from control import request
    with owned_process() as process:
        if process is None:
            return
        kernel, handle, info = process
        state = request("snapshot")
        if state["identity"] != info["profile"]:
            raise RuntimeError("Test process profile does not match pid.json")
        request("quit")
        if kernel.WaitForSingleObject(handle, 10000) != 0:
            raise TimeoutError("Test game did not close; no replacement process was launched")


@exclusive
def launch_game(replay=None):
    movie = json.loads(Path(replay).read_text(encoding="utf-8")) if replay else None
    validate_environment(movie)
    with owned_process() as process:
        if process is not None:
            raise RuntimeError("Test game is already running; close it before launching")
    env = os.environ.copy()
    env["KR_TAS_PROFILE"] = "kingdom_rush_tas_" + uuid.uuid4().hex[:12]
    env.pop("KR_TAS_MOVIE", None)
    if movie is not None:
        (LAB / "control/replay-input.json").write_text(json.dumps(movie), encoding="utf-8")
        env["KR_TAS_MOVIE"] = "../control/replay-input.json"
    (LAB / "control/request.json").write_text('{"id":"boot","op":"pause"}', encoding="utf-8")
    with (LAB / "stdout.log").open("wb") as out, (LAB / "stderr.log").open("wb") as err:
        process = subprocess.Popen([str(EXE)], cwd=EXE.parent, stdout=out, stderr=err, env=env)
    info = {"pid": process.pid, "profile": env["KR_TAS_PROFILE"], "lab": str(LAB)}
    (LAB / "pid.json").write_text(json.dumps(info), encoding="utf-8")
    return info


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    print(json.dumps(launch_game(args.replay), ensure_ascii=False))
