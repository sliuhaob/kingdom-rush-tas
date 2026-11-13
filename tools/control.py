"""File-based lab controller, bound to the private test game."""
import argparse
import json
from pathlib import Path
import time
import uuid
import sys
from session_lock import exclusive

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "lab/kr1-test/control"


@exclusive
def request(op, **kwargs):
    rid = uuid.uuid4().hex
    req = {"id": rid, "op": op, **kwargs}
    temp = CONTROL / "request.tmp"
    temp.write_text(json.dumps(req), encoding="utf-8")
    for attempt in range(100):
        try:
            temp.replace(CONTROL / "request.json")
            break
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(0.01)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            result = json.loads((CONTROL / "response.json").read_text(encoding="utf-8"))
            if result.get("id") == rid:
                result.pop("id")
                if "error" in result:
                    raise RuntimeError(result["error"])
                return result
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.05)
    raise TimeoutError("Game did not acknowledge command; inspect runtime.log and the game window")


@exclusive
def advance(count):
    if type(count) is not int or not 0 <= count <= 36000:
        raise ValueError("Advance count must be an integer between 0 and 36000")
    current = request("snapshot")
    if not current["paused"] or current["pending"]:
        raise RuntimeError("Pause and finish any pending steps before advancing")
    if count == 0:
        return current
    start = current["frame"]
    request("step", count=count)
    deadline = time.monotonic() + max(30, count / 15)
    while time.monotonic() < deadline:
        state = request("snapshot")
        if state["pending"] == 0:
            if state["frame"] != start + count:
                raise RuntimeError(f"Expected frame {start + count}, got {state['frame']}")
            return state
        time.sleep(0.1)
    raise TimeoutError("Step batch did not complete")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("op")
    parser.add_argument("--args", default="{}", help="JSON fields for command")
    parser.add_argument("--count", type=int, help="Frame count for advance/step (avoids shell JSON quoting)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fields = json.loads(args.args)
    if args.count is not None:
        if args.op not in {"advance", "step"}:
            parser.error("--count is only valid with advance or step")
        fields["count"] = args.count
    result = json.dumps(advance(fields.get("count", 1)) if args.op == "advance" else request(args.op, **fields), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result)
