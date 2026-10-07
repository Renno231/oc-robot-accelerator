-- Hardware is loaded only for this explicitly interactive entry point.
local view=require("warehouse.view")
local warehouse=require("warehouse")
local logistics=require("logistics")
local map=require("map")
local M={}
function M.show(options)
  options=options or {}
  local component=require("component");local event=require("event");local keys=require("keyboard").keys
  local computer=require("computer");local tty=require("tty");local qmenu=require("qmenu")
  local gpu=assert(component.gpu,"warehouse UI requires a GPU and /lib/qmenu.lua (1.1.0)")
  local w,h=gpu.getResolution();local viewport={tty.getViewport()};local fg,fp=gpu.getForeground();local bg,bp=gpu.getBackground()
  local running=true;local stack={{kind="items",top=true,tab=1}};local menu;local message,timer;local dirty=true;local lastSignal
  local palette={normal=0xFFFFFF,muted=0x999999,member=0x55CC55,group=0x55CCCC,failed=0xFF5555,partial=0xFFFF55}
  if gpu.getDepth()==1 then for k in pairs(palette) do palette[k]=0xFFFFFF end end
  local function screen() return stack[#stack] end
  local function push(s) s.tab=stack[1].tab;stack[#stack+1]=s;dirty=true end
  local function back() if #stack==1 then running=false else table.remove(stack);dirty=true end end
  local function notify(text)
    message=tostring(text);dirty=true
    if timer then event.cancel(timer) end
    timer=event.timer(4,function() message=nil;dirty=true;computer.pushSignal("warehouse_ui_message") end,1)
  end
  local function snapshot()
    local state={members=warehouse.members(),groups=warehouse.groups(),storages=map.storages(),contents={},jobs=logistics.jobs(true),drones=logistics.drones(),now=computer.uptime()}
    if screen().kind=="job" then
      local id=screen().job;local detail=logistics.status(id)
      if detail then detail.id=id;for n,j in ipairs(state.jobs) do if j.id==id then state.jobs[n]=detail;break end end end
    end
    for name in pairs(state.storages) do state.contents[name]=warehouse.contents(name) end
    return state
  end
  local function guarded(fn)
    local ok,a,b=pcall(fn)
    if not ok then notify(a) elseif a==nil and b then notify(b) end
    dirty=true;return ok and a or nil,b
  end
  local function pick(title,rows,callback)
    push({kind="pick",title=title,rows=rows,choose=callback})
  end
  local function confirm(summary,callback)
    push({kind="confirm",title="Confirm",summary=summary,choose=callback,selected="no"})
  end
  local function input(prompt,default,callback)
    push({kind="input",title="Input",prompt=prompt,default=default and tostring(default) or "",choose=callback,selected="input"})
  end
  local function storages(title,callback,clear)
    local rows=view.storageRows(snapshot())
    if clear then table.insert(rows,1,{key="clear",text="Clear shared inventory",value=false}) end
    for _,r in ipairs(rows) do r.action="choose" end
    pick(title,rows,callback)
  end
  local function items(title,callback,storage)
    local state=snapshot();local rows
    if storage then
      local e=state.contents[storage];rows={}
      for _,v in pairs(e and e.items or {}) do if v.count>0 then rows[#rows+1]={key=view.identity(v.item),text=view.itemText(v),value=v.item,action="choose",count=v.count} end end
      table.sort(rows,function(a,b) if a.count~=b.count then return a.count>b.count end;return a.key<b.key end)
    else rows=view.items(state);for _,r in ipairs(rows) do r.action="choose" end end
    pick(title,rows,callback)
  end
  local function settings(storage,edit)
    local s=assert(warehouse.members()[storage],"not a warehouse member");edit(s);warehouse.add(storage,s);notify("Settings saved")
  end
  local function amount(kind,i,endpoint,available)
    input("Quantity (all allowed)",warehouse.stackSize(i) or 1,function(text)
      local n=text=="all" and available or tonumber(text)
      assert(n and n>0 and n%1==0,"positive quantity or all required")
      confirm(kind.." "..n.." "..i.name.." "..(kind=="fetch" and "to " or "from ")..endpoint,function()
        local id,err=warehouse[kind](i,n,endpoint)
        if not id then notify(err) else notify("Job "..id.." submitted") end
      end)
    end)
  end
  local function storeItem(i,storage)
    local n=0;for _,v in pairs((warehouse.contents(storage) or {}).items or {}) do if view.identity(v.item)==view.identity(i) then n=n+v.count end end
    amount("store",i,storage,n)
  end
  local function typedItem(callback)
    input("Item registry name",nil,function(name)
      assert(name~="","item name required")
      input("Damage",0,function(damage) local n=assert(tonumber(damage),"numeric damage required");assert(n>=0 and n%1==0,"invalid damage");callback({name=name,damage=n}) end)
    end)
  end
  local function editRole(name,role)
    storages("Storage for "..role,function(storage)
      local g=assert(warehouse.groups()[name],"machine no longer exists");g.roles[role]=storage;warehouse.group(name,g.type,g.roles);notify("Role saved")
    end)
  end
  local function newMachine()
    input("Machine name",nil,function(name)
      assert(name~="" and not warehouse.groups()[name],"new machine name required")
      local function withType(kind)
        assert(kind~="","machine type required");local draft={}
        local function roleMenu()
          pick("Roles for "..name,{{key="add",text="Add role",action="choose",value="add"},{key="finish",text="Finish machine",action="choose",value="finish"}},function(choice)
            if choice=="finish" then assert(next(draft),"at least one role required");warehouse.group(name,kind,draft);notify("Machine created")
            else input("Role name",nil,function(role) assert(role~="","role name required");storages("Storage for "..role,function(storage) draft[role]=storage;roleMenu() end) end) end
          end)
        end
        roleMenu()
      end
      local types,seen={},{};for _,g in pairs(warehouse.groups()) do if not seen[g.type] then seen[g.type]=true;types[#types+1]=g.type end end;table.sort(types)
      local rows={{key="typed",text="Type a new type",action="choose",value=false}}
      for _,kind in ipairs(types) do rows[#rows+1]={key="type:"..kind,text=kind,action="choose",value=kind} end
      pick("Machine type",rows,function(kind) if kind then withType(kind) else input("Machine type",nil,withType) end end)
    end)
  end
  local function activate(r)
    local s=screen();local a=r.action;local storage=s.storage
    if a=="back" then back()
    elseif a=="previous" or a=="next" then s.page=(s.page or 1)+(a=="next" and 1 or -1);s.selected=nil;dirty=true
    elseif a=="choose" then local fn=s.choose;back();fn(r.value)
    elseif a=="yes" then local fn=s.choose;back();fn()
    elseif a=="input" then
      local old={tty.getViewport()};local core=require("core/cursor");local oldClear=core.vertical.clear
      local readFg,readFp=gpu.getForeground();local readBg,readBp=gpu.getBackground()
      local ok,text=pcall(function()
        if options.input then return options.input(s.prompt,s.default,menu,w,h) end
        return menu:read(1,r.y,w)
      end)
      if not options.input then pcall(require("io").write,"\27[0m") end
      core.vertical.clear=oldClear;tty.setViewport(table.unpack(old))
      gpu.setForeground(readFg,readFp);gpu.setBackground(readBg,readBp)
      local field=menu:getOption(r.key);if field then field:y(field:y()) end -- read writes directly over this option
      if not ok then error(text) end
      local fn=s.choose;back();if text~=nil and running then fn(text=="" and s.default or text) end
    elseif a=="item" then push({kind="item",item=r.value})
    elseif a=="storage" then push({kind="storage",storage=r.value})
    elseif a=="machine" then push({kind="machine",machine=r.value})
    elseif a=="job" then push({kind="job",job=r.value})
    elseif a=="fetch" then local i=s.item;storages("Fetch destination",function(to) amount("fetch",i,to,warehouse.count(i)) end)
    elseif a=="find" then s.page=1;s.selected=nil;notify("Catalogue refreshed")
    elseif a=="scan" then local ids=warehouse.scan({storage});notify("Scan job "..table.concat(ids,","))
    elseif a=="store" then items("Store item",function(i) storeItem(i,storage) end,storage)
    elseif a=="storeItem" then storeItem(r.value,storage)
    elseif a=="membership" then
      if warehouse.members()[storage] then confirm("Remove "..storage.." from warehouse?",function() warehouse.remove(storage);notify("Member removed") end)
      else warehouse.add(storage);notify("Member added") end
    elseif a=="filter" then push({kind="filter",storage=storage})
    elseif a=="filterAdd" or a=="filterTyped" then
      local function add(i) settings(storage,function(v) v.filter=v.filter or {};v.filter[#v.filter+1]=i end) end
      if a=="filterAdd" then items("Filter item",add) else typedItem(add) end
    elseif a=="filterRemove" then settings(storage,function(v) table.remove(v.filter,r.value) end)
    elseif a=="filterClear" then settings(storage,function(v) v.filter=nil end)
    elseif a=="priority" then input("Priority (empty unsets)",nil,function(text) local n=text~="" and assert(tonumber(text),"numeric priority required") or nil;settings(storage,function(v) v.priority=n end) end)
    elseif a=="inventory" then storages("Same inventory as",function(other) settings(storage,function(v) v.inventory=other and ((warehouse.members()[other] or {}).inventory or other) or nil end) end,true)
    elseif a=="newMachine" then newMachine()
    elseif a=="editRole" then
      local name,role=s.machine,r.value
      pick("Role "..role,{{key="change",text="Change storage",action="choose",value="change"},{key="remove",text="Remove role",action="choose",value="remove"}},function(choice)
        if choice=="change" then editRole(name,role) else local g=warehouse.groups()[name];g.roles[role]=nil;assert(next(g.roles),"a machine needs a role");warehouse.group(name,g.type,g.roles);notify("Role removed") end
      end)
    elseif a=="roleAdd" then local name=s.machine;input("Role name",nil,function(role) assert(role~="","role required");editRole(name,role) end)
    elseif a=="deleteMachine" then local name=s.machine;confirm("Delete machine "..name.."?",function() warehouse.ungroup(name);back();notify("Machine deleted") end)
    elseif a=="cancel" then assert(logistics.status(s.job).state=="queued","only queued jobs can be cancelled");assert(logistics.cancel(s.job),"cancel failed");notify("Job cancelled")
    end
  end
  local function interrupt() running=false end
  local function run()
    tty.setViewport(w,h,0,0);gpu.setBackground(0);gpu.setForeground(palette.normal);gpu.fill(1,1,w,h," ")
    menu=qmenu.create();menu._onError=notify
    local rebuilding=false
    local function render()
      rebuilding=true
      local s=screen();local model=view.build(snapshot(),s,w,h);s.page=model.page
      local desired,nav={},{}
      local function option(name,x,y,text,colour,locked,background)
        background=background or 0
        desired[name]=true;local o=menu:getOption(name)
        if not o then o=menu:addOption(name,x,y,text);o:lock(locked or false);o:setStyle(locked and "locked" or "normal",colour or palette.normal,background);o:setStyle("selected",0,0xFFFFFF)
        else if o:x()~=x then o:x(x) end;if o:y()~=y then o:y(y) end;o:text(text)
          if o._warehouseColour~=colour or o._warehouseBackground~=background then o:setStyle(locked and "locked" or "normal",colour or palette.normal,background) end
        end
        o._warehouseColour=colour;o._warehouseBackground=background;return o
      end
      for _,r in ipairs(model.header) do
        option(r.key,r.x,1,r.text,r.selected and 0 or palette.muted,true,r.selected and 0xFFFFFF or 0)
      end
      option("status",1,2,view.fit(model.status,w),palette.muted,true)
      option("footer",1,h,view.fit(message or model.footer,w),palette.muted,true)
      if model.subtitle then option("screenTitle",1,3,view.fit(model.title,w),palette.muted,true) end
      for _,r in ipairs(model.rows) do
        local o=option(r.key,1,r.y,r.text,palette[r.colour] or palette.normal,false);nav[#nav+1]=o
        o:onSelect(function() if not rebuilding and screen()==s then s.selected=r.key end end);o:onActivate(function() guarded(function() activate(r) end) end)
      end
      local removed={};for name in pairs(menu._options) do if not desired[name] then removed[#removed+1]=name end end
      for _,name in ipairs(removed) do
        local y=menu:getOption(name):y();menu:removeOption(name)
        -- qmenu's cleanup measures codepoints, not wide-character columns.
        -- A removed full-width row must also clear its old rightmost cells.
        if y>2 and y<=h then gpu.fill(1,y,w,1," ") end
      end
      for n,o in ipairs(nav) do o:bind(keys.up,nav[(n-2)%#nav+1].name);o:bind(keys.down,nav[n%#nav+1].name) end
      if not s.selected or not menu:getOption(s.selected) then s.selected=nav[1].name end
      menu:setSelected(s.selected);rebuilding=false;menu:draw();dirty=false
      if options.onRender then options.onRender(model,s,menu,lastSignal) end
      lastSignal=nil
    end
    while running do
      if dirty then render() end
      if not running then break end
      local signal,_,char,key=event.pull()
      lastSignal=signal
      if signal=="interrupted" then running=false
      elseif signal=="key_down" then
        guarded(function()
          local s=screen()
          if key==keys.q or key==keys.back then back()
          elseif key==keys.left or key==keys.right then if s.top then
            local tab=((s.tab or 1)-1+(key==keys.right and 1 or -1))%4+1;stack[1]={kind=view.tabs[tab]:lower(),top=true,tab=tab};dirty=true end
          elseif key==keys.pageUp or key==keys.pageDown then s.page=(s.page or 1)+(key==keys.pageDown and 1 or -1);s.selected=nil;dirty=true
          elseif char==47 or key==keys.slash then input("Search (empty clears)",nil,function(text) s.search=text;s.page=1;s.selected=nil end)
          else menu:handleEvent(key);menu:draw() end
        end)
      elseif signal=="warehouse" or signal=="logistics" or signal=="logistics_work" or signal=="warehouse_ui_message" or signal=="screen_resized" then
        if signal=="screen_resized" then w,h=gpu.getResolution() end;dirty=true
      end
    end
  end
  event.listen("interrupted",interrupt)
  local ok,err=xpcall(run,debug.traceback)
  local restore,restoreErr=pcall(function() tty.setViewport(table.unpack(viewport));gpu.setForeground(fg,fp);gpu.setBackground(bg,bp) end)
  event.ignore("interrupted",interrupt);if timer then event.cancel(timer) end
  if not ok then return nil,err end;if not restore then return nil,restoreErr end;return true
end
return M
