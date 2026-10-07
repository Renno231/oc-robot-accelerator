-- Native-controller checks of voxel conservatism, numeric keys and invalidation.
return function(map)
  if not map.smooth then return end
  local half={x=.375,y=.1875,z=.375,offsetY=.1875}
  local names={}
  local function add(n,x,y,z) names[#names+1]=n;map.add(n,x,y,z) end
  add('_gA',-12,65,-12);add('_gB',-10,65,-12);add('_gC',-10,67,-12)
  map.link('_gA','_gB');map.link('_gB','_gC')
  assert(map.clearLine('_gA','_gB',half))
  assert(not map.clearLine('_gA','_gC',half),'unknown L interior cleared')
  assert(#map.smooth({'_gA','_gB','_gC'},half)==3)
  local original=map.clear
  map.clearLine('_gA','_gB',half);assert(original==map.clear,'clear rebuilt per check')
  local key=assert(map.blockKey(-11,65,-12))
  assert(not map.clearLine('_gA','_gB',half,{blocks={[key]=true}}),'avoid block ignored')
  assert(#map.linksAtBlock(key,half)==1,'original link attribution')
  map.unlink('_gA','_gB');assert(not map.clearLine('_gA','_gB',half),'unlink retained air')
  map.link('_gA','_gB')
  local function n(x,y) return '_grid'..x..'_'..y end
  for x=0,2 do for y=0,2 do
    add(n(x,y),-20+x,65+y,-20)
    if x>0 then map.link(n(x-1,y),n(x,y)) end
    if y>0 then map.link(n(x,y-1),n(x,y)) end
  end end
  assert(#map.smooth(map.route(n(0,0),n(2,2)),half)==2,'grid staircase not collapsed')
  assert(#map.theta(n(0,0),n(2,2),half)==2)
  -- Closed-face convention: a larger box touches unknown neighbouring air.
  assert(not map.clearLine(n(0,0),n(2,2),.5),'face contact omitted')
  map.buildClear(half)
  for _,name in ipairs(names) do map.remove(name) end
  map.buildClear(half)
  print('native map geometry tests passed')
end
