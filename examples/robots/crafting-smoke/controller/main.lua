local event = require('event')
local modem = require('component').modem
assert(modem.open(2468))
local f = assert(io.open('/home/remove-request', 'w'))
f:write('remove once'); f:close()
local done, removed = {}, false
local deadline = require('computer').uptime() + 30
while not (removed and done['crafted-a'] and done['crafted-b']) do
  assert(require('computer').uptime() < deadline, 'craft/removal acknowledgement timeout')
  modem.broadcast(2468, 'start-crafting')
  local name, _, _, _, _, message = event.pull(0.1)
  if name == 'items_removed' then removed = true end
  if name == 'modem_message' then done[message] = true end
end
-- A coordinator must acknowledge its service work before returning. Native
-- inventory checks remain authoritative; independent robot services may run.
print('GENERIC_CONTAINER_EDIT_OK')
