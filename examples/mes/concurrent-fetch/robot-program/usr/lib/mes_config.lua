-- MES configuration and paired craftServer hosts; resource occupancy belongs to mes.
local M = {}
local path = "/etc/mes.cfg"
local cache
local function copy(t)
  if type(t)~="table" then return t end
  local out={};for k,v in pairs(t) do out[k]=copy(v) end;return out
end
local function text(v) return type(v)=="string" and v:match("%S")~=nil end
local function finite(v) return type(v)=="number" and v==v and math.abs(v)<math.huge end
local function integer(v) return finite(v) and v>0 and v%1==0 end
function M.config(opts)
  if opts and opts.config then assert(type(opts.config)=="table","Config table required");return opts.config end
  if cache then return copy(cache) end
  local f,err=io.open(path,"r")
  if not f then
    if not require("filesystem").exists(path) then cache={machineTypes={},crafters={}};return copy(cache) end
    error(err or "Cannot read /etc/mes.cfg",0)
  end
  local data=f:read("*a");f:close()
  local cfg=require("serialization").unserialize(data)
  assert(type(cfg)=="table","Invalid /etc/mes.cfg")
  cache=cfg;return copy(cfg)
end
local saveSequence=0
local function save(cfg)
  -- Encode first. A failed buffered write must never truncate the durable file.
  local data=require("serialization").serialize(cfg)
  assert(type(data)=="string","Cannot encode /etc/mes.cfg")
  local fs=require("filesystem")
  assert(type(fs.rename)=="function","filesystem.rename required for atomic config saves")
  saveSequence=saveSequence+1
  local temporary=path..".tmp."..saveSequence
  local function cleanup() if fs.remove then pcall(fs.remove,temporary) end end
  local opened,f,openErr=pcall(io.open,temporary,"w")
  if not opened or not f then cleanup();error(openErr or f or "Cannot write temporary /etc/mes.cfg",0) end
  local written,ok,writeErr=pcall(f.write,f,data)
  local flushed,flushOK,flushErr=true,true,nil
  if written and ok and f.flush then flushed,flushOK,flushErr=pcall(f.flush,f) end
  -- OpenOS close ignores flush failure: check explicit flush before rename.
  local closed,closeOK,closeErr=pcall(f.close,f)
  local failure
  if not written or not ok then failure=writeErr or ok or "Cannot write /etc/mes.cfg"
  elseif not flushed or not flushOK then failure=flushErr or flushOK or "Cannot flush /etc/mes.cfg"
  elseif not closed or closeOK==false or closeErr then failure=closeErr or closeOK or "Cannot close /etc/mes.cfg" end
  if failure then cleanup();error(tostring(failure),0) end
  local renamed,renameOK,renameErr=pcall(fs.rename,temporary,path)
  if not renamed or not renameOK then cleanup();error(tostring(renameErr or renameOK or "Cannot rename /etc/mes.cfg"),0) end
  cache=cfg
end
local function persist(cfg,opts)
  if not (opts and opts.config) then save(cfg) end
  require("event").push("mes","changed")
  return true
