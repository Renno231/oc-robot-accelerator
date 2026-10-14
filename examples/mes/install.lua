-- Install the user's sources without rewriting them or entering a UI.
local fs=require('filesystem')
local function copyTree(source,destination)
  fs.makeDirectory(destination)
  for name in fs.list(source) do
    local src,dst=fs.concat(source,name),fs.concat(destination,name)
    if fs.isDirectory(src) then copyTree(src,dst) else assert(fs.copy(src,dst)) end
  end
end
copyTree('/home/program/usr','/usr')
package.path='/usr/lib/?.lua;/usr/lib/?/init.lua;'..package.path
-- The user's ore dictionary eagerly opens its archive even for concrete recipes.
-- This fixture uses no ore aliases; ship a valid empty archive on both computers.
fs.makeDirectory('/usr/lib/oredict')
local ores=assert(require('liblz16').open('/usr/lib/oredict/oredict.dblz','wb'))
ores:close()
return true
