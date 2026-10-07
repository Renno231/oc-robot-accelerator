local warehouse=require("warehouse")
local serialization=require("serialization")
local args={...};local command=table.remove(args,1)
local function decode(s) return assert(serialization.unserialize(assert(s,"serialized table required")),"invalid table") end
local function item() return args[1]:sub(1,1)=="{" and decode(args[1]) or {name=args[1],damage=tonumber(args[4]) or 0} end
local function endpoint(s) return s:sub(1,1)=="{" and decode(s) or s end
local value,err
if command=="add" then value=warehouse.add(args[1],args[2] and decode(args[2]))
elseif command=="remove" then value=warehouse.remove(args[1])
elseif command=="members" then value=warehouse.members()
elseif command=="group" then value=warehouse.group(args[1],args[2],decode(args[3]))
elseif command=="ungroup" then value=warehouse.ungroup(args[1])
elseif command=="groups" then value=warehouse.groups(args[1])
elseif command=="scan" then value=warehouse.scan(#args>0 and args or nil)
elseif command=="find" or command=="count" then value=warehouse[command](args[1]:sub(1,1)=="{" and decode(args[1]) or {name=args[1],damage=tonumber(args[2]) or 0,label=args[3]})
elseif command=="contents" then value=warehouse.contents(args[1])
elseif command=="fetch" or command=="store" then value,err=warehouse[command](item(),tonumber(args[2]),endpoint(args[3]),args[5] and decode(args[5]))
else error("warehouse add storage [settings-table]|remove storage|members|group name type roles-table|ungroup name|groups [type]|scan [storages...]|find/count item [damage [label]]|contents storage|fetch/store item count endpoint [damage [options-table]]") end
if err then io.stderr:write(err,"\n") else print(serialization.serialize(value)) end
