"""Replay recorded input from a fresh profile and compare gameplay checkpoints."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from control import request, advance
from kr_lab import compare_traces
from movie_format import validate

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "lab/kr1-test"


def gameplay(state):
    return {k: v for k, v in state.items()
            if k not in {"identity", "save_directory", "paused", "pending", "replay_done", "queued_inputs"}}


def differences(a, b, path=""):
    if type(a) is not type(b):
        return [{"path": path, "left": a, "right": b}]
    if isinstance(a, dict):
        out = []
        for key in sorted(a.keys() | b.keys()):
            if key not in a or key not in b:
                out.append({"path": path + "/" + key, "left": a.get(key), "right": b.get(key)})
            else:
                out.extend(differences(a[key], b[key], path + "/" + key))
            if len(out) >= 10:
                return out[:10]
        return out
    if a != b:
        return [{"path": path, "left": a, "right": b}]
    return []


def checkpoint_frames(path, end_frame):
    frames = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(frames, list) or not frames:
        raise ValueError("Checkpoints must be a nonempty array of frame numbers")
    if any(type(f) is not int or not 0 < f <= end_frame for f in frames):
        raise ValueError("Checkpoint frames must be positive integers within the movie")
    if frames != sorted(set(frames)) or frames[-1] != end_frame:
        raise ValueError("Checkpoints must be strictly increasing and end at end_frame")
    return frames


def load_reference(path, metadata, frames, end):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(frames) + 2 or rows[0] != metadata or rows[-1] != end:
        raise ValueError("Reference metadata, length, or completed ending does not match this movie")
    states = []
    for row, frame in zip(rows[1:-1], frames):
        if row.get("type") != "state" or row.get("frame") != frame:
            raise ValueError("Reference checkpoint frames do not match")
        states.append({k: v for k, v in row.items() if k != "type"})
    return states


def validate_victory(state, expected=None):
    store = state.get("store", {})
    outcome = store.get("game_outcome", {})
    if outcome.get("victory") is not True or store.get("waves_finished") is not True:
        raise ValueError("Movie ended without a confirmed in-game victory")
    if state.get("lives", 0) <= 0 or state.get("wave") != store.get("wave_group_total"):
        raise ValueError("Victory requires positive lives and the final wave")
    for key, value in (expected or {}).items():
        if outcome.get(key) != value:
            raise ValueError(f"Unexpected victory outcome for {key}: {outcome.get(key)!r} != {value!r}")
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--movie", type=Path, default=ROOT / "examples/southport-probe.movie.json")
    parser.add_argument("--checkpoints", type=Path, default=ROOT / "examples/southport-probe.checkpoints.json")
    parser.add_argument("--require-victory", action="store_true", help="Require the native game_outcome to confirm victory; also implied by a movie's expected_outcome")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record-reference", action="store_true", help="Record a fresh reference, then compare independent replays")
    mode.add_argument("--reference", type=Path, help="Compare against a previously recorded reference.jsonl")
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing directories are never overwritten")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    movie = args.movie.resolve()
    data = validate(json.loads(movie.read_text(encoding="utf-8")))
    require_victory = args.require_victory or bool(data.get("expected_outcome"))
    frames = checkpoint_frames(args.checkpoints, data["end_frame"])
    metadata = {"type": "metadata", "movie_sha256": hashlib.sha256(movie.read_bytes()).hexdigest(),
                "game_sha256": data["game_sha256"], "seed": data["seed"], "dt": data["dt"],
                "runtime_sha256": hashlib.sha256((ROOT / "runtime/tas_lab.lua").read_bytes()).hexdigest()}
    end = {"type": "end", "completed": True, "frame": data["end_frame"], "scope": "startup and first-wave probe, not level completion"}
    if require_victory:
        end["scope"] = "completed level with native victory outcome"
        metadata["require_victory"] = True
    expected = load_reference(args.reference, metadata, frames, end) if args.reference else None
    def trace(path, states):
        rows = [metadata, *[{"type": "state", **s} for s in states], end]
        path.write_text("\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows), encoding="utf-8")
    outdir = args.output
    outdir.mkdir(parents=True, exist_ok=False)
    if not args.record_reference:
        trace(outdir / "reference.jsonl", expected)
    report = []
    for run in range(0 if args.record_reference else 1, args.runs + 1):
        try:
            request("quit")
        except TimeoutError:
            pass
        time.sleep(0.5)
        launch = subprocess.run([sys.executable, str(ROOT / "tools/launch.py"), "--replay", str(movie)],
                                capture_output=True, text=True, encoding="utf-8", check=True)
        info = json.loads(launch.stdout)
        actual = []
        try:
            for index, frame in enumerate(frames):
                current = request("snapshot")
                count = frame - current["frame"]
                # Vary command batch boundaries to detect dependence on real pauses.
                if run == 3 and count > 2:
                    advance(count // 2)
                    time.sleep(0.2)
                    count -= count // 2
                state = advance(count)
                actual.append(gameplay(state))
                diff = differences(expected[index], actual[-1]) if run else []
                print(json.dumps({"run": run, "frame": frame, "match": (not diff) if run else "reference", "differences": diff}), flush=True)
            if state.get("replay_done") is not True:
                raise RuntimeError("Replay did not reach its completed ending")
            if require_victory:
                validate_victory(state, data.get("expected_outcome"))
        finally:
            request("quit")
        if run == 0:
            expected = actual
            trace(outdir / "reference.jsonl", expected)
            continue
        trace(outdir / f"replay-{run}.jsonl", actual)
        comparison = compare_traces(outdir / "reference.jsonl", outdir / f"replay-{run}.jsonl")
        report.append({"run": run, "profile": info["profile"], "match": comparison["match"],
                       "checkpoint_count": len(actual), "replay_done": state["replay_done"],
                       "game_outcome": state.get("store", {}).get("game_outcome")})
        (outdir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if all(r["match"] and r["replay_done"] for r in report) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
