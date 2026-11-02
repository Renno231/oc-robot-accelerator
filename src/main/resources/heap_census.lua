-- Heap census of one OpenComputers machine (Lua 5.3/5.4). The runner runs it
-- on the machine's raw Lua state between execution slices, never from an OC
-- program. Arguments: the kernel thread and OC's ramScale. Returns one JSON
-- object of who holds the live heap: each OpenOS package.loaded module, split
-- into its table fields and its locals (upvalues of its functions), with code
-- apart; then programs' globals; then the kernel and everything else. Each
-- object counts once, for the first holder in that order, applications' own
-- modules (loaded from /usr or /home) before OpenOS's and OC's, whose event
-- list reaches every listener's data. Sizes follow Lua's
-- object layouts and its table rehash rule, so they are estimates; the runner
-- reports the allocator's exact live total beside them.
local kernel, scale = ...
local next, type, tostring, pcall = next, type, tostring, pcall
local floor, mtype = math.floor, math.type
local getmetatable, getuservalue = debug.getmetatable, debug.getuservalue
local getinfo, getlocal, getupvalue, upvalueid = debug.getinfo, debug.getlocal, debug.getupvalue, debug.upvalueid
local dump, format, sort, concat = string.dump, string.format, table.sort, table.concat

local v54 = _VERSION == "Lua 5.4"
local TABLE, SLOT, NODE = 56, 16, v54 and 24 or 32
local STRING, LCLOSURE, CCLOSURE, UPVAL = 25, 32, 32, v54 and 40 or 32
local USERDATA, THREAD = 40, 1000

local seen, seenUp = {}, {}
seen[coroutine.running()] = true -- the census's own thread and locals
local stack, sp, objects = {}, 0, 0
local boundary = {}
local cur, curCode -- accumulators the walk is charging: data, and code
local protos, protoList = {}, {}

local nums = {}
local function tablesize(t)
  for i = 0, 31 do nums[i] = 0 end
  local total, ints = 0, 0
  for k in next, t do
    total = total + 1
    if mtype(k) == "integer" and k >= 1 and k <= 0x7fffffff then
      local b, x = 0, k - 1
      while x > 0 do x = x // 2; b = b + 1 end
      ints = ints + 1; nums[b] = nums[b] + 1
    end
  end
  -- ltable.c computesizes: the largest power of two more than half full.
  local a, na, optimal, twotoi, i = 0, 0, 0, 1, 0
  while i <= 31 and ints > twotoi // 2 do
    if nums[i] > 0 then
      a = a + nums[i]
      if a > twotoi // 2 then optimal, na = twotoi, a end
    end
    i, twotoi = i + 1, twotoi * 2
  end
  local h, size = total - na, 1
  if h == 0 then size = 0 else while size < h do size = size * 2 end end
  return TABLE + SLOT * optimal + NODE * size, total
end

local function push(v)
  local tv = type(v)
  if (tv == "table" or tv == "function" or tv == "string" or tv == "thread" or tv == "userdata")
      and not seen[v] and not boundary[v] then
    sp = sp + 1; stack[sp] = v
  end
end

