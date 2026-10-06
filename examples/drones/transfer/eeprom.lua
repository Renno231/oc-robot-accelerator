local drone = component.proxy(component.list("drone")())
local inv = component.proxy(component.list("inventory_controller")())
drone.select(1)
assert(inv.suckFromSlot(0, 1, 64) == 64, "pickup failed")
drone.move(6, 0, 0)
repeat
  computer.pullSignal(0.1)
until drone.getOffset() < 0.02 and drone.getVelocity() < 0.02
assert(inv.dropIntoSlot(0, 3, 64), "drop failed")
computer.shutdown()