end
function M.types(opts) return copy(M.config(opts).machineTypes or {}) end
function M.crafters(opts) return copy(M.config(opts).crafters or {}) end
local function list(t,what)
  assert(type(t)=="table" and #t>0,what.." required")
  local seen,n={},0
  for k,v in pairs(t) do
    assert(integer(k) and k<=#t and text(v) and not seen[v],"Invalid "..what)
    seen[v]=true;n=n+1
  end
  assert(n==#t,"Sparse "..what)
  return seen
end
local function definition(def)
  assert(type(def)=="table","Type definition required")
  local d=copy(def);list(d.inputs,"input roles");assert(text(d.output),"Output role required")
  assert(integer(d.batch),"Batch must be a positive integer")
  assert(d.seconds==nil or finite(d.seconds) and d.seconds>=0,"Seconds must be finite and non-negative")
  assert(type(d.blocking)=="boolean","Blocking is required and must be boolean")
  if d.fuel~=nil then
    assert(type(d.fuel)=="table" and text(d.fuel.role),"Fuel role required")
    local id=d.fuel.item
    assert(type(id)=="string" and (id:match("^[^:%s]+:[^:%s]+$") or id:match("^[^:%s]+:[^:%s]+:%d+$")) and
      not id:find("*",1,true) and id:sub(1,4)~="ore:" and id~="minecraft:air","Concrete fuel item required")
    assert(finite(d.fuel.per) and d.fuel.per>0,"Fuel per must be positive and finite")
  end
  if d.roles==nil then
    d.roles={};local seen={}
    local function add(r) if not seen[r] then seen[r]=true;d.roles[#d.roles+1]=r end end
    for _,r in ipairs(d.inputs) do add(r) end
    if d.fuel then add(d.fuel.role) end;add(d.output)
  end
  local roles=list(d.roles,"roles")
  for _,r in ipairs(d.inputs) do assert(roles[r],"Input role absent from roles: "..r) end
  assert(roles[d.output],"Output role absent from roles")
  if d.fuel then assert(roles[d.fuel.role],"Fuel role absent from roles") end
  assert(type(d.roleSlots)=="table","Role slots are required")
  for role in pairs(d.roleSlots) do assert(roles[role],"Unknown role slots: "..tostring(role)) end
  for _,role in ipairs(d.roles) do
    local slots=d.roleSlots[role]
    assert(type(slots)=="table" and #slots>0,"Non-empty slot list required for role: "..role)
    local seen,n={},0
    for k,slot in pairs(slots) do
      assert(integer(k) and k<=#slots and integer(slot) and not seen[slot],"Invalid slot list for role: "..role)
      seen[slot]=true;n=n+1
    end
    assert(n==#slots,"Sparse slot list for role: "..role)
  end
  return d
end
function M.setType(name,def,opts)
  local ok,d=pcall(function()
    assert(text(name),"Type name required");return definition(def)
  end)
  if not ok then return nil,tostring(d) end
  local cfg=M.config(opts)
  cfg.machineTypes=cfg.machineTypes or {};cfg.machineTypes[name]=d
  return persist(cfg,opts)
end
function M.removeType(name,opts)
  assert(text(name),"Type name required");local cfg=M.config(opts)
  if cfg.machineTypes then cfg.machineTypes[name]=nil end
  return persist(cfg,opts)
end
function M.setCrafter(name,c,opts)
  assert(text(name),"Crafter name required")
  assert(type(c)=="table" and text(c.robot) and text(c.buffer),"Robot and buffer required")
  local host=require("hosts").getHost(c.robot)
  assert(host and host:getKeys().service=="craftServer" and text(host:getWakeKey()),"Crafting robot is not paired")
  local cfg=M.config(opts);local wh=require("warehouse")
  local old=wh.groups()[name]
  assert(not old or old.type=="crafter","Group name is already used by a machine")
  assert(wh.group(name,"crafter",{buffer=c.buffer}),"Cannot register crafter group")
  cfg.crafters=cfg.crafters or {};cfg.crafters[name]={robot=host:getAddress(),buffer=c.buffer}
  return persist(cfg,opts)
end
function M.removeCrafter(name,opts)
  assert(text(name),"Crafter name required");local cfg=M.config(opts);local wh=require("warehouse")
  local old=wh.groups()[name]
  assert(not old or old.type=="crafter","Group name is already used by a machine")
  wh.ungroup(name);if cfg.crafters then cfg.crafters[name]=nil end
  return persist(cfg,opts)
end
function M.robots(timeout)
  timeout=timeout==nil and 3 or timeout
  assert(finite(timeout) and timeout>=0,"Timeout must be finite and non-negative")
  local ok,result=pcall(function()
    local out={}
    for _,host in ipairs(require("hosts").getAll()) do
      if host:getKeys().service=="craftServer" and text(host:getWakeKey()) then
        local status=require("craft_client").status(host:getAddress(),{connectTimeout=timeout})
        out[#out+1]={address=host:getAddress(),name=host:getName(),busy=status and status.busy}
      end
    end
    table.sort(out,function(a,b) return a.address<b.address end)
    return out
  end)
  if not ok then return nil,tostring(result) end
  return result
end
local pending,H,D,E={}
local function key() return string.format("%06x%06x",math.random(0,0xffffff),math.random(0,0xffffff)) end
local function welcome(a,h)
  if not H.localhost() then H.addHost(D.address,require("computer").address(),nil,key(),{},true) end
  local c=H.localhost()
  D.send(a,27105,"mes_robot_welcome",require("serialization").serialize({name=h:getName(),wake=h:getWakeKey(),
    controller={address=c:getAddress(),cid=c:getCID(),name=c:getName()}}))
end
function M.installRobots()
  if H then return end
  H,D,E=require("hosts"),require("component").modem,require("event")
  D.open(27105)
  E.listen("modem_message",function(_,_,a,p,_,kind,cid)
    if p~=27105 then return end
    local h=H.getHost(a);local paired=h and h:getKeys().service=="craftServer" and text(h:getWakeKey())
    if kind=="mes_robot_hello" then
      if paired then welcome(a,h)
      elseif not pending[a] then pending[a]=cid;E.push("mes_robot_announce",a) end
    elseif kind=="mes_robot_boot" and paired then require("craft_client").reboot(a) end
  end)
end
function M.pendingRobots()
  local out={};for a in pairs(pending) do out[#out+1]={address=a} end;return out
end
function M.registerRobot(a,n,b)
  local ok,err=pcall(function()
    assert(pending[a],"Robot is not pending")
    local cfg,wh=M.config(),require("warehouse")
    assert(type(n)=="string" and #n<=48 and n:match("^[%w_-]+$") and not H.getHost(n)
      and not (cfg.crafters or {})[n],"Invalid or used name")
    local members,groups=wh.members(),wh.groups();local g=groups[n]
    assert(not g or g.type=="crafter","Group name is used")
    assert(require("map").storage(b),"Unknown buffer")
    local inventory=(members[b] or {}).inventory or b;local grouped
    for _,v in pairs(groups) do for _,s in pairs(v.roles) do
      if ((members[s] or {}).inventory or s)==inventory then grouped=true end
    end end
    assert(not members[b] or grouped,"Buffer is stock")
    for _,c in pairs(cfg.crafters or {}) do
      assert(((members[c.buffer] or {}).inventory or c.buffer)~=inventory,"Buffer is used")
    end
    H.addHost(a,pending[a],n,key(),{service="craftServer"},true)
    welcome(a,H.getHost(a));M.setCrafter(n,{robot=a,buffer=b});pending[a]=nil
  end)
  return ok or nil,not ok and tostring(err) or nil
end
return M
