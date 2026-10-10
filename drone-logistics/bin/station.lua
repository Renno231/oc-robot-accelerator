local s=require('stations')
local map=require('map')
local a={...};local op=a[1]
local function show(r)
  if not r then return print('unknown station') end
  print(r.name..' '..r.state..(r.phase and '/'..r.phase or ''))
  if r.reason then print(r.reason) end
  if r.note then print(r.note) end
  for _,m in ipairs(r.members or {}) do
    local p=map.node(m.node)
    print(m.storage..' '..m.node..' ('..p.x..','..p.y..','..p.z..') side '..m.side)
  end
  if r.created then
    for n,size in pairs(r.sizes or {}) do print(n..' inventory size '..size) end
    print('created nodes: '..table.concat(r.created.nodes,', '))
    for _,v in ipairs(r.created.links) do print('created link: '..v[1]..' -> '..v[2]) end
  end
end
local value,err
if op=='storage' or op=='row' then
  local spec={x=tonumber(a[2]),y=tonumber(a[3]),z=tonumber(a[4]),face=a[5]}
  if op=='storage' then spec.name=a[6];spec.role=a[7] or 'stock'
  else spec.rowDir=a[6];spec.count=tonumber(a[7]);spec.spacing=tonumber(a[8]);spec.prefix=a[9];spec.role=a[10]~='--pair' and a[10] or 'stock'
    if a[#a-1]=='--pair' then spec.pair=tonumber(a[#a]) end
  end
  value,err=s.add(op,spec)
elseif op=='list' then for _,r in ipairs(s.list()) do show(r) end;return
elseif op=='show' then show(s.get(a[2]));return
elseif op=='retry' then value,err=s.retry(a[2])
elseif op=='remove' then value,err=s.remove(a[2],{items=a[3]})
else print('station storage x y z face name [stock|other] | row x y z face rowDir count spacing prefix [stock|other] [--pair 2] | list | show name | retry name | remove name [move|forget]');return end
print(value and tostring(value) or err)
