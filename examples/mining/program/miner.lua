local robot = require("robot")
local miner = {}
function miner.tunnelAndReturn(distance)
  for step = 1, distance do
    assert(robot.swing())
    assert(robot.forward())
  end
  for step = 1, distance do
    assert(robot.back())
  end
end
return miner
