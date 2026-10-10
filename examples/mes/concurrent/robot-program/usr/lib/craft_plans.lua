-- Labelled fixed batches for UI and unattended callers. No GPU, menu, robot,
-- recipe-database or network dependency is loaded merely by requiring this module.
local filesystem = require "filesystem"
local serialization = require "serialization"
local validator = require "craft_plan"
local plans = {directory = "/usr/craftplans/"}

local function validName(name)
    return type(name) == "string" and #name > 0 and #name <= 120 and name:match("%S") and
        name ~= "." and name ~= ".." and not name:find("/", 1, true) and
        not name:find("\\", 1, true) and not name:find("%c")
end

local function pathFor(name)
    if not validName(name) then return nil, "Invalid plan name: use a nonblank label without slashes or control characters (max 120 bytes)." end
    return filesystem.concat(plans.directory, name .. ".plan")
end

local function copy(map)
    local result = {}
    for k, v in pairs(map) do result[k] = v end
    return result
end

local function nested(map)
    local result={};for k,v in pairs(map or {}) do result[k]=copy(v) end;return result
end

-- Keep only execution data. Calculation coroutines, caches, callbacks and other
-- caller fields never enter the plan file or the modem payload.
local function prepare(plan)
    if type(plan) ~= "table" or plan.success == false or plan.craftable == false or
        plan.error or plan.cancelled or plan.yield_data or
        (plan.coroutine and (type(plan.coroutine) ~= "thread" or coroutine.status(plan.coroutine) ~= "dead")) then
        return nil, "Only finalized, craftable plans can be saved or run."
    end
    local valid, err = validator.validate(plan)
    if not valid then return nil, err end
    local fixed = {success = true, craftable = true, requestItem = plan.requestItem,
        requestQuantity = plan.requestQuantity, inventory_needed = copy(plan.inventory_needed),
        external_needed = {}, tasks = {}}
    if not fixed.requestItem then
        local outputs=assert(validator.outputs(plan));local names={}
        for item in pairs(outputs) do names[#names+1]=item end;table.sort(names)
        fixed.requestItem=names[1];fixed.requestQuantity=outputs[names[1]]
    end
    if plan.requestOutputs then fixed.requestOutputs=copy(plan.requestOutputs) end
    if plan.tools then
        fixed.tools={}
        for family,p in pairs(plan.tools) do
            fixed.tools[family]={durability=p.durability,durabilityPerUse=p.durabilityPerUse}
        end
    end
    if plan.tool_stock then fixed.tool_stock=nested(plan.tool_stock) end
    if plan.node_items then
        fixed.node_items=copy(plan.node_items);fixed.stock_nodes=copy(plan.stock_nodes)
        fixed.request_nodes=copy(plan.request_nodes);fixed.tool_stock_nodes=nested(plan.tool_stock_nodes)
    end
    for i, task in ipairs(plan.tasks) do
        fixed.tasks[i] = {item = task.item, qty_produced = task.qty_produced,
            recipeOutput = task.recipeOutput, repetitions = task.qty_produced / task.recipeOutput,
            recipe = copy(task.recipe)}
        if task.tool_slots then fixed.tasks[i].tool_slots=copy(task.tool_slots) end
        if task.node then
            fixed.tasks[i].node=task.node;fixed.tasks[i].input_nodes=copy(task.input_nodes)
        end
    end
    if plan.blueprint then
        local b,problem=require("craft_blueprint").copy(plan.blueprint)
        if not b then return nil,problem end
        local targets={}
        for _,root in ipairs(b.roots) do
            local item=b.nodes[root.node].item
            targets[item]=(targets[item] or 0)+root.quantity
        end
        local outputs=assert(validator.outputs(fixed))
        for item,qty in pairs(targets) do if outputs[item]~=qty then return nil,"Blueprint target mismatch." end end
        for item,qty in pairs(outputs) do if targets[item]~=qty then return nil,"Blueprint target mismatch." end end
        for family,p in pairs(fixed.tools or {}) do
            local captured=b.tools[family]
            if not captured or p.durability~=captured.durability or p.durabilityPerUse~=captured.durabilityPerUse then
                return nil,"Blueprint tool profile mismatch."
            end
        end
        fixed.blueprint=b
    end
    return fixed
end

function plans.prepare(plan)
    local ok,fixed,err=pcall(prepare,plan)
    if not ok then return nil,tostring(fixed) end
    return fixed,err
end
function plans.payload(plan)
    local fixed,err=plans.prepare(plan);if not fixed then return nil,err end
    fixed.blueprint=nil
    return fixed
end

local function withFile(path, mode, operation)
    local opened, file, err = pcall(io.open, path, mode)
    if not opened then return nil, tostring(file) end
    if not file then return nil, "Cannot open " .. path .. ": " .. tostring(err) end
    local ok, value, problem = pcall(operation, file)
    local closeOk, closed, closeError = pcall(file.close, file)
    if not ok then return nil, "Cannot process " .. path .. ": " .. tostring(value) end
    if value == nil then return nil, tostring(problem) end
    if not closeOk or closed == false or closeError then
        return nil, "Cannot close " .. path .. ": " .. tostring(closeError or closed)
    end
    return value
end

function plans.save(name, plan)
    local path, err = pathFor(name)
    if not path then return nil, err end
    local ok, fixed, problem = pcall(prepare, plan)
    if not ok then return nil, tostring(fixed) end
    if not fixed then return nil, problem end
    local encodedOk, encoded = pcall(serialization.serialize, fixed)
    if not encodedOk or type(encoded) ~= "string" then return nil, "Cannot serialize plan: " .. tostring(encoded) end
    local dirOk, made, dirError = pcall(function()
        if filesystem.exists(plans.directory) then return true end
        return filesystem.makeDirectory(plans.directory)
    end)
    if not dirOk or not made then return nil, "Cannot create plan directory: " .. tostring(dirError or made) end
    return withFile(path, "w", function(file)
        local written, writeError = file:write(encoded)
        if not written then error(writeError or "Plan write failed.") end
        return true
    end)
end

function plans.load(name)
    local path, err = pathFor(name)
    if not path then return nil, err end
    return withFile(path, "r", function(file)
        local data, readError = file:read(math.huge)
        if not data then error(readError or "Empty plan file.") end
        local decoded, decodeError = serialization.unserialize(data)
        if type(decoded) ~= "table" then error(decodeError or "Invalid saved plan.") end
        return prepare(decoded)
    end)
end

-- Directory enumeration only: no per-plan open/read/stat, no manifest/index.
-- The filename stem is both the stable lookup name and the display label.
function plans.list()
    local ok, names = pcall(function()
        if not filesystem.exists(plans.directory) then return {} end
        local iterator, err = filesystem.list(plans.directory)
        if not iterator then error(err or "Cannot list plan directory.") end
        local result = {}
        for file in iterator do
            if file:sub(-5) == ".plan" then
                local name = file:sub(1, -6)
                if validName(name) then result[#result + 1] = name end
            end
        end
        table.sort(result)
        return result
    end)
    if not ok then return nil, tostring(names) end
    return names
end

function plans.remove(name)
    local path,err=pathFor(name);if not path then return nil,err end
    local ok,removed,problem=pcall(filesystem.remove,path)
    if not ok or not removed then return nil,tostring(problem or removed) end
    return true
end

function plans.inventory(options)
    options=options or {}
    local side=options.storageSide==nil and 0 or options.storageSide
    if type(side)~="number" or side<0 or side>5 or side%1~=0 then error("Invalid storage side.") end
    local snapshot=options.inventory
    if not snapshot then
        local proxy=options.transposer or require("component").transposer
        snapshot=assert(require("inventory").new(proxy,side),"Unable to read stock inventory.")
    end
    local reserved=assert(validator.reservations(options.externalReserved))
    if not next(reserved) then return snapshot end
    local all={}
    for slot=1,snapshot:getInventorySize() do
        local stack=copy(snapshot:getItemInSlot(slot))
        local item=require("item_identity").stackName(stack)
        local removed=math.min(stack.size or 0,reserved[item] or 0)
        stack.size=(stack.size or 0)-removed;reserved[item]=(reserved[item] or 0)-removed
        all[slot]=stack
    end
    for item,qty in pairs(reserved) do
        if qty>0 then error("Reserved kit output missing from storage: "..item,0) end
    end
    return assert(require("inventory").new({getAllStacks=function()
        return {getAll=function() return all end}
    end},side))
end
function plans.refresh(plan,options)
    local ok,result,problem=pcall(function()
        local fixed,err
        if type(plan)=="string" then fixed,err=plans.load(plan) else fixed,err=plans.prepare(plan) end
        if not fixed then return nil,err end
        if not fixed.blueprint then return nil,"Saved plan has no blueprint; explicitly capture its choices before refreshing." end
        local refreshed,why=require("craft_blueprint").calculate(fixed.blueprint,plans.inventory(options))
        if not refreshed then return nil,why end
        if not refreshed.craftable then return nil,"Missing allowed inputs: "..serialization.serialize(refreshed.external_needed),refreshed end
        return plans.prepare(refreshed)
    end)
    if not ok then return nil,tostring(result) end
    return result,problem
end

local function countStock(item, options)
    if options.countStock then return options.countStock(item) end
    local side = options.storageSide == nil and 0 or options.storageSide
    if type(side) ~= "number" or side < 0 or side > 5 or side % 1 ~= 0 then error("Invalid storage side.") end
    local transposer = options.transposer or require("component").transposer
    local snapshot = require("inventory").new(transposer, side)
    if not snapshot then error("Unable to read stock inventory.") end
    return snapshot:countItemByName(item)
end

local function nonnegativeInteger(value)
    return type(value) == "number" and value >= 0 and value < math.huge and value % 1 == 0
end

-- Blocking, prompt-free fixed-batch execution. A threshold skips an entire batch
-- when stock >= threshold; it never scales/replans the saved tasks or exports stock.
function plans.run(nameOrPlan, options)
    options = options or {}
    local result = {status = "failed", success = false}
    if type(nameOrPlan) == "string" then result.name = nameOrPlan; result.label = nameOrPlan end
    local ok, err = pcall(function()
        if type(options) ~= "table" then error("Options must be a table.") end
        if options.accounting~=nil and options.accounting~="saved" and options.accounting~="refresh" then
            error("Accounting must be saved or refresh.")
        end
        for _, hook in ipairs({"onSuccess", "onFailure", "onSkip", "onMessage", "shouldContinue", "countStock"}) do
            if options[hook] ~= nil and type(options[hook]) ~= "function" then error(hook .. " must be a function.") end
        end
        if options.stockAtLeast ~= nil and not nonnegativeInteger(options.stockAtLeast) then error("stockAtLeast must be a finite nonnegative integer.") end
        local reserved=assert(validator.reservations(options.externalReserved))
        local fixed, problem
        if type(nameOrPlan) == "string" then fixed, problem = plans.load(nameOrPlan)
        else fixed, problem = prepare(nameOrPlan) end
        if not fixed then error(problem, 0) end
        result.item, result.quantity = fixed.requestItem, fixed.requestQuantity
        result.outputs=assert(validator.outputs(fixed))
        if options.stockAtLeast ~= nil then
            local count = countStock(fixed.requestItem, options)
            if not nonnegativeInteger(count) then error("Stock count must be a finite nonnegative integer.") end
            result.stockCount, result.stockAtLeast = count, options.stockAtLeast
            if count >= options.stockAtLeast then
                result.status, result.message = "skipped", "Stock threshold already met."
                return
            end
        end
        if options.accounting=="refresh" then
            fixed,problem=plans.refresh(fixed,options)
            if not fixed then error(problem,0) end
        end
        local payload=assert(plans.payload(fixed))
        if next(reserved) then payload.external_reserved=reserved end
        assert(validator.validate(payload))
        local execution = require("craft_client").runDetailed(payload, options)
        result.status, result.success, result.message = execution.status, execution.success, execution.message
        result.cleanupError, result.mayHaveExecuted = execution.cleanupError, execution.mayHaveExecuted
        result.jobId,result.serverAddress,result.receiptStatus=execution.jobId,execution.serverAddress,execution.receiptStatus
    end)
    if not ok then result.message = tostring(err) end
    local hookName = result.status == "complete" and "onSuccess" or result.status == "skipped" and "onSkip" or "onFailure"
    local callback = type(options) == "table" and options[hookName]
    if type(callback) == "function" then
        local hookResult=copy(result)
        if result.outputs then hookResult.outputs=copy(result.outputs) end
        local hookOk, hookError = pcall(callback, hookResult)
        -- Hook exceptions do not turn a verified craft into a failed/retryable job.
        if not hookOk then result.hookError = tostring(hookError) end
    end
    return result
end

function plans.preview(nameOrPlan)
    local p,err
    if type(nameOrPlan)=="string" then p,err=plans.load(nameOrPlan) else p,err=plans.prepare(nameOrPlan) end
    if not p then return nil,err end
    return require("craft_preview").describe(p)
end
function plans.edit(nameOrPlan,change,options,selectChoice)
    return require("craft_edit").candidate(nameOrPlan,change,options,selectChoice)
end
function plans.query(serverAddress,jobId,options) return require("craft_client").query(serverAddress,jobId,options) end

return plans