local function closure(f)
  local info = getinfo(f, "Su")
  local code = curCode or cur
  if info.what == "C" then
    code.bytes = code.bytes + CCLOSURE + 16 * info.nups
  else
    code.bytes = code.bytes + LCLOSURE + 8 * info.nups
    local ok, text = pcall(dump, f)
    local bytes = ok and #text or 0
    local key = info.source .. ":" .. info.linedefined .. ":" .. info.lastlinedefined .. ":" .. bytes
    if not protos[key] then
      local p = {source = info.source, first = info.linedefined,
                 last = info.linedefined == 0 and math.huge or info.lastlinedefined, bytes = bytes, owner = code}
      protos[key] = p; protoList[#protoList + 1] = p
    end
    for i = 1, info.nups do
      local id = upvalueid(f, i)
      if not seenUp[id] then seenUp[id] = true; code.bytes = code.bytes + UPVAL end
    end
  end
  return info.nups
end

local function drain()
  while sp > 0 do
    local v = stack[sp]; stack[sp] = nil; sp = sp - 1
    if not seen[v] then
      seen[v] = true; objects = objects + 1
      local tv = type(v)
      if tv == "string" then
        cur.bytes = cur.bytes + STRING + #v
      elseif tv == "table" then
        cur.bytes = cur.bytes + tablesize(v)
        push(getmetatable(v))
        for k, x in next, v do push(k); push(x) end
      elseif tv == "function" then
        for i = 1, closure(v) do local _, x = getupvalue(v, i); push(x) end
      elseif tv == "thread" then
        cur.bytes = cur.bytes + THREAD
        local level = 0
        while getinfo(v, level, "f") do
          push(getinfo(v, level, "f").func)
          local i = 1
          while true do
            local name, x = getlocal(v, level, i)
            if not name then break end
            push(x); i = i + 1
          end
          level = level + 1
        end
      elseif tv == "userdata" then
        cur.bytes = cur.bytes + USERDATA
        push(getmetatable(v)); push(getuservalue(v))
      end
    end
  end
end

-- Keeps the `limit` biggest parts in top.
local function note(top, limit, key, bytes, fields)
  if bytes <= 0 or (#top == limit and top[limit].bytes >= bytes) then return end
  local name = tostring(key)
  if #name > 60 then name = name:sub(1, 57) .. "..." end
  top[#top + 1] = {key = name, bytes = bytes, fields = fields}
  sort(top, function(a, b) return a.bytes > b.bytes end)
  top[limit + 1] = nil
end

-- Walks x into cur. A fresh table or function is split into its biggest
-- parts (a function's parts are its upvalues, named ^name) and those parts
-- are returned, `split` levels deep.
local function walkParts(x, split, limit)
  local tx = type(x)
  if split == 0 or seen[x] or boundary[x] or (tx ~= "table" and tx ~= "function") then
    push(x); drain(); return nil, 0
  end
  seen[x] = true; objects = objects + 1
  local top, n = {}, 0
  if tx == "table" then
    local size; size, n = tablesize(x)
    cur.bytes = cur.bytes + size
    push(getmetatable(x)); drain()
    for k, y in next, x do
      local before = cur.bytes
      push(k); drain()
      local fields = walkParts(y, split - 1, 5)
      note(top, limit, k, cur.bytes - before, fields)
    end
  else
    for i = 1, closure(x) do
      local name, y = getupvalue(x, i)
      local before = cur.bytes
      local fields = walkParts(y, split - 1, 5)
      note(top, limit, "^" .. name, cur.bytes - before, fields)
    end
  end
  return top, n
end

-- One holder's value: split into its biggest entries, fourteen levels deep.
local function walkValue(c, x)
  cur = c
  local top, n = walkParts(x, 14, 10)
  if top then c.top = top; c.entries = c.entries + n end
end

local function child(mod, name)
  local c = mod.children[name]
  if not c then
    c = {name = name, bytes = 0, entries = 0, top = {}}
    mod.children[name] = c; mod.order[#mod.order + 1] = c
  end
  return c
end

local function walkFunction(mod, f)
  if seen[f] then return end
  seen[f] = true; objects = objects + 1
  cur = mod.code
  for i = 1, closure(f) do
    local name, x = getupvalue(f, i)
    walkValue(child(mod, "local " .. (name ~= "" and name or "?")), x)
  end
end

local function sortedKeys(t)
  local keys = {}
  for k in next, t do keys[#keys + 1] = k end
  sort(keys, function(a, b)
    local ta, tb = type(a), type(b)
    if ta ~= tb then return ta < tb end
    if ta == "string" or ta == "number" then return a < b end
    return tostring(a) < tostring(b)
  end)
  return keys
end

-- machine.lua's top frame holds the programs' environment as local `sandbox`.
local sandbox
local level = 0
while not sandbox and getinfo(kernel, level, "f") do
  local i = 1
  while true do
    local name, x = getlocal(kernel, level, i)
    if not name then break end
    if name == "sandbox" and type(x) == "table" then sandbox = x; break end
    i = i + 1
  end
  level = level + 1
end
local package = sandbox and rawget(sandbox, "package")
local loaded = type(package) == "table" and rawget(package, "loaded")
if type(loaded) ~= "table" then return '{"booted":false}' end -- OpenOS has not booted yet.

local names = {}
for name, m in next, loaded do
  if type(name) == "string" and name ~= "_G" then names[#names + 1] = name end
  if type(m) == "table" or type(m) == "function" then boundary[m] = true end
end
boundary[sandbox] = true
-- Where a module's code was loaded from: applications install under /usr or /home.
local function application(m)
  local f = m
  if type(m) == "table" then
    f = nil
    for _, x in next, m do
      if type(x) == "function" and getinfo(x, "S").what == "Lua" then f = x; break end
    end
  end
  local source = type(f) == "function" and getinfo(f, "S").source or ""
  return source:match("^[=@]/usr/") or source:match("^[=@]/home/")
end
local rank = {}
for _, name in ipairs(names) do rank[name] = application(loaded[name]) and 0 or 1 end
sort(names, function(a, b) if rank[a] ~= rank[b] then return rank[a] < rank[b] end return a < b end)

local modules = {}
for _, name in ipairs(names) do
  local m = loaded[name]
  local mod = {name = name, children = {}, order = {}, code = {bytes = 0}}
  modules[#modules + 1] = mod
  curCode = mod.code
  if type(m) == "table" and not seen[m] then
    seen[m] = true; objects = objects + 1
    local root = child(mod, "(module table)")
    root.bytes = root.bytes + tablesize(m)
    cur = root; push(getmetatable(m)); drain()
    local functions = {}
    for _, k in ipairs(sortedKeys(m)) do
      local x = m[k]
      cur = root; push(k); drain()
      if type(x) == "function" then functions[#functions + 1] = x
      else walkValue(child(mod, tostring(k)), x) end
    end
    for _, f in ipairs(functions) do walkFunction(mod, f) end
  elseif type(m) == "function" then
    walkFunction(mod, m)
  end
end

curCode = nil
local globals = {bytes = 0}
cur = globals
seen[sandbox] = true; objects = objects + 1
globals.bytes = globals.bytes + tablesize(sandbox)
push(getmetatable(sandbox))
for k, x in next, sandbox do push(k); push(x) end
drain()

local rest = {bytes = 0}
cur = rest
push(debug.getregistry()); push(kernel); drain()

-- A live function's dump holds its nested functions: count outermost ones.
sort(protoList, function(a, b)
  if a.source ~= b.source then return a.source < b.source end
  if a.first ~= b.first then return a.first < b.first end
  if a.last ~= b.last then return a.last > b.last end
  return a.bytes > b.bytes
end)
local outer
local bySource, sources = {}, {}
for _, p in ipairs(protoList) do
  if not (outer and outer.source == p.source and p.first >= outer.first and p.last <= outer.last) then
    p.owner.bytes = p.owner.bytes + p.bytes; outer = p
    if not bySource[p.source] then bySource[p.source] = 0; sources[#sources + 1] = p.source end
    bySource[p.source] = bySource[p.source] + p.bytes
  end
end
sort(sources, function(a, b) return bySource[a] > bySource[b] end)

local function n(bytes) return format("%d", floor(bytes / scale + 0.5)) end
local function q(s)
  return '"' .. s:gsub('[%c"\\\127-\255]', function(c) return format("\\u%04x", c:byte()) end) .. '"'
end

local function parts(top)
  local out = {}
  for j, t in ipairs(top) do
    -- Parts under 1 KB are not split further in the output.
    local split = t.fields and #t.fields > 0 and t.bytes >= 1024 * scale
    out[j] = '{"key":' .. q(t.key) .. ',"bytes":' .. n(t.bytes) ..
      (split and ',"fields":' .. parts(t.fields) or '') .. '}'
  end
  return '[' .. concat(out, ",") .. ']'
end

local walked = globals.bytes + rest.bytes
for _, mod in ipairs(modules) do
  mod.bytes = mod.code.bytes
  for _, c in ipairs(mod.order) do mod.bytes = mod.bytes + c.bytes end
  walked = walked + mod.bytes
end
sort(modules, function(a, b) return a.bytes > b.bytes end)

local out = {}
for _, mod in ipairs(modules) do
  if mod.bytes > 0 then
    sort(mod.order, function(a, b) return a.bytes > b.bytes end)
    local children = {}
    for i, c in ipairs(mod.order) do
      if c.bytes > 0 then
        children[#children + 1] = '{"name":' .. q(c.name) .. ',"bytes":' .. n(c.bytes) ..
          ',"entries":' .. c.entries .. ',"top":' .. parts(c.top) .. '}'
      end
    end
    out[#out + 1] = '{"name":' .. q(mod.name) .. ',"bytes":' .. n(mod.bytes) .. ',"codeBytes":' ..
      n(mod.code.bytes) .. ',"children":[' .. concat(children, ",") .. ']}'
  end
end
-- Resident code by the file it was loaded from, programs included.
local code = {}
for i, src in ipairs(sources) do code[i] = '{"source":' .. q(src) .. ',"bytes":' .. n(bySource[src]) .. '}' end
return '{"lua":' .. q(_VERSION) .. ',"walkedBytes":' .. n(walked) .. ',"objects":' .. objects ..
  ',"globalsBytes":' .. n(globals.bytes) .. ',"kernelBytes":' .. n(rest.bytes) ..
  ',"modules":[' .. concat(out, ",") .. '],"codeBySource":[' .. concat(code, ",") .. ']}'
