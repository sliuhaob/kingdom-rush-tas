import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import control
import verify_replay as verify
from movie_format import validate


class ReplayTests(unittest.TestCase):
    def test_movie_ending_is_not_proof_of_victory(self):
        with self.assertRaises(ValueError):
            verify.validate_victory({"replay_done": True, "lives": 20, "wave": 1})
        state = {"replay_done": True, "lives": 19, "wave": 7,
                 "store": {"waves_finished": True, "wave_group_total": 7,
                           "game_outcome": {"victory": True, "stars": 3, "lives_left": 19}}}
        self.assertTrue(verify.validate_victory(state, {"stars": 3})["victory"])
        with self.assertRaises(ValueError):
            verify.validate_victory(state, {"lives_left": 20})
        state["store"]["waves_finished"] = False
        with self.assertRaises(ValueError):
            verify.validate_victory(state)

    def test_public_sample_matches_runtime_and_checkpoints(self):
        for name in ["southport-probe", "southport-normal"]:
            with self.subTest(movie=name):
                movie = validate(json.loads((ROOT / f"examples/{name}.movie.json").read_text(encoding="utf-8")))
                self.assertEqual(movie["runtime_sha256"], hashlib.sha256((ROOT / "runtime/tas_lab.lua").read_bytes()).hexdigest())
                frames = verify.checkpoint_frames(ROOT / f"examples/{name}.checkpoints.json", movie["end_frame"])
                self.assertEqual(frames[-1], movie["end_frame"])

    def test_zero_advance_never_sends_step(self):
        state = {"frame": 10, "paused": True, "pending": 0}
        with patch.object(control, "request", return_value=state) as request:
            self.assertEqual(control.advance(0), state)
            request.assert_called_once_with("snapshot")

    def test_invalid_advance_never_sends_input(self):
        with patch.object(control, "request") as request:
            for count in (-1, 36001, 1.5, True):
                with self.assertRaises(ValueError):
                    control.advance(count)
            request.assert_not_called()

    def test_reference_requires_matching_metadata_and_completed_ending(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reference.jsonl"
            meta = {"type": "metadata", "seed": 1}
            end = {"type": "end", "completed": True, "frame": 10}
            rows = [meta, {"type": "state", "frame": 10, "gold": 100}, end]
            path.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
            self.assertEqual(verify.load_reference(path, meta, [10], end)[0]["gold"], 100)
            with self.assertRaises(ValueError):
                verify.load_reference(path, {**meta, "seed": 2}, [10], end)
            rows[-1]["completed"] = False
            path.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify.load_reference(path, meta, [10], {**end, "completed": True})

    def run_fake_suite(self, output, drift=False):
        frame, run = 0, -1

        def state():
            return {"frame": frame, "paused": True, "pending": 0, "replay_done": frame == 3741,
                    "gold": 99 if drift and run > 0 else 100, "identity": f"test_{run}"}

        def launch(*args, **kwargs):
            nonlocal frame, run
            frame = 0
            run += 1
            return SimpleNamespace(stdout=json.dumps({"profile": f"test_{run}"}))

        def request(op):
            return state() if op == "snapshot" else {"ok": True}

        def advance(count):
            nonlocal frame
            frame += count
            return state()

        with patch.object(verify.subprocess, "run", side_effect=launch), \
             patch.object(verify, "request", side_effect=request), \
             patch.object(verify, "advance", side_effect=advance), \
             patch.object(verify.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            return verify.main(["--record-reference", "--runs", "1", "--output", str(output)])

    def test_fresh_reference_uses_public_inputs_without_private_lab_records(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "new"
            self.assertEqual(self.run_fake_suite(output), 0)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report[0]["match"])
            self.assertEqual(report[0]["checkpoint_count"], 6)

    def test_suite_fails_when_replay_gameplay_drifts(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self.run_fake_suite(Path(td) / "new", drift=True), 1)


if __name__ == "__main__":
    unittest.main()
