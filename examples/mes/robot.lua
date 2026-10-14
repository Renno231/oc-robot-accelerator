assert(loadfile('/home/program/install.lua'))()
local fs=require('filesystem')
fs.makeDirectory('/etc/rc.d')
assert(fs.copy('/home/program/etc/rc.d/cproc.lua','/etc/rc.d/cproc.lua'))
assert(fs.copy('/home/program/etc/rc.cfg','/etc/rc.cfg'))
local rc=assert(loadfile('/bin/rc.lua'))
assert(rc('cproc','start')~=1)
while true do require('event').pull() end
