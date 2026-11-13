from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import rewind


class RewindTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name in ("BOOKMARKS", "HISTORY"):
            p = patch.object(rewind, name, root / name)
            p.start()
            self.addCleanup(p.stop)
        self.state = {"frame": 5, "paused": True, "pending": 0, "queued_inputs": 0,
                      "gold": 100, "input_state": {"keys": {"w": True}}}
        self.movie = {"format": "kr-tas-v1", "dt": 1/60, "end_frame": 20,
                      "events": [{"frame": 2, "name": "keypressed", "args": ["w"]},
                                 {"frame": 10, "name": "keyreleased", "args": ["w"]}]}

    def test_invalid_target_never_closes_game(self):
        with patch.object(rewind, "capture", return_value=(self.state, self.movie)), \
             patch.object(rewind, "stop_owned") as stop:
            for target in (-1, 21, True):
                with self.assertRaises(ValueError):
                    rewind.seek(target)
            stop.assert_not_called()

    def test_bookmark_integrity_and_no_overwrite(self):
        with patch.object(rewind, "capture", return_value=(self.state, self.movie)):
            rewind.save("held-key")
            with self.assertRaises(FileExistsError):
                rewind.save("held-key")
        path = rewind.bookmark_path("held-key")
        data = json.loads(path.read_text())
        self.assertEqual(len(data["movie"]["events"]), 2)  # Includes the future release.
        data["state"]["gold"] = 999
        path.write_text(json.dumps(data))
        with patch.object(rewind, "stop_owned") as stop:
            with self.assertRaises(ValueError):
                rewind.load("held-key", edit=True)
            stop.assert_not_called()
        for name in ("../outside", "a/b", "", "x" * 65):
            with self.assertRaises(ValueError):
                rewind.bookmark_path(name)

    def test_pending_inputs_cannot_silently_disappear(self):
        for changes in ({"paused": False}, {"pending": 1}, {"queued_inputs": 1}):
            with patch.object(rewind, "request", return_value={**self.state, **changes}):
                with self.assertRaises(RuntimeError):
                    rewind.capture()

    def test_restore_mismatch_never_allows_edit_and_keeps_history(self):
        @contextmanager
        def owned():
            yield object()

        actual = copy.deepcopy(self.state)
        actual["gold"] = 99
        with patch.object(rewind, "validate_environment"), \
             patch.object(rewind, "owned_process", owned), \
             patch.object(rewind, "capture", return_value=(self.state, self.movie)), \
             patch.object(rewind, "stop_owned"), patch.object(rewind, "launch_game"), \
             patch.object(rewind, "request", return_value=actual) as request:
            with self.assertRaisesRegex(RuntimeError, "state mismatch"):
                rewind.restore(self.movie, 5, rewind.gameplay(self.state), edit=True)
            self.assertNotIn("takeover", [c.args[0] for c in request.call_args_list])
        histories = [json.loads(p.read_text()) for p in rewind.HISTORY.glob("*.json")]
        archived = next(d for d in histories if d.get("format") == "kr-tas-history-v1")
        self.assertEqual(archived["movie"], self.movie)
        report = next(d for d in histories if d.get("method") == "fresh-process-replay")
        self.assertFalse(report["verified"])

    def test_replay_restores_then_branches_only_after_comparison(self):
        @contextmanager
        def none():
            yield None

        events = []
        def request(op):
            events.append(op)
            return {**self.state, "frame": 0} if op == "snapshot" else self.state

        with patch.object(rewind, "validate_environment"), \
             patch.object(rewind, "owned_process", none), \
             patch.object(rewind, "stop_owned"), patch.object(rewind, "launch_game"), \
             patch.object(rewind, "advance", return_value=self.state) as advance, \
             patch.object(rewind, "request", side_effect=request):
            result = rewind.restore(self.movie, 5, rewind.gameplay(self.state), edit=True)
        advance.assert_called_once_with(5)
        self.assertEqual(events, ["snapshot", "takeover"])
        self.assertTrue(result["verified"])
        self.assertTrue(result["edit"])


if __name__ == "__main__":
    unittest.main()
