local shell=require "shell"
local mes=require "mes"
local args,flags=shell.parse(...)
local opts={crafter=flags.crafter,machines={},onStage=function(stage,index)
  print("Stage "..index..": "..stage.kind)
end}
if flags.machines then
  for mapping in flags.machines:gmatch("[^;]+") do
    local kind,list=mapping:match("^([^:]+):(.+)$")
    if not kind then io.stderr:write("Invalid --machines mapping\n");return 1 end
    local groups={};for name in list:gmatch("[^,]+") do groups[#groups+1]=name end
    opts.machines[kind]=groups
  end
end
local command=args[1]
local function fail(err) io.stderr:write(tostring(err).."\n");return 1 end
if command=="start" then
  local ok,err=mes.start()
  if not ok then return fail(err) end
  print("MES service started");return 0
end
if command=="recipe" then
  local recipes=require("recipes")
  local sub=args[2]
  if sub=="list" then
    if not args[3] then return fail("Item required") end
    local entries,err=recipes.list(args[3]);if not entries then return fail(err) end
    for i,r in ipairs(entries) do
      print(i.." "..r.kind.." "..tostring(r.machineType or "").." "..r.source)
      for _,v in ipairs(r.inputs or {}) do print("  in "..v.item.." x"..v.qty) end
      for _,v in ipairs(r.outputs or {}) do print("  out "..v.item.." x"..v.qty) end
    end
    return 0
  elseif sub=="remove" then
    local n=tonumber(args[4])
    if not args[3] or not n or n<1 or n%1~=0 then return fail("Item and positive recipe index required") end
    local ok,err=recipes.remove(args[3],n);if not ok then return fail(err) end;return 0
  elseif sub=="import" then
    if flags.kind~="processing" and flags.kind~="crafting" then return fail("--kind=processing|crafting required") end
    if flags.kind=="processing" and not flags.type then return fail("--type required for processing") end
    if flags.storage and (flags.side or flags.transposer) then return fail("Choose storage or transposer source, not both") end
    local slots,size
    if flags.storage then
      local wh=require("warehouse");local logistics=require("logistics");local event=require("event")
      local ids,err=wh.scan(flags.storage);if not ids then return fail(err) end
      if #ids~=1 then return fail("Storage scan must return one read job") end
      local listing,inventorySize
      for _,id in ipairs(ids) do
        while true do
          local s=logistics.status(id);if not s then return fail("Missing scan job") end
          local terminal=s.state=="done" or s.state=="partial" or s.state=="failed"
          if terminal and wh.settled(id) then
            if s.state~="done" then return fail(s.reason or ("Scan "..s.state)) end
            for _,step in ipairs(s.steps or {}) do
              if step.listing and step.size then listing=step.listing;inventorySize=step.size end
            end
            if not listing then return fail("Scan returned no inventory listing") end
            break
          end
          event.pull()
        end
      end
      slots,size=recipes.slotsFromListing(listing,inventorySize)
    else
      local side=tonumber(flags.side)
      if not side or side%1~=0 or side<0 or side>5 then return fail("--side must be 0..5") end
      local addr=flags.transposer
      if not addr then
        local choices,err=recipes.transposerInventories();if not choices then return fail(err) end
        for _,v in ipairs(choices) do if v.side==side then
          if addr and addr~=v.address then return fail("Multiple transposers: specify --transposer") end
          addr=v.address
        end end
        if not addr then return fail("No transposer inventory on that side") end
      end
      slots,size=recipes.readSlots{transposer=addr,side=side}
    end
    if not slots then return fail(size) end
    local draft,err=recipes.recipeFromSlots(flags.kind,slots,size,flags.type);if not draft then return fail(err) end
    local ok,why=recipes.save(draft);if not ok then return fail(why) end
    print("Recipe imported");return 0
  end
  return fail("mes recipe import --side=N [--transposer=ADDR] | --storage=NAME --kind=processing|crafting [--type=TYPE]; list ITEM; remove ITEM N")
end
if command=="crafters" or command=="types" then
  local entries=mes[command]()
  local names={};for name in pairs(entries) do names[#names+1]=name end;table.sort(names)
  for _,name in ipairs(names) do
    local v=entries[name];print(name..(v.robot and (" "..v.robot.." "..tostring(v.buffer)) or ""))
  end
  return 0
end
local plan,err
if command=="craft" then plan,err=mes.plan(args[2],tonumber(args[3]),opts)
elseif command=="run" then plan=args[2]
elseif command and command:find(":",1,true) then plan,err=mes.plan(command,tonumber(args[2]) or 1,opts)
else print("mes start | craft ITEM QTY [--crafter=NAME] [--machines=TYPE:GROUP,GROUP] | run PLAN | crafters | types | recipe import|list|remove");return 1 end
if not plan then io.stderr:write(tostring(err or "Plan required").."\n");return 1 end
local id,why=mes.run(plan,opts)
if not id then return fail(why) end
local result,waitError=mes.wait(id)
if not result then return fail(waitError) end
print(result.status)
if result.reason or result.error then io.stderr:write((result.reason or result.error).."\n") end
return result.status=="complete" and 0 or 1
