local component = require("component")
local event = require("event")
local computer = require("computer")
local modem = component.modem
local port = 27101
assert(modem.isWireless())
modem.setStrength(32)
modem.open(port)
local address
local deadline = computer.uptime() + 20
repeat
  modem.broadcast(port, "hello")
  local _, _, sender, received, _, kind, own = event.pull(1, "modem_message")
  if received == port and kind == "hello" then assert(sender == own); address = sender end
until address or computer.uptime() > deadline
assert(address, "no drone hello")
modem.send(address, port, "transfer")
local _, _, sender, received, _, kind, count = event.pull(20, "modem_message")
assert(sender == address and received == port and kind == "done" and count == 64, "bad done reply")
print("link done", address, count)
