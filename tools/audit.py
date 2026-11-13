"""Verify original code preservation and record provenance for the active lab."""
import hashlib
import json
from pathlib import Path
import zipfile
from kr_lab import sha256

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "lab/kr1-test"
base = json.loads((LAB / "baseline.json").read_text(encoding="utf-8"))
original = Path(base["directory"])
original_matches = {f["name"]: sha256(original / f["name"]) == f["sha256"] for f in base["files"]}
unchanged, mismatched = 0, []
with zipfile.ZipFile(original / "Kingdom Rush.exe") as src, zipfile.ZipFile(LAB / "game/Kingdom Rush.exe") as dst:
    for entry in src.namelist():
        mapped = {"main.lua": "_tas_original_main.lua", "conf.lua": "_tas_original_conf.lua"}.get(entry, entry)
        if src.read(entry) != dst.read(mapped):
            mismatched.append(entry)
        else:
            unchanged += 1
    runtime_hash = hashlib.sha256(dst.read("tas_lab.lua")).hexdigest()
    config = json.loads(dst.read("tas_config.json"))
report = {"original_files_unchanged": all(original_matches.values()), "original_files": original_matches,
          "preserved_archive_entries": unchanged, "changed_original_entries": mismatched,
          "runtime_sha256": runtime_hash, "runtime_matches_source": runtime_hash == sha256(ROOT / "runtime/tas_lab.lua"),
          "game_sha256": config["game_sha256"], "seed": config["seed"], "dt": config["dt"],
          "seed_boundary": "game.init", "platform_services": "disabled in lab only"}
(ROOT / "lab/audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["original_files_unchanged"] and not mismatched and report["runtime_matches_source"] else 1)
