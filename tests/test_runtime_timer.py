"""Optional native LuaJIT regression test using the user's private game library."""
import ctypes
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DLL = ROOT / "lab/kr1-test/game/lua51.dll"


@unittest.skipUnless(DLL.exists(), "Requires the user's local LuaJIT; never bundled in CI")
class TimerTests(unittest.TestCase):
    def test_callback_additions_cancellations_and_registration_order(self):
        source = (ROOT / "runtime/tas_lab.lua").read_text(encoding="utf-8")
        adapter = source[source.index("local function deterministic_timers("):
                         source.index("local function write(")]
        script = adapter + r'''
local native_pairs=pairs
local proto={}; proto.__index=proto
local timer={new=function() return setmetatable({functions={}},proto) end}
function proto:during(delay,callback)
  local h={callback=callback}; self.functions[h]=true; return h
end
proto.every=proto.during
local t=timer.new()
deterministic_timers(timer)
local seen={}
local cancelled
t:during(0,function()
  seen[#seen+1]='A'; t.functions[cancelled]=nil
  t:during(0,function() seen[#seen+1]='C' end)
end)
cancelled=t:during(0,function() error('cancelled callback ran') end)
t:every(0,function() seen[#seen+1]='B' end)
local function update()
  for h in pairs(t.functions) do h.callback(); t.functions[h]=nil end
end
update(); assert(table.concat(seen)=="AB",table.concat(seen))
update(); assert(table.concat(seen)=="ABC",table.concat(seen))
local ordinary={x=1}
local f,s,k=pairs(ordinary)
local nf,ns,nk=native_pairs(ordinary)
assert(f==nf and s==ns and k==nk,'changed unrelated table iteration')
'''
        lib = ctypes.CDLL(str(DLL))
        lib.luaL_newstate.restype = ctypes.c_void_p
        lib.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lib.luaL_loadbuffer.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
        lib.lua_pcall.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.lua_tolstring.restype = ctypes.c_char_p
        lib.lua_close.argtypes = [ctypes.c_void_p]
        state = lib.luaL_newstate()
        self.assertTrue(state)
        try:
            lib.luaL_openlibs(state)
            code = script.encode()
            status = lib.luaL_loadbuffer(state, code, len(code), b"timer-regression")
            if status == 0:
                status = lib.lua_pcall(state, 0, 0, 0)
            error = lib.lua_tolstring(state, -1, None) if status else b""
            self.assertEqual(status, 0, error.decode(errors="replace"))
        finally:
            lib.lua_close(state)


if __name__ == "__main__":
    unittest.main()
