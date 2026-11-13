from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import launch


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "runtime").mkdir()
        runtime = b"return {}"
        (root / "runtime/tas_lab.lua").write_bytes(runtime)
        exe = root / "test.exe"
        with zipfile.ZipFile(exe, "w") as archive:
            archive.writestr("tas_lab.lua", runtime)
            archive.writestr("tas_config.json", json.dumps({"game_sha256": "test", "dt": 1/60, "seed": 1}))
        for key, value in (("ROOT", root), ("EXE", exe)):
            p = patch.object(launch, key, value)
            p.start()
            self.addCleanup(p.stop)
        self.movie = {"format": "kr-tas-v1", "end_frame": 1, "events": [], "dt": 1/60,
                      "seed": 1, "game_sha256": "test", "runtime_sha256": hashlib.sha256(runtime).hexdigest()}

    def test_movie_must_match_all_reconstruction_conditions(self):
        launch.validate_environment(self.movie)
        for key, value in (("seed", 2), ("game_sha256", "wrong"),
                           ("runtime_sha256", None), ("dt", 0.5)):
            with self.subTest(field=key), self.assertRaises(ValueError):
                launch.validate_environment({**self.movie, key: value})
        (launch.ROOT / "runtime/tas_lab.lua").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Runtime changed"):
            launch.validate_environment(self.movie)

    def test_running_process_is_never_replaced_by_launcher(self):
        @contextmanager
        def owned():
            yield object()
        with patch.object(launch, "owned_process", owned), patch.object(launch.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "already running"):
                launch.launch_game()
            spawn.assert_not_called()

    def test_wrong_profile_is_never_sent_quit(self):
        kernel = Mock()
        @contextmanager
        def owned():
            yield kernel, object(), {"profile": "expected"}
        with patch.object(launch, "owned_process", owned), \
             patch("control.request", return_value={"identity": "different"}) as request:
            with self.assertRaisesRegex(RuntimeError, "profile"):
                launch.stop_owned()
            request.assert_called_once_with("snapshot")
            kernel.WaitForSingleObject.assert_not_called()


if __name__ == "__main__":
    unittest.main()
