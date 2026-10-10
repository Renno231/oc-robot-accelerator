-- Verified execution of 3x3 plans. Machine-processing tasks require a separate
-- executor and are rejected before inventory is moved.
local component = require "component"
local sides = require "sides"
local robinv = require "robinv"
local identity = require "item_identity"
local executor = {}

executor.validatePlan = require("craft_plan").validate

function executor.storageCounts(side,all)
    local ok,counts=pcall(function()
        if not all then
            local iterator=assert(component.inventory_controller.getAllStacks(side),"Unable to read return storage.")
            all=iterator.getAll()
        end
        assert(type(all)=="table","Invalid storage contents.")
        local out={}
        for _,stack in ipairs(all) do
            assert(type(stack)=="table","Invalid storage stack.")
            local qty=stack.size or 0
            assert(type(qty)=="number" and qty>=0 and qty<math.huge and qty%1==0,"Invalid storage quantity.")
            if qty>0 then
                assert(type(stack.name)=="string","Invalid storage item.")
                local item=identity.stackName(stack)
                out[item]=(out[item] or 0)+qty
                assert(out[item]<math.huge,"Storage quantity overflow.")
            end
        end
        return out
    end)
    if not ok then return nil,tostring(counts) end
    return counts
end

function executor.verifyReturned(side,outputs,reserved)
    local counts,err=executor.storageCounts(side);if not counts then return false,err end
    local needed={}
    for item,qty in pairs(outputs or {}) do needed[item]=(needed[item] or 0)+qty end
    for item,qty in pairs(reserved or {}) do needed[item]=(needed[item] or 0)+qty end
    for item,qty in pairs(needed) do
        if (counts[item] or 0)<qty then return false,"Returned output or external reservation missing from storage: "..item end
    end
    return true,counts
end

function executor.dumpInventory(side)
    side = side or sides.front
    for slot = 1, robinv.getInventorySize() do
        while component.robot.count(slot) > 0 do
            local before = component.robot.count(slot)
            robinv.transferToExternal(side, slot, before)
            if component.robot.count(slot) >= before then
                return false, "Unable to return items from robot slot " .. slot .. "; storage may be full."
            end
        end
    end
    return true
end

local function getName(stack)
    if type(stack) ~= "table" or not stack.name or not stack.size or stack.size <= 0 then return nil end
    return identity.stackName(stack)
end

local function bufferDestination(item)
    local slot = robinv.nextSlotContainingItemWithRoom(item, 1, true)
    if not slot then return nil end
    local stack = robinv.getStack(slot)
    return slot, type(stack) == "table" and stack.maxSize - stack.size or 64
end

local function clearGrid()
    robinv.resyncCraftingGrid()
    for index = 1, 9 do
        local slot = robinv.toCraftingSlot(index)
        while component.robot.count(slot) > 0 do
            local item = robinv.getItemNameInSlot(slot)
            local destination, room = bufferDestination(item)
            if not destination then return false, "No buffer space for crafting-grid leftovers." end
            local before = component.robot.count(slot)
            robinv.transferInternal(slot, destination, math.min(before, room))
            if component.robot.count(slot) >= before then return false, "Unable to clear crafting grid." end
        end
    end
    return true
end

