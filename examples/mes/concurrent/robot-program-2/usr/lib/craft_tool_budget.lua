-- Calculation-local tool pools. Each scope is a captured manufacturing branch.
-- Reservations are global: two branches cannot claim the same stocked unit.
local rules = require "craft_tool_rules"
local identity = require "item_identity"
local budget = {}
function budget.new(inventory, profiles, ignoreInventory, reserved)
    reserved = reserved or {}
    local pools, available, usedProfiles, usedStock = {}, {}, {}, {}
    local function stockFor(family)
        if available[family] then return available[family] end
        local units, ordinals = {}, {}
        if not ignoreInventory and inventory then
            local _, slots = inventory:countItemByName(family .. ":*")
            table.sort(slots)
            for _, slot in ipairs(slots) do
                local stack = inventory:getItemInSlot(slot)
                local exact = identity.stackName(stack)
                local capacity = rules.usesLeft(stack, profiles[family])
                assert(type(stack.size)=="number" and stack.size>0 and stack.size<math.huge and stack.size%1==0,
                    "Invalid stocked tool quantity.")
                local first=(ordinals[exact] or 0)+1
                local last=first+stack.size-1
                assert(last>=first and last<math.huge,"Stocked tool quantity overflow.")
                units[#units+1]={remaining=capacity,exact=exact,cursor=first,last=last}
                ordinals[exact]=last
            end
        end
        available[family] = units
        return units
    end
    local function poolFor(family, scope)
        local key = scope or family
        if pools[key] then return pools[key] end
        assert(rules.validate(profiles[family]))
        usedProfiles[family] = {durability=profiles[family].durability,
            durabilityPerUse=profiles[family].durabilityPerUse}
        local pool = {groups={}, life=rules.usesLeft({damage=0}, profiles[family])}
        pools[key] = pool
        return pool
    end
    local function charge(family, slots, operations, scope, useStock)
        assert(type(operations)=="number" and operations>0 and operations<math.huge and
            operations%1==0 and type(slots)=="number" and slots>0 and slots<=9 and slots%1==0,
            "Invalid tool operation count.")
        local pool, fresh, seen = poolFor(family, scope), 0, {}
        while operations > 0 do
            -- Claim stock only as needed, leaving unused units for other scopes.
            local current = 0
            for _, group in ipairs(pool.groups) do current=current+group.count end
            if useStock ~= false and current < slots then
                for _, cohort in ipairs(stockFor(family)) do
                    if current>=slots then break end
                    if cohort.remaining>0 then
                        cohort.cursor=math.max(cohort.cursor,(reserved[cohort.exact] or 0)+1)
                        while current<slots and cohort.cursor<=cohort.last do
                            local unit={remaining=cohort.remaining,count=1,used=0,stocked=true,
                                exact=cohort.exact,scope=scope or family,sequence=#usedStock+1}
                            cohort.cursor=cohort.cursor+1
                            reserved[unit.exact]=(reserved[unit.exact] or 0)+1
                            usedStock[#usedStock+1]={family=family,node=scope,unit=unit}
                            pool.groups[#pool.groups+1]=unit;current=current+1
                        end
                    end
                end
            end
            table.sort(pool.groups,function(a,b)
                if (a.stocked==true)~=(b.stocked==true) then return a.stocked==true end
                if a.stocked then return a.sequence<b.sequence end
                if a.remaining~=b.remaining then return a.remaining>b.remaining end
                return a.count>b.count
            end)
            local state, hasStock = {}, false
            for _, group in ipairs(pool.groups) do
                if group.stocked then hasStock=true end
                state[#state+1]=tostring(group.remaining)..":"..group.count
            end
            if not hasStock then
                local key=table.concat(state,","); local previous=seen[key]
                if previous then
                    local period=previous.operations-operations
                    if period>0 then
                        local cycles=math.floor(operations/period)
                        fresh=fresh+cycles*(fresh-previous.fresh)
                        operations=operations-cycles*period
                        if operations==0 then break end
                    end
                else seen[key]={operations=operations,fresh=fresh} end
            end
            local selected, needed, batch = {}, slots, operations
            for _, group in ipairs(pool.groups) do
                if needed>0 then
                    local take=math.min(needed,group.count)
                    selected[#selected+1]={group=group,count=take}
                    needed=needed-take; batch=math.min(batch,group.remaining)
                end
            end
            if needed==slots then
                local cohorts=pool.life==math.huge and 1 or math.ceil(operations/pool.life)
                fresh=fresh+slots*cohorts
                local lastUses=pool.life==math.huge and operations or operations-(cohorts-1)*pool.life
                pool.groups={{remaining=pool.life-lastUses,count=slots}}
                if pool.groups[1].remaining<=0 then pool.groups={} end
                operations=0
            else
                if needed>0 then
                    local group={remaining=pool.life,count=needed}
                    pool.groups[#pool.groups+1]=group
                    selected[#selected+1]={group=group,count=needed}
                    batch=math.min(batch,pool.life); fresh=fresh+needed
                end
                for _, choice in ipairs(selected) do
                    local group=choice.group
                    if group.stocked then
                        group.remaining=group.remaining-batch; group.used=group.used+batch
                    else
                        group.count=group.count-choice.count
                        pool.groups[#pool.groups+1]={remaining=group.remaining-batch,count=choice.count}
                    end
                end
                operations=operations-batch
                local active={}
                for _, group in ipairs(pool.groups) do
                    if group.count>0 and group.remaining>0 then active[#active+1]=group end
                end
                pool.groups=active
            end
        end
        assert(fresh>=0 and fresh<math.huge,"Tool demand overflow.")
        return fresh
    end
    local function snapshot()
        local stock, nodes = {}, {}
        -- Preserve allocation order. The robot follows these logical capacities,
        -- rather than inventing a different wear schedule from observed damage.
        for _, entry in ipairs(usedStock) do
            local family=entry.family
            stock[family]=stock[family] or {}; nodes[family]=nodes[family] or {}
            stock[family][#stock[family]+1]=entry.unit.used
            nodes[family][#nodes[family]+1]=entry.node or family
        end
        return usedProfiles, stock, nodes
    end
    local supplied=0
    local function supply(family,count,capacity,scope,stocked)
        assert(type(count)=="number" and count>0 and count%1==0 and count<math.huge and capacity>0,
            "Invalid supplied tool units.")
        local pool=poolFor(family,scope);supplied=supplied+1
        pool.groups[#pool.groups+1]={remaining=capacity,count=count,stocked=stocked,
            used=0,sequence=supplied}
    end
    return {charge=charge,snapshot=snapshot,supply=supply}
end
return budget
