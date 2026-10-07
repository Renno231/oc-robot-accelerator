-- Execution-local provenance and tool-use ledger. Robot/component proxies are
-- supplied by the executor; requiring this module performs no hardware access.
local identity=require "item_identity"
local rules=require "craft_tool_rules"
local resources={}
function resources.new(plan,inventory,robot)
    local lots,units,held={}, {}, {}
    local outputs=assert(require("craft_plan").outputs(plan))
    local function key(item,node) return node or "item:"..identity.canonical(item) end
    local function tag(slot,node,qty)
        lots[slot]=lots[slot] or {};lots[slot][node]=(lots[slot][node] or 0)+qty
    end
    local function add(slot,item,qty,node)
        tag(slot,key(item,node),qty)
    end
    local function quantity(item,node,bufferOnly)
        local total=0;local id=key(item,node)
        for slot=bufferOnly and 13 or 1,inventory.getInventorySize() do
            local s=inventory.getStack(slot)
            if type(s)=="table" and identity.stackName(s)==identity.canonical(item) then
                total=total+math.min(s.size,(lots[slot] or {})[id] or 0)
            end
        end
        return total
    end
    local function free(item,node)
        return math.max(0,quantity(item,node,true)-(held[key(item,node)] or 0))
    end
    local function source(item,node)
        item=identity.canonical(item)
        if free(item,node)<=0 then return nil end
        for slot=13,inventory.getInventorySize() do
            local s=inventory.getStack(slot)
            if type(s)=="table" and identity.stackName(s)==item and
                ((lots[slot] or {})[key(item,node)] or 0)>0 then return slot end
        end
    end
    local function recordTool(slot,family,node,capacity,stocked)
        local unit={slot=slot,family=family,node=key(family,node),remaining=capacity,stocked=stocked}
        units[#units+1]=unit
        return unit
    end
    local function tool(family,node)
        -- Follow the planner's stock-first allocation order and minimum-use
        -- grants. Observed spare durability never changes a fixed wear schedule.
        for _,stocked in ipairs({true,false}) do
            local best
            for _,unit in ipairs(units) do
                if unit.stocked==stocked and unit.family==family and unit.node==key(family,node) and
                    unit.remaining>0 and unit.slot and unit.slot>=13 then
                    local s=inventory.getStack(unit.slot)
                    if type(s)=="table" and rules.family(s)==family and rules.usesLeft(s,plan.tools[family])>0 then
                        local exact=identity.stackName(s)
                        local protectedItem=plan.node_items and plan.node_items[node] or family
                        if (held[unit.node] or 0)==0 or exact~=identity.canonical(protectedItem) or free(exact,node)>0 then
                            if stocked then return unit end
                            if not best or unit.remaining>best.remaining then best=unit end
                        end
                    end
                end
            end
            if best then return best end
        end
    end
    local function move(from,to,qty,node,selectedUnit)
        local before=robot.count(from)
        inventory.transferInternal(from,to,qty)
        local moved=before-robot.count(from)
        if moved<=0 or moved>qty then return 0 end
        local left=moved
        if node then
            local count=(lots[from] or {})[node] or 0
            if count<moved then error("Ingredient branch ownership changed.") end
            lots[from][node]=count-moved;tag(to,node,moved);left=0
        else
            for id,count in pairs(lots[from] or {}) do
                local take=math.min(count,left)
                lots[from][id]=count-take;tag(to,id,take);left=left-take
                if left==0 then break end
            end
        end
        if selectedUnit then selectedUnit.slot=to
        else
            local movedUnits=0
            for _,unit in ipairs(units) do
                if movedUnits<moved and unit.slot==from and (not node or unit.node==node) then
                    unit.slot=to;movedUnits=movedUnits+1
                end
            end
        end
        return moved
    end
    local function afterCraft(task,loaded,outputSlot,produced,batch)
        for _,input in ipairs(loaded) do
            local s=inventory.getStack(input.slot)
            if input.unit then
                local profile=plan.tools[input.unit.family]
                if type(s)~="table" or s.size<=0 then
                    if input.actualCapacity>batch then return false,"Reusable tool unexpectedly consumed." end
                    input.unit.slot=nil;lots[input.slot]={}
                else
                    local damage=tonumber(s.damage or 0)
                    if rules.family(s)~=input.unit.family or s.size~=1 or
                        not damage or damage<0 or damage>=math.huge or damage%1~=0 or
                        damage<input.damage or damage-input.damage>batch*profile.durabilityPerUse then
                        return false,"Tool identity or wear differs from the captured profile."
                    end
                    lots[input.slot]={[input.node]=1}
                end
                input.unit.remaining=input.unit.remaining-batch
            else
                lots[input.slot]={}
                if type(s)=="table" and identity.stackName(s)==input.item then
                    if s.size>input.count then return false,"Unexpected ingredient quantity after crafting." end
                    lots[input.slot][input.node]=s.size
                end
            end
        end
        local node=key(task.item,task.node)
        tag(outputSlot,node,produced)
        local requested=plan.node_items and (plan.request_nodes[task.node] or 0) or (outputs[identity.canonical(task.item)] or 0)
        held[node]=math.min(requested,(held[node] or 0)+produced)
        local family=rules.family(task.item)
        if (plan.tools or {})[family] then
            local s=inventory.getStack(outputSlot)
            local capacity=rules.usesLeft(s,plan.tools[family])
            for _=1,produced do recordTool(outputSlot,family,task.node,capacity,false) end
        end
        return true
    end
    local function verify()
        if plan.node_items then
            for node,qty in pairs(plan.request_nodes) do
                if (held[node] or 0)<qty or quantity(plan.node_items[node],node,false)<qty then return false,"Protected output branch is incomplete: "..plan.node_items[node] end
            end
        else
            for item,qty in pairs(outputs) do
                if (held[key(item)] or 0)<qty then return false,"Requested output was not produced: "..item end
            end
        end
        for item,qty in pairs(outputs) do
            if inventory.countItemByName(item)<qty then return false,"Crafted quantity is below the requested quantity: "..item end
        end
        return true
    end
    return {add=add,recordTool=recordTool,tool=tool,source=source,free=free,move=move,
        afterCraft=afterCraft,verify=verify,key=key}
end
return resources
