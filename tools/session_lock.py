"""One controller owns the private game's request channel at a time."""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import os
import threading

LOCK = Path(__file__).resolve().parents[1] / "lab/kr1-test/control/controller.lock"
_mutex = threading.RLock()
_depth = 0


@contextmanager
def session_lock():
    global _depth
    with _mutex:
        if _depth:
            _depth += 1
            try:
                yield
            finally:
                _depth -= 1
            return
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        with LOCK.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("Another controller is using the test game") from exc
            _depth = 1
            try:
                yield
            finally:
                _depth = 0
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def exclusive(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with session_lock():
            return function(*args, **kwargs)
    return wrapped
