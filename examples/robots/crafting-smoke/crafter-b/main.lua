local component = require('component')
local robot = require('robot')
local sides = require('sides')
assert(component.modem.isWireless())
assert(component.modem.open(2468))
local event = require('event')
repeat
  local _, _, _, _, _, message = event.pull(30, 'modem_message')
  assert(message, 'controller start timeout')
until message == 'start-crafting'
for _, slot in ipairs({1, 2, 5, 6}) do
  robot.select(slot)
  assert(component.inventory_controller.suckFromSlot(sides.down, 1, 1) == 1, 'pluck plank from chest')
end
robot.select(12)
local ok, count = component.crafting.craft(1)
assert(ok and count == 1, 'native crafting table recipe')
assert(component.inventory_controller.getStackInInternalSlot(12).name == 'minecraft:crafting_table')
assert(robot.dropDown(1), 'return crafting table to chest')
assert(component.modem.broadcast(2468, 'crafted-b'))
print('NATIVE_CRAFTING_TABLE_B_OK')
