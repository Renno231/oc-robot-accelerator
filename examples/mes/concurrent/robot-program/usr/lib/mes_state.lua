-- MES decision engine. Facts and cached observations in; nonblocking actions out.
-- There are deliberately no event, computer, warehouse or transport imports.
local M = {}
local identity = require('item_identity')
-- Machine timing. A load may run this long past its expected finish, and a
-- blocked request may wait this long for input room, before it fails.
local MACHINE_GRACE = 60
-- Re-read delays for machine input and output start here and double up to
-- the maximum while nothing changes.
local BACKOFF, MAX_BACKOFF = 0.5, 8
local function copy(t)
  if type(t) ~= 'table' then
    return t
  end
  local o = {}
  for k, v in pairs(t) do
    o[k] = copy(v)
  end
  return o
end
local function sorted(t)
  local o = {}
  for k in pairs(t) do
    o[#o + 1] = k
  end
  table.sort(o)
  return o
end
local function item(id)
  local n, d = id:match('^(.*):(%d+)$')
  return { name = n or id, damage = tonumber(d) or 0 }
end
local function terminal(s)
  return s == 'done' or s == 'partial' or s == 'failed'
end
-- The public status of a step. Everything else on a stage is working state.
local stagePublic = {}
for _, k in ipairs({
  'index', 'kind', 'state', 'status', 'detail', 'error', 'done', 'total',
  'tasks', 'taskIndices', 'firstTask', 'inputs', 'outputs', 'after',
  'crafter', 'machineType', 'groups', 'loads', 'fuel', 'locations',
  'assigned', 'started', 'craftStarted', 'craftFinished', 'released', 'finished',
  'jobId', 'submitted', 'admission', 'receipt', 'toolReservations',
  'itemsMoved', 'physicalJobs', 'loadLedger', 'loadsDelivered', 'storeAllocations',
}) do
  stagePublic[k] = true
end
function M.stageSnapshot(s)
  local o = {}
  for k, v in pairs(s) do
    if stagePublic[k] then
      o[k] = copy(v)
    end
  end
  return o
end
local function stop(run, reason)
  run.stopping = true
  run.reason = run.reason or tostring(reason)
  run.error = run.reason
end
local function changed(run, s, state, detail, done)
  run.world.revision = run.world.revision + 1
  if state then
    s.state = state
  end
  if detail then
    s.detail = tostring(detail)
  end
  if done then
    s.done = done
  end
  run.active = {}
  for i, v in ipairs(run.stages) do
    if v.state ~= 'waiting' and v.state ~= 'done' and v.state ~= 'failed' then
      run.active[#run.active + 1] = i
    end
  end
  run.stage = run.active[1]
  run.ports.emit('stage', run.id, s.index, s.state)
  if run.onStage then
    local ok, e = pcall(run.onStage, M.stageSnapshot(s), s.index)
    if not ok then
      run.callbackError = tostring(e)
    end
  end
end
local function action(run, kind, data)
  run.sequence = run.sequence + 1
  local token = tostring(run.id) .. ':' .. run.sequence
  local a = data or {}
  a.kind = kind
  a.token = token
  a.ids = {}
  a.run = run
  run.actions[token] = a
  local _, err = run.ports.dispatch(a, run)
  if err then
    stop(run, err)
  end
  return a
end
-- A job that moved less than asked and left nothing on a drone: a machine refused
-- part of a delivery (the drone returned the rest), or a slot held fewer items
-- than expected. Machine loads and collections count what moved.
local function cleanPartial(job)
  if next(job.held or {}) then
    return false
  end
  if (job.refused or 0) > 0 then
    return true
  end
  for _, s in ipairs(job.steps or {}) do
    if s.short then
      return true
    end
  end
  return false
end
-- Whether job id belongs to a machine load or collection, which may move less.
local function partialOk(run, id)
  for _, a in pairs(run.actions) do
    if a.partialOk or (a.sourceRetry and (run.jobs[id].refused or 0) == 0) then
      for _, j in ipairs(a.ids or {}) do
        if j == id then
          return true
        end
      end
    end
  end
  return false
end
-- update records facts only. All transitions, including failures, happen in advance.
function M.update(run, what, data)
  data = data or {}
  if what == 'tick' then
    run.now = data.now
  elseif what == 'cancel' then
    run.world.revision = run.world.revision + 1
    run.failureFacts[#run.failureFacts + 1] = data.reason or 'Cancelled'
  elseif what == 'job' then
    run.jobs[data.id] = copy(data.receipt)
    local r = data.receipt
    if r and terminal(r.state) and r.state ~= 'done' and not (cleanPartial(r) and partialOk(run, data.id)) then
      run.failureFacts[#run.failureFacts + 1] = r.reason or ('Logistics ' .. r.state)
    end
  elseif what == 'settled' then
    run.settled[data.id] = data.settled ~= false
  elseif what == 'job_missing' then
    run.failureFacts[#run.failureFacts + 1] = data.reason
  elseif what == 'action_submitted' then
    local a = run.actions[data.token]
    if a then
      run.world.revision = run.world.revision + 1
      a.submitted = true
      a.ids = copy(data.ids or {})
      a.error = data.error
      if data.error then
        run.failureFacts[#run.failureFacts + 1] = data.error
      end
    end
  elseif what:sub(1, 6) == 'robot_' then
    if what == 'robot_transport' or (what == 'robot_status' and data.jobId == nil) then
      M.updateWorld(run.world, what, data)
    else
      local f = { what = what, data = copy(data), token = data.token }
      run.robotFacts[#run.robotFacts + 1] = f
      -- Record terminal candidates in the same arrival stream as other errors.
      -- Matching and failure policy belong to advance, not this fact recorder.
      if what == 'robot_terminal' then
        run.failureFacts[#run.failureFacts + 1] = f
      end
    end
  elseif what == 'reconcile' then
    M.updateWorld(run.world, what, data)
  end
end
-- Shared by all runs: robots, buffers and machine groups are scheduled across requests.
function M.world()
  return { robots = {}, buffers = {}, machines = {}, facts = {}, groups = {}, toolReservations = {}, waiting = {}, serves = 0, now = 0, revision = 0 }
end
function M.confirmIdle(world, address)
  local r = world.robots[address]
  if r and r.state == 'busy' and r.run then
    return
  end
  if not r or r.state ~= 'idle' or r.last or r.run or r.step then
    world.revision = world.revision + 1
  end
  world.robots[address] = { state = 'idle' }
  for _, b in pairs(world.buffers) do
    if b.state == 'unknown' and b.owner == address then
      world.revision = world.revision + 1
      b.state = 'idle'
      b.owner = nil
      b.run = nil
      b.step = nil
    end
  end
end
-- Resource reconciliation is state policy too. The plumbing never infers idle,
-- clears quarantine, or decides when a public status request is needed.
function M.updateWorld(world, what, data)
  if what == 'robot_transport' or (what == 'robot_status' and data.jobId == nil) or what == 'reconcile' then
    world.facts[#world.facts + 1] = { what = what, data = copy(data) }
  end
end
function M.advanceWorld(world, dispatch, options)
  local function inspect(address, opts)
    if not world.robots[address] then world.revision = world.revision + 1 end
    local r = world.robots[address] or { state = 'unknown' }
    world.robots[address] = r
    if r.run or r.pending then
      return
    end
    r.pending = true
    dispatch({ kind = 'robot_inspect', token = 'idle:' .. address, address = address, options = opts
      or options })
  end
  for _, f in ipairs(world.facts) do
    local d = f.data
    if f.what == 'reconcile' then
      for address in pairs(d.addresses) do
        inspect(address, d.opts)
      end
    else
      local previous = world.robots[d.address]
      local r = world.robots[d.address] or { state = 'unknown' }
      local before = r.state
      world.robots[d.address] = r
      if f.what == 'robot_status' then
        r.pending = nil
        if not r.run then
          if d.unknown then
            r.state = 'unknown'
          elseif d.busy == false then
            M.confirmIdle(world, d.address)
          elseif d.busy == true then
            r.state = 'busy'
          end
        end
      elseif not r.run then
        if d.state == 'ready' then
          inspect(d.address)
        else
          r.state = 'unknown'
        end
      end
      if not previous or r.state ~= before then world.revision = world.revision + 1 end
    end
  end
  world.facts = {}
end
function M.new(id, plan, cfg, opts, world, ports, now)
  world.revision = world.revision + 1
  local run = {
    id = id,
    item = plan.requestItem,
    qty = plan.requestQuantity,
    status = 'running',
    stages = copy(plan.stages),
    active = {},
    started = now,
    trips = 0,
    plan = plan,
    cfg = cfg,
    opts = opts,
    world = world,
    ports = ports,
    now = now,
    onStage = opts.onStage,
    actions = {},
    jobs = {},
    settled = {},
    robotFacts = {},
    sequence = 0,
    claims = {},
    inflight = {},
    fuelAvailable = {},
    failureFacts = {},
  }
  for i, s in ipairs(run.stages) do
    s.index = i
    s.state = 'waiting'
    s.status = 'waiting'
    s.done = 0
    s.total = 0
    s.detail = 'Waiting for inputs'
    s.itemsMoved = {}
    s.firstTask = s.taskIndices[1]
    for _, v in ipairs(s.outputs) do
      s.total = s.total + v.qty
    end
    if s.fuel then
      run.fuelAvailable[s.fuel.item] = (run.fuelAvailable[s.fuel.item] or 0) + s.fuel.need
      run.claims[s.fuel.item] = (run.claims[s.fuel.item] or 0) + s.fuel.need
    end
  end
  -- Raw inputs taken from stock stay claimed until fetched or the run ends.
  for id, n in pairs(plan.inventory_needed or {}) do
    id = identity.canonical(id)
    run.claims[id] = (run.claims[id] or 0) + n
  end
  return run
end
local function outcome(run, a)
  if not a or not a.submitted then
    return
  end
  if a.accounted then
    return a.results, a.problem
  end
  local all = true
  local receipts = {}
  local problem = a.error
  if problem then
    stop(run, problem)
  end
  for i, id in ipairs(a.ids) do
    local r = run.jobs[id]
    if r and terminal(r.state) and r.state ~= 'done' and not (a.partialOk and cleanPartial(r)) then
      problem = problem or r.reason or ('Logistics ' .. r.state)
      if not (a.sourceRetry and cleanPartial(r) and (r.refused or 0) == 0) then stop(run, problem) end
    end
    if not r or not terminal(r.state) or not run.settled[id] then
      all = false
    else
      receipts[i] = r
    end
  end
  if not all then
    return
  end
  if not a.accounted then
    a.accounted = true
    a.results = receipts
    a.problem = problem
    run.actions[a.token] = nil
    for _, id in ipairs(a.ids) do
      run.jobs[id] = nil
      run.settled[id] = nil
    end
    if a.kind == 'scan' then
      for i in ipairs(a.ids) do
        run.trips = run.trips + (receipts[i].trips or 0)
      end
    end
  end
  return receipts, problem
end
local function beginMany(run, stage, kind, requests, endpoint, wait)
  local bundle = { records = {}, physical = {}, kind = kind, endpoint = endpoint }
  local payload = {}
  for _, r in ipairs(requests) do
    if r.count > 0 then
      local id = type(r.item) == 'table' and identity.stackName(r.item) or identity.canonical(r.item)
      local dest = r.endpoint or endpoint
      local record = {
        kind = kind,
        item = id,
        quantity = r.count,
        moved = 0,
        shortfall = 0,
        status = 'pending',
        jobs = {},
        allocations = {},
        storage = type(dest) == 'table' and dest.storage or dest,
        slots = type(dest) == 'table' and copy(dest.slots) or nil,
      }
      -- The claimed part of a fetch is in flight until its receipt.
      if kind == 'fetch' and run.claims[id] then
        record.claimed = math.max(0, math.min(r.count, run.claims[id] - (run.inflight[id] or 0)))
        run.inflight[id] = (run.inflight[id] or 0) + record.claimed
      end
      stage.itemsMoved[#stage.itemsMoved + 1] = record
      bundle.records[#bundle.records + 1] = record
      r.receipt = record
      payload[#payload + 1] = { item = item(id), count = r.count, to = kind == 'fetch' and dest or nil, waitFor = r.waitFor }
    end
  end
  if #payload == 0 then
    bundle.action = { kind = kind .. 'Many', token = 'empty:' .. run.id, submitted = true, ids = {} }
  else
    bundle.action =
      action(run, kind .. 'Many', { requests = payload, endpoint = endpoint, wait = wait })
  end
  bundle.stage = stage
  bundle.run = run
  return bundle
end
local function finishMany(run, bundle)
  local a = bundle.action
  local stage = bundle.stage
  if a.submitted and not bundle.registered then
    bundle.registered = true
    stage.physicalJobs = stage.physicalJobs or {}
    for _, id in ipairs(a.ids) do
      local p = {
        job = id,
        kind = bundle.kind,
        status = 'pending',
        storage = type(bundle.endpoint) == 'table' and bundle.endpoint.storage or bundle.endpoint,
        slots = type(bundle.endpoint) == 'table' and copy(bundle.endpoint.slots) or nil,
      }
      stage.physicalJobs[#stage.physicalJobs + 1] = p
      bundle.physical[#bundle.physical + 1] = p
    end
  end
  local ledgers, problem = outcome(run, a)
  if not ledgers then
    return
  end
  local errorText = problem
  if bundle.finished then
    return true, bundle.error
  end
  bundle.finished = true
  for i, id in ipairs(a.ids) do
    local ledger = ledgers[i]
    local physical = bundle.physical[i]
    if a.partialOk and cleanPartial(ledger) then
      bundle.partial = true
    end
    physical.status = ledger.state == 'done' and 'complete' or ledger.state
    for _, k in ipairs({
      'reason',
      'moved',
      'taken',
      'returned',
      'held',
      'trips',
      'perItem',
      'queuedAt',
      'dispatchedAt',
      'finishedAt',
      'tripTimings',
    }) do
      physical[k] = copy(ledger[k])
    end
    if type(ledger.perItem) ~= 'table' then
      errorText = errorText or 'Packed job has no per-item receipt'
    end
    for _, row in ipairs(ledger.perItem or {}) do
      local name = identity.stackName(row.item)
      local requested, moved = row.requested or 0, row.moved or 0
      local taken, returned = row.taken, row.returned
      for index, r in ipairs(bundle.records) do
        if
          r.item == name
          and requested > 0
          and (row.requestIndex == nil or row.requestIndex == index)
        then
          local assigned = math.min(requested, r.quantity - (r.accounted or 0))
          if assigned > 0 then
            local delivered = math.min(assigned, moved)
            local link = {
              job = id,
              item = name,
              requested = assigned,
              count = delivered,
              moved = delivered,
              shortfall = assigned - delivered,
              storage = r.storage,
              slots = copy(r.slots),
              status = delivered == assigned and 'complete' or 'partial',
            }
            r.allocations[#r.allocations + 1] = link
            r.jobs[#r.jobs + 1] = id
            r.job = r.job or id
            r.accounted = (r.accounted or 0) + assigned
            r.moved = r.moved + delivered
            r.shortfall = r.shortfall + assigned - delivered
            r.held = copy(row.held or ledger.held)
            if delivered < assigned and ledger.state ~= 'done' then
              r.physicalStatus = ledger.state
            end
            if taken ~= nil then
              local n = math.min(assigned, taken)
              r.taken = (r.taken or 0) + n
              taken = taken - n
            end
            if returned ~= nil then
              local n = math.min(assigned, returned)
              r.returned = (r.returned or 0) + n
              returned = returned - n
            end
            requested = requested - assigned
            moved = moved - delivered
            if delivered < assigned then
              r.reason = r.reason or row.reason or ledger.reason or 'Packed item shortfall'
            end
          end
        end
      end
      if requested > 0 then
        errorText = errorText or 'Unexpected item in packed receipt: ' .. name
      end
    end
  end
  for _, r in ipairs(bundle.records) do
    r.shortfall = math.max(r.shortfall, r.quantity - r.moved)
    r.status = r.shortfall == 0 and 'complete' or r.moved > 0 and 'partial' or 'failed'
    if r.physicalStatus then
      r.status = r.physicalStatus
    end
    if r.shortfall > 0 and not bundle.partial then
      r.reason = r.reason or errorText or 'Packed item shortfall'
      errorText = errorText or r.reason
    end
    r.accounted = nil
  end
  if bundle.kind == 'fetch' then
    for _, r in ipairs(bundle.records) do
      if r.claimed then
        run.inflight[r.item] = run.inflight[r.item] - r.claimed
        r.claimed = nil
      end
      local c = run.claims[r.item]
      if c then
        -- A claim on stock the drone found missing withholds nothing real.
        c = math.min(c - math.min(c, r.moved), r.shortfall > 0 and run.ports.stock(r.item) or c)
        run.claims[r.item] = c > 0 and c or nil
      end
    end
  end
  bundle.error = errorText
  if errorText and not a.sourceRetry then
    stop(run, errorText)
  end
  return true, errorText
end
local function release(run, s)
  local tools = run.world.toolReservations
  for id, n in pairs(s.toolReservations or {}) do
    tools[id] = tools[id] - n
    if tools[id] == 0 then
      tools[id] = nil
    end
  end
  s.toolReservations = nil
  if s.robotLock then
    local state = s.status == 'unknown' and 'unknown' or 'idle'
    local r = run.world.robots[s.robotLock]
    r.state = state
    r.run = nil
    r.step = nil
    r.last = run.id
    local b = run.world.buffers[s.bufferLock]
    b.state = state
    b.run = nil
    b.step = nil
    if state == 'idle' then
      b.owner = nil
    end
    if s.status == 'complete' then
      s.released = run.now
    end
  end
end
local function completeStage(run, s)
  s.status = 'complete'
  s.phase = 'closed'
  s.finished = run.now
  changed(run, s, 'done', 'Complete', s.total)
  release(run, s)
end
local function failStage(run, s, err, unknown)
  if s.phase == 'closed' then
    return
  end
  stop(run, err)
  s.error = tostring(err)
  s.status = unknown and 'unknown' or 'failed'
  if unknown then
    run.uncertain = true
  end
  changed(run, s, 'failed', s.error)
  s.phase = 'closed'
  s.finished = run.now
  release(run, s)
end
local function robotMatches(s, d)
  return s.robotLock == d.address
    and s.robotAction
    and (d.jobId == s.jobId or (d.jobId == nil and d.token == s.robotAction.token))
end
local function robotResult(d)
  local result = copy(d.receipt or {})
  result.notFound = result.status == 'NOT_FOUND' or result.notFound or nil
  result.status = d.status or (d.unknown and 'unknown') or result.status
  result.message = result.message or d.reason
  return result
end
local function robotFacts(run)
  for _, f in ipairs(run.robotFacts) do
    local d = f.data
    for _, s in ipairs(run.stages) do
      if robotMatches(s, d) then
        if f.what == 'robot_progress' then
          local receipt = d.receipt or {}
          local message = receipt.message or receipt.status or ''
          changed(run, s, nil, message)
          local cb = (run.opts.client or {}).onMessage
          if cb then
            local ok, e = pcall(cb, message)
            if not ok then
              run.callbackError = tostring(e)
            end
          end
        elseif f.what == 'robot_admitted' then
          s.admission = copy(d)
          run.world.revision = run.world.revision + 1
        end
      end
    end
  end
  run.robotFacts = {}
end
local function acquireRobot(run, s)
  local crafters = run.ports.crafters()
  local names = s.crafter and { s.crafter } or sorted(crafters)
  local w = run.world
  local tools = w.toolReservations
  -- A run that just released a robot lets another waiting run have it first.
  local function wanted(name)
    for id, want in pairs(w.waiting) do
      if id ~= run.id and (want.any or want[name]) then
        return true
      end
    end
  end
  for _, name in ipairs(names) do
    local c = assert(crafters[name], 'Unknown crafter ' .. tostring(name))
    assert(c.robot and c.buffer, 'Crafter needs a robot and warehouse buffer')
    local r = run.world.robots[c.robot] or { state = 'unknown' }
    run.world.robots[c.robot] = r
    local key = run.ports.bufferIdentity(c.buffer)
    local b = run.world.buffers[key] or { state = 'idle' }
    run.world.buffers[key] = b
    local yield = r.last == run.id and wanted(name)
    if yield then
      run.yielded = true
    end
    if r.state == 'idle' and b.state == 'idle' and not yield then
      local sub, err, withdrawals = run.ports.prepareRobot(run, s, tools)
      if not sub then
        if next(tools) then
          return false
        end
        error(err, 0)
      end
      s.prepared = sub
      s.toolWithdrawals = withdrawals
      s.toolReservations = withdrawals
      for id, n in pairs(withdrawals) do
        tools[id] = (tools[id] or 0) + n
      end
      w.waiting[run.id] = nil
      w.serves = w.serves + 1
      run.served = w.serves
      r.last = nil
      r.state = 'busy'
      r.run = run.id
      r.step = s.index
      b.state = 'busy'
      b.owner = c.robot
      b.run = run.id
      b.step = s.index
      s.crafter = name
      s.robotLock = c.robot
      s.bufferLock = key
      s.buffer = c.buffer
      s.locations = { c.buffer }
      s.assigned = run.now
      s.started = run.now
      s.status = 'running'
      changed(run, s, 'fetching', 'Preparing inputs')
      s.phase = 'robot_fetch'
      return true
    end
  end
  local want = w.waiting[run.id] or {}
  w.waiting[run.id] = want
  want[s.crafter or 'any'] = true
  return false
end
local function robotAdvance(run, s)
  if s.phase == 'robot_fetch' then
    if run.stopping then
      failStage(run, s, run.reason)
      return true
    end
    local needed = copy(s.prepared.inventory_needed)
    for id, n in pairs(s.toolWithdrawals) do
      needed[id] = (needed[id] or 0) + n
    end
    local requests = {}
    for _, id in ipairs(sorted(needed)) do
      local held = 0
      if s.bufferRead then
        for _, v in pairs((run.ports.contents(s.buffer) or {}).items or {}) do
          if identity.stackName(v.item) == identity.canonical(id) then held = held + v.count end
        end
      end
      local n = needed[id] - held
      if n > 0 then requests[#requests + 1] = { item = id, count = n, endpoint = s.buffer } end
    end
    s.bundle = beginMany(run, s, 'fetch', requests, s.buffer)
    s.bundle.action.sourceRetry = true
    s.phase = 'robot_fetching'
    return true
  elseif s.phase == 'robot_fetching' then
    local done, err = finishMany(run, s.bundle)
    if not done then
      return false
    end
    if err or run.stopping then
      if err and not run.stopping then
        local requests, retry = {}, true
        for _, ledger in ipairs(s.bundle.action.results or {}) do
          if ledger.state ~= 'done' and not (cleanPartial(ledger) and (ledger.refused or 0) == 0) then retry = false end
        end
        for _, r in ipairs(s.bundle.records) do
          if r.shortfall > 0 then
            if run.ports.stock(r.item) < r.shortfall then retry = false end
            requests[#requests + 1] = { item = r.item, count = r.shortfall }
          end
        end
        if retry and #requests > 0 then
          s.bundle = beginMany(run, s, 'fetch', requests, s.buffer)
          s.bundle.action.sourceRetry = true
          return true
        end
      end
      failStage(run, s, err or run.reason)
      return true
    end
    s.submitted = true
    s.jobId = 'mes-' .. run.id .. '-' .. s.index .. (s.bufferRead and ('-' .. (run.sequence + 1)) or '')
    s.bufferRead = nil
    s.robotResult, s.robotResultAt = nil, nil
    s.craftStarted = run.now
    changed(run, s, 'crafting', 'Robot crafting')
    s.robotAction = action(run, 'robot_begin', { address = s.robotLock, plan = s.prepared, jobId = s.jobId })
    s.phase = 'robot_crafting'
    return true
  elseif s.phase == 'robot_crafting' then
    local a = s.robotAction
    if a.submitted and a.error and not s.robotResult then
      s.robotResult = { status = 'failed', message = a.error }
    end
    if not s.robotResult then
      return false
    end
    local result = s.robotResult
    if result.notFound then
      s.bufferRead = action(run, 'scan', { storage = s.buffer })
      s.phase = 'robot_reread'
      return true
    end
    s.receipt = copy(result)
    -- The robot read its buffer after crafting: inputs used and tools broken are gone.
    if result.buffer then
      local counts = {}
      for _, id in ipairs(sorted(result.buffer)) do
        counts[#counts + 1] = { item = item(id), count = result.buffer[id] }
      end
      run.ports.observed(s.buffer, counts)
    end
    s.status = result.status
    s.craftFinished = s.robotResultAt or run.now
    if result.status ~= 'complete' then
      -- A robot that failed mid-craft dumps everything into its buffer and reports nothing: read it.
      if result.status == 'failed' and not result.buffer and not a.error and not s.bufferRead then
        stop(run, result.message or 'Robot did not complete')
        s.bufferRead = action(run, 'scan', { storage = s.buffer })
        return true
      end
      if s.bufferRead and not outcome(run, s.bufferRead) then
        return false
      end
      failStage(run, s, result.message or 'Robot did not complete', result.status == 'unknown')
      return true
    end
    -- The robot read its buffer after crafting; take exactly what it reported.
    changed(run, s, 'storing', 'Storing robot output')
    local requests = {}
    for _, id in ipairs(sorted(result.buffer or {})) do
      if result.buffer[id] > 0 then
        requests[#requests + 1] = { item = id, count = result.buffer[id] }
      end
    end
    if #requests == 0 then
      completeStage(run, s)
    else
      s.bundle = beginMany(run, s, 'collect', requests, s.buffer)
      s.phase = 'robot_storing'
    end
    return true
  elseif s.phase == 'robot_reread' then
    if not outcome(run, s.bufferRead) then return false end
    s.phase = 'robot_fetch'
    return true
  elseif s.phase == 'robot_storing' then
    local done, err = finishMany(run, s.bundle)
    if not done then
      return false
    end
    if err then
      failStage(run, s, err)
    else
      completeStage(run, s)
    end
    return true
  end
  return false
end
local function publish(w, g)
  local resource = w.machines[g.name]
  resource.loads = {}
  for _, load in ipairs(g.loads) do
    resource.loads[#resource.loads + 1] = copy(load.record)
  end
  for _, load in ipairs(g.quarantined) do
    resource.loads[#resource.loads + 1] = copy(load.record)
  end
  if resource.state ~= 'unknown' then
    resource.state = #g.loads > 0 and 'busy' or 'idle'
  end
end
local function bad(w, g, r, err, unknown)
  r.error = g.name .. ': ' .. tostring(err)
  r.left = 0
  stop(r.run, r.error)
  if unknown then
    w.machines[g.name].state = 'unknown'
  end
end
local function quarantine(w, g, load, state)
  if not load.quarantined then
    load.quarantined = true
    load.unresolved = copy(load.remaining)
    g.quarantined[#g.quarantined + 1] = load
  end
  load.record.state = state or 'unknown'
  w.machines[g.name].state = 'unknown'
  -- The records no longer match the machine: it is read and recovered before more work.
  if not g.recovery then
    g.recovery = { request = load.request, phase = 'read' }
    load.request.active = load.request.active + 1
  end
end
local function hasWork(r)
  for _, v in ipairs(r.work.requests) do
    if v.left > 0 then
      return true
    end
  end
  return false
end
local function donorFor(r)
  if r.left > 0 then
    return r
  end
  for _, v in ipairs(r.work.requests) do
    if v.left > 0 and v.blocked and not v.admitting then
      return v
    end
  end
end
function M.machineRequests(run, s)
  local mt = assert(run.cfg.machineTypes[s.machineType], 'Unknown machine type')
  local available = run.ports.groups(s.machineType)
  local free = s.groups
  s.locations = {}
  local t = run.plan.tasks[s.firstTask]
  local quantities = t.input_quantities
    or (run.plan.blueprint and run.plan.blueprint.nodes[t.node] and run.plan.blueprint.nodes[t.node].input_quantities)
    or {}
  local perOp = 0
  local ingredients, outputs, signature = {}, {}, {}
  local operations = t.qty_produced / t.recipeOutput
  for _, v in ipairs(s.outputs) do
    outputs[v.item] = v.qty / operations
    signature[#signature + 1] = 'out:' .. v.item .. '=' .. outputs[v.item]
  end
  local slots = sorted(t.recipe)
  for _, slot in ipairs(slots) do
    if t.recipe[slot] ~= 'minecraft:air' then
      local id = identity.canonical(t.recipe[slot])
      local q = quantities[slot] or 1
      assert(q > 0 and q % 1 == 0, 'Machine ingredient quantities must be positive integers')
      ingredients[id] = (ingredients[id] or 0) + q
      perOp = perOp + q
    end
  end
  assert(perOp > 0 and perOp <= mt.batch, 'Recipe inputs exceed machine load batch')
  for _, id in ipairs(sorted(ingredients)) do
    signature[#signature + 1] = id .. '=' .. ingredients[id]
  end
  local order = 0
  for _, slot in ipairs(slots) do
    if t.recipe[slot] ~= 'minecraft:air' then
      order = order + 1
      signature[#signature + 1] = 'role:'
        .. mt.inputs[math.min(order, #mt.inputs)]
        .. ':'
        .. identity.canonical(t.recipe[slot])
        .. '='
        .. (quantities[slot] or 1)
    end
  end
  local work = { requests = {} }
  s.machineWork = work
  for i, name in ipairs(free) do
    local roles = available[name].roles
    local occupied = {}
    for role, storage in pairs(roles) do
      s.locations[#s.locations + 1] = storage
      for _, slot in ipairs(mt.roleSlots[role] or {}) do
        occupied[storage] = occupied[storage] or {}
        assert(not occupied[storage][slot], 'Overlapping machine role slots')
        occupied[storage][slot] = true
      end
    end
    assert(roles[mt.output], 'Missing output role')
    local r = {
      group = name,
      run = run,
      stage = s,
      left = math.floor(operations / #free) + (i <= operations % #free and 1 or 0),
      capacity = math.floor(mt.batch / perOp),
      perOp = perOp,
      outputs = outputs,
      recipe = table.concat(signature, ';'),
      inputs = {},
      deadline = run.now + MACHINE_GRACE,
      work = work,
      active = 0,
    }
    local order = 0
    for _, slot in ipairs(slots) do
      if t.recipe[slot] ~= 'minecraft:air' then
        order = order + 1
        local role = mt.inputs[math.min(order, #mt.inputs)]
        local storage = assert(roles[role], 'Missing input role ' .. role)
        local id = identity.canonical(t.recipe[slot])
        r.inputs[role] = r.inputs[role]
          or { storage = storage, slots = assert(mt.roleSlots[role], 'Missing role slots'), items = {} }
        r.inputs[role].items[id] = (r.inputs[role].items[id] or 0) + (quantities[slot] or 1)
      end
    end
    work.requests[#work.requests + 1] = r
  end
  return work
end
local function startMachine(run, s)
  local mt = assert(run.cfg.machineTypes[s.machineType], 'Unknown machine type')
  local available = run.ports.groups(s.machineType)
  assert(
    type(mt.seconds) == 'number' and mt.seconds >= 0 and mt.seconds < math.huge,
    'Invalid batch/deadline configuration'
  )
  local names = s.groups == 'any' and sorted(available)
    or type(s.groups) == 'string' and { s.groups }
    or s.groups
  assert(type(names) == 'table' and #names > 0, 'No machine groups')
  local free, seen = {}, {}
  for _, name in ipairs(names) do
    assert(available[name] and not seen[name], 'Unknown or duplicate machine group ' .. tostring(name))
    seen[name] = true
    run.world.machines[name] = run.world.machines[name] or { state = 'idle', type = s.machineType, loads = {} }
    free[#free + 1] = name
  end
  s.groups = free
  s.phase = 'machine'
  s.status = 'running'
  s.started = run.now
  local work = M.machineRequests(run, s)
  for i, name in ipairs(free) do
    local roles, r = available[name].roles, work.requests[i]
    local g = run.world.groups[name]
    if not g then
      g = {
        name = name,
        mt = mt,
        roles = roles,
        runs = {},
        opts = run.opts,
        pending = {},
        loads = {},
        quarantined = {},
        phase = 'idle',
        inputDue = 0,
        outputDue = math.huge,
        inputBackoff = BACKOFF,
        outputBackoff = BACKOFF,
      }
      -- Fuel the MES has put in this machine and the inputs it has burned through
      -- outlive any one request.
      local resource = run.world.machines[name]
      resource.fuel = resource.fuel or { credit = 0, admitted = 0 }
      g.fuel = resource.fuel
      -- So do loads whose output is still unaccounted for.
      run.world.stuck = run.world.stuck or {}
      run.world.stuck[name] = run.world.stuck[name] or {}
      g.quarantined = run.world.stuck[name]
      run.world.groups[name] = g
    end
    -- An unknown machine is read first; one holding inputs or output no load
    -- accounts for (left over, or there when it was added) is emptied first.
    if not g.recovery then
      local phase = run.world.machines[name].state == 'unknown' and 'read'
      if not phase and #g.loads == 0 then
        for role, storage in pairs(roles) do
          if not (mt.fuel and role == mt.fuel.role) then
            for _, v in pairs((run.ports.contents(storage) or {}).items or {}) do
              if v.count > 0 then
                phase = 'empty'
              end
            end
          end
        end
      end
      if phase then
        g.recovery = { request = r, phase = phase }
        r.active = r.active + 1
      end
    end
    g.runs[run.id] = true
    g.pending[#g.pending + 1] = r
  end
  changed(run, s, 'processing', 'Machine processing')
  return true
end
local function additional(g, r, n)
  local f = g.mt.fuel
  return f and math.max(0, math.ceil((g.fuel.admitted + n * r.perOp) / f.per) - g.fuel.credit)
    or 0
end
local function blocked(w, g)
  g.inputDue = w.now + g.inputBackoff
  g.inputBackoff = math.min(g.inputBackoff * 2, MAX_BACKOFF)
  g.phase = 'idle'
end
local function admit(w, g)
  local mt = g.mt
  -- The machine holds only what our own loads put in; once they are all
  -- collected it is empty.
  local empty = #g.loads == 0
  if empty then
    g.inputRecipe = nil
  end
  for position, r in ipairs(g.pending) do
    local donor = donorFor(r)
    local same = g.inputRecipe == r.recipe
    local ops = donor and math.min(donor.left, r.capacity) or 0
    -- After a refusal, or a blocking machine found holding other work, the
    -- machine takes nothing new until its next collection.
    if donor and not g.awaitCollection and (mt.blocking == false or empty or same) then
      -- Load only what the stock this run may take covers; with none, the request cannot finish.
      local missing
      for _, input in pairs(r.inputs) do
        for id, n in pairs(input.items) do
          ops = math.min(ops, math.floor(r.run.ports.stock(id) / n))
          missing = missing or (ops == 0 and id)
        end
      end
      if mt.fuel then
        local fuel = r.run.ports.stock(mt.fuel.item)
        while ops > 0 and additional(g, r, ops) > math.min(fuel, r.run.fuelAvailable[mt.fuel.item] or 0) do
          ops = math.floor(ops / 2)
        end
        missing = missing or (ops == 0 and additional(g, r, 1) > fuel and mt.fuel.item)
      end
      if missing and not r.run.stopping then
        bad(w, g, r, 'Not enough ' .. missing .. ' in stock')
      end
      if ops > 0 and not r.run.stopping then
        donor.left = donor.left - ops
        r.blocked = false
        r.admitting = true
        local fuelAdditional = additional(g, r, ops)
        if mt.fuel then
          r.run.fuelAvailable[mt.fuel.item] = r.run.fuelAvailable[mt.fuel.item] - fuelAdditional
        end
        local record = {
          run = r.run.id,
          step = r.stage.index,
          group = g.name,
          recipe = r.recipe,
          state = 'fetching',
          inputs = {},
          outputs = {},
          collectedItems = {},
          items = ops * r.perOp,
        }
        for id, n in pairs(r.outputs) do
          record.outputs[id] = ops * n
        end
        local load = {
          request = r,
          record = record,
          remaining = copy(record.outputs),
          ops = ops,
          donor = donor,
          fuelAdditional = fuelAdditional,
          position = position,
          fetches = {},
        }
        g.sequence = (g.sequence or 0) + 1
        load.sequence = g.sequence
        r.active = r.active + 1
        g.loads[#g.loads + 1] = load
        r.stage.loadLedger = r.stage.loadLedger or {}
        r.stage.loadLedger[#r.stage.loadLedger + 1] = record
        if mt.fuel then
          load.fetches[#load.fetches + 1] = {
            item = mt.fuel.item,
            count = fuelAdditional,
            endpoint = { storage = g.roles[mt.fuel.role], slots = mt.roleSlots[mt.fuel.role] },
            fuel = true,
          }
        end
        for _, role in ipairs(sorted(r.inputs)) do
          local input = r.inputs[role]
          for _, id in ipairs(sorted(input.items)) do
            load.fetches[#load.fetches + 1] = {
              item = id,
              count = ops * input.items[id],
              endpoint = { storage = input.storage, slots = input.slots },
              role = role,
            }
          end
        end
        load.bundle = beginMany(r.run, r.stage, 'fetch', load.fetches, load.fetches[1].endpoint)
        load.bundle.action.partialOk = true
        g.loading = load
        g.phase = 'loading'
        publish(w, g)
        return true
      end
    end
    -- Loads already in the machine, from any run, must clear first.
    if donor then
      r.blocked = true
      for _, l in ipairs(g.loads) do
        r.deadline = math.max(r.deadline, l.deadline or w.now + MACHINE_GRACE)
      end
      if w.now >= r.deadline then
        bad(w, g, r, 'Machine input deadline exceeded', false)
      end
    end
  end
  -- A blocking machine that could take nothing waits for its next collection.
  if mt.blocking ~= false and next(g.pending) and #g.loads > 0 then
    g.awaitCollection = true
  end
  blocked(w, g)
  return true
end
local function tripSeconds(g, bundle)
  local longest
  for _, p in ipairs(bundle.physical) do
    for _, t in ipairs(p.tripTimings or {}) do
      if t.startedAt and t.finishedAt then longest = math.max(longest or 0, t.finishedAt - t.startedAt) end
    end
  end
  g.tripSeconds = longest
end
local function finishLoad(w, g)
  local load = g.loading
  local done, err = finishMany(load.bundle.run, load.bundle)
  if not done then
    return false
  end
  local r = load.request
  tripSeconds(g, load.bundle)
  local mt = g.mt
  local record = load.record
  for _, fetch in ipairs(load.fetches) do
    if not fetch.fuel and fetch.receipt then
      record.inputs[#record.inputs + 1] = {
        item = fetch.item,
        count = fetch.receipt.moved or 0,
        wanted = fetch.count,
        storage = fetch.endpoint.storage,
        role = fetch.role,
        slots = copy(fetch.endpoint.slots),
        job = fetch.receipt.job,
        status = fetch.receipt.status,
      }
    end
  end
  r.admitting = false
  -- The machine may refuse part of a delivery: the load is what went in, and
  -- the rest goes back to the request to retry after the next collection.
  local ops, fuelMoved = load.ops, 0
  for _, fetch in ipairs(load.fetches) do
    local moved = fetch.receipt and fetch.receipt.moved or 0
    if fetch.fuel then
      fuelMoved = moved
    else
      ops = math.min(ops, math.floor(moved / r.inputs[fetch.role].items[fetch.item]))
    end
  end
  if err then
    bad(w, g, r, err, true)
    quarantine(w, g, load, 'failed')
    r.active = r.active - 1
    table.remove(g.loads, #g.loads)
  elseif ops == 0 then
    if mt.fuel then
      g.fuel.credit = g.fuel.credit + fuelMoved
      r.run.fuelAvailable[mt.fuel.item] = r.run.fuelAvailable[mt.fuel.item] + load.fuelAdditional - fuelMoved
    end
    load.donor.left = load.donor.left + load.ops
    g.awaitCollection = true
    r.blocked = true
    r.active = r.active - 1
    table.remove(g.loads, #g.loads)
    for i, v in ipairs(r.stage.loadLedger) do
      if v == record then
        table.remove(r.stage.loadLedger, i)
        break
      end
    end
    changed(r.run, r.stage, nil, 'Machine ' .. g.name .. ' refused the load; retrying after collection')
  else
    if mt.fuel then
      g.fuel.credit = g.fuel.credit + fuelMoved
      r.run.fuelAvailable[mt.fuel.item] = r.run.fuelAvailable[mt.fuel.item] + load.fuelAdditional - fuelMoved
    end
    if ops < load.ops then
      load.donor.left = load.donor.left + load.ops - ops
      g.awaitCollection = true
      load.ops = ops
      record.items = ops * r.perOp
      for id, n in pairs(r.outputs) do
        record.outputs[id] = ops * n
      end
      load.remaining = copy(record.outputs)
    end
    local duration = load.ops * r.perOp * mt.seconds
    load.duration = duration
    load.due = math.max(w.now, g.lastExpectedDue or w.now) + duration
    g.lastExpectedDue = load.due
    load.deadline = load.due + duration + MACHINE_GRACE
    record.state = 'processing'
    record.started = w.now
    record.delivered = w.now
    g.fuel.admitted = g.fuel.admitted + record.items
    g.outputDue = math.min(g.outputDue, load.due)
    g.inputRecipe = r.recipe
    r.deadline = load.deadline
    r.stage.loadsDelivered = (r.stage.loadsDelivered or 0) + 1
    changed(r.run, r.stage, nil, 'Load ' .. r.stage.loadsDelivered .. ' delivered')
    for i, candidate in ipairs(g.pending) do
      if candidate == r then
        table.remove(g.pending, i)
        break
      end
    end
    if hasWork(r) and not r.run.stopping then
      g.pending[#g.pending + 1] = r
    end
  end
  g.loading = nil
  g.phase = 'idle'
  g.inputDue = w.now
  g.inputBackoff = BACKOFF
  publish(w, g)
  return true
end
local function reap(w, g, collected)
  g.outputDue = math.huge
  for i = #g.loads, 1, -1 do
    local load = g.loads[i]
    local n = 0
    for _, q in pairs(load.remaining) do
      n = n + q
    end
    if n == 0 or w.now >= load.deadline then
      if n > 0 then
        bad(w, g, load.request, 'Machine output deadline exceeded', true)
        quarantine(w, g, load)
      elseif load.record.state ~= 'failed' then
        load.record.state = 'done'
        load.record.collected = w.now
      end
      load.record.finished = w.now
      load.request.active = load.request.active - 1
      table.remove(g.loads, i)
    else
      if w.now >= load.due then
        -- Short: come back when the missing output should be done. The backoff
        -- only matters for a machine that has stopped making progress.
        local ops = 0
        for id, q in pairs(load.remaining) do
          ops = math.max(ops, math.ceil(q / load.request.outputs[id]))
        end
        load.due = w.now + math.max(ops * load.request.perOp * g.mt.seconds, g.outputBackoff)
      end
    end
  end
  -- The machine works through its loads in order: a late load delays the ones after it.
  local previous
  for _, load in ipairs(g.loads) do
    if previous and load.due < previous.due + load.duration then
      load.due = previous.due + load.duration
      load.deadline = math.max(load.deadline, load.due + load.duration + MACHINE_GRACE)
    end
    g.outputDue = math.min(g.outputDue, load.due)
    g.lastExpectedDue = math.max(g.lastExpectedDue or load.due, load.due)
    previous = load
  end
  if collected then
    g.awaitCollection = nil
  end
  g.outputBackoff = collected and BACKOFF or math.min(g.outputBackoff * 2, MAX_BACKOFF)
  g.phase = 'idle'
  publish(w, g)
end
-- Take what our loads should have produced by now, without looking first. The
-- receipt says how much was there; anything not ready is taken next time.
local function collect(w, g)
  local requests, byItem, first = {}, {}, nil
  for _, load in ipairs(g.loads) do
    -- The trip is made for the due loads; output of later loads that is already
    -- finished comes along at no cost. Items are credited oldest load first.
    for _, id in ipairs(sorted(load.remaining)) do
      local n = load.remaining[id]
      if n > 0 then
        if not byItem[id] then
          byItem[id] = {}
          requests[#requests + 1] = { item = id, count = 0 }
        end
        local allocations = byItem[id]
        allocations[#allocations + 1] = { load = load, count = n }
        first = first or load.request
        for _, q in ipairs(requests) do
          if q.item == id then
            q.count = q.count + n
            if g.tripSeconds and w.now >= load.due then q.waitFor = (q.waitFor or 0) + n end
          end
        end
      end
    end
  end
  if #requests == 0 then
    reap(w, g, false)
    return
  end
  g.collection = {
    requests = requests,
    byItem = byItem,
    bundle = beginMany(
      first.run,
      first.stage,
      'collect',
      requests,
      { storage = g.roles[g.mt.output], slots = g.mt.roleSlots[g.mt.output] },
      g.tripSeconds and { timeout = g.tripSeconds } or nil
    ),
  }
  g.collection.bundle.action.partialOk = true
  g.phase = 'storing'
end
-- Collected output means the machine used up its inputs, and the fuel burned for them.
local function consume(g, load)
  local r = load.request
  local ops = load.ops
  for id, n in pairs(r.outputs) do
    ops = math.min(ops, math.floor((load.record.collectedItems[id] or 0) / n))
  end
  local delta = ops - (load.consumed or 0)
  if delta <= 0 then
    return
  end
  load.consumed = ops
  local consumed = r.run.ports.consumed
  for _, fetch in ipairs(load.fetches) do
    if not fetch.fuel then
      consumed(fetch.endpoint.storage, item(fetch.item), delta * r.inputs[fetch.role].items[fetch.item])
    end
  end
  local f = g.mt.fuel
  if f then
    local before = g.fuel.processed or 0
    g.fuel.processed = before + delta * r.perOp
    consumed(g.roles[f.role], item(f.item), math.ceil(g.fuel.processed / f.per) - math.ceil(before / f.per))
  end
end
local function finishCollection(w, g)
  local c = g.collection
  local done, err = finishMany(c.bundle.run, c.bundle)
  if not done then
    return false
  end
  local any = false
  tripSeconds(g, c.bundle)
  for i, request in ipairs(c.requests) do
    local id = request.item
    local movement = c.bundle.records[i]
    local partIndex, offset = 1, 0
    for _, allocation in ipairs(c.byItem[id]) do
      local load = allocation.load
      local r = load.request
      load.record.storeJobs = load.record.storeJobs or {}
      r.stage.storeAllocations = r.stage.storeAllocations or {}
      local left, got = allocation.count, 0
      while left > 0 do
        local part = movement.allocations[partIndex]
        local quota = part and part.requested or left
        local assigned = math.min(left, quota - offset)
        if assigned > 0 then
          local moved = part and math.min(assigned, math.max(0, (part.moved or 0) - offset)) or 0
          local link = {
            job = part and part.job,
            item = id,
            requested = assigned,
            count = moved,
            moved = moved,
            shortfall = assigned - moved,
            storage = movement.storage,
            slots = copy(movement.slots),
            status = moved == assigned and 'complete' or (part and 'partial' or 'not_submitted'),
          }
          -- A collection that found nothing ready yet is not part of the load's record.
          if moved > 0 or err then
            load.record.storeJobs[#load.record.storeJobs + 1] = link
            r.stage.storeAllocations[#r.stage.storeAllocations + 1] = copy(link)
          end
          got = got + moved
          left = left - assigned
          offset = offset + assigned
        end
        if not part or offset >= quota then
          partIndex = partIndex + 1
          offset = 0
        end
      end
      if err then
        bad(w, g, r, err, true)
        quarantine(w, g, load, 'failed')
        load.remaining = {}
      elseif got > 0 then
        -- What was not there yet stays expected and is taken next time.
        any = true
        load.remaining[id] = load.remaining[id] - got
        load.record.collectedItems[id] = (load.record.collectedItems[id] or 0) + got
        consume(g, load)
        r.stage.done = r.stage.done + got
        load.record.state = 'processing'
        changed(r.run, r.stage, 'processing', 'Machine processing', r.stage.done)
      end
    end
  end
  g.collection = nil
  reap(w, g, any)
  return true
end
-- Recovery: read the machine if its contents are unknown, take its inputs and
-- output back to stock, and set its fuel ledger from the fuel it holds.
-- What came out of the machine explains its stuck loads: inputs taken back
-- are operations never run, output collected is work finished.
local function settle(g, back, out)
  local missing = {}
  for _, load in ipairs(g.quarantined) do
    local r, u = load.request, load.unresolved
    local ops = 0
    for id, n in pairs(u) do
      ops = math.max(ops, math.ceil(n / r.outputs[id]))
    end
    for _, input in pairs(r.inputs) do
      for id, n in pairs(input.items) do
        ops = math.min(ops, math.floor((back[id] or 0) / n))
      end
    end
    for _, input in pairs(r.inputs) do
      for id, n in pairs(input.items) do
        back[id] = (back[id] or 0) - ops * n
      end
    end
    for id, n in pairs(u) do
      local m = math.max(0, n - ops * r.outputs[id])
      local got = math.min(m, out[id] or 0)
      out[id] = (out[id] or 0) - got
      u[id] = m - got
      if u[id] > 0 then
        missing[#missing + 1] = (math.tointeger(u[id]) or u[id]) .. ' ' .. id
      end
    end
  end
  return #missing > 0 and table.concat(missing, ', ') or nil
end
local function recovered(w, g, problem)
  local rc = g.recovery
  g.recovery = nil
  rc.request.active = rc.request.active - 1
  local resource = w.machines[g.name]
  if problem then
    -- Work may still be inside: the machine stays out of service and is read
    -- again when a run next wants it.
    for _, r in ipairs(g.pending) do
      if r.left > 0 then
        bad(w, g, r, problem)
      end
    end
  else
    for i = #g.quarantined, 1, -1 do
      g.quarantined[i] = nil
    end
    resource.state = 'idle'
    local f = g.mt.fuel
    if f then
      local held = 0
      for _, v in pairs((rc.request.run.ports.contents(g.roles[f.role]) or {}).items or {}) do
        if identity.stackName(v.item) == identity.canonical(f.item) then
          held = held + v.count
        end
      end
      g.fuel.credit, g.fuel.admitted, g.fuel.processed = held, 0, 0
    end
  end
  publish(w, g)
  return true
end
local function recover(w, g)
  local rc = g.recovery
  local run, stage = rc.request.run, rc.request.stage
  if rc.phase == 'read' then
    local faces = {}
    for _, storage in pairs(g.roles) do
      faces[#faces + 1] = storage
    end
    table.sort(faces)
    rc.read = action(run, 'scan', { storage = faces })
    rc.phase = 'reading'
    return true
  elseif rc.phase == 'reading' then
    local done, err = outcome(run, rc.read)
    if not done then
      return false
    end
    if err then
      return recovered(w, g, 'Machine could not be read: ' .. tostring(err))
    end
    rc.phase = 'empty'
    return true
  elseif rc.phase == 'empty' then
    rc.bundles = {}
    for _, role in ipairs(sorted(g.roles)) do
      if not (g.mt.fuel and role == g.mt.fuel.role) then
        local storage, requests = g.roles[role], {}
        for _, v in pairs((run.ports.contents(storage) or {}).items or {}) do
          if v.count > 0 then
            requests[#requests + 1] = { item = identity.stackName(v.item), count = v.count }
          end
        end
        if #requests > 0 then
          local bundle = beginMany(run, stage, 'collect', requests, { storage = storage, slots = g.mt.roleSlots[role] })
          bundle.action.partialOk = true
          bundle.role = role
          rc.bundles[#rc.bundles + 1] = bundle
        end
      end
    end
    rc.phase = 'emptying'
    return true
  elseif rc.phase == 'emptying' then
    local back, out, problem = {}, {}, nil
    for _, bundle in ipairs(rc.bundles) do
      local done, err = finishMany(run, bundle)
      if not done then
        return false
      end
      problem = problem or err and 'Machine could not be emptied: ' .. tostring(err)
      local pool = bundle.role == g.mt.output and out or back
      for _, record in ipairs(bundle.records) do
        pool[record.item] = (pool[record.item] or 0) + record.moved
      end
    end
    problem = problem or settle(g, back, out)
    return recovered(w, g, problem and 'May still hold work: ' .. problem)
  end
  return false
end
local function groupAdvance(w, g)
  local mt = g.mt
  for i = #g.pending, 1, -1 do
    local r = g.pending[i]
    if r.run.stopping then
      r.left = 0
      table.remove(g.pending, i)
    end
  end
  for i = #g.pending, 1, -1 do
    if not hasWork(g.pending[i]) and not g.pending[i].admitting then
      table.remove(g.pending, i)
    end
  end
  if g.phase == 'idle' then
    -- Output is collected when our loads should be done.
    if #g.loads > 0 and w.now >= g.outputDue then
      collect(w, g)
      return true
    end
    if g.recovery then
      return #g.loads == 0 and recover(w, g)
    end
    local ready = false
    for _, r in ipairs(g.pending) do
      if donorFor(r) then
        ready = true
      end
    end
    if not ready or w.now < g.inputDue then
      return false
    end
    g.phase = 'admit'
    return true
  elseif g.phase == 'admit' then
    if not next(g.pending) then
      g.phase = 'idle'
      return true
    end
    return admit(w, g)
  elseif g.phase == 'loading' then
    return finishLoad(w, g)
  elseif g.phase == 'storing' then
    return finishCollection(w, g)
  end
  return false
end
local function finishRun(run)
  local locations, counted = {}, {}
  for _, s in ipairs(run.stages) do
    for _, storage in ipairs(s.locations or {}) do
      locations[storage] = true
    end
    for _, p in ipairs(s.physicalJobs or {}) do
      if not counted[p.job] then
        counted[p.job] = true
        run.trips = run.trips + (p.trips or 0)
      end
    end
  end
  if run.stopping then
    run.where = {}
    for _, storage in ipairs(sorted(locations)) do
      for _, v in pairs((run.ports.contents(storage) or {}).items or {}) do
        if v.count > 0 then
          run.where[#run.where + 1] =
            { item = identity.stackName(v.item), count = v.count, storage = storage }
        end
      end
    end
    run.status = run.uncertain and 'unknown' or 'failed'
  else
    run.status = 'complete'
    run.where = nil
  end
  run.finished = run.now
  run.active = {}
  run.stage = nil
  run.onStage = nil
  run.stopping = nil
  run.uncertain = nil
  run.ports.emit('done', run.id, run.status)
  -- Retain public ledgers, not planner blueprints and transient action graphs.
  for _, s in ipairs(run.stages) do
    for key in pairs(s) do
      if not stagePublic[key] then
        s[key] = nil
      end
    end
  end
  -- A machine group outlives a run only while another run still uses it.
  local w = run.world
  w.waiting[run.id] = nil
  for name, g in pairs(w.groups) do
    g.runs[run.id] = nil
    if not next(g.runs) then
      w.groups[name] = nil
    end
  end
  run.plan = nil
  run.cfg = nil
  run.opts = nil
  run.actions = {}
  run.jobs = {}
  run.settled = {}
  run.robotFacts = {}
  run.claims = {}
  run.inflight = {}
  run.fuelAvailable = {}
  run.ports = nil
  run.world = nil
end
function M.advance(run)
  if run.status ~= 'running' then
    return
  end
  assert(not run.advancing, 'MES advance reentry')
  run.advancing = true
  run.yielded = nil
  local w = run.world
  w.now = math.max(w.now, run.now or 0)
  local ok, err = pcall(function()
    -- Every known failure is applied in arrival order before *any* dispatch,
    -- even when its robot has a later stage index than a newly ready sibling.
    for _, f in ipairs(run.failureFacts) do
      if type(f) == 'table' then
        for _, s in ipairs(run.stages) do
          if s.phase == 'robot_crafting' and not s.robotResult and robotMatches(s, f.data) then
            local result = robotResult(f.data)
            s.robotResult = result
            s.robotResultAt = f.data.at or run.now
            w.revision = w.revision + 1
            if result.status ~= 'complete' and not result.notFound then
              stop(run, result.message or 'Robot did not complete')
            end
          end
        end
      else
        stop(run, f)
        w.revision = w.revision + 1
      end
    end
    run.failureFacts = {}
    M.advanceWorld(run.world, run.ports.dispatch, run.opts.client)
    robotFacts(run)
    local progressed = true
    while progressed do
      progressed = false
      -- Observe all outstanding failures before any new dispatch (STOP race).
      for _, a in pairs(run.actions) do
        if a.kind ~= 'robot_begin' then
          outcome(run, a)
        end
      end
      if not run.stopping then
        for _, s in ipairs(run.stages) do
          if s.state == 'waiting' then
            local ready = true
            for _, parent in ipairs(s.after) do
              if run.stages[parent].state ~= 'done' then
                ready = false
              end
            end
            if ready then
              local good, result = pcall(s.kind == 'robot' and acquireRobot or startMachine, run, s)
              if not good then
                failStage(run, s, result)
                progressed = true
              elseif result then
                progressed = true
              end
            end
          end
        end
      end
      for _, s in ipairs(run.stages) do
        if s.kind == 'robot' and s.phase and s.phase ~= 'closed' then
          local good, result = pcall(robotAdvance, run, s)
          if not good then
            failStage(run, s, result)
            progressed = true
          elseif result then
            progressed = true
          end
        end
      end
      for _, name in ipairs(sorted(w.groups)) do
        local g = w.groups[name]
        local good, result = pcall(groupAdvance, w, g)
        if not good then
          -- Unanticipated adapter/validation failure retains unresolved ownership.
          for _, r in ipairs(g.pending) do
            bad(w, g, r, result, true)
          end
          g.pending = {}
          for _, load in ipairs(g.loads) do
            bad(w, g, load.request, result, true)
            quarantine(w, g, load)
            load.request.active = load.request.active - 1
          end
          g.loads = {}
          g.phase = 'idle'
          publish(w, g)
          progressed = true
        elseif result then
          progressed = true
        end
      end
      for _, s in ipairs(run.stages) do
        if s.phase == 'machine' then
          local pending = false
          local problem
          for _, r in ipairs(s.machineWork.requests) do
            if r.left > 0 or r.active > 0 then
              pending = true
            end
            problem = problem or r.error
          end
          if not pending then
            if problem then
              failStage(run, s, problem)
            elseif run.stopping and s.done < s.total then
              failStage(run, s, run.reason or 'Stopped after sibling failure')
            else
              completeStage(run, s)
            end
            progressed = true
          end
        end
      end
      if progressed then w.revision = w.revision + 1 end
    end
    local active = false
    local waiting = false
    local initialPending = false
    for _, s in ipairs(run.stages) do
      if s.phase and s.phase ~= 'closed' then
        active = true
      end
      if s.state == 'waiting' then
        waiting = true
      end
    end
    -- Resources held by other runs will be released; wait for them.
    local held = run.yielded
    for _, r in pairs(w.robots) do
      if r.pending then
        initialPending = true
      end
      if r.run then
        held = true
      end
    end
    for _, g in pairs(w.groups) do
      if #g.pending > 0 or #g.loads > 0 then
        held = true
      end
    end
    for _, a in pairs(run.actions) do
      if a.kind ~= 'robot_begin' and not outcome(run, a) then
        active = true
      end
    end
    if not active then
      if waiting and not run.stopping and not initialPending and not held then
        stop(run, 'No idle resources for ready steps')
      end
      if not waiting or run.stopping then
        w.revision = w.revision + 1
        finishRun(run)
      end
    end
  end)
  run.advancing = nil
  if not ok then
    stop(run, err)
    error(err, 0)
  end
end
M.copy = copy
return M
