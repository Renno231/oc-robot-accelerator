-- Public facade: planning uses plain coroutines, execution is service-owned.
local M = {}
local identity = require('item_identity')
local service = require('mes_service')
local copy = require('mes_state').copy
local function sorted(t)
  local o = {}
  for k in pairs(t) do
    o[#o + 1] = k
  end
  table.sort(o)
  return o
end
local function positive(n)
  return type(n) == 'number' and n > 0 and n < math.huge and n % 1 == 0
end
local function concrete(id)
  return type(id) == 'string'
    and id:match('^[^:]+:[^:]+:?[0-9]*$')
    and id ~= 'minecraft:air'
    and not id:find('*', 1, true)
    and not id:find(' | ', 1, true)
    and id:sub(1, 4) ~= 'ore:'
end
local function config(opts)
  if opts and opts.config then
    return opts.config
  end
  return require('mes_config').config(opts)
end
-- Calls fn(stack) for every stack in ordinary stock: warehouse members that are
-- not a machine or crafter role, each physical inventory once.
local function eachStock(fn)
  local wh = require('warehouse')
  local members = wh.members()
  local roles, seen = {}, {}
  for _, g in pairs(wh.groups()) do
    for _, s in pairs(g.roles) do
      roles[(members[s] or {}).inventory or s] = true
    end
  end
  for _, s in ipairs(sorted(members)) do
    local key = members[s].inventory or s
    if not roles[key] and not seen[key] then
      seen[key] = true
      for _, v in pairs((wh.contents(s) or {}).items or {}) do
        fn(v)
      end
    end
  end
end
-- What a chain of robot tasks takes from outside, and its net outputs. Items an
-- earlier task makes are used by later ones before anything is fetched.
local function chainNeeds(tasks)
  local needed, balance = {}, {}
  for _, t in ipairs(tasks) do
    local ops = t.qty_produced / t.recipeOutput
    for slot, id in pairs(t.recipe) do
      id = identity.canonical(id)
      if id ~= 'minecraft:air' and not (t.tool_slots or {})[slot] then
        local deficit = math.max(0, ops - (balance[id] or 0))
        needed[id] = (needed[id] or 0) + deficit
        balance[id] = (balance[id] or 0) + deficit - ops
      end
    end
    local id = identity.canonical(t.item)
    balance[id] = (balance[id] or 0) + t.qty_produced
  end
  local outputs = {}
  for id, n in pairs(balance) do
    if n - (needed[id] or 0) > 0 then
      outputs[id] = n - (needed[id] or 0)
    end
  end
  return needed, outputs
end
-- Operations that machine group i of count gets when ops are split evenly.
local function share(ops, count, i)
  return math.floor(ops / count) + (i <= ops % count and 1 or 0)
end
local function inputQuantities(t, plan)
  local node = plan.blueprint and plan.blueprint.nodes[t.node]
  return t.input_quantities or (node and node.input_quantities) or {}
end
local function stockSnapshot(reserved)
  local stacks = {}
  reserved = copy(reserved or {})
  eachStock(function(v)
    local id = identity.stackName(v.item)
    local withheld = math.min(v.count, reserved[id] or 0)
    reserved[id] = (reserved[id] or 0) - withheld
    if v.count > withheld then
      stacks[#stacks + 1] =
        { name = v.item.name, damage = v.item.damage or 0, size = v.count - withheld, maxSize = v.maxSize or 64 }
    end
  end)
  return assert(require('inventory').new({
    getAllStacks = function()
      return {
        getAll = function()
          return stacks
        end,
      }
    end,
  }, 0))
end
-- Prefix deficits preserve task order; exact physical tool wear is rebudgeted
-- after settlement. Cached plans retain their blueprint-independent payload.
function M.robotPlan(plan, first, last, inventory)
  local sub = {
    success = true,
    craftable = true,
    tasks = {},
    inventory_needed = {},
    requestOutputs = {},
    tools = copy(plan.tools or {}),
    tool_stock = {},
  }
  local usedTools, manufacturedTools = {}, {}
  for i = first, last do
    local t = copy(plan.tasks[i])
    t.node = nil
    t.input_nodes = nil
    sub.tasks[#sub.tasks + 1] = t
    for slot, id in pairs(t.recipe) do
      if (t.tool_slots or {})[slot] then
        usedTools[identity.canonical(id)] = true
      end
    end
    local family = require('craft_tool_rules').family(identity.canonical(t.item))
    if sub.tools[family] then
      manufacturedTools[family] = true
    end
  end
  sub.inventory_needed, sub.requestOutputs = chainNeeds(sub.tasks)
  for id in pairs(usedTools) do
    if manufacturedTools[id] then
      return nil,
        'Unsupported stage-tool contract: a tool is manufactured and reused in the same robot stage ('
          .. id
          .. '); fresh-output protection needs branch-aware tool accounting'
    end
    if (plan.tool_stock or {})[id] then
      sub.tool_stock[id] = copy(plan.tool_stock[id])
    end
  end
  for id, n in pairs(sub.inventory_needed) do
    if n == 0 then
      sub.inventory_needed[id] = nil
    end
  end
  local withdrawals = {}
  if inventory and next(usedTools) then
    local reserved = copy(sub.inventory_needed)
    local pool = require('craft_tool_budget').new(inventory, sub.tools, false, reserved)
    for _, t in ipairs(sub.tasks) do
      local slots = {}
      for _, family in pairs(t.tool_slots or {}) do
        slots[family] = (slots[family] or 0) + 1
      end
      for family, n in pairs(slots) do
        local missing = pool.charge(family, n, t.qty_produced / t.recipeOutput, family, true)
        if missing > 0 then
          return nil, 'Insufficient stage tool wear budget: ' .. family
        end
      end
    end
    local _, stock = pool.snapshot()
    sub.tool_stock = stock
    for exact, n in pairs(reserved) do
      local toolCount = n - (sub.inventory_needed[exact] or 0)
      if toolCount > 0 then
        withdrawals[exact] = toolCount
      end
    end
  else
    for family, units in pairs(sub.tool_stock) do
      withdrawals[family] = #units
    end
  end
  local valid, err = require('craft_plan').validate(sub)
  if not valid then
    return nil, err
  end
  local flow, problem = require('craft_plan').validateFlow(sub)
  if not flow then
    return nil, problem
  end
  return sub, nil, withdrawals
end
local function prepareRobot(run, s, reserved)
  local selected = { tasks = {}, tools = run.plan.tools, tool_stock = run.plan.tool_stock }
  for _, i in ipairs(s.taskIndices) do
    selected.tasks[#selected.tasks + 1] = run.plan.tasks[i]
  end
  return M.robotPlan(selected, 1, #selected.tasks, stockSnapshot(reserved))
end
function M.start(opts)
  return service.start(opts, prepareRobot)
end
local function start(opts)
  local ok, e = M.start(opts)
  assert(ok, e)
end
function M.status(id)
  return service.status(id)
end
function M.crafters(opts)
  return copy(config(opts).crafters or {})
end
function M.types(opts)
  return copy(config(opts).machineTypes or {})
end
function M.plan(id, qty, opts)
  opts = opts or {}
  local ok, p, err = pcall(function()
    assert(positive(qty), 'Quantity must be a positive integer')
    start(opts)
    local snapshot = require('craft_plans').inventory({ inventory = stockSnapshot(service.claims()) })
    local all = {}
    for i = 1, snapshot:getInventorySize() do
      all[i] = snapshot:getItemInSlot(i)
    end
    local planner = require('craftingv4_4')
    local result = planner.calculateCraftingPlan(identity.canonical(id), qty, {
      getAllStacks = function()
        return {
          getAll = function()
            return all
          end,
        }
      end,
    }, 0, true, { toolProfiles = opts.toolProfiles })
    while result.yield_data do
      local choice
      if opts.selectChoice then
        choice = opts.selectChoice(result.yield_data)
      end
      planner.resumeCalculation(result, choice)
    end
    if not result.success then
      return nil, result.error
    end
    result.stages = M.graph(result, config(opts), opts)
    local deficits = copy(result.external_needed or {})
    local fuel = {}
    for _, s in ipairs(result.stages) do
      if s.fuel then
        fuel[s.fuel.item] = (fuel[s.fuel.item] or 0) + s.fuel.need
      end
    end
    for name, n in pairs(fuel) do
      local have = snapshot:countItemByName(name)
      local reserved = (result.inventory_needed or {})[name] or 0
      deficits[name] = (deficits[name] or 0) + math.max(0, n - math.max(0, have - reserved))
    end
    result.missing = {}
    for _, name in ipairs(sorted(deficits)) do
      if deficits[name] > 0 then
        local have = snapshot:countItemByName(name)
        result.missing[#result.missing + 1] = { item = name, need = have + deficits[name], have = have }
      end
    end
    result.craftable = #result.missing == 0
    return result
  end)
  if not ok then
    return nil, tostring(p)
  end
  return p, err
end
local function processingOutputs(t, plan)
  local outputs = { [identity.canonical(t.item)] = t.recipeOutput }
  local byproducts = t.byproducts
  if not byproducts then
    local db = require('recipes')
    local all = db.getAll and db.getAll(t.item)
    local quantities = inputQuantities(t, plan)
    for _, recipe in ipairs(all or {}) do
      if
        recipe.isProcessing
        and recipe.machineType == t.machineType
        and (recipe.qty or 1) == t.recipeOutput
      then
        local matches = true
        local slots = 0
        for slot, value in pairs(recipe) do
          if type(slot) == 'number' then
            local id, q = value:match('^(.-),([%d%.]+)$')
            id = id or value
            q = tonumber(q) or 1
            if
              not t.recipe[slot]
              or identity.canonical(id) ~= identity.canonical(t.recipe[slot])
              or q ~= (quantities[slot] or 1)
            then
              matches = false
            end
            slots = slots + 1
          end
        end
        local expected = 0
        for _, id in pairs(t.recipe) do
          if id ~= 'minecraft:air' then
            expected = expected + 1
          end
        end
        if matches and slots == expected then
          byproducts = recipe.byproducts
          break
        end
      end
    end
  end
  for _, v in ipairs(byproducts or {}) do
    assert(concrete(v.item) and positive(v.qty), 'Invalid processing byproduct')
    local id = identity.canonical(v.item)
    outputs[id] = (outputs[id] or 0) + v.qty
  end
  return outputs
end
function M.graph(plan, cfg, opts)
  cfg = cfg or {}
  opts = opts or {}
  start(opts)
  local tasks, nodes = assert(plan.tasks, 'Invalid plan'), {}
  local selectedStages = plan.stages or {}
  local deps, consumers = {}, {}
  for i, t in ipairs(tasks) do
    if t.node then
      assert(not nodes[t.node], 'Duplicate task node')
      nodes[t.node] = i
    end
    deps[i] = {}
    consumers[i] = {}
  end
  local latest = {}
  for i, t in ipairs(tasks) do
    local refs = t.input_nodes
      or (plan.blueprint and plan.blueprint.nodes[t.node] and plan.blueprint.nodes[t.node].deps)
    for slot, id in pairs(t.recipe or {}) do
      if id ~= 'minecraft:air' then
        local parent = refs and nodes[refs[slot]] or (not refs and latest[identity.canonical(id)])
        if parent then
          assert(parent ~= i, 'Dependency cycle')
          deps[i][parent] = true
          consumers[parent][i] = true
        end
      end
    end
    latest[identity.canonical(t.item)] = i
  end
  local function number(t)
    local n = 0
    for _ in pairs(t) do
      n = n + 1
    end
    return n
  end
  local function processing(t)
    return t.isProcessing or t.machineType
  end
  local root = {}
  for i in ipairs(tasks) do
    root[i] = i
  end
  local function owner(i)
    while root[i] ~= i do
      i = root[i]
    end
    return i
  end
  for i, t in ipairs(tasks) do
    if not processing(t) and number(deps[i]) == 1 then
      local p = next(deps[i])
      local tool = false
      for _, family in pairs(t.tool_slots or {}) do
        if family == require('craft_tool_rules').family(tasks[p].item) then
          tool = true
        end
      end
      if p < i and not processing(tasks[p]) and number(consumers[p]) == 1 and not tool then
        root[i] = owner(p)
      end
    end
  end
  local stages, indices = {}, {}
  for i, t in ipairs(tasks) do
    local r = owner(i)
    local s = indices[r]
    if not s then
      s = #stages + 1
      indices[r] = s
      stages[s] = {
        kind = processing(t) and 'machine' or 'robot',
        after = {},
        tasks = {},
        inputs = {},
        outputs = {},
        taskIndices = {},
      }
    end
    local stage = stages[s]
    stage.taskIndices[#stage.taskIndices + 1] = i
    stage.tasks[#stage.tasks + 1] = { item = t.item, qty = t.qty_produced }
  end
  local wh = require('warehouse')
  local stock = {}
  eachStock(function(v)
    local id = identity.stackName(v.item)
    stock[id] = (stock[id] or 0) + v.count
  end)
  -- Stock claimed by running requests is not available to this plan.
  for id, n in pairs(service.claims()) do
    stock[id] = math.max(0, (stock[id] or 0) - n)
  end
  local fuelBudgets = {}
  for index, stage in ipairs(stages) do
    local after = {}
    for _, i in ipairs(stage.taskIndices) do
      for dep in pairs(deps[i]) do
        local s = indices[owner(dep)]
        if s ~= index then
          after[s] = true
        end
      end
    end
    stage.after = sorted(after)
    local t = tasks[stage.taskIndices[1]]
    local needed = {}
    if stage.kind == 'robot' then
      local chain = {}
      for _, i in ipairs(stage.taskIndices) do
        chain[#chain + 1] = tasks[i]
      end
      local outputs
      needed, outputs = chainNeeds(chain)
      for _, id in ipairs(sorted(outputs)) do
        stage.outputs[#stage.outputs + 1] = { item = id, qty = outputs[id] }
      end
      stage.crafter = (selectedStages[index] or {}).crafter or opts.crafter
    else
      stage.machineType = t.machineType
      local mt =
        assert((cfg.machineTypes or {})[t.machineType], 'Unknown machine type ' .. tostring(t.machineType))
      assert(
        type(mt.blocking) == 'boolean' and type(mt.roleSlots) == 'table',
        'Machine blocking and roleSlots are required'
      )
      local ops = t.qty_produced / t.recipeOutput
      local per = 0
      local quantities = inputQuantities(t, plan)
      for slot, id in pairs(t.recipe) do
        if id ~= 'minecraft:air' then
          local q = quantities[slot] or 1
          assert(positive(q), 'Machine ingredient quantities must be positive integers')
          needed[id] = (needed[id] or 0) + ops * q
          per = per + q
        end
      end
      assert(positive(mt.batch) and per > 0 and per <= mt.batch, 'Recipe inputs exceed machine load batch')
      stage.groups =
        copy((selectedStages[index] or {}).groups or (opts.machines or {})[t.machineType] or 'any')
      local groups = wh.groups(t.machineType)
      local names = stage.groups == 'any' and sorted(groups)
        or type(stage.groups) == 'string' and { stage.groups }
        or stage.groups
      assert(type(names) == 'table' and #names > 0, 'No machine groups')
      stage.loads = 0
      for i = 1, #names do
        stage.loads = stage.loads + math.ceil(share(ops, #names, i) / math.floor(mt.batch / per))
      end
      local outputs = processingOutputs(t, plan)
      for _, id in ipairs(sorted(outputs)) do
        stage.outputs[#stage.outputs + 1] = { item = id, qty = outputs[id] * ops }
      end
      if mt.fuel then
        local neededFuel = 0
        for i, name in ipairs(names) do
          local group = assert(groups[name], 'Unknown machine group ' .. tostring(name))
          local n = share(ops, #names, i)
          local budget = fuelBudgets[name]
          if not budget then
            local held = 0
            local view = wh.cachedRoleContents
              and wh.cachedRoleContents(group.roles[mt.fuel.role], mt.roleSlots[mt.fuel.role])
            for _, v in pairs((view or {}).items or {}) do
              if identity.stackName(v.item) == identity.canonical(mt.fuel.item) then
                held = held + v.count
              end
            end
            budget = { inputs = 0, credited = held }
            fuelBudgets[name] = budget
          end
          local total = math.ceil((budget.inputs + n * per) / mt.fuel.per)
          local additional = math.max(0, total - budget.credited)
          neededFuel = neededFuel + additional
          budget.credited = budget.credited + additional
          budget.inputs = budget.inputs + n * per
        end
        stage.fuel = { item = mt.fuel.item, need = neededFuel, have = stock[mt.fuel.item] or 0 }
      end
    end
    for _, id in ipairs(sorted(needed)) do
      stage.inputs[#stage.inputs + 1] = { item = id, need = needed[id], have = stock[id] or 0 }
    end
  end
  local visiting, done = {}, {}
  local function visit(i)
    assert(not visiting[i], 'Dependency cycle')
    if done[i] then
      return
    end
    visiting[i] = true
    for _, p in ipairs(stages[i].after) do
      visit(p)
    end
    visiting[i] = nil
    done[i] = true
  end
  for i in ipairs(stages) do
    visit(i)
  end
  for _, stage in ipairs(stages) do
    local ancestors = {}
    local function include(index)
      if ancestors[index] then
        return
      end
      ancestors[index] = true
      for _, parent in ipairs(stages[index].after) do
        include(parent)
      end
    end
    for _, parent in ipairs(stage.after) do
      include(parent)
    end
    local balance = copy(stock)
    for index in pairs(ancestors) do
      for _, v in ipairs(stages[index].inputs) do
        balance[v.item] = (balance[v.item] or 0) - v.need
      end
      for _, v in ipairs(stages[index].outputs) do
        balance[v.item] = (balance[v.item] or 0) + v.qty
      end
    end
    for _, v in ipairs(stage.inputs) do
      v.have = math.max(0, balance[v.item] or 0)
    end
  end
  return stages
end
function M.choose(plan, index, choice, opts)
  local ok, err = pcall(function()
    local s = assert(plan.stages and plan.stages[index], 'Unknown stage')
    if s.kind == 'robot' then
      assert(type(choice) == 'string' and M.crafters(opts)[choice], 'Unknown crafter')
      s.crafter = choice
    else
      if choice == 'any' then
        s.groups = 'any'
        return
      end
      start(opts)
      local names = type(choice) == 'string' and { choice } or choice
      assert(type(names) == 'table' and #names > 0, 'Machine choice must be any, a group or a set')
      local groups = require('warehouse').groups(s.machineType)
      local seen = {}
      for i, name in pairs(names) do
        assert(
          positive(i) and i <= #names and groups[name] and not seen[name],
          'Unknown or duplicate machine group'
        )
        seen[name] = true
      end
      assert(#sorted(seen) == #names, 'Sparse machine group set')
      s.groups = copy(names)
    end
  end)
  if not ok then
    return nil, tostring(err)
  end
  return true
end
function M.run(plan, opts)
  opts = copy(opts or {})
  local ok, result, cfg = pcall(function()
    if type(plan) == 'string' then
      if plan:find('/', 1, true) or plan:sub(-5) == '.plan' then
        local f = assert(io.open(plan, 'r'))
        local text = f:read('*a')
        f:close()
        plan = assert(require('serialization').unserialize(text), 'Invalid saved plan')
      else
        plan = assert(require('craft_plans').load(plan))
      end
    end
    assert(type(plan) == 'table' and type(plan.tasks) == 'table' and plan.success ~= false, 'Invalid plan')
    assert(plan.craftable ~= false and #(plan.missing or {}) == 0, 'Missing inputs')
    local n = 0
    for index, t in pairs(plan.tasks) do
      n = n + 1
      assert(
        positive(index)
          and index <= #plan.tasks
          and type(t) == 'table'
          and concrete(t.item)
          and positive(t.qty_produced)
          and positive(t.recipeOutput)
          and t.qty_produced % t.recipeOutput == 0
          and type(t.recipe) == 'table'
          and next(t.recipe),
        'Invalid task'
      )
      assert(t.isProcessing == nil or type(t.isProcessing) == 'boolean', 'Invalid processing flag')
      assert(
        t.machineType == nil or (type(t.machineType) == 'string' and #t.machineType > 0),
        'Invalid machine type'
      )
      for slot, id in pairs(t.recipe) do
        assert(positive(slot) and (id == 'minecraft:air' or concrete(id)), 'Invalid recipe ingredient')
      end
    end
    assert(n == #plan.tasks, 'Sparse task list')
    local configuration = config(opts)
    start(opts)
    plan = copy(plan)
    local selected = plan.stages
    plan.stages = M.graph(plan, configuration, opts)
    if selected then
      for i, s in ipairs(plan.stages) do
        local prior = selected[i]
        if prior then
          s.crafter = prior.crafter or s.crafter
          s.groups = copy(prior.groups or s.groups)
        end
      end
    end
    service.reconcile(configuration, opts)
    return plan, configuration
  end)
  if not ok then
    return nil, tostring(result)
  end
  return service.submit(result, cfg, opts)
end
function M.wait(id)
  return service.wait(id)
end
function M.runs()
  return service.runs()
end
function M.resources(opts)
  start(opts)
  return service.resources(config(opts))
end
function M.cancel(id, reason)
  return service.cancel(id, reason)
end
function M.robots(timeout, opts)
  local discovered, err = require('mes_config').robots(timeout)
  if not discovered then
    return nil, err
  end
  for _, robot in ipairs(discovered) do
    if robot.busy == false then
      service.confirmIdle(robot.address)
    end
  end
  return copy(discovered)
end
for _, name in ipairs({ 'setType', 'removeType', 'setCrafter', 'removeCrafter' }) do
  M[name] = function(...)
    return require('mes_config')[name](...)
  end
end
function M.search(...)
  return require('recipes').search(...)
end
return M
