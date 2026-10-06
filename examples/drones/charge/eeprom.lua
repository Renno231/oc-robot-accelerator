local start = computer.uptime()
while computer.energy() < 2000 do
  assert(computer.uptime() - start < 30, "charge timeout")
  computer.pullSignal(0.05)
end
computer.shutdown()
