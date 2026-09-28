local robot = require("robot")
local miner = {}
function miner.tunnelAndReturn(distance, record)
  for step = 1, distance do
    local ok, reason = robot.swing()
    record("swing", step, ok, reason)
    assert(ok, reason or "mining failed")
    ok, reason = robot.forward()
    record("forward", step, ok, reason)
    assert(ok, reason or "movement failed")
  end
  for step = 1, distance do
    local ok, reason = robot.back()
    record("back", step, ok, reason)
    assert(ok, reason or "return failed")
  end
end
return miner
