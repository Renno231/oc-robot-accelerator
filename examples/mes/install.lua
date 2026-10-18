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
return true
