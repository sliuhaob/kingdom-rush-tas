-- Experimental TAS controls. All gameplay actions go through original callbacks.
local M = {}
local cfg, json, log, frame = nil, nil, nil, 0
local paused, pending, events = true, 0, {}
local request_id, recording, movie, replay = nil, true, {}, nil
local replay_index, replay_done, drawn = 1, false, -1
local keys, buttons, mx, my = {}, {}, 0, 0
local native = {}
local rng_count,rng_hash=0,0
local unpack = unpack or table.unpack

-- HUMP stores timers as table keys. Its native update walks pairs(functions)
-- while callbacks can add timers: a hash-table resize can skip/revisit handles.
-- Keep the original update, arithmetic and callbacks, but enumerate a stable
-- registration-order snapshot. Timers created inside update wait for the next.
local function deterministic_timers(timer)
  local proto=getmetatable(timer.new())
  local native_pairs=pairs
  local sets=setmetatable({}, {__mode='k'})
  local ids=setmetatable({}, {__mode='k'})
  local next_id=0
  for _,name in ipairs({'during','every'}) do
    local original=proto[name]
    proto[name]=function(self,...)
      local handle=original(self,...)
      next_id=next_id+1; ids[handle]=next_id; sets[self.functions]=true
      return handle
    end
  end
  pairs=function(t)
    if not sets[t] then return native_pairs(t) end
    local handles={}
    for h in native_pairs(t) do
      assert(ids[h], 'unregistered timer handle')
      handles[#handles+1]=h
    end
    table.sort(handles,function(a,b) return ids[a]<ids[b] end)
    local index=0
    return function()
      repeat index=index+1 until not handles[index] or t[handles[index]]
      local h=handles[index]
      if h then return h,t[h] end
    end,t,nil
  end
end

local function write(path, data)
  local f=assert(io.open(path,'wb')); f:write(data); f:close()
end
local function note(s)
  if log then log:write(tostring(s)..'\n'); log:flush() end
end
local function read(path)
  local f=io.open(path,'rb'); if not f then return nil end
  local s=f:read('*a'); f:close(); return s
end
local function scalar(t, depth, seen)
  local ty=type(t)
  if ty=='number' then if t~=t then return 'NaN' end; return t end
  if ty=='string' or ty=='boolean' then return t end
  if ty~='table' or depth<=0 then return nil end
  if seen[t] then return nil end
  seen[t]=true
  local out={}
  for k,v in pairs(t) do
    if type(k)=='string' or type(k)=='number' then
      local value=scalar(v,depth-1,seen)
      if value~=nil then out[tostring(k)]=value end
    end
  end
  seen[t]=nil
  return out
end
local function snapshot()
  local g=rawget(_G,'game') or package.loaded.game
  local s=g and g.store
  local result={frame=frame, paused=paused, dt=cfg.dt,
    identity=love.filesystem.getIdentity(), save_directory=love.filesystem.getSaveDirectory(),
    love_version=love._version, game_present=g~=nil, store_present=s~=nil}
  result.width=love.graphics.getWidth(); result.height=love.graphics.getHeight()
  result.pending=pending; result.replay_done=replay_done
  result.queued_inputs=#events
  result.input_state={keys=scalar(keys,2,{}),buttons=scalar(buttons,2,{}),x=mx,y=my}
  result.scene=rawget(_G,'director') and director.last_item_name
  result.math_rng_count=rng_count; result.math_rng_hash=rng_hash
  if s then
    result.tick=s.tick; result.tick_ts=s.tick_ts; result.gold=s.player_gold
    result.lives=s.lives; result.wave=s.wave_group_number; result.level=s.level_idx
    result.game_paused=s.paused
    result.store=scalar(s,2,{})
    result.entities={}
    for id,e in pairs(s.entities or {}) do
      result.entities[tostring(id)]=scalar(e,6,{})
    end
  end
  if love.math and love.math.getRandomState then result.rng=love.math.getRandomState() end
  return result
end
local function dispatch(e)
  local name,a=e.name,e.args or {}
  if name=='keypressed' then keys[a[1]]=true
  elseif name=='keyreleased' then keys[a[1]]=nil
  elseif name=='mousepressed' then mx,my=a[1],a[2]; buttons[a[3]]=true
  elseif name=='mousereleased' then mx,my=a[1],a[2]; buttons[a[3]]=nil
  elseif name=='mousemoved' then mx,my=a[1],a[2] end
  if native[name] then native[name](unpack(a)) end
end
local function response(id, data)
  data.id=id
  write(cfg.directory..'/control/response.json',json.encode(data))
end
local function command()
  local raw=read(cfg.directory..'/control/request.json'); if not raw then return end
  local ok,c=pcall(json.decode,raw); if not ok or not c or c.id==request_id then return end
  request_id=c.id
  local ok,result=pcall(function()
    if c.op=='snapshot' then return snapshot()
    elseif c.op=='pause' then paused=true; return snapshot()
    elseif c.op=='resume' then
      assert(not replay_done,'replay ended; take over before extending the timeline')
      paused=false; return {ok=true}
    elseif c.op=='step' then
      local count=tonumber(c.count) or 1
      assert(count>=1 and count<=36000 and count==math.floor(count),'invalid step count')
      assert(pending==0,'another step batch is pending')
      assert(not replay or frame+count<=replay.end_frame,'step exceeds replay ending')
      paused=true; pending=count; return {ok=true,steps=pending}
    elseif c.op=='input' then
      assert(native[c.name] or c.name=='mousemoved', 'unsupported input')
      assert(not replay,'live input disabled during replay')
      events[#events+1]={name=c.name,args=c.args}; return {ok=true}
    elseif c.op=='movie' then
      return {format='kr-tas-v1',game_sha256=cfg.game_sha256,seed=cfg.seed,dt=cfg.dt,
              runtime_sha256=cfg.runtime_sha256,seed_boundary='game.init',initial_profile='fresh',
              end_frame=replay and replay.end_frame or math.max(1,frame),
              events=replay and replay.events or movie,offline=true,clock_epoch=1700000000}
    elseif c.op=='takeover' then
      assert(paused and pending==0,'pause and finish steps before takeover')
      assert(#events==0,'execute queued input before takeover')
      if replay then
        movie={}
        for _,e in ipairs(replay.events) do
          if e.frame<frame then movie[#movie+1]=e end
        end
      end
      replay=nil; replay_done=false; recording=true
      return snapshot()
    elseif c.op=='inspect' then
      local value=_G
      for _,key in ipairs(c.path or {}) do value=value and value[key] end
      if type(value)=='table' then
        local out={}; for k,v in pairs(value) do out[tostring(k)]=type(v) end; return {fields=out}
      end
      return {kind=type(value),value=scalar(value,2,{})}
    elseif c.op=='quit' then love.event.quit(); return {ok=true}
    else error('unknown command') end
  end)
  if not ok then result={error=tostring(result)}; note(result.error) end
  response(c.id,result)
end

function M.before()
  -- The game establishes its own package paths later. Load JSON by exact path.
  json=assert(love.filesystem.load('lib/json.lua'))()
  cfg=json.decode(assert(love.filesystem.read('tas_config.json')))
  log=assert(io.open(cfg.directory..'/runtime.log','wb'))
  note('boot '..tostring(love._version)..' save='..love.filesystem.getSaveDirectory())
  native.time=os.time
  os.time=function(t) if t then return native.time(t) end; return 1700000000 end
  native.randomseed=math.randomseed
  native.random=math.random
  math.random=function(...)
    local r=native.random(...)
    rng_count=rng_count+1; rng_hash=(rng_hash*65599+math.floor(r*1000000))%4294967296
    return r
  end
  math.randomseed=function(_)
    rng_count=0; rng_hash=0
    return native.randomseed(cfg.seed)
  end
  math.randomseed(cfg.seed)
  if love.math then
    native.setRandomSeed=love.math.setRandomSeed
    love.math.setRandomSeed=function() return native.setRandomSeed(cfg.seed) end
    love.math.setRandomSeed(cfg.seed)
  end
  local movie_path=os.getenv('KR_TAS_MOVIE')
  if movie_path then
    replay=json.decode(assert(read(movie_path)))
    assert(replay.game_sha256==cfg.game_sha256,'movie game version mismatch')
    assert(replay.dt==cfg.dt or math.abs(replay.dt-cfg.dt)<1e-14,'movie timestep mismatch')
    assert(replay.seed==cfg.seed,'movie seed mismatch')
    recording=false
    note('replaying '..movie_path)
  end
  local original_require=require
  local timer_hooked=false
  local initialized=false
  require=function(name)
    local module=original_require(name)
    if name=='hump.timer' and not timer_hooked then
      timer_hooked=true
      deterministic_timers(module)
    end
    if name=='game' and type(module)=='table' and not initialized then
      initialized=true
      local init=module.init
      module.init=function(...)
        -- Explicit per-level initial seed, preserving the game's PRNG algorithm.
        -- Menu/loading RNG consumption is outside this level's seed boundary.
        math.randomseed(cfg.seed)
        love.math.setRandomSeed(cfg.seed)
        note('level seed reset at frame '..frame)
        return init(...)
      end
    end
    return module
  end
end

function M.after()
  note('original main loaded')
  -- Disable account/network services in this isolated experimental profile.
  -- This changes platform integration only; all combat code stays original.
  local features=require('features')
  for name,service in pairs(features.platform_services or {}) do
    if type(service)=='table' then service.enabled=false; note('offline service '..tostring(name)) end
  end
  local mu=require('main_utils')
  local default_params=mu.default_params
  mu.default_params=function(p,...)
    default_params(p,...)
    p.skip_settings_dialog=true; p.width=1024; p.height=768
    p.fullscreen=false; p.vsync=false; p.pause_on_switch=false
  end
  local original_load=love.load
  love.load=function(...)
    if original_load then original_load(...) end
    note('load finished save='..love.filesystem.getSaveDirectory())
    note('love.update='..type(love.update)..' love.draw='..type(love.draw))
  end
  native.getDelta=love.timer.getDelta
  native.getTime=love.timer.getTime
  love.timer.getDelta=function() return cfg.dt end
  love.timer.getTime=function() return frame*cfg.dt end
  local original_update=love.update
  love.update=function(dt)
    command()
    if not paused or pending>0 then
      if replay then
        events={}
        while replay.events[replay_index] and replay.events[replay_index].frame==frame do
          events[#events+1]=replay.events[replay_index]; replay_index=replay_index+1
        end
      end
      for _,e in ipairs(events) do
        if recording then movie[#movie+1]={frame=frame,name=e.name,args=e.args} end
        dispatch(e)
      end
      events={}
      original_update(cfg.dt)
      frame=frame+1
      if pending>0 then pending=pending-1 end
      if replay and frame>=replay.end_frame then replay_done=true; paused=true; pending=0 end
    end
  end
  for _,name in ipairs({'keypressed','keyreleased','mousepressed','mousereleased','mousemoved','wheelmoved','textinput'}) do
    native[name]=love[name]
    love[name]=function(...)
      if not replay then events[#events+1]={name=name,args={...}} end
    end
  end
  love.mouse.getPosition=function() return mx,my end
  love.mouse.getX=function() return mx end
  love.mouse.getY=function() return my end
  love.mouse.isDown=function(...)
    for _,b in ipairs({...}) do if buttons[b] then return true end end; return false
  end
  love.keyboard.isDown=function(...)
    for _,k in ipairs({...}) do if keys[k] then return true end end; return false
  end
  love.keyboard.isScancodeDown=love.keyboard.isDown
  love.run=function()
    if love.load then love.load(arg) end
    while true do
      love.event.pump()
      for name,a,b,c,d,e,f in love.event.poll() do
        if name=='quit' then
          if not love.quit or not love.quit() then return end
        elseif love.handlers[name] then love.handlers[name](a,b,c,d,e,f) end
      end
      love.update(cfg.dt)
      if love.graphics.isActive() and drawn~=frame then
        love.graphics.clear(love.graphics.getBackgroundColor())
        love.graphics.origin()
        if rawget(_G,'director') then director:draw()
        elseif love.draw then love.draw() end
        love.graphics.present()
        drawn=frame
      end
      love.timer.sleep(0.001)
    end
  end
  local errhand=love.errhand
  love.errhand=function(err)
    note('ERROR '..tostring(err)..'\n'..debug.traceback())
    return errhand(err)
  end
  note('hooks installed')
end
return M
