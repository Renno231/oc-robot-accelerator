-- Pure screen model. State is a snapshot of public API results; no hardware.
local unicode=require("unicode") -- Pure native string-width helpers, not hardware.
local M={tabs={"Items","Storages","Machines","Jobs"}}
function M.clip(text,width)
  text=tostring(text or ""):gsub("[%c]"," ");width=math.max(0,width)
  if unicode.wlen(text)<=width then return text end
  local used,last=0,0
  for n=1,unicode.len(text) do
    local size=math.max(1,unicode.charWidth(unicode.sub(text,n,n)))
    if used+size>width then break end;used=used+size;last=n
  end
  return unicode.sub(text,1,last)
end
function M.fit(text,width)
  local clipped=M.clip(text,width);return clipped..string.rep(" ",math.max(0,width-unicode.wlen(clipped)))
end
function M.identity(i) return i.name..":"..tostring(i.damage or 0)..":"..(i.label or "") end
function M.itemText(v) local i=v.item;return tostring(v.count).."  "..(i.label or i.name).." ("..i.name..":"..(i.damage or 0)..")" end
local function sorted(t) local out={};for k in pairs(t or {}) do out[#out+1]=k end;table.sort(out);return out end
local function roles(state,storage)
  local out={};for _,name in ipairs(sorted(state.groups)) do local g=state.groups[name]
    for _,role in ipairs(sorted(g.roles)) do if g.roles[role]==storage then out[#out+1]=name.."."..role end end
  end;return table.concat(out,",")
end
function M.storageRows(state)
  local rows={};for _,name in ipairs(sorted(state.storages)) do
    local settings=state.members[name];local group=roles(state,name)
    rows[#rows+1]={key="storage:"..name,value=name,action="storage",colour=group~="" and "group" or settings and "member",
      text=(settings and "* " or "- ")..name..(group~="" and " ["..group.."]" or "")..
        (settings and (" p="..tostring(settings.priority or 0).." f="..(settings.filter and #settings.filter or "any")) or "")}
  end;return rows
end
function M.items(state)
  local items,seen={},{}
  for _,name in ipairs(sorted(state.members)) do
    local settings=state.members[name];local key=settings.inventory or name
    if not seen[key] and roles(state,name)=="" then
      seen[key]=true
      for _,v in pairs(state.contents[name] and state.contents[name].items or {}) do if v.count>0 then
        local k=M.identity(v.item);local old=items[k]
        if old then old.count=old.count+v.count else items[k]={item=v.item,count=v.count,maxSize=v.maxSize} end
      end end
    end
  end
  local out={};for k,v in pairs(items) do out[#out+1]={key="item:"..k,text=M.itemText(v),value=v.item,action="item",count=v.count,maxSize=v.maxSize} end
  table.sort(out,function(a,b) if a.count~=b.count then return a.count>b.count end;return a.key<b.key end);return out
end
local function age(state,e) return e and e.time and tostring(math.floor(math.max(0,(state.now or 0)-e.time))).."s" or "unknown" end
local function endpoint(e,state)
  if not e then return "?" end
  if type(e)=="string" then return e end
  if state then for name,s in pairs(state.storages) do if s.node==e.node and s.side==e.side then return name end end end
  return tostring(e.storage or e.node or "?")..(e.side and ":"..e.side or "")
end
local function jobItem(j) if j.item then return j.item.name end;for _,s in ipairs(j.steps or {}) do if s.item then return s.item.name end end;return "read/action" end
local function linkText(link)
  if type(link)=="table" then return tostring(link.a or "?").."→"..tostring(link.b or "?") end
  return tostring(link or "?")
end
local function row(rows,key,text,action,value,colour) rows[#rows+1]={key=key,text=text,action=action,value=value,colour=colour} end
function M.build(state,screen,width,height)
  assert(width>=50 and height>=16,"warehouse UI requires at least 50x16")
  local rows={};local kind=screen.kind or "items";local title=screen.title or kind
  if kind=="items" then rows=M.items(state)
  elseif kind=="storages" then rows=M.storageRows(state)
  elseif kind=="item" then
    local i=screen.item;title=i.label or i.name;local total=0
    for _,v in ipairs(M.items(state)) do if M.identity(v.value)==M.identity(i) then total=v.count end end
    row(rows,"total","Total: "..total)
    title="Total: "..total.."  "..title
    local seen,holdings={},{};for _,name in ipairs(sorted(state.members)) do
      local settings=state.members[name];local e=state.contents[name];local key=settings.inventory or name
      if not seen[key] and roles(state,name)=="" then
        seen[key]=true;local count=0
        for _,v in pairs(e and e.items or {}) do if M.identity(v.item)==M.identity(i) then count=count+v.count end end
        if count>0 then holdings[#holdings+1]={key="storage:"..name,text=name.."  "..count.."  read "..age(state,e),action="storage",value=name,colour="member",count=count} end
      end
    end
    table.sort(holdings,function(a,b) if a.count~=b.count then return a.count>b.count end;return a.key<b.key end)
    for _,r in ipairs(holdings) do rows[#rows+1]=r end
    row(rows,"fetch","Fetch...","fetch");row(rows,"find","Find again","find")
  elseif kind=="storage" then
    title=screen.storage;local e=state.contents[screen.storage]
    row(rows,"age","Last read: "..age(state,e)..(e and e.estimated and " (estimated)" or ""))
    local contents={};for k,v in pairs(e and e.items or {}) do if v.count>0 then contents[#contents+1]={key="item:"..k,text=M.itemText(v),value=v.item,action="storeItem",count=v.count} end end
    table.sort(contents,function(a,b) if a.count~=b.count then return a.count>b.count end;return a.key<b.key end)
    for _,v in ipairs(contents) do rows[#rows+1]=v end
    row(rows,"scan","Scan","scan");row(rows,"store","Store from here...","store")
    row(rows,"membership",state.members[screen.storage] and "Membership: remove" or "Membership: add","membership")
    if state.members[screen.storage] then
      row(rows,"filter","Filter","filter");row(rows,"priority","Priority","priority");row(rows,"inventory","Same inventory as...","inventory")
    end
  elseif kind=="filter" then
    title="Filter: "..screen.storage;row(rows,"add","Add from Items","filterAdd");row(rows,"typed","Type an item","filterTyped")
    for n,i in ipairs((state.members[screen.storage] or {}).filter or {}) do row(rows,"remove:"..n,"Remove "..i.name..":"..(i.damage or 0),"filterRemove",n) end
    row(rows,"clear","Clear filter (accept any)","filterClear")
  elseif kind=="machines" then
    local names=sorted(state.groups);table.sort(names,function(a,b) local x,y=state.groups[a],state.groups[b];if x.type~=y.type then return x.type<y.type end;return a<b end)
    for _,name in ipairs(names) do local g=state.groups[name];local parts={};for _,r in ipairs(sorted(g.roles)) do parts[#parts+1]=r.."="..g.roles[r] end
      row(rows,"machine:"..name,g.type.."  "..name.."  "..table.concat(parts," "),"machine",name,"group")
    end
    row(rows,"new","New machine","newMachine")
  elseif kind=="machine" then
    title=screen.machine;local g=state.groups[screen.machine]
    if g then for _,r in ipairs(sorted(g.roles)) do row(rows,"role:"..r,r.." = "..g.roles[r],"editRole",r,"group") end
      row(rows,"roleAdd","Add role","roleAdd");row(rows,"delete","Delete machine","deleteMachine") end
  elseif kind=="jobs" then
    local jobs={};for _,j in ipairs(state.jobs or {}) do jobs[#jobs+1]=j end;table.sort(jobs,function(a,b) return a.id>b.id end)
    for _,j in ipairs(jobs) do local first,last=(j.steps or {})[1],(j.steps or {})[#(j.steps or {})]
      row(rows,"job:"..j.id,j.id.."  "..j.state.."  "..(j.moved or 0).."/"..(j.requested or 0).."  "..jobItem(j).."  "..endpoint(j.from or first and first.take,state).."→"..endpoint(j.to or last and last.put,state),"job",j.id,j.state=="failed" and "failed" or j.state=="partial" and "partial")
    end
  elseif kind=="job" then
    title="Job "..screen.job;local j;for _,v in ipairs(state.jobs or {}) do if v.id==screen.job then j=v end end
    if j then
      row(rows,"state",j.state.."  "..(j.moved or 0).."/"..(j.requested or 0));row(rows,"reason","Reason: "..tostring(j.reason or "none"))
      if j.item then row(rows,"item","Item: "..j.item.name..":"..(j.item.damage or 0).." "..(j.item.label or "")) end
      for _,k in ipairs({"from","to","overflowEndpoint"}) do if j[k] then row(rows,k,k..": "..endpoint(j[k],state)) end end
      for _,k in ipairs({"remaining","taken","returned","refused","overflow","trips","shortfalls"}) do row(rows,k,k..": "..tostring(j[k] or 0)) end
      if j.maxSize then row(rows,"maxSize","Stack size: "..j.maxSize) end
      if j.short then row(rows,"short","Short; observed remaining="..(j.found or 0)) end
      for n,held in ipairs(j.held or {}) do row(rows,"held:"..n,"Held: "..held.drone.."  "..held.count.."  "..held.item.name..":"..(held.item.damage or 0)) end
      if j.test then row(rows,"test","Route test: "..tostring(j.test)) end
      for _,k in ipairs(sorted(type(j.scan)=="table" and j.scan or {})) do
        local v=j.scan[k];row(rows,"scan:"..k,"Scan "..k..": "..(type(v)=="table" and (v.name or v.type or "reported") or tostring(v)))
      end
      for n,s in ipairs(j.steps or {}) do
        row(rows,"step:"..n,"Step "..n.." "..endpoint(s.take or s.put or s.read or s.go,state).." moved="..(s.moved or 0).."/"..tostring(s.requested or 0))
        if s.item then row(rows,"stepItem:"..n,"Item: "..s.item.name..":"..(s.item.damage or 0).." "..(s.item.label or "")) end
        row(rows,"stepCounts:"..n,"taken="..(s.taken or 0).." returned="..(s.returned or 0).." refused="..(s.refused or 0).." overflow="..(s.overflow or 0))
        if s.maxSize then row(rows,"stepStack:"..n,"Stack size: "..s.maxSize) end
        if s.size then local stacks=0;for _ in pairs(s.listing or {}) do stacks=stacks+1 end;row(rows,"stepRead:"..n,"Read: "..s.size.." inventory slots, "..stacks.." reported stacks") end
        if s.short then row(rows,"stepShort:"..n,"Short; observed remaining="..(s.found or 0)) end
      end
      for n,b in ipairs(j.blockedReports or {}) do
        row(rows,"blocked:"..n,"Blocked link: "..(type(b)=="table" and linkText(b.link) or tostring(b)))
        if type(b)=="table" then row(rows,"blockedLeg:"..n,"Leg: "..linkText(b.leg).."; stalled seconds: "..tostring(b.stalledSeconds))
          if b.offset then row(rows,"blockedOffset:"..n,"Offset: "..(type(b.offset)=="table" and (tostring(b.offset.x)..","..tostring(b.offset.y)..","..tostring(b.offset.z)) or tostring(b.offset))) end
          for k,link in ipairs(b.links or {}) do row(rows,"blockedAffected:"..n..":"..k,"Affected: "..linkText(link)) end
        end
      end
      if j.state=="queued" then row(rows,"cancel","Cancel","cancel") end
    end
  elseif kind=="pick" then rows=screen.rows or {}
  elseif kind=="confirm" then row(rows,"summary",screen.summary);row(rows,"yes","Confirm","yes");row(rows,"no","Back","back")
  elseif kind=="input" then row(rows,"prompt",screen.prompt);row(rows,"input","> "..(screen.default or ""),"input")
  end
  if kind=="job" then
    local expanded={}
    for _,r in ipairs(rows) do
      if r.action then expanded[#expanded+1]=r else
        local text=r.text:gsub("[%c]"," ");local part=1
        repeat
          local fitted=M.clip(text,width)
          expanded[#expanded+1]={key=part==1 and r.key or r.key..":line:"..part,text=fitted,colour=r.colour,searchText=r.text}
          text=text:sub(#fitted+1);part=part+1
        until text==""
      end
    end
    rows=expanded
  end
  local filtered={};local search=(screen.search or ""):lower()
  for _,r in ipairs(rows) do if search=="" or (r.searchText or r.text):lower():find(search,1,true) then filtered[#filtered+1]=r end end
  local subtitle=not screen.top
  local size=height-(subtitle and 7 or 6);local pages=math.max(1,math.ceil(#filtered/size));local page=math.max(1,math.min(screen.page or 1,pages))
  -- Preserve the logical selection even if a changed sort moves it to a new page.
  if screen.selected then for n,r in ipairs(filtered) do if r.key==screen.selected then page=math.ceil(n/size);break end end end
  local visible={};for n=(page-1)*size+1,math.min(#filtered,page*size) do local r=filtered[n]
    visible[#visible+1]={key=r.key,text=M.clip(r.text,width),action=r.action,value=r.value,colour=r.colour,y=(subtitle and 4 or 3)+#visible}
  end
  row(visible,"previous","< Page "..page.."/"..pages,"previous");visible[#visible].y=height-3
  row(visible,"next","> Next page","next");visible[#visible].y=height-2
  row(visible,"back",screen.top and "Exit / q" or "Back / q","back");visible[#visible].y=height-1
  for _,r in ipairs(visible) do r.text=M.fit(r.text,width) end
  local idle,active,members=0,0,0
  for _ in pairs(state.members) do members=members+1 end
  for _,d in ipairs(state.drones or {}) do if d.state=="idle" then idle=idle+1 end end
  for _,j in ipairs(state.jobs or {}) do if j.state=="queued" or j.state=="active" then active=active+1 end end
  local footer=kind=="input" and "Enter edit  q back" or "↑↓ Enter  PgUp/PgDn  / search  q back"
  if screen.top then footer="↑↓ Enter  ←→ tabs  PgUp/PgDn  / search  q exit" end
  local header={{key="header",x=1,text="Warehouse"}};local x=12
  for n,label in ipairs(M.tabs) do local current=n==(screen.tab or 1)
    header[#header+1]={key="tab:"..n,x=x,text=current and "["..label.."]" or " "..label.." ",selected=current};x=x+#label+3
  end
  return {title=M.clip(title,width),subtitle=subtitle,rows=visible,page=page,pages=pages,total=#filtered,
    header=header,
    status=M.clip(members.." members  "..#M.items(state).." items  "..idle.."/"..#(state.drones or {}).." drones  "..active.." jobs",width),
    footer=M.clip(footer,width)}
end
return M
