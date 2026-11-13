import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from movie_format import validate


class MovieTests(unittest.TestCase):
    def movie(self):
        return {"format": "kr-tas-v1", "dt": 1/60, "end_frame": 10,
                "events": [{"frame": 2, "name": "keypressed", "args": ["w", "w", False]}]}

    def test_valid_and_same_frame_order_preserved(self):
        m = self.movie()
        m["events"].append({"frame": 2, "name": "keyreleased", "args": ["w", "w"]})
        self.assertEqual(validate(m)["events"][0]["name"], "keypressed")

    def test_unreachable_or_unordered_inputs_rejected(self):
        for frame in (-1, 10, 1.5, True):
            m = self.movie()
            m["events"][0]["frame"] = frame
            with self.assertRaises(ValueError):
                validate(m)
        m = self.movie()
        m["events"].append({"frame": 1, "name": "keyreleased", "args": ["w", "w"]})
        with self.assertRaises(ValueError):
            validate(m)
