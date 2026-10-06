local api=require("mapclient")
local term=require("term")
local client=api.new()
local selected,position
local function input(prompt)
  io.write(prompt..": ");return io.read()
end
local function call(op,args)
  local value,err,ok=client:request(op,args)
  if not ok then error(type(err)=="table" and (err.reason or err.state) or tostring(err),0) end
  return value
end
local function coordinates(p)
  local out={}
  for _,axis in ipairs({"x","y","z"}) do
    local text=input(axis..(p and " ["..p[axis].."]" or ""))
    assert(text,"input closed");out[axis]=text=="" and p and p[axis] or assert(tonumber(text),"number required")
  end
  return api.block(out.x,out.y,out.z)
end
local function pick()
  local nodes,err=client:nodes(input("search (blank = newest first)"));assert(nodes,err)
  local first=1
  while first<=#nodes do
    for i=first,math.min(first+9,#nodes) do local n=nodes[i];print(i.." "..n.name.." ("..n.x..","..n.y..","..n.z..")") end
    local text=input("number / next / blank cancel");if not text or text=="" then return end
    if text=="next" then first=first+10 else local n=nodes[tonumber(text)];assert(n,"invalid selection");return n.name end
  end
  print("no more matches")
end
local function node() assert(selected,"pick or add a node first");return assert(call("node",{selected}),"node removed") end
print("Map editor. sides: 0 down, 1 up, 2 north, 3 south, 4 west, 5 east")
print("here | position | nudge | add | pick | link | unlink | test | faces")
print("scan | name | unname | remove | quit")
while true do
  io.write((selected or "-").."> ");local command=io.read()
  if not command or command=="quit" then break end
  local ok,err=pcall(function()
    if command=="here" then
      local p,why=client:position();if not p then print(why) end
      position=coordinates(p);print("position",position.x,position.y,position.z)
    elseif command=="position" then position=coordinates(position)
    elseif command=="nudge" then
      assert(position,"use here or position first")
      position=api.nudge(position,input("axis x/y/z"),tonumber(input("delta -1/+1")));print(position.x,position.y,position.z)
    elseif command=="add" then
      position=position or coordinates();local name=assert(input("node name"))
      call("add",{name,position.x,position.y,position.z,{charger=input("drone charger here? y/n")=="y"}});selected=name
    elseif command=="pick" then selected=pick() or selected
    elseif command=="faces" then
      local n=node();local faces={}
      for side=0,5 do if input("side "..side.." storage? y/n")=="y" then faces[side]=true end end
      call("add",{selected,n.x,n.y,n.z,{faces=faces,charger=n.charger}})
    elseif command=="scan" then
      node();local result=call("scan",{selected})
      for side=0,5 do print("side "..side..": "..tostring(result.scan[side] or "none")) end
      print("Scan does not change the map; use faces to mark storage sides.")
    elseif command=="link" or command=="unlink" or command=="test" then
      node();local target=pick();assert(target,"no target picked")
      if command=="test" then
        local result=call("test",{selected,target});print("flight",result.test)
        if result.test=="ok" and input("save link? y/n")=="y" then call("link",{selected,target}) end
      elseif command=="link" then
        if input("save clear link? y/n")=="y" then call("link",{selected,target}) end
      else call("unlink",{selected,target}) end
    elseif command=="name" then node();call("name",{input("storage name"),selected,tonumber(input("side 0..5"))})
    elseif command=="unname" then call("unname",{input("storage name")})
    elseif command=="remove" then node();if input("remove "..selected.."? y/n")=="y" then call("remove",{selected});selected=nil end
    elseif command~="" then print("Unknown action") end
  end)
  if not ok then print("Error: "..tostring(err)) end
end
return true
