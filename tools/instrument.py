"""Install our instrumentation into the private lab copy, never the Steam copy."""
import hashlib
import json
from pathlib import Path
import zipfile
import os

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "lab/kr1-test"
baseline = json.loads((LAB / "baseline.json").read_text(encoding="utf-8"))
source = Path(baseline["directory"]) / "Kingdom Rush.exe"
target = LAB / "game/Kingdom Rush.exe"
assert source.resolve() != target.resolve()
expected = next(f["sha256"] for f in baseline["files"] if f["name"] == source.name)
supported = "ebb4a3a9fd4fa6a30fb98e2b39fb32f0eff8630d47a3951b658339c26ce91e7b"
if expected != supported:
    raise ValueError("Unsupported executable: this prototype targets Steam build 24662480 (6.4.46)")
if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
    raise ValueError("Original version changed since prepare; create a new verified lab")
(LAB / "control").mkdir(exist_ok=True)
(LAB / "control/request.json").write_text('{"id":"boot","op":"pause"}', encoding="utf-8")
config = {"directory": "..", "identity": "kingdom_rush_tas_lab",
          "seed": 246420, "dt": 1 / 60, "game_sha256": expected}
conf = '''local f=assert(love.filesystem.load('_tas_original_conf.lua')); f()
local original=love.conf
function love.conf(t)
  if original then original(t) end
  t.identity=os.getenv('KR_TAS_PROFILE') or 'kingdom_rush_tas_lab'
  t.console=false
end
'''
main = '''local original_identity=love.filesystem.setIdentity
local identity=os.getenv('KR_TAS_PROFILE') or 'kingdom_rush_tas_lab'
love.filesystem.setIdentity=function(_) return original_identity(identity) end
love.filesystem.setIdentity(identity)
local lab=assert(love.filesystem.load('tas_lab.lua'))()
lab.before()
assert(love.filesystem.load('_tas_original_main.lua'))()
lab.after()
'''
with zipfile.ZipFile(source) as zin:
    prefix_size = min(i.header_offset for i in zin.infolist())
    temp = target.with_suffix(".tmp")
    with source.open("rb") as src, temp.open("wb") as dst:
        dst.write(src.read(prefix_size))
    with zipfile.ZipFile(temp, "a", compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            name = {"main.lua": "_tas_original_main.lua", "conf.lua": "_tas_original_conf.lua"}.get(item.filename, item.filename)
            zout.writestr(name, zin.read(item.filename))
        zout.writestr("conf.lua", conf)
        zout.writestr("main.lua", main)
        zout.writestr("tas_lab.lua", (ROOT / "runtime/tas_lab.lua").read_bytes())
        zout.writestr("tas_config.json", json.dumps(config))
    os.replace(temp, target)
print("Instrumented private copy. Steam original hash verified unchanged.")
