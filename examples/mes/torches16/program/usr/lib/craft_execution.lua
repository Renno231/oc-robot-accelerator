-- Tool-aware and multi-output execution. All choices/rules come from the payload.
local component=require "component"
local sides=require "sides"
local robinv=require "robinv"
local identity=require "item_identity"
local rules=require "craft_tool_rules"
local execution={}
local function keys(t) local out={};for k in pairs(t) do out[#out+1]=k end;table.sort(out);return out end
local function destination(item)
    local slot=robinv.nextSlotContainingItemWithRoom(item,1,true)
    if not slot then return nil end
    local s=robinv.getStack(slot);return slot,type(s)=="table" and s.maxSize-s.size or 64
end
local function stacks(side)
    local iterator=component.inventory_controller.getAllStacks(side)
    if not iterator then return nil end
    return iterator.getAll()
end
function execution.execute(plan,options,dump,verifyReturned,storageCounts)
    local side=options.side or sides.front
    local reserved=assert(require("craft_plan").reservations(plan.external_reserved))
    local function checkReserved()
        if not next(reserved) then return true end
        return verifyReturned(side,{},reserved)
    end
    local function active() return not options.shouldContinue or options.shouldContinue() end
    local function progress(s) if options.onProgress then options.onProgress(s) end end
    if not active() then return false,"Crafting cancelled." end
    robinv.sync();local ok,err=dump(side);if not ok then return false,err end
    local ledger=require("craft_resources").new(plan,robinv,component.robot)
    local function pull(item,quantity,node)
        while quantity>0 do
            if not active() then return false,"Crafting cancelled." end
            local all=stacks(side);if not all then return false,"Unable to read source inventory." end
            local counts,why=storageCounts(side,all);if not counts then return false,why end
            if (counts[item] or 0)-(reserved[item] or 0)<quantity then
                return false,"Missing prerequisite or externally reserved output: "..item.." x"..quantity
            end
            local from,s
            for i,stack in ipairs(all) do
                if stack.size and stack.size>0 and identity.stackName(stack)==item then from=i;s=stack;break end
            end
            if not from then return false,"Missing prerequisite: "..item.." x"..quantity end
            local to,room=destination(item);if not to then return false,"Insufficient robot buffer capacity for "..item end
            local before=component.robot.count(to)
            robinv.transferToInternal(side,from,to,math.min(quantity,s.size,s.maxSize,room))
            local moved=component.robot.count(to)-before
            if moved<=0 or robinv.getItemNameInSlot(to)~=item then return false,"Ingredient transfer failed: "..item end
            ledger.add(to,item,moved,node);quantity=quantity-moved
        end
        return true
    end
    if plan.node_items then
        for _,node in ipairs(keys(plan.stock_nodes)) do
            local good,problem=pull(identity.canonical(plan.node_items[node]),plan.stock_nodes[node],node)
            if not good then return false,problem end
        end
    else
        for _,item in ipairs(keys(plan.inventory_needed)) do
            local good,problem=pull(identity.canonical(item),plan.inventory_needed[item])
            if not good then return false,problem end
        end
    end
    for _,family in ipairs(keys(plan.tool_stock or {})) do
        local profile=plan.tools[family]
        for index,uses in ipairs(plan.tool_stock[family]) do
            if not active() then return false,"Crafting cancelled." end
            local all=stacks(side);if not all then return false,"Unable to read source tools." end
            local counts,why=storageCounts(side,all);if not counts then return false,why end
            local from,s,best
            for i,stack in ipairs(all) do
                if stack.size and stack.size>0 and rules.family(stack)==family then
                    local capacity=rules.usesLeft(stack,profile)
                    local exact=identity.stackName(stack)
                    if (counts[exact] or 0)>(reserved[exact] or 0) and capacity>=uses and (not best or capacity<best) then from=i;s=stack;best=capacity end
                end
            end
            if not from then return false,"Missing prerequisite tool: "..family.." ("..uses.." uses)." end
            local item=identity.stackName(s);local to=destination(item)
            if not to then return false,"Insufficient robot buffer capacity for tools." end
            local before=component.robot.count(to);robinv.transferToInternal(side,from,to,1)
            local moved=component.robot.count(to)-before;local actual=robinv.getStack(to)
            if moved~=1 or type(actual)~="table" or rules.family(actual)~=family or rules.usesLeft(actual,profile)<uses then
                return false,"Tool transfer failed or source wear changed."
            end
            local node=plan.node_items and plan.tool_stock_nodes[family][index] or nil
            ledger.add(to,family,1,node);ledger.recordTool(to,family,node,uses,true)
        end
    end
    progress("Prerequisites gathered.")
    local function clearGrid()
        robinv.resyncCraftingGrid()
        for index=1,9 do
            local from=robinv.toCraftingSlot(index)
            while component.robot.count(from)>0 do
                local to,room=destination(robinv.getItemNameInSlot(from))
                if not to then return false,"No buffer space for crafting-grid leftovers." end
                if ledger.move(from,to,math.min(component.robot.count(from),room))<=0 then return false,"Unable to clear crafting grid." end
            end
        end
        return true
    end
    for taskIndex,task in ipairs(plan.tasks) do
        local remaining=task.qty_produced/task.recipeOutput
        local outputMax
        while remaining>0 do
            if not active() then return false,"Crafting cancelled." end
            local intact,why=checkReserved();if not intact then return false,why end
            local cleared,problem=clearGrid();if not cleared then return false,problem end
            local hasTools=next(task.tool_slots or {})~=nil
            local batch=hasTools and 1 or (outputMax and math.min(remaining,math.max(1,math.floor(outputMax/task.recipeOutput))) or 1)
            local groups={}
            for slot,item in pairs(task.recipe) do
                item=identity.canonical(item)
                if item~="minecraft:air" and not (task.tool_slots or {})[slot] then
                    local node=task.input_nodes and task.input_nodes[slot]
                    local id=ledger.key(item,node)
                    groups[id]=groups[id] or {item=item,node=node,count=0}
                    groups[id].count=groups[id].count+1
                end
            end
            for _,group in pairs(groups) do
                local from=ledger.source(group.item,group.node)
                if not from then return false,"Missing task ingredient or protected output: "..group.item end
                batch=math.min(batch,math.floor(ledger.free(group.item,group.node)/group.count),robinv.getStack(from).maxSize)
            end
            if batch<1 then return false,"Insufficient distinct task ingredients." end
            local loaded={}
            for index=1,9 do
                local item=identity.canonical(task.recipe[index])
                if item and item~="minecraft:air" then
                    local target=robinv.toCraftingSlot(index)
                    local node=task.input_nodes and task.input_nodes[index]
                    local id=ledger.key(item,node)
                    local family=(task.tool_slots or {})[index]
                    if family then
                        local unit=ledger.tool(family,node)
                        if not unit then return false,"No eligible allocated tool: "..family end
                        local s=robinv.getStack(unit.slot)
                        local damage=tonumber(s.damage or 0);local capacity=rules.usesLeft(s,plan.tools[family])
                        if ledger.move(unit.slot,target,1,id,unit)~=1 then return false,"Unable to load tool." end
                        loaded[#loaded+1]={slot=target,node=id,unit=unit,damage=damage,actualCapacity=capacity}
                    else
                        while component.robot.count(target)<batch do
                            local from=ledger.source(item,node)
                            if not from then return false,"Missing ingredient branch: "..item end
                            local count=math.min(batch-component.robot.count(target),ledger.free(item,node))
                            if ledger.move(from,target,count,id)<=0 or robinv.getItemNameInSlot(target)~=item then
                                return false,"Unable to load crafting-grid ingredient: "..item
                            end
                        end
                        loaded[#loaded+1]={slot=target,node=id,item=item,count=batch}
                    end
                end
            end
            local outputSlot=robinv.nextSlotContainingItemWithRoom(task.item,batch*task.recipeOutput,true)
            if not outputSlot then return false,"No robot buffer slot for craft output: "..task.item end
            robinv.select(outputSlot)
            local before=robinv.countItemByName(task.item)
            local crafted=component.crafting.craft(batch*task.recipeOutput)
            robinv.forceSyncStack(outputSlot);robinv.resyncCraftingGrid()
            local produced=robinv.countItemByName(task.item)-before
            if not crafted or produced~=batch*task.recipeOutput then return false,"Craft output verification failed at task "..taskIndex end
            local verified,why=ledger.afterCraft(task,loaded,outputSlot,produced,batch)
            if not verified then return false,why end
            outputMax=robinv.getStack(outputSlot).maxSize;remaining=remaining-batch
            progress("Task "..taskIndex.."/"..#plan.tasks..": "..task.item)
        end
    end
    if not active() then return false,"Crafting cancelled." end
    local verified,why=ledger.verify();if not verified then return false,why end
    local returned,problem=dump(side);if not returned then return false,problem end
    local stored,counts=verifyReturned(side,assert(require("craft_plan").outputs(plan)),reserved)
    if not stored then return false,counts end
    progress("All requested outputs verified and returned to storage.")
    -- The robot just read its buffer; report it so nothing has to look again.
    return true,nil,counts
end
return execution
