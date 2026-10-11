-- Long-lived plumbing singleton (Lua's package.loaded owns its lifetime).
-- Callbacks enqueue; only the guarded pump invokes update/advance or reconnect.
local M = {}
local state = require('mes_state')
local event = require('event')
local computer = require('computer')
local world = state.world()
local queue, head = {}, 1
local installed, pumping = false, false
local history, active, nextRun, none = {}, {}, 0, { status = 'idle', stages = {}, active = {} }
local wh, lg, client, prepareRobot
local persist, disk, savedRevision, portsFor, snapshot
local watched = {} -- logistics job id -> owning run id
local function enqueue(id, what, data)
  queue[#queue + 1] = { id = id, what = what, data = data }
end
M.enqueue = enqueue
function M.guarded()
  return pumping
end
local function onRobot(token, what, data)
  local d = state.copy(data or {})
  d.token = token
  enqueue(nil, what, d)
end
local function observeJobs()
  for id in pairs(watched) do
    local r = lg.status(id)
    if r then
      enqueue(watched[id], 'job', { id = id, receipt = r })
      local done = r.state == 'done' or r.state == 'failed' or r.state == 'partial'
      if done and wh.settled(id) == true then
        enqueue(watched[id], 'settled', { id = id })
        watched[id] = nil
      end
    else
      enqueue(watched[id], 'job_missing', { id = id, reason = 'Missing logistics job ' .. tostring(id) })
    end
  end
end
local function dispatch(a, run)
  local ok, ids, err, partial
  if a.kind == 'robot_inspect' then
    ok, ids, err = pcall(client.inspect, a.token, a.address, nil, a.options or M.clientOptions)
    if not ok or not ids then
      onRobot(
        a.token,
        'robot_status',
        { address = a.address, unknown = true, reason = not ok and tostring(ids) or tostring(err) }
      )
    end
    return ok and ids
  end
  local options = run.opts.logistics
  if a.kind == 'robot_begin' then
    ok, ids, err = pcall(client.begin, a.token, a.address, a.plan, a.jobId, run.opts.client)
    enqueue(
      run.id,
      'action_submitted',
      { token = a.token, ids = {}, error = not ok and tostring(ids) or not ids and tostring(err) or nil }
    )
    return ok and ids, not ok and tostring(ids) or not ids and tostring(err) or nil
  elseif a.kind == 'fetchMany' then
    ok, ids, err, partial = pcall(wh.fetchMany, a.requests, a.endpoint, options)
  elseif a.kind == 'collectMany' then
    options = state.copy(options or {})
    options.wait = a.wait
    ok, ids, err, partial = pcall(wh.collect, a.endpoint, a.requests, options)
  elseif a.kind == 'scan' then
    ok, ids, err, partial = pcall(wh.scan, a.storage)
  else
    ok = false
    ids = 'Unknown MES action ' .. tostring(a.kind)
  end
  local submitted = ok and (ids or partial) or {}
  if type(submitted) ~= 'table' then
    submitted = {}
  end
  if ok and ids and a.kind == 'scan' and #submitted == 0 then
    ids = nil
    err = 'Warehouse scan submitted no jobs'
  end
  for _, id in ipairs(submitted) do
    watched[id] = run.id
  end
  enqueue(
    run.id,
    'action_submitted',
    { token = a.token, ids = submitted, error = not ok and tostring(ids) or not ids and tostring(err) or nil }
  )
  return ok and ids, not ok and tostring(ids) or not ids and tostring(err) or nil
end
-- Facts carry their run id, a robot token "<run>:<n>" or job id "mes-<run>-<stage>"; the rest are world facts.
local function owner(f)
  local d = type(f.data) == 'table' and f.data or {}
  local n = type(d.token) == 'string' and d.token:match('^(%d+):')
    or type(d.jobId) == 'string' and d.jobId:match('^mes%-(%d+)%-')
  local run = history[f.id or tonumber(n or '')]
  return run and run.status == 'running' and run
end
-- Least recently served run decides first, so no request starves.
local function order()
  table.sort(active, function(a, b)
    if (a.served or 0) ~= (b.served or 0) then
      return (a.served or 0) < (b.served or 0)
    end
    return a.id < b.id
  end)
  return { table.unpack(active) }
end
function M.pump()
  if pumping or not installed then
    return
  end
  pumping = true
  local ok, err = xpcall(function()
    while head <= #queue do
      local f = queue[head]
      head = head + 1
      if f.what == 'tick' then
        -- The only permitted blocking call lives below client.tick: api.connect.
        -- A nested signal callback may enqueue but cannot re-enter this pump.
        client.tick(f.data.now)
        f.data.now = computer.uptime()
        observeJobs()
      elseif f.what == 'observe_jobs' then
        observeJobs()
      end
      -- Finished runs are not visited, so history never slows a tick.
      local run = owner(f)
      if f.what == 'tick' then
        for _, r in ipairs(active) do
          state.update(r, 'tick', f.data)
        end
      elseif run then
        state.update(run, f.what, f.data)
      else
        state.updateWorld(world, f.what, f.data)
      end
      -- Drain nested facts together before decisions, preserving first-known
      -- failures and preventing any policy execution in transport callbacks.
      if head > #queue then
        state.advanceWorld(world, dispatch, M.clientOptions)
        if head > #queue then
          local now = computer.uptime()
          for _, r in ipairs(order()) do
            if r.status == 'running' then
              state.update(r, 'tick', { now = now })
              state.advance(r)
            end
          end
          for i = #active, 1, -1 do
            if active[i].status ~= 'running' then
              table.remove(active, i)
            end
          end
        end
      end
    end
    queue = {}
    head = 1
    if world.revision ~= savedRevision then
      persist.save(disk, world, history, active, nextRun, snapshot)
      savedRevision = world.revision
    end
  end, debug.traceback)
  pumping = false
  if not ok then
    error(err, 0)
  end
end
function M.start(opts, prepare)
  opts = opts or {}
  if prepare then
    prepareRobot = prepare
  end
  if installed then
    return true
  end
  require('mes_config').installRobots()
  -- First imports occur here, never in a transient stage/client.
  lg = require('logistics')
  require('map')
  wh = require('warehouse')
  require('stations')
  require('stats')
  require('iochest')
  client = require('craft_client')
  persist = require('mes_persist')
  disk = persist.open()
  M.clientOptions = state.copy(opts.client or {})
  installed = true
  pumping = true
  local ok, rows = pcall(client.install, onRobot, M.clientOptions)
  if ok then
    history, active, nextRun, watched = persist.restore(disk, world,
      function() return require('mes_config').config(opts) end, portsFor, client, computer.uptime())
    savedRevision = world.revision
    for _, row in ipairs(rows or {}) do
      if not world.robots[row.address] then
        world.robots[row.address] = { state = 'unknown' }
        world.revision = world.revision + 1
      end
    end
  end
  pumping = false
  if not ok then
    installed = false
    return nil, tostring(rows)
  end
  local function signal()
    enqueue(nil, 'observe_jobs', {})
    M.pump()
  end
  event.listen('logistics', signal)
  event.listen('warehouse', signal)
  M.timer = event.timer(opts.serviceSeconds or 0.1, function()
    enqueue(nil, 'tick', { now = computer.uptime() })
    M.pump()
  end, math.huge)
  M.pump()
  return true
end
function M.reconcile(cfg, opts)
  local addresses = {}
  for _, c in pairs(cfg.crafters or {}) do
    addresses[c.robot] = true
  end
  enqueue(nil, 'reconcile', { addresses = addresses, opts = opts.client })
  M.pump()
end
local function crafters(cfg)
  local out = state.copy(cfg.crafters or {})
  local groups = wh.groups('crafter')
  for name, c in pairs(out) do
    c.buffer = (groups[name] and groups[name].roles.buffer) or c.buffer
  end
  return out
end
local function bufferIdentity(storage)
  local member = wh.members()[storage]
  return member and member.inventory or storage
end
portsFor = function(id, cfg)
  return {
    dispatch = dispatch,
    emit = function(...)
      event.push('mes', ...)
    end,
    contents = wh.contents,
    consumed = wh.consumed,
    observed = wh.observed,
    -- Stock this run may take: what no drone is already taking, less what
    -- other runs claim and have not yet sent a drone for.
    stock = function(item)
      local n, d = item:match('^(.*):(%d+)$')
      local count = wh.available({ name = n or item, damage = tonumber(d) or 0 })
      for _, r in ipairs(active) do
        if r.id ~= id then
          count = count - math.max(0, ((r.claims or {})[item] or 0) - ((r.inflight or {})[item] or 0))
        end
      end
      return math.max(0, count)
    end,
    crafters = function()
      return crafters(cfg)
    end,
    groups = wh.groups,
    bufferIdentity = bufferIdentity,
    prepareRobot = prepareRobot,
  }
end
function M.submit(plan, cfg, opts)
  nextRun = nextRun + 1
  local run = state.new(nextRun, plan, cfg, opts, world, portsFor(nextRun, cfg), computer.uptime())
  persist.plan(disk, run)
  history[nextRun] = run
  active[#active + 1] = run
  enqueue(run.id, 'advance', {})
  M.pump()
  return run.id
end
-- The public status of a run; the rest is working state.
local public = {}
for _, k in ipairs({
  'id', 'item', 'qty', 'status', 'stage', 'active', 'started', 'finished', 'trips',
  'reason', 'error', 'where', 'stopping', 'uncertain', 'callbackError',
}) do
  public[k] = true
end
snapshot = function(run)
  if not run then
    return
  end
  local o = {}
  for k, v in pairs(run) do
    if public[k] then
      o[k] = state.copy(v)
    end
  end
  o.stages = {}
  for i, s in ipairs(run.stages) do
    o.stages[i] = state.stageSnapshot(s)
  end
  return o
end
function M.status(id)
  if id ~= nil then
    return snapshot(history[id])
  end
  return snapshot(history[nextRun] or none)
end
-- Raw stock still claimed by running requests; planning withholds it.
function M.claims()
  local o = {}
  for _, r in ipairs(active) do
    for id, n in pairs(r.claims or {}) do
      o[id] = (o[id] or 0) + n
    end
  end
  return o
end
function M.wait(id)
  local run = history[id]
  if not run then
    return nil, 'Unknown run'
  end
  while run.status == 'running' do
    event.pull(0.2)
  end
  return snapshot(run)
end
function M.runs()
  local o = {}
  for id = nextRun, 1, -1 do
    local r = history[id]
    if r then o[#o + 1] = {
      id = id,
      item = r.item,
      qty = r.qty,
      status = r.status,
      stage = r.stage,
      active = state.copy(r.active),
      stages = #r.stages,
    } end
  end
  return o
end
function M.resources(cfg)
  local o = { crafters = {}, machines = {} }
  for name, c in pairs(crafters(cfg)) do
    local r = state.copy(world.robots[c.robot] or { state = 'unknown' })
    r.pending = nil
    r.robot = c.robot
    r.buffer = c.buffer
    local b = world.buffers[bufferIdentity(c.buffer)]
    if b and b.state ~= 'idle' then
      r.state = b.state
      r.run = b.run
      r.step = b.step
      r.bufferOwner = b.owner
    end
    o.crafters[name] = r
  end
  for name, g in pairs(wh.groups()) do
    if g.type ~= 'crafter' then
      o.machines[name] = state.copy(world.machines[name] or { state = 'idle', type = g.type, loads = {} })
    end
  end
  return o
end
-- Fuel the MES has delivered to a machine and the inputs admitted against it.
function M.fuel(name)
  local m = world.machines[name]
  return state.copy(m and m.fuel or { credit = 0, admitted = 0 })
end
function M.confirmIdle(address)
  enqueue(nil, 'robot_status', { address = address, busy = false })
  M.pump()
end
function M.cancel(id, reason)
  if not history[id] then
    return nil, 'Unknown run'
  end
  enqueue(id, 'cancel', { reason = reason })
  M.pump()
  return true
end
return M
