-- Candidate edits: never save implicitly or modify the supplied snapshot.
local blueprint=require "craft_blueprint"
local identity=require "item_identity"
local edit={}
function edit.recipes(item)
    local db=require "recipes"
    local all,err=db.getAll(item)
    if not all then all,err=db.getAll(item..":0") end
    return all,err
end
local function prune(b)
    local seen,stack={},{}
    for _,r in ipairs(b.roots) do stack[#stack+1]=r.node end
    while #stack>0 do
        local id=table.remove(stack)
        if not seen[id] then seen[id]=true;for _,dep in pairs(b.nodes[id].deps or {}) do stack[#stack+1]=dep end end
    end
    for id in pairs(b.nodes) do if not seen[id] then b.nodes[id]=nil end end
end
local function graft(b,sub,target)
    local translated={};local root=sub.roots[1].node
    local serial=0
    for id in pairs(sub.nodes) do
        if id==root and target then translated[id]=target
        else
            local new
            repeat serial=serial+1;new="edit"..serial until not b.nodes[new]
            b.nodes[new]={};translated[id]=new
        end
    end
    for id,n in pairs(sub.nodes) do
        if n.deps then for slot,dep in pairs(n.deps) do n.deps[slot]=translated[dep] end end
        b.nodes[translated[id]]=n
    end
    for family,p in pairs(sub.tools) do b.tools[family]=p end
    return translated[root]
end
function edit.candidate(plan,change,options,selectChoice)
    local ok,candidate,difference=pcall(function()
        options=options or {}
        local plans=require "craft_plans"
        local original,problem
        if type(plan)=="string" then original,problem=plans.load(plan) else original,problem=plans.prepare(plan) end
        assert(original,problem)
        assert(original.blueprint,"Legacy plan has no captured choices; explicitly recapture a recipe first.")
        assert(type(change)=="table","Missing edit.")
        local b=assert(blueprint.copy(original.blueprint))
        local node=assert(b.nodes[change.node],"Unknown captured branch.")
        local inv=plans.inventory(options)
        if change.kind=="stock" then
            assert(type(change.useStock)=="boolean","Stock policy must be boolean.");node.useStock=change.useStock
        elseif change.kind=="recipe" or change.kind=="material" then
            local planner=require "craftingv4_4"
            local profiles={}
            for family,p in pairs(options.toolProfiles or require("craft_tools").list()) do profiles[family]=p end
            -- Existing branches keep their saved rules. Newly introduced tool
            -- families use the explicitly edited route's current registry.
            for family,p in pairs(b.tools) do profiles[family]=p end
            local target=node.item
            if change.kind=="material" then
                assert(node.recipe and node.recipe[change.slot],"Unknown ingredient slot.")
                local source=(node.ingredient_sources or {})[change.slot]
                assert(source,"Ingredient alternatives were not captured; explicitly replace/recapture this recipe first.")
                assert(type(change.item)=="string" and planner.materialAllowed(source,change.item),"Material is not an allowed ingredient for this slot.")
                target=identity.canonical(change.item)
            else assert(type(change.recipe)=="table" or change.recipe==false,"Select a recipe or external route explicitly.") end
            local family=require("craft_tool_rules").family(target)
            if change.kind=="material" and profiles[family] then target=family end
            local override;if change.kind=="recipe" then override=change.recipe end
            local sub,why=planner.captureChoices(target,inv,profiles,selectChoice,override)
            assert(sub,why)
            if change.kind=="recipe" then
                sub.nodes[sub.roots[1].node].useStock=node.useStock
                graft(b,sub,change.node)
            else
                node.recipe[change.slot]=target;node.deps[change.slot]=graft(b,sub)
                if profiles[family] then
                    local p=profiles[family];b.tools[family]={durability=p.durability,durabilityPerUse=p.durabilityPerUse}
                end
                node.tool_slots=node.tool_slots or {};node.tool_slots[change.slot]=profiles[family] and family or nil
            end
            prune(b)
        else error("Edit kind must be stock, recipe or material.") end
        local result,why=blueprint.calculate(b,inv);assert(result,why)
        if not result.craftable then error("Missing allowed inputs: "..require("serialization").serialize(result.external_needed),0) end
        local fixed=assert(plans.prepare(result))
        assert(require("craft_plan").validateFlow(fixed))
        return fixed,assert(require("craft_preview").diff(original,fixed))
    end)
    if not ok then return nil,tostring(candidate) end
    return candidate,difference
end
return edit
