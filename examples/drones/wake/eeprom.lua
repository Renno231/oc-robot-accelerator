local modem = component.proxy(component.list("modem")())
local ee = component.proxy(component.list("eeprom")())
local port = 27102
local data = ee.getData()
local token = data:sub(1, 6)
local previous = modem.getWakeMessage()
modem.setStrength(32)
modem.setWakeMessage(token, true)
modem.open(port)
if previous == token then
  local sender = data:sub(8)
  local seen = false
  local deadline = computer.uptime() + 0.5
  repeat
    local e = {computer.pullSignal(0.1)}
    if e[1] == "modem_message" and e[6] == token then seen = true end
  until computer.uptime() >= deadline
  modem.send(sender, port, "awake", seen)
  while true do computer.pullSignal(1) end
else
  -- The OpenOS host needs time to boot before it can hear the announcement.
  while true do
    local e = {computer.pullSignal(1)}
    if e[1] == "modem_message" and e[4] == port and e[6] == "ready" then
      ee.setData(token .. "|" .. e[3])
      modem.broadcast(port, "address", modem.address)
      computer.shutdown()
    end
  end
end
