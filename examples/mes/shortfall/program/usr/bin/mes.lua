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
else print("mes craft ITEM QTY [--crafter=NAME] [--machines=TYPE:GROUP,GROUP] | run PLAN | crafters | types");return 1 end
if not plan then io.stderr:write(tostring(err or "Plan required").."\n");return 1 end
local result,why=mes.run(plan,opts)
if not result then io.stderr:write(tostring(why).."\n");return 1 end
print(result.status)
if result.error then io.stderr:write(result.error.."\n") end
return result.status=="complete" and 0 or 1
