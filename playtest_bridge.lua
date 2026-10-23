-- Playtest screen bridge: lets the host drive this computer's screen through
-- files on its own disk (the host sees the disk as a world folder).
--   bridge        start in the background (a timer; the shell stays usable)
--   bridge stop   stop it
-- The host writes /home/.bridge/in/<n> files of lines:
--   down <char> <code>   key_down from the primary keyboard
--   up <char> <code>     key_up
--   dump                 write the screen to /home/.bridge/screen
-- screen: "w h", then per row its text line and a line of colour runs
-- "x:fg:bg" (hex), each run starting at column x.
local fs=require("filesystem");local event=require("event")
local computer=require("computer");local component=require("component")
local dir="/home/.bridge";local inbox=dir.."/in"
local arg=...
if _G.bridgeTimer then event.cancel(_G.bridgeTimer);_G.bridgeTimer=nil end
if arg=="stop" then print("bridge stopped");return end
fs.makeDirectory(inbox)
for n in fs.list(inbox) do fs.remove(inbox.."/"..n) end

local function dump()
  local gpu=component.gpu;local w,h=gpu.getResolution()
  local f=assert(io.open(dir.."/screen.tmp","w"))
  f:write(w," ",h,"\n")
  for y=1,h do
    local text,runs,lf,lb={},{}
    for x=1,w do
      local ch,fg,bg=gpu.get(x,y);text[x]=ch
      if fg~=lf or bg~=lb then runs[#runs+1]=string.format("%d:%06x:%06x",x,fg,bg);lf,lb=fg,bg end
    end
    f:write(table.concat(text),"\n",table.concat(runs," "),"\n")
  end
  f:close()
  fs.remove(dir.."/screen");fs.rename(dir.."/screen.tmp",dir.."/screen")
end

local function poll()
  local kb=component.list("keyboard")()
  local names={};for n in fs.list(inbox) do if tonumber(n) then names[#names+1]=n end end
  table.sort(names,function(a,b) return tonumber(a)<tonumber(b) end)
  for _,n in ipairs(names) do
    local p=inbox.."/"..n;local f=io.open(p,"r");local body=f and f:read("*a") or "";if f then f:close() end
    fs.remove(p)
    for line in body:gmatch("[^\n]+") do
      local op,a,b=line:match("^(%S+)%s*(%S*)%s*(%S*)")
      if op=="down" or op=="up" then computer.pushSignal(op=="down" and "key_down" or "key_up",kb,tonumber(a),tonumber(b),"bridge")
      elseif op=="dump" then dump() end
    end
  end
end

_G.bridgeTimer=event.timer(0.2,function()
  local ok,err=pcall(poll)
  if not ok then local f=io.open(dir.."/error","a");if f then f:write(tostring(err),"\n");f:close() end end
end,math.huge)
print("bridge running: "..dir)
