local r = component.proxy(component.list("robot")())
local e = component.proxy(component.list("eeprom")())
local count = 0
if __PREPARED_START__ then
  e.setData("READY")
  repeat local name = computer.pullSignal() until name == "spike_go"
end
local function checked(name, ...)
  local result = table.pack(r[name](...))
  assert(result[1], name .. ": " .. tostring(result[2]))
  count = count + 1
end
local ok, err = pcall(function()
  checked("swing", 3)
  for i = 1, 8 do
    checked("move", 3)
    checked("place", 3)
    checked("swing", 3)
    checked("move", 2)
  end
  local moved, why = r.move(0)
  assert(moved == nil and why == "solid", "solid floor must return nil, solid")
end)
e.setData(ok and ("PASS:" .. count) or ("FAIL:" .. tostring(err)):sub(1, 240))
computer.shutdown()