function executor.executePlan(plan, options)
    options = options or {}
    local valid, reason = executor.validatePlan(plan)
    if not valid then return false, reason end
    if plan.node_items or plan.tools or plan.requestOutputs or plan.external_reserved then
        return require("craft_execution").execute(plan,options,executor.dumpInventory,executor.verifyReturned,executor.storageCounts)
    end
    local side = options.side or sides.front
    local function active() return not options.shouldContinue or options.shouldContinue() end
    local function progress(message)
        if options.onProgress then options.onProgress(message) end
    end
    if not active() then return false, "Crafting cancelled." end
    robinv.sync()
    local emptied, dumpError = executor.dumpInventory(side)
    if not emptied then return false, dumpError end

    -- Read live external slots after every pull. Storage drawers can change slot
    -- indices, and transfer success does not imply the requested quantity moved.
    for item, required in pairs(plan.inventory_needed) do
        item = identity.canonical(item)
        local remaining = required
        while remaining > 0 do
            if not active() then return false, "Crafting cancelled." end
            local iterator = component.inventory_controller.getAllStacks(side)
            if not iterator then return false, "Unable to read source inventory." end
            local source, sourceStack
            for index, stack in ipairs(iterator.getAll()) do
                if getName(stack) == item then source, sourceStack = index, stack; break end
            end
            if not source then return false, "Missing prerequisite: " .. item .. " x" .. remaining end
            local destination, room = bufferDestination(item)
            if not destination then return false, "Insufficient robot buffer capacity for " .. item end
            local before = component.robot.count(destination)
            robinv.transferToInternal(side, source, destination,
                math.min(remaining, sourceStack.size, sourceStack.maxSize, room))
            local moved = component.robot.count(destination) - before
            if moved <= 0 or robinv.getItemNameInSlot(destination) ~= item then
                return false, "Ingredient transfer failed or source inventory changed: " .. item
            end
            remaining = remaining - moved
        end
    end
    progress("Prerequisites gathered.")

    for taskIndex, task in ipairs(plan.tasks) do
        local remaining = task.qty_produced / task.recipeOutput
        local outputMaxSize
        while remaining > 0 do
            if not active() then return false, "Crafting cancelled." end
            local cleared, gridError = clearGrid()
            if not cleared then return false, gridError end
            -- Probe one operation to discover the output's real stack limit.
            local batch = outputMaxSize and math.min(remaining,
                math.max(1, math.floor(outputMaxSize / task.recipeOutput))) or 1
            for _, item in pairs(task.recipe) do
                item = identity.canonical(item)
                if item ~= "minecraft:air" then
                    local stack = robinv.getStack(robinv.nextSlotContaining(item, true))
                    if type(stack) ~= "table" then return false, "Missing task ingredient: " .. item end
                    batch = math.min(batch, stack.maxSize)
                end
            end
            for index = 1, 9 do
                local item = identity.canonical(task.recipe[index])
                if item and item ~= "minecraft:air" then
                    local target = robinv.toCraftingSlot(index)
                    while component.robot.count(target) < batch do
                        local source = robinv.nextSlotContaining(item, true)
                        if not source then return false, "Missing task ingredient: " .. item end
                        local before = component.robot.count(target)
                        robinv.transferInternal(source, target, batch - before)
                        if component.robot.count(target) <= before or robinv.getItemNameInSlot(target) ~= item then
                            return false, "Unable to load crafting-grid ingredient: " .. item
                        end
                    end
                end
            end
            local outputSlot = robinv.nextSlotContainingItemWithRoom(task.item, batch * task.recipeOutput, true)
            if not outputSlot then return false, "No robot buffer slot for craft output: " .. task.item end
            robinv.select(outputSlot)
            local before = robinv.countItemByName(task.item)
            local crafted = component.crafting.craft(batch * task.recipeOutput)
            robinv.forceSyncStack(outputSlot)
            robinv.resyncCraftingGrid()
            local produced = robinv.countItemByName(task.item) - before
            if not crafted or produced ~= batch * task.recipeOutput then
                return false, "Craft output verification failed at task " .. taskIndex .. " (" .. task.item .. ")."
            end
            outputMaxSize = robinv.getStack(outputSlot).maxSize
            remaining = remaining - batch
            progress("Task " .. taskIndex .. "/" .. #plan.tasks .. ": " .. task.item)
        end
    end
    if not active() then return false, "Crafting cancelled." end
    if robinv.countItemByName(plan.requestItem) < plan.requestQuantity then
        return false, "Crafted quantity is below the requested quantity."
    end
    -- COMPLETE is permitted only after both quantity verification and return.
    local returned, returnError = executor.dumpInventory(side)
    if not returned then return false, returnError end
    local stored,counts=executor.verifyReturned(side,assert(require("craft_plan").outputs(plan)))
    if not stored then return false,counts end
    progress("Requested output verified and returned to storage.")
    -- The robot just read its buffer; report it so nothing has to look again.
    return true,nil,counts
end

return executor
