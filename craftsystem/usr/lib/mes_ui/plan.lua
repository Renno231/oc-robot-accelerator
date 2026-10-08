-- Plan preview: the stages as a chain. Enter on a stage chooses its crafter
-- or machines; the last rows run it or save it.
local ui=require("mes_ui.core");local wh=require("warehouse")
local S={hints="Enter on a stage: choose machines · R refresh · ⌫ back · H help",
  help={{"Enter","on a stage: choose its crafter or machines; on the last rows: run, re-plan, save"}}}
local function mes() return require("mes") end
local circled={"①","②","③","④","⑤","⑥","⑦","⑧","⑨"}

function S:open(arg)
  self.plan=arg.plan;local a=ui.area();self.rows={}
  self.list=ui.list(self.menu,{name="p",x=1,y=a.y,w=a.w,h=a.h,
    count=function() return #self.rows end,
    row=function(i) local r=self.rows[i];return r.text,r.fg,r.locked end,
    activate=function(i) self:activate(self.rows[i]) end})
  self:rebuild();self.list:refresh()
  for i,r in ipairs(self.rows) do if r.run then self.list:set(i) end end
end
local function items(list)
  local t={};for _,x in ipairs(list) do t[#t+1]=ui.label(x.item).." ×"..(x.qty or x.need) end;return table.concat(t,", ")
end
local function machines(s)
  if s.groups==nil or s.groups=="any" then local n=0;for _ in pairs(wh.groups(s.machineType)) do n=n+1 end;return "any ("..n..")" end
  if type(s.groups)=="string" then return s.groups end
  return table.concat(s.groups,", ")
end
function S:rebuild()
  local rows,P,plan=self.rows,ui.P,self.plan;for k=#rows,1,-1 do rows[k]=nil end
  local function add(r) rows[#rows+1]=r end
  local n=#plan.stages
  for i,s in ipairs(plan.stages) do
    local branch=i==1 and (n==1 and "─" or "┌") or (i==n and "└" or "├")
    local cont=i==n and " " or "│"
    local head
    if s.kind=="robot" then head=(circled[i] or i).." Robot · "..(s.crafter or "first idle crafter")
    else head=(circled[i] or i).." "..s.machineType.." · "..machines(s).." · "..s.loads.." load"..(s.loads==1 and "" or "s") end
    add({text=branch.." "..ui.fit(head,38).."→ "..items(s.outputs),fg=P.fg,stage=i})
    for _,x in ipairs(s.inputs) do
      local short=x.have<x.need
      add({text=cont.."     "..ui.fit(ui.label(x.item),24)..ui.right(ui.num(x.need),7).."  have "..ui.num(x.have)..(short and "  short "..ui.num(x.need-x.have) or ""),fg=short and P.bad or P.dim,locked=true})
    end
    if s.fuel then local f=s.fuel;local short=f.have<f.need
      add({text=cont.."     "..ui.fit("fuel "..ui.label(f.item),24)..ui.right(ui.num(f.need),7).."  have "..ui.num(f.have),fg=short and P.bad or P.dim,locked=true}) end
  end
  add({text="",locked=true})
  if #plan.missing>0 then
    add({text="Missing: "..#plan.missing.." input"..(#plan.missing==1 and "" or "s").." short; add stock and re-plan",fg=P.bad,locked=true})
    add({text="↻ Re-plan",fg=P.accent,replan=true})
  else add({text="▶ Run",fg=P.good,run=true}) end
  add({text="  Save as plan file…",fg=P.fg,save=true})
end
function S:draw()
  local p=self.plan
  ui.title("Plan · "..ui.label(p.item).." ×"..p.qty,#p.stages.." stage"..(#p.stages==1 and "" or "s")..(#p.missing>0 and " · cannot run yet" or " · ready"))
end
function S:refresh() self:rebuild();self.list:refresh();self:draw() end
function S:activate(r)
  if not r then return end
  local plan=self.plan
  if r.stage then
    local s=plan.stages[r.stage]
    if s.kind=="robot" then
      local rows={{text="First idle crafter",value=false}}
      for n,c in pairs(mes().crafters()) do rows[#rows+1]={text=ui.fit(n,10).." robot "..c.robot:sub(1,8).."…  buffer "..c.buffer,value=n} end
      ui.pick("Stage "..r.stage.." · crafter",rows,function(v) s.crafter=v or nil;if v then ui.try(mes().choose,plan,r.stage,v) end;self:refresh() end,{nofilter=true})
    else
      local groups=wh.groups(s.machineType);local names={};for n in pairs(groups) do names[#names+1]=n end;table.sort(names)
      ui.pick("Stage "..r.stage.." · "..s.machineType.." machines",{
        {text="Any: split over all "..#names,value="any"},{text="One machine…",value="one"},{text="A set…",value="set"}},function(v)
        if v=="any" then ui.try(mes().choose,plan,r.stage,"any");self:refresh()
        elseif v=="one" then
          local rows={};for _,n in ipairs(names) do rows[#rows+1]={text=n,value=n} end
          ui.pick("One "..s.machineType,rows,function(n) ui.try(mes().choose,plan,r.stage,n);self:refresh() end)
        else
          local rows,chosen={},{};for _,n in ipairs(names) do rows[#rows+1]={text=n,value=n} end
          if type(s.groups)=="table" then for _,n in ipairs(s.groups) do chosen[n]=true end end
          ui.checklist(s.machineType.." machines to use",rows,chosen,function(c)
            local set={};for _,n in ipairs(names) do if c[n] then set[#set+1]=n end end
            if #set==0 then ui.fail("pick at least one") else ui.try(mes().choose,plan,r.stage,set) end;self:refresh()
          end)
        end
      end,{nofilter=true})
    end
  elseif r.run then
    local id=ui.try(mes().run,plan);if id then ui.replace("mes_ui.run",{id=id}) end
  elseif r.replan then
    local p=require("mes_ui.choice").plan(plan.item,plan.qty);if p then self.plan=p;self:refresh() end
  elseif r.save then
    ui.prompt("Save plan","Plan name",ui.label(plan.item).." x"..plan.qty,function(name)
      local ok=ui.try(function() return require("craft_plans").save(name,plan) end);if ok then ui.ok("Saved plan "..name) end
    end)
  end
end
return S
