-- Read-only explanations of recorded plans. No recipe lookup or recalculation.
local identity=require "item_identity"
local preview={}
local function keys(t) local r={};for k in pairs(t or {}) do r[#r+1]=k end;table.sort(r);return r end
local function add(t,k,n) k=identity.canonical(k);t[k]=(t[k] or 0)+n end
function preview.describe(plan)
    local p,err=require("craft_plans").prepare(plan);if not p then return nil,err end
    local out={requested=assert(require("craft_plan").outputs(p)),withdrawals={},manufactured={},
        remaining={},operations={},tools={},routes={},captured=p.blueprint~=nil}
    for item,n in pairs(p.inventory_needed) do add(out.withdrawals,item,n);add(out.remaining,item,n) end
    for _,t in ipairs(p.tasks) do
        local ops=t.qty_produced/t.recipeOutput
        add(out.manufactured,t.item,t.qty_produced);add(out.remaining,t.item,t.qty_produced)
        out.operations[#out.operations+1]={node=t.node,item=t.item,batches=ops,output=t.qty_produced}
        for slot,item in pairs(t.recipe) do
            if item~="minecraft:air" and not (t.tool_slots or {})[slot] then add(out.remaining,item,-ops) end
        end
    end
    for family,pf in pairs(p.tools or {}) do
        local wear,slots=0,0
        for _,t in ipairs(p.tasks) do
            for _,f in pairs(t.tool_slots or {}) do if f==family then
                slots=slots+1;wear=wear+(t.qty_produced/t.recipeOutput)*pf.durabilityPerUse
            end end
        end
        out.tools[family]={durability=pf.durability,wearPerUse=pf.durabilityPerUse,
            wear=wear,stockUnits=#((p.tool_stock or {})[family] or {}),manufactured=out.manufactured[family] or 0,slots=slots}
    end
    if p.blueprint then
        local roots={};for _,r in ipairs(p.blueprint.roots) do roots[r.node]=true end
        for _,id in ipairs(keys(p.blueprint.nodes)) do
            local n=p.blueprint.nodes[id]
            local parts={}
            for _,slot in ipairs(keys(n.recipe)) do parts[#parts+1]=slot.."="..n.recipe[slot] end
            local policy
            if roots[id] then policy="Requested output: manufacture new"
            elseif not n.recipe then policy=n.useStock and "External input: use stock; report any shortage" or "External input: stock not permitted"
            else policy=n.useStock and "Use stock first; manufacture shortage" or "Manufacture; do not borrow stock" end
            out.routes[#out.routes+1]={node=id,item=n.item,policy=policy,
                recipe=n.recipe and table.concat(parts,", ") or "External input only",
                output=n.recipeOutput,stock=(p.stock_nodes or {})[id] or 0}
        end
    end
    return out
end
function preview.lines(plan)
    local d,err=preview.describe(plan);if not d then return nil,err end
    local lines={"Recorded plan; viewing does not recalculate costs."}
    for _,item in ipairs(keys(d.requested)) do
        local left=d.remaining[item] or 0
        lines[#lines+1]=item..": requested "..d.requested[item]..", manufactured "..(d.manufactured[item] or 0)..
            ", remaining before tool wear "..left..", surplus "..math.max(0,left-d.requested[item])
    end
    lines[#lines+1]="Withdrawals (ordinary ingredients):"
    for _,item in ipairs(keys(d.withdrawals)) do lines[#lines+1]="  "..d.withdrawals[item].." x "..item end
    lines[#lines+1]="Manufacturing order (rounded batches):"
    for i,t in ipairs(d.operations) do lines[#lines+1]=i..": "..t.batches.." batches -> "..t.output.." x "..t.item..(t.node and " ["..t.node.."]" or "") end
    lines[#lines+1]="Captured choices:"
    if not d.captured then lines[#lines+1]="Legacy snapshot: route/stock choices were not captured." end
    for _,r in ipairs(d.routes) do
        lines[#lines+1]="["..r.node.."] "..r.item..": "..r.policy.." (withdraw "..r.stock..")"
        lines[#lines+1]="  "..r.recipe..(r.output and " -> "..r.output or "")
    end
    for _,family in ipairs(keys(d.tools)) do
        local t=d.tools[family]
        lines[#lines+1]="Tool "..family..": durability "..t.durability..", wear/use "..t.wearPerUse..
            ", total wear "..t.wear..", stocked units "..t.stockUnits..", manufactured units "..t.manufactured
    end
    if next(d.tools) then lines[#lines+1]="Tool variants/retained tools change through wear; ordinary-input balances do not predict their final damage." end
    return lines
end
function preview.diff(before,after)
    local a,err=preview.describe(before);if not a then return nil,err end
    local b,why=preview.describe(after);if not b then return nil,why end
    local lines={"Before -> after (candidate only; nothing saved):"}
    for _,field in ipairs({"withdrawals","manufactured","remaining"}) do
        local union={};for k in pairs(a[field]) do union[k]=true end;for k in pairs(b[field]) do union[k]=true end
        for _,item in ipairs(keys(union)) do
            local old,new=a[field][item] or 0,b[field][item] or 0
            if old~=new then lines[#lines+1]=field.." "..item..": "..old.." -> "..new end
        end
    end
    local function routes(d) local r={};for _,n in ipairs(d.routes) do r[n.node]=n.item.." | "..n.policy.." | "..n.recipe.." | "..tostring(n.output) end;return r end
    local old,new=routes(a),routes(b);local all={};for id in pairs(old) do all[id]=true end;for id in pairs(new) do all[id]=true end
    for _,id in ipairs(keys(all)) do if old[id]~=new[id] then lines[#lines+1]="Route ["..id.."]: "..(old[id] or "absent").." -> "..(new[id] or "absent") end end
    local allTools={};for f in pairs(a.tools) do allTools[f]=true end;for f in pairs(b.tools) do allTools[f]=true end
    for _,f in ipairs(keys(allTools)) do
        local x,y=a.tools[f] or {},b.tools[f] or {}
        for _,key in ipairs({"durability","wearPerUse","wear","stockUnits","manufactured"}) do
            if x[key]~=y[key] then lines[#lines+1]="Tool "..f.." "..key..": "..tostring(x[key]).." -> "..tostring(y[key]) end
        end
    end
    if #lines==1 then lines[#lines+1]="No execution-cost or route differences." end
    return lines
end
return preview
