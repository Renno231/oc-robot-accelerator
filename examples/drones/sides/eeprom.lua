local drone = component.proxy(component.list("drone")())
local inv = component.proxy(component.list("inventory_controller")())
for side = 0, 5 do
  drone.select(side + 1)
  assert(inv.suckFromSlot(side, 1, 1) == 1, "side " .. side .. " did not yield one item")
end
computer.shutdown()
