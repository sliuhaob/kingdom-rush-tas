"""Replay-based rewind with validated bookmarks and optional input branching."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

from control import advance, request
from launch import LAB, launch_game, stop_owned, validate_environment, owned_process
from movie_format import validate
from session_lock import exclusive
from verify_replay import gameplay, differences

BOOKMARKS = LAB / "bookmarks"
HISTORY = LAB / "history"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode()).hexdigest()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


def bookmark_path(name):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError("Bookmark name must be 1–64 ASCII letters, digits, underscores or hyphens")
    return BOOKMARKS / (name + ".json")


def capture():
    state = request("snapshot")
    if not state["paused"] or state["pending"]:
        raise RuntimeError("Pause and finish pending steps before saving or rewinding")
    if state.get("queued_inputs", 0):
        raise RuntimeError("Unexecuted inputs are queued; advance them before saving or rewinding")
    movie = validate(request("movie"))
    validate_environment(movie)
    return state, movie


def archive(state, movie):
    path = HISTORY / (uuid.uuid4().hex + ".json")
    write_new(path, {"format": "kr-tas-history-v1", "frame": state["frame"], "movie": movie,
                     "state": gameplay(state)})
    return path


def validate_target(frame, movie):
    if type(frame) is not int or not 0 <= frame <= movie["end_frame"]:
        raise ValueError("Target frame is outside the saved input timeline")


def restore(movie, frame, expected=None, edit=False):
    # All checks that can run without the game precede closing the current process.
    validate_environment(movie)
    validate_target(frame, movie)
    if expected is not None and expected.get("frame") != frame:
        raise ValueError("Bookmark state and target frame disagree")
    history = None
    with owned_process() as process:
        if process is not None:
            old_state, old_movie = capture()
            history = archive(old_state, old_movie)
    path = HISTORY / (uuid.uuid4().hex + ".movie.json")
    write_new(path, movie)
    stop_owned()
    launch_game(path)
    state = request("snapshot")
    while state["frame"] < frame:
        state = advance(min(36000, frame - state["frame"]))
    diff = differences(expected, gameplay(state)) if expected is not None else []
    report = {"frame": frame, "method": "fresh-process-replay", "verified":
              (not diff) if expected is not None else None, "differences": diff,
              "edit": False, "history": str(history) if history else None,
              "replay_movie": str(path)}
    if not diff and edit:
        state = request("takeover")
        report["edit"] = True
    report_path = path.with_suffix(".restore.json")
    write_new(report_path, report)
    report["report"] = str(report_path)
    if diff:
        raise RuntimeError(f"Rewind state mismatch; game remains paused in replay mode. See {report_path}")
    return report


@exclusive
def save(name):
    path = bookmark_path(name)
    if path.exists():
        raise FileExistsError(f"Bookmark exists; choose a new name: {path}")
    state, movie = capture()
    payload = {"format": "kr-tas-bookmark-v1", "frame": state["frame"],
               "movie": movie, "state": gameplay(state)}
    write_new(path, {**payload, "sha256": digest(payload)})
    return {"bookmark": str(path), "frame": state["frame"]}


@exclusive
def load(name, edit=False):
    payload = json.loads(bookmark_path(name).read_text(encoding="utf-8"))
    checksum = payload.pop("sha256", None)
    if payload.get("format") != "kr-tas-bookmark-v1" or digest(payload) != checksum:
        raise ValueError("Invalid or damaged bookmark")
    return restore(payload["movie"], payload["frame"], payload["state"], edit)


@exclusive
def seek(frame, edit=False, relative=False):
    state, movie = capture()
    if relative:
        if type(frame) is not int or frame < 0:
            raise ValueError("Back count must be a nonnegative integer")
        frame = state["frame"] - frame
    validate_target(frame, movie)
    # An arbitrary target has no recorded state to compare, unlike a bookmark.
    return restore(movie, frame, gameplay(state) if frame == state["frame"] else None, edit)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="op", required=True)
    subs.add_parser("save").add_argument("name")
    load_parser = subs.add_parser("load")
    load_parser.add_argument("name")
    load_parser.add_argument("--edit", action="store_true")
    for command in ("seek", "back"):
        sub = subs.add_parser(command)
        sub.add_argument("frame", type=int)
        sub.add_argument("--edit", action="store_true")
    args = parser.parse_args()
    if args.op == "save":
        result = save(args.name)
    elif args.op == "load":
        result = load(args.name, args.edit)
    else:
        result = seek(args.frame, args.edit, args.op == "back")
    print(json.dumps(result, ensure_ascii=False, indent=2))
