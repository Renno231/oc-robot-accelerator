-- Admit RPC requests without yielding; execute only from this program's main loop.
package.loaded.robinv = nil
package.loaded.craft_executor = nil
local sides = require("sides")
local event = require("event")
local executor = require("craft_executor")
local api = require("api")
local _, options = require("shell").parse(...)
local storageSide = options.side == nil and sides.front or tonumber(options.side)
assert(type(storageSide)=="number" and storageSide>=0 and storageSide<=5 and storageSide%1==0, "Invalid storage side.")
local receipts = require("craft_receipts").new()
local running, active = true, nil
local publisher
local function stopProgram() running=false;return false end
event.listen("interrupted", stopProgram)
local function failed(id, message)
    return {status="FAILED",jobId=id,message=message}
end
local handlers = {}
function handlers.status(id)
    if id==nil then return {busy=active~=nil,currentJobId=active and active.id or nil} end
    local owner = api.caller().address
    local receipt, why = receipts.lookup(id, owner)
    return receipt or failed(id,why)
end
function handlers.craft(plan,id,retryOnly)
    local owner = api.caller().address
    local existing, why = receipts.lookup(id,owner)
    if not existing then return "failed",failed(id,why) end
    if existing.status~="NOT_FOUND" or retryOnly then
        local admitted, receipt = receipts.begin(id,owner,plan,true)
        return admitted==nil and "failed" or "status", admitted==nil and failed(id,receipt) or receipt
    end
    if active then return "busy",failed(id,"Crafting robot is busy.") end
    local valid, validationError = executor.validatePlan(plan)
    if not valid then return "failed",failed(id,validationError) end
    local admitted, receipt = receipts.begin(id,owner,plan)
    if admitted~=true then return admitted==nil and "failed" or "status", admitted==nil and failed(id,receipt) or receipt end
    active={plan=plan,id=id}
    return "accepted",{status="ACCEPTED",jobId=id,receipt=true}
end
local function execute(job)
    local ok, completed, executionError, buffer = xpcall(function()
        return executor.executePlan(job.plan, {
            side=storageSide,
            shouldContinue=function() return running end,
            onProgress=function(message)
                publisher:publish("job:"..job.id,{status="WORKING",jobId=job.id,message=message})
            end
        })
    end,debug.traceback)
    if not ok then executionError=completed;completed=false end
    if not completed then
        local cleanupOk, returned, cleanupError = pcall(executor.dumpInventory,storageSide)
        if not cleanupOk or not returned then
            executionError=tostring(executionError).."; cleanup failed: "..tostring(cleanupError or returned)
        end
    end
    local terminal=receipts.finish(job.id,completed and "COMPLETE" or "FAILED",executionError,completed and buffer or nil)
    active=nil
    publisher:publish("job:"..job.id,terminal)
end
-- cproc owns its computer's networking; a lost subscriber never cancels admitted work.
local ok, startupError = xpcall(function()
    pcall(executor.dumpInventory,storageSide)
    local endpoint=api.expose("craftServer",handlers,5990)
    local host=require("hosts").localhost()
    assert(host and type(host:getWakeKey())=="string" and host:getWakeKey()~="", "Pair this robot before starting cproc.")
    endpoint:setAccessKey(host:getWakeKey())
    publisher=require("pubsub").attach(endpoint)
    print("CraftProcessor ready. Awaiting connection.")
    while running do
        if active then execute(active) else os.sleep(0.1) end
    end
end,debug.traceback)
local listenerOk, listenerError = pcall(event.ignore,"interrupted",stopProgram)
local cleanupOk, cleanupError = pcall(require("tnet").shutdown)
if not ok then error(startupError,0) end
if not cleanupOk then error(cleanupError,0) end
if not listenerOk then error(listenerError,0) end
print("CraftProcessor shutting down.")
