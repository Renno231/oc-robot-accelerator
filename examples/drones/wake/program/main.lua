local component = require("component")
local event = require("event")
local computer = require("computer")
local modem = component.modem
local port, token = 27102, "wakeup"
modem.setStrength(32)
modem.open(port)
local address
local deadline = computer.uptime() + 20
repeat
  modem.broadcast(port, "ready")
  local _, _, sender, received, _, kind, own = event.pull(1, "modem_message")
  if received == port and kind == "address" then assert(sender == own); address = sender end
until address or computer.uptime() > deadline
assert(address, "no drone address")
print("drone announced", address, "uptime", computer.uptime())
os.sleep(2)
print("sending wrong", "uptime", computer.uptime())
modem.send(address, port, "wrong")
local eventName = event.pull(3, "modem_message")
assert(eventName == nil, "wrong token caused reply")
print("wrong token: no reply for 3 seconds")
print("sending wake", "uptime", computer.uptime())
modem.send(address, port, token, "go")
local _, _, sender, received, _, kind, sawWake = event.pull(5, "modem_message")
assert(sender == address and received == port and kind == "awake", "drone did not wake")
print("awake", address, "waking-message-visible", sawWake)
