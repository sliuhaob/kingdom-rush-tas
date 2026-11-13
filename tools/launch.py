"""Launch only the isolated instrumented game. Keeps an auditable PID and logs."""
from pathlib import Path
import subprocess
import json
import sys
import argparse
import os
import uuid
import zipfile
import hashlib
from movie_format import validate

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "lab/kr1-test"
sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--replay", type=Path)
args = parser.parse_args()
env = os.environ.copy()
env["KR_TAS_PROFILE"] = "kingdom_rush_tas_" + uuid.uuid4().hex[:12]
if args.replay:
    movie = validate(json.loads(args.replay.read_text(encoding="utf-8")))
    if movie.get("runtime_sha256"):
        with zipfile.ZipFile(LAB / "game/Kingdom Rush.exe") as archive:
            runtime_hash = hashlib.sha256(archive.read("tas_lab.lua")).hexdigest()
        if movie["runtime_sha256"] != runtime_hash:
            raise ValueError("Movie requires a different instrumentation version")
    # Lua 5.1 io.open on Windows expects ANSI paths; keep the movie path relative.
    env["KR_TAS_MOVIE"] = os.path.relpath(args.replay.resolve(), LAB / "game").replace("\\", "/")
(LAB / "control/request.json").write_text('{"id":"boot","op":"pause"}', encoding="utf-8")
with (LAB / "stdout.log").open("wb") as out, (LAB / "stderr.log").open("wb") as err:
    p = subprocess.Popen([str(LAB / "game/Kingdom Rush.exe")], cwd=LAB / "game", stdout=out, stderr=err, env=env)
(LAB / "pid.json").write_text(json.dumps({"pid": p.pid,"profile":env["KR_TAS_PROFILE"]}), encoding="utf-8")
print(json.dumps({"pid": p.pid, "lab": str(LAB),"profile":env["KR_TAS_PROFILE"]}, ensure_ascii=False))
