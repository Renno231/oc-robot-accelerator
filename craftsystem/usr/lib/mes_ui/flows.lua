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

---------------------------------------------------------------- stations
-- A storage or a row by coordinates: stations.add builds the nodes, links
-- and names, then checks them asynchronously. Face, direction and count
-- start unset and are required; coordinates reuse the last station's.
local faces={"top","bottom","north","south","west","east"}
local opposite={top="bottom",bottom="top",north="south",south="north",west="east",east="west"}
local last={}
local function freeName(st,prefix)
  local used={};for _,n in ipairs(map.storageNames()) do used[n]=true end
  for _,r in ipairs(st.list()) do used[r.name]=true end
  local n=1;while used[prefix..n] or map.node(prefix..n) do n=n+1 end;return prefix..n
end
-- help: a dim first line; with no current value the cursor rests on it, so
-- nothing is picked until the user moves to an option.
local function choose(title,values,cur,done,text,help)
  local rows,at={},nil;if help then rows[1]={text=help,fg=ui.P.dim,locked=true};at=1 end
  for _,v in ipairs(values) do rows[#rows+1]={text=(v==cur and "● " or "  ")..(text and text(v) or tostring(v)),value=v};if v==cur then at=#rows end end
  ui.pick(title,rows,done,{nofilter=true,at=at})
end
function F.addStation(kind,done)
  local st=require("stations");local row=kind=="row"
  local s={x=last.x,y=last.y,z=last.z,role="stock"}
  if row then s.spacing=1;s.pair=1;s.prefix="stock" else s.name=freeName(st,"stock") end
  local function dirs() local t={};for _,f in ipairs(faces) do if f~=s.face and f~=opposite[s.face] then t[#t+1]=f end end;return t end
  local function need(k,tail) return s[k] and tostring(s[k])..(tail or "") or "— required" end
  local function warn(k) return function() return not s[k] and ui.P.warn or nil end end
  local function coord(k,label) return {label=label,show=function() return need(k) end,colour=warn(k),edit=function(r)
      ui.prompt(label,label.." (block coordinate)",s[k],function(v) s[k]=v;r() end,{integer=true}) end} end
  local w=row and " of the first block" or ""
  local fields={coord("x","X"..w),coord("y","Y"..w),coord("z","Z"..w),
    {label="Face",show=function() return need("face","  (the face the drone reaches)") end,colour=warn("face"),edit=function(r)
      choose("Face the drone reaches",faces,s.face,function(v) s.face=v
        if row and (s.rowDir==v or s.rowDir==opposite[v]) then s.rowDir=nil end;r() end,nil,"Use a side face for chest walls; top blocks stacking.") end}}
  if row then
    fields[#fields+1]={label="Direction",show=function() return need("rowDir","  (the row runs this way)") end,colour=warn("rowDir"),edit=function(r)
      choose("Direction the row runs",dirs(),s.rowDir,function(v) s.rowDir=v;r() end,nil,"The row runs this way from the first block.") end}
    fields[#fields+1]={label="Count",show=function() return need("count"," blocks") end,colour=warn("count"),edit=function(r)
      ui.prompt("Count","Blocks in the row (1..64)",s.count,function(v) s.count=v;r() end,{integer=true,min=1,check=function(v) if v>64 then return nil,"64 at most" end;return true end}) end}
    fields[#fields+1]={label="Spacing",show=function() return s.spacing==1 and "1  (adjacent blocks)" or "2  (every other block)" end,edit=function(r)
      choose("Spacing",{1,2},s.spacing,function(v) s.spacing=v;r() end,function(v) return v==1 and "1: adjacent blocks" or "2: every other block" end) end}
    fields[#fields+1]={label="Pair",show=function() return s.pair.."  · adjacent vanilla chests merge into double chests: use pair 2" end,edit=function(r)
      choose("Pair: blocks per inventory",{1,2},s.pair,function(v) s.pair=v;r() end,function(v) return v==1 and "1: one inventory per block" or "2: double chests, two blocks per inventory" end) end}
  end
  local nk=row and "prefix" or "name"
  fields[#fields+1]={label=row and "Prefix" or "Name",show=function() return s[nk]..(row and "  ("..s.prefix.."1.."..s.prefix..(s.count or "N")..")" or "") end,edit=function(r)
    ui.prompt(row and "Prefix" or "Name",row and "Name prefix: members are prefix1, prefix2, …" or "Storage name",s[nk],function(v) s[nk]=v;r() end) end}
  fields[#fields+1]={label="Role",show=function() return s.role=="stock" and "stock  (count and use its contents)" or "other  (a buffer or machine face)" end,edit=function(r)
    choose("Role",{"stock","other"},s.role,function(v) s.role=v;r() end,function(v) return v=="stock" and "stock: count and use its contents" or "other: a buffer, machine face or other storage" end) end}
  ui.form(row and "Add a row of storages" or "Add a storage",fields,row and "Add row" or "Add storage",function(close)
    local miss=not s.face and "pick the side drones use" or row and (not s.rowDir and "pick the row direction" or not s.count and "enter how many chests")
    if miss then ui.fail(miss);return end
    local name,err=st.add(kind,s)
    -- stations asserts: OC prefixes "file:line: " to the message.
    if not name then ui.fail((tostring(err):gsub("^[^:]+:%d+: ","")));return end
    last.x,last.y,last.z=s.x,s.y,s.z;close();ui.ok(name..": checking; it updates when done")
    if done then done(name) end
  end,96)
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
