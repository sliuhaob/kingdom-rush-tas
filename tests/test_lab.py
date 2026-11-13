import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("kr_lab", Path(__file__).resolve().parents[1] / "tools/kr_lab.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def trace(self, name, rows):
        p = self.root / name
        p.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
        return p

    def test_compare_requires_complete_replay(self):
        rows = [{"type": "metadata", "seed": 1}, {"type": "state", "tick": 1}]
        a = self.trace("a", rows)
        with self.assertRaises(ValueError):
            lab.compare_traces(a, a)

    def test_compare_reports_first_divergence_and_metadata(self):
        rows = [{"type": "metadata", "seed": 1}, {"type": "state", "tick": 1, "gold": 100},
                {"type": "end", "completed": True}]
        a = self.trace("a", rows)
        self.assertTrue(lab.compare_traces(a, a)["match"])
        rows[1]["gold"] = 99
        b = self.trace("b", rows)
        self.assertEqual(lab.compare_traces(a, b)["row"], 2)
        rows[0]["seed"] = 2
        b = self.trace("b", rows)
        self.assertEqual(lab.compare_traces(a, b)["row"], 1)

    def test_prepare_copies_fused_executable_without_modifying_original(self):
        source = self.root / "installed"
        source.mkdir()
        exe = source / "Kingdom Rush.exe"
        exe.write_bytes(b"MZ" + b"\0" * 64)
        with zipfile.ZipFile(exe, "a") as z:
            z.writestr("main.lua", b"\x1bLJ\x02fake")
        original = exe.read_bytes()
        old_root = lab.ROOT
        lab.ROOT = self.root / "workspace"
        try:
            result = lab.prepare(source, "test")
            self.assertTrue(result["copy_verified"])
            self.assertEqual(exe.read_bytes(), original)
            self.assertEqual((Path(result["lab"]) / "game/Kingdom Rush.exe").read_bytes(), original)
            with self.assertRaises(ValueError):
                lab.prepare(source, "test")
            with self.assertRaises(ValueError):
                lab.prepare(source, "../escape")
        finally:
            lab.ROOT = old_root


if __name__ == "__main__":
    unittest.main()
