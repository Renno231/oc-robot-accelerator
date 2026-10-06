local drone = component.proxy(component.list("drone")())
local modem = component.proxy(component.list("modem")())
local inv = component.proxy(component.list("inventory_controller")())
local port = 27101
modem.setStrength(32)
modem.open(port)
while true do
  local e = {computer.pullSignal(1)}
  if e[1] == "modem_message" and e[4] == port then
    if e[6] == "hello" then
      modem.send(e[3], port, "hello", modem.address)
    elseif e[6] == "transfer" then
      drone.select(1)
      local count = assert(inv.suckFromSlot(0, 1, 64))
      assert(count == 64, "pickup count")
      drone.move(6, 0, 0)
      repeat computer.pullSignal(0.1) until drone.getOffset() < 0.02 and drone.getVelocity() < 0.02
      assert(inv.dropIntoSlot(0, 3, count), "drop failed")
      drone.move(-6, 0, 0)
      repeat computer.pullSignal(0.1) until drone.getOffset() < 0.02 and drone.getVelocity() < 0.02
      modem.send(e[3], port, "done", count)
    end
  end
end
