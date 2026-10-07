-- Short-lived result tickets shared by a shell caller and its crafting menus.
-- No filesystem, events or hardware. The caller consumes/releases its ticket.
local handoff={}
local tickets,serial={},0
local function copy(value,seen)
    if type(value)~="table" then return value end
    seen=seen or {};if seen[value] then return seen[value] end
    local out={};seen[value]=out;for k,v in pairs(value) do out[k]=copy(v,seen) end;return out
end
function handoff.begin()
    serial=serial+1
    local id="craft_"..serial
    tickets[id]={results={},counts={},total=0,dropped=0}
    return id
end
function handoff.report(id,result)
    local ticket=tickets[id]
    if not ticket then return false,"Result ticket is not active." end
    if type(result)~="table" or type(result.status)~="string" then return false,"Invalid crafting outcome." end
    local outcome=copy(result)
    ticket.total=ticket.total+1
    ticket.counts[outcome.status]=(ticket.counts[outcome.status] or 0)+1
    if #ticket.results==32 then table.remove(ticket.results,1);ticket.dropped=ticket.dropped+1 end
    ticket.results[#ticket.results+1]=outcome
    return true
end
function handoff.finish(id)
    local ticket=tickets[id]
    if not ticket then return nil,"Result ticket is not active." end
    tickets[id]=nil
    return copy(ticket)
end
function handoff.release(id) if id~=nil then tickets[id]=nil end end
return handoff
