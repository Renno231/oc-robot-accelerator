-- Picker flows shared by the tabs: build the chain node → storage →
-- machine/crafter → type by choosing, typing only names and numbers.
local ui=require("mes_ui.core");local map=require("map");local wh=require("warehouse")
local F={}
local function mes() return require("mes") end

-- storage -> "group.role" for every storage used by a machine or crafter.
function F.roleOf()
  local used={};for name,g in pairs(wh.groups()) do for role,s in pairs(g.roles) do used[s]=name.."."..role end end
  return used
end

-- Pick a storage. opts.free: hide storages already in a group role;
-- opts.add: offer "+ Add storage…" (prefilled with opts.add as the name).
function F.pickStorage(title,opts,done)
  local used=F.roleOf();local members=wh.members();local rows={}
  if opts.add then rows[1]={text="+ Add storage…",value=false,fg=ui.P.accent,keep=true} end
  -- Machine faces, buffers and loose chests first: fetch targets and role
  -- assignments are rarely stock storages.
  for pass=1,2 do
    for _,s in ipairs(map.storageNames()) do
      if not (opts.free and used[s]) and (members[s]~=nil)==(pass==2) then
        local e=map.storage(s);local tag=used[s] or (members[s] and "stock") or ""
        rows[#rows+1]={text=ui.fit(s,16).." "..ui.fit(e.node.." "..ui.sideGlyph[e.side],14).." "..tag,value=s,fg=used[s] and ui.P.dim or nil}
      end
    end
  end
  ui.pick(title,rows,function(s)
    if s then done(s) else F.addStorage(opts.add~=true and opts.add or nil,done) end
  end)
end

-- Node, then face on a compass cross, then name, then stock membership.
function F.addStorage(prefill,done)
  local rows={}
  for _,n in ipairs(map.names()) do
    local e=map.node(n);local k=0;for _ in pairs(e.faces) do k=k+1 end
    rows[#rows+1]={text=ui.fit(n,14).." ("..e.x..", "..e.y..", "..e.z..")"..(e.charger and "  charger" or "")..(k>0 and "  "..k.." named" or ""),value=n}
  end
  ui.pick("Add storage · 1/3 pick the node next to it",rows,function(node)
    F.pickFace(node,function(side)
      ui.prompt("Add storage · 3/3","Name for the "..ui.sides[side].." face of "..node,prefill or "",function(name)
        local s=ui.try(map.name,name,node,side);if not s then return end
        map.save()
        ui.pick("Stock?",{{text="Is "..name.." part of stock?",locked=true},{text="  No: a machine, buffer or other storage",value=false},{text="  Yes: count and use its contents",value=true}},function(member)
          -- A new inventory may already hold items: read it once.
          if member and ui.try(wh.add,name) then ui.try(wh.scan,name) end
          ui.ok("Storage "..name.." added"..(member and " to stock" or ""))
          if done then done(name) end
        end,{nofilter=true})
      end,{check=function(v) if map.storage(v) or map.node(v) then return nil,"name already used" end;return true end})
    end)
  end)
end

-- Faces laid out as seen from above: N/S/W/E around the node, Up/Down to
-- the right. Arrow keys move spatially through qmenu bindings.
function F.pickFace(node,done)
  local named={};for s,e in pairs(map.storages()) do if e.node==node then named[e.side]=s end end
  local e=map.node(node)
  ui.modal({title="Add storage · 2/3 which face of "..node,w=54,h=11,build=function(m)
    local cw=14;local cx=m.ix+math.floor((m.iw-cw*3-2)/2)
    local place={[2]={cx+cw+1,m.iy+1},[4]={cx,m.iy+3},[5]={cx+2*cw+2,m.iy+3},[3]={cx+cw+1,m.iy+5},[1]={cx+2*cw+2,m.iy+1},[0]={cx+2*cw+2,m.iy+5}}
    local label={[0]="Down","Up","North","South","West","East"}
    local keys=ui.keys
    for side=0,5 do
      local p=place[side];local text=label[side]..": "..(named[side] or "—")
      local o=ui.decorate(m.menu:addOption("f"..side,p[1],p[2],ui.fit(text,cw)),ui.P.bg)
      if named[side] then ui.style(o,ui.P.dim) end
      o:onActivate(function()
        if named[side] then ui.fail(label[side].." is already "..named[side]);return end
        ui.close(m);done(side)
      end)
    end
    local function bind(a,key,b) m.menu:getOption("f"..a):bind(key,"f"..b) end
    bind(2,keys.down,3);bind(2,keys.left,4);bind(2,keys.right,1)
    bind(3,keys.up,2);bind(3,keys.left,4);bind(3,keys.right,0)
    bind(4,keys.right,5);bind(4,keys.up,2);bind(4,keys.down,3)
    bind(5,keys.left,4);bind(5,keys.up,1);bind(5,keys.down,0)
    bind(1,keys.left,2);bind(1,keys.down,5)
    bind(0,keys.left,3);bind(0,keys.up,5)
    -- First free face, else North.
    for _,side in ipairs({2,3,4,5,1,0}) do if not named[side] then m.menu:setSelected("f"..side);break end end
    m.paint=function()
      ui.text(cx+cw+1,m.iy+3,ui.fit("  ◆ "..e.x..","..e.y..","..e.z,cw),ui.P.accent,ui.P.box)
      ui.text(m.ix,m.iy+7,ui.fit("arrows move · Enter picks · ⌫ back",m.iw),ui.P.dim,ui.P.box)
    end
    m.key=function(_,code) if code==keys.back then ui.close(m);return true end end
  end})
end

-- Item from stock, or typed as mod:name[:damage].
function F.pickItem(title,done)
  local rows={{text="Type an item ID…",value=false,fg=ui.P.accent,keep=true}}
  for _,e in ipairs(wh.totals()) do rows[#rows+1]={text=ui.fit(ui.label(e.item),28).." "..ui.id(e.item),value=e.item} end
  ui.pick(title,rows,function(i)
    if i then done(i) else ui.prompt(title,"Item ID (mod:name or mod:name:damage)","",function(v) done(ui.item(v)) end,
      {check=function(v) if v:match("^[^:]+:[^:]+$") or v:match("^[^:]+:[^:]+:%d+$") then return true end;return nil,"use mod:name or mod:name:damage" end}) end
  end)
end

---------------------------------------------------------------- machine types
function F.editType(name,def,done)
  def=def or {roles={"input","output"},inputs={"input"},output="output",batch=64,seconds=10}
  local fields
  local function list(t) return table.concat(t,", ") end
  fields={
    {label="Name",show=function() return name or "—" end,edit=function(r) ui.prompt("Machine type","Type name (e.g. furnace)",name or "",function(v) name=v;r() end) end},
    {label="Roles",show=function() return list(def.roles) end,edit=function(r)
      ui.prompt("Roles","Faces it has, in order, comma separated",list(def.roles),function(v)
        local roles={};for s in v:gmatch("[^,%s]+") do roles[#roles+1]=s end
        def.roles=roles;local keep={};for _,x in ipairs(def.inputs) do for _,y in ipairs(roles) do if x==y then keep[#keep+1]=x end end end
        def.inputs=#keep>0 and keep or {roles[1]}
        local has=false;for _,y in ipairs(roles) do if y==def.output then has=true end end
        if not has then def.output=roles[#roles] end
        if def.fuel then local f=false;for _,y in ipairs(roles) do if y==def.fuel.role then f=true end end;if not f then def.fuel=nil end end
        r()
      end) end},
    {label="Inputs go to",show=function() return list(def.inputs) end,edit=function(r)
      local rows,chosen={},{};for _,x in ipairs(def.roles) do rows[#rows+1]={text=x,value=x} end
      for _,x in ipairs(def.inputs) do chosen[x]=true end
      ui.checklist("Roles that receive ingredients (in recipe slot order)",rows,chosen,function(c)
        local out={};for _,x in ipairs(def.roles) do if c[x] then out[#out+1]=x end end
        if #out==0 then ui.fail("pick at least one input role") else def.inputs=out end;r()
      end) end},
    {label="Output from",show=function() return def.output or "—" end,edit=function(r)
      local rows={};for _,x in ipairs(def.roles) do rows[#rows+1]={text=x,value=x} end
      ui.pick("Role the product comes out of",rows,function(v) def.output=v;r() end) end},
    {label="Fuel",show=function() local f=def.fuel;return f and (ui.label(f.item).." into "..f.role..", 1 per "..f.per.." items") or "none" end,edit=function(r)
      ui.pick("Fuel",{{text="No fuel",value=false},{text="Uses fuel…",value=true}},function(v)
        if not v then def.fuel=nil;r();return end
        local rows={};for _,x in ipairs(def.roles) do rows[#rows+1]={text=x,value=x} end
        ui.pick("Role fuel goes into",rows,function(role)
          F.pickItem("Fuel item",function(i)
            ui.prompt("Fuel","Items processed per fuel item",def.fuel and def.fuel.per or 8,function(per)
              def.fuel={role=role,item=ui.id(i),per=per};r()
            end,{integer=true,min=1})
          end)
        end)
      end,{nofilter=true}) end},
    {label="Batch",show=function() return def.batch.." input items per load" end,edit=function(r)
      ui.prompt("Batch","Most input items loaded at once",def.batch,function(v) def.batch=v;r() end,{integer=true,min=1}) end},
    {label="Time",show=function() return def.seconds.." s per output" end,edit=function(r)
      ui.prompt("Time","Seconds per output (for the wait deadline)",def.seconds,function(v) def.seconds=v;r() end,{number=true,min=0}) end},
  }
  ui.form(name and ("Machine type "..name) or "New machine type",fields,"Save type",function(close)
    if not name then ui.fail("give the type a name");return end
    if ui.try(mes().setType,name,def) then close();ui.ok("Saved machine type "..name);if done then done(name) end end
  end)
end

---------------------------------------------------------------- machines
-- Type, name, then one storage per role; "add storage…" works inline.
function F.newMachine(kind)
  local types=mes().types()
  local function named(kind)
    local def=types[kind];local n=0;for _ in pairs(wh.groups(kind)) do n=n+1 end
    ui.prompt("New "..kind,"Machine name",kind..string.char(65+n),function(name)
      F.assignRoles(name,kind,def,{},1)
    end,{check=function(v) if wh.groups()[v] then return nil,"name already used" end;return true end})
  end
  if kind then return named(kind) end
  local rows={{text="+ New machine type…",value=false,fg=ui.P.accent}}
  for k,d in pairs(types) do rows[#rows+1]={text=ui.fit(k,14).." "..table.concat(d.roles,", "),value=k} end
  ui.pick("New machine · type",rows,function(k)
    if k then named(k) else F.editType(nil,nil,function(n) types=mes().types();named(n) end) end
  end)
end
function F.assignRoles(name,kind,def,roles,k)
  local role=def.roles[k]
  if not role then
    if ui.try(wh.group,name,kind,roles) then
      local faces={};for _,s in pairs(roles) do faces[#faces+1]=s end
      ui.try(wh.scan,faces)
      ui.ok("Machine "..name.." ready: "..#def.roles.." faces")
    end
    return
  end
  F.pickStorage(name.." · "..role.." ("..k.."/"..#def.roles..")",{free=true,add=name.."."..role},function(s)
    roles[role]=s;F.assignRoles(name,kind,def,roles,k+1)
  end)
end

---------------------------------------------------------------- crafters
function F.newCrafter()
  ui.busy("Looking for crafting robots…")
  local robots=ui.try(mes().robots,3) or {}
  local taken={};for _,c in pairs(mes().crafters()) do taken[c.robot]=true end
  local rows={{text="Enter an address…",value=false,fg=ui.P.accent,keep=true}}
  for _,r in ipairs(robots) do
    rows[#rows+1]={text=r.address:sub(1,8).."…  "..(r.busy and "busy" or "idle")..(taken[r.address] and "  (already a crafter)" or ""),value=r.address,locked=taken[r.address] or nil}
  end
  local function named(addr)
    local n=0;for _ in pairs(mes().crafters()) do n=n+1 end
    ui.prompt("New crafter","Crafter name","cpu"..(n+1),function(name)
      F.pickStorage(name.." · buffer chest in front of the robot",{free=true,add=name..".buf"},function(buf)
        if ui.try(mes().setCrafter,name,{robot=addr,buffer=buf}) then ui.try(wh.scan,buf);ui.ok("Crafter "..name.." ready: robot "..addr:sub(1,8).."…, buffer "..buf) end
      end)
    end)
  end
  ui.pick("New crafter · robot ("..#robots.." found)",rows,function(addr)
    if addr then named(addr) else ui.prompt("New crafter","Robot modem address","",named) end
  end)
end

---------------------------------------------------------------- stock membership
function F.membership(storage)
  local m=wh.members()[storage];local member=m~=nil;local was=member;m=m or {}
  local filter=m.filter or {};local priority=m.priority
  ui.form("Stock settings · "..storage,{
    {label="In stock",show=function() return member and "yes" or "no" end,edit=function(r) member=not member;r() end},
    {label="Priority",show=function() return priority and tostring(priority) or "unset" end,edit=function(r)
      ui.prompt("Priority","Higher fills first; blank = unset",priority,function(v) priority=v or nil;r() end,{number=true,optional=true}) end},
    {label="Filter",show=function() if #filter==0 then return "any item" end;local t={};for _,i in ipairs(filter) do t[#t+1]=ui.label(i) end;return table.concat(t,", ") end,edit=function(r)
      ui.pick("Filter",{{text="Add an item…",value="add"},{text="Clear filter",value="clear"}},function(v)
        if v=="clear" then filter={};r() else F.pickItem("Filter item",function(i) filter[#filter+1]={name=i.name,damage=i.damage or 0};r() end) end
      end,{nofilter=true}) end},
  },"Save",function(close)
    local ok
    if member then ok=ui.try(wh.add,storage,{priority=priority,filter=#filter>0 and filter or nil}) else ok=ui.try(wh.remove,storage)~=nil end
    if ok and member and not was then ui.try(wh.scan,storage) end
    if ok then close();ui.ok(storage..(member and " is in stock" or " is not stock")) end
  end)
end
return F
