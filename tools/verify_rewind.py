"""Real-game acceptance test: bookmark, replay continuation, rewind and input branch."""
import argparse
import json
from pathlib import Path
import sys
import uuid

from control import advance, request
from launch import launch_game, stop_owned
from movie_format import validate
import rewind
from session_lock import exclusive
from verify_replay import differences, gameplay, validate_victory

ROOT = Path(__file__).resolve().parents[1]


@exclusive
def verify(movie_path, output):
    movie = validate(json.loads(movie_path.read_text(encoding="utf-8")))
    if movie["end_frame"] < 5103:
        raise ValueError("This acceptance test requires the full Southport input sample")
    output.mkdir(parents=True, exist_ok=False)
    prefix = "verify_" + uuid.uuid4().hex[:12]
    report = {"movie": str(movie_path), "checks": []}

    def check(name, actual, expected):
        diff = differences(expected, actual)
        report["checks"].append({"name": name, "match": not diff, "differences": diff})
        rewind.write_new(output / (name + ".json"), actual)
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if diff:
            raise RuntimeError(f"Rewind acceptance failed: {name}")
        print(json.dumps({"check": name, "match": True}), flush=True)

    stop_owned()
    try:
        launch_game(movie_path)
        start = gameplay(advance(3741))
        rewind.save(prefix + "_battle")
        final = advance(movie["end_frame"] - 3741)
        validate_victory(final, movie.get("expected_outcome"))
        final = gameplay(final)
        result = rewind.load(prefix + "_battle")
        check("bookmark_verified", result["verified"], True)
        check("bookmark_state", gameplay(request("snapshot")), start)
        check("continued_victory", gameplay(advance(movie["end_frame"] - 3741)), final)

        rewind.seek(movie["end_frame"] - 3741, edit=True, relative=True)
        check("back_state", gameplay(request("snapshot")), start)
        prefix_events = [e for e in movie["events"] if e["frame"] < 3741]
        exported = request("movie")
        check("branch_prefix", exported["events"], prefix_events)
        check("branch_end", exported["end_frame"], 3741)
        # Exercise a held key across a bookmark, and a distinct new mouse input.
        request("input", name="keypressed", args=["w", "w", False])
        request("input", name="mousemoved", args=[111, 222, 0, 0, False])
        held = gameplay(advance(1))
        check("held_key", held["input_state"]["keys"].get("w"), True)
        rewind.save(prefix + "_held")
        request("input", name="keyreleased", args=["w", "w"])
        branch = gameplay(advance(5103 - 3742))
        branch_movie = request("movie")
        validate(branch_movie)
        branch_path = output / "branch.movie.json"
        rewind.write_new(branch_path, branch_movie)
        check("branch_input_count", len(branch_movie["events"]), len(prefix_events) + 3)

        result = rewind.load(prefix + "_held", edit=True)
        check("held_bookmark_verified", result["verified"], True)
        check("held_bookmark_state", gameplay(request("snapshot")), held)
        request("input", name="keyreleased", args=["w", "w"])
        check("edited_continuation", gameplay(advance(5103 - 3742)), branch)
        stop_owned()
        launch_game(branch_path)
        check("branch_replay_held", gameplay(advance(3742)), held)
        ending = advance(5103 - 3742)
        check("branch_replay_final", gameplay(ending), branch)
        check("branch_replay_done", ending["replay_done"], True)
    finally:
        stop_owned()
    return report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movie", type=Path, default=ROOT / "examples/southport-normal.movie.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.movie.resolve(), args.output.resolve())
    print(json.dumps({"passed": len(result["checks"]), "output": str(args.output)}))
