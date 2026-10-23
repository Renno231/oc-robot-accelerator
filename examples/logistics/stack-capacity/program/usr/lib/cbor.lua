-- CBOR (RFC 8949) for Lua 5.3, with lua-cbor's interface and the same encoded bytes.
--
-- A string encodes as a byte string, a table whose keys run 1..n in pairs order as an array, any
-- other table as a map in pairs order, and a float as a double. A table or userdata whose
-- metatable has an encoder in the options (options[metatable]) or a __tocbor field is encoded by
-- that function, which returns the bytes. CBOR null decodes as cbor.null, not nil.
--
-- Encoding appends pieces to one list joined once at the end, so a nested value is never copied
-- into its parent's string. Decoding walks the input by position and makes new strings only for
-- string values.
local M = {}
local byte, char, sub, pack, unpack = string.byte, string.char, string.sub, string.pack, string.unpack
local concat, sort = table.concat, table.sort
local type, pairs, ipairs, getmetatable, setmetatable = type, pairs, ipairs, getmetatable, setmetatable
local mtype, huge = math.type, math.huge
local rawmeta = debug and debug.getmetatable or getmetatable

-- Simple values (major type 7) and tags (major type 6) as objects.
local Simple = {}
function Simple:__tostring() return self.name or ('simple(%d)'):format(self.value) end
local Tagged = {}
function Tagged:__tostring() return ('%d(%s)'):format(self.tag, tostring(self.value)) end

-- The initial byte(s) of an item: major is the major type shifted into the high 3 bits.
local function head(n, major)
  if n < 24 then return char(major + n)
  elseif n < 256 then return char(major + 24, n)
  elseif n < 65536 then return pack('>BI2', major + 25, n)
  elseif n < 4294967296 then return pack('>BI4', major + 26, n)
  else return pack('>BI8', major + 27, n) end
end

function Simple:__tocbor() return self.cbor or head(self.value, 224) end
function Tagged:__tocbor(options) return head(self.tag, 192) .. M.encode(self.value, options) end

function M.simple(value, name, cbor) -- simple value 0..255 -- object
  assert(value >= 0 and value <= 255, "bad argument #1 to 'simple' (integer in range 0..255 expected)")
  return setmetatable({value = value, name = name, cbor = cbor}, Simple)
end
function M.tagged(tag, value) -- tag, value -- object
  assert(tag >= 0, "bad argument #1 to 'tagged' (positive integer expected)")
  return setmetatable({tag = tag, value = value}, Tagged)
end
M.null, M.undefined = M.simple(22, 'null'), M.simple(23, 'undefined')
local BREAK = M.simple(31, 'break', '\255')
local null, undefined = M.null, M.undefined

-- Encoding. Each put appends a value's pieces to out after index k and returns the new last index.
local put, putters

local function putMap(t, options, out, k)
  local count = 0
  for _ in pairs(t) do count = count + 1 end
  k = k + 1; out[k] = head(count, 160)
  for key, v in pairs(t) do k = put(key, options, out, k); k = put(v, options, out, k) end
  return k
end

local function putTable(t, options, out, k)
  local count, array = 0, true
  for key in pairs(t) do
    count = count + 1
    if array and key ~= count then array = false end
  end
  if not array then
    k = k + 1; out[k] = head(count, 160)
    for key, v in pairs(t) do k = put(key, options, out, k); k = put(v, options, out, k) end
    return k
  end
  k = k + 1; out[k] = head(count, 128)
  for i = 1, count do k = put(t[i], options, out, k) end
  return k
end

local function putArray(t, options, out, k)
  local count = 0
  for _ in ipairs(t) do count = count + 1 end
  k = k + 1; out[k] = head(count, 128)
  for i = 1, count do k = put(t[i], options, out, k) end
  return k
end

-- Keys in the order of t's own array part, or else sorted.
local function putOrderedMap(t, options, out, k)
  local keys = t
  if not t[1] then
    keys = {}
    for key in pairs(t) do keys[#keys + 1] = key end
    sort(keys)
  end
  local count = 0
  for _ in ipairs(keys) do count = count + 1 end
  k = k + 1; out[k] = head(count, 160)
  for i = 1, count do local key = keys[i]; k = put(key, options, out, k); k = put(t[key], options, out, k) end
  return k
end

-- A value whose metatable names an encoder; false if none does.
local function putCustom(v, mt, options, out, k)
  local encoder = options and options[mt] or mt.__tocbor
  if not encoder then return false end
  local putter = putters[encoder]
  if putter then return putter(v, options, out, k) end
  k = k + 1; out[k] = encoder(v, options)
  return k
end

function put(v, options, out, k)
  local t = type(v)
  if t == 'string' then
    out[k + 1] = head(#v, 64); out[k + 2] = v
    return k + 2
  elseif t == 'number' then
    if mtype(v) == 'integer' then
      out[k + 1] = v < 0 and head(-1 - v, 32) or head(v, 0)
    else
      out[k + 1] = pack('>Bd', 251, v)
    end
    return k + 1
  elseif t == 'table' then
    local mt = getmetatable(v)
    if mt then
      local done = putCustom(v, mt, options, out, k)
      if done then return done end
    end
    return putTable(v, options, out, k)
  elseif t == 'boolean' then
    out[k + 1] = v and '\245' or '\244'
    return k + 1
  elseif t == 'nil' then
    out[k + 1] = '\246'
    return k + 1
  elseif t == 'userdata' then
    local mt = rawmeta(v)
    local done = mt and putCustom(v, mt, options, out, k)
    if done then return done end
  end
  error("can't encode " .. t)
end

function M.encode(v, options) -- value, options -- string
  local out = {}
  return concat(out, '', 1, put(v, options, out, 0))
end

-- Encoders that return a value's bytes, for options and __tocbor fields.
local function bytesOf(putter)
  return function(v, options)
    local out = {}
    return concat(out, '', 1, putter(v, options, out, 0))
  end
end
local function putUtf8(s, _, out, k)
  out[k + 1] = head(#s, 96); out[k + 2] = s
  return k + 2
end
local function putFloat(v, _, out, k)
  out[k + 1] = pack('>Bd', 251, v)
  return k + 1
end
M.type_encoders = {
  number = bytesOf(put), integer = bytesOf(put), float = bytesOf(putFloat),
  bytestring = bytesOf(put), utf8string = bytesOf(putUtf8), string = bytesOf(put),
  boolean = bytesOf(put), ['nil'] = bytesOf(put), userdata = bytesOf(put), ['function'] = bytesOf(put),
  table = bytesOf(putTable), array = bytesOf(putArray), map = bytesOf(putMap), ordered_map = bytesOf(putOrderedMap),
}
M.type_encoders.dict = M.type_encoders.map
-- Table encoders named in options or __tocbor run in place rather than through their strings.
putters = {
  [M.type_encoders.table] = putTable, [M.type_encoders.array] = putArray,
  [M.type_encoders.map] = putMap, [M.type_encoders.ordered_map] = putOrderedMap,
}

-- Decoding. The input is s, the next byte at, its last byte last; more, if set, returns further
-- input. Tags without a decoder in the options (options[tag]) or tagged_decoders become objects.
M.tagged_decoders = {}
local s, at, last, more, opts

local function fill(n) -- make s hold the n bytes from at
  local short = at + n - 1 - last
  local chunk = more and more(short)
  if type(chunk) ~= 'string' or chunk == '' then error('input too short') end
  s = sub(s, at) .. chunk; at = 1; last = #s
  if last < n then fill(n) end
end

local WIDE = {[2] = '>I2', [4] = '>I4', [8] = '>I8'}
local item

local function simple(n)
  if n == 24 then
    if at > last then fill(1) end
    n = byte(s, at); at = at + 1
  end
  if n == 20 then return false
  elseif n == 21 then return true
  elseif n == 22 then return null
  elseif n == 23 then return undefined
  elseif n == 25 then
    if at + 1 > last then fill(2) end
    local a, b = byte(s, at, at + 1); at = at + 2
    local sign, mantissa, exponent = a < 128 and 1 or -1, b + a * 256 % 1024, (a >> 2) % 32
    if exponent == 0 then return sign * (mantissa * 2.0 ^ -24) -- a float first, so -0 keeps its sign
    elseif exponent ~= 31 then return sign * (mantissa + 1024) * 2.0 ^ (exponent - 25)
    elseif mantissa == 0 then return sign * huge
    else return 0 / 0 end
  elseif n == 26 or n == 27 then
    local w = n == 26 and 4 or 8
    if at + w - 1 > last then fill(w) end
    local v = unpack(n == 26 and '>f' or '>d', s, at); at = at + w
    return v
  elseif n == 31 then return BREAK end
  if opts and opts.simple then return opts.simple(n) end
  return M.simple(n)
end

-- An indefinite-length string, array or map: items up to a break.
local function indefinite(major)
  local t, i, v = {}, 0, item()
  if major == 5 then
    while v ~= BREAK do t[v] = item(); v = item() end
    return t
  end
  while v ~= BREAK do i = i + 1; t[i] = v; v = item() end
  if major == 4 then return t end
  return concat(t)
end

function item()
  if at > last then fill(1) end
  local initial = byte(s, at); at = at + 1
  local major, n = initial >> 5, initial & 31
  if major == 7 then return simple(n) end
  if n >= 24 then
    if n == 24 then
      if at > last then fill(1) end
      n = byte(s, at); at = at + 1
    elseif n < 28 then
      local w = 1 << (n - 24)
      if at + w - 1 > last then fill(w) end
      n = unpack(WIDE[w], s, at); at = at + w
    elseif n == 31 and major >= 2 and major <= 5 then
      return indefinite(major)
    else
      error('invalid length')
    end
  end
  if major == 0 then return n
  elseif major == 1 then return -1 - n
  elseif major <= 3 then
    if n < 0 then error('invalid length') end
    if at + n - 1 > last then fill(n) end
    local v = sub(s, at, at + n - 1); at = at + n
    return v
  elseif major == 4 then
    local t = {}
    for i = 1, n do t[i] = item() end
    return t
  elseif major == 5 then
    local t = {}
    for _ = 1, n do local key = item(); t[key] = item() end
    return t
  end
  local v = item()
  local decoder = opts and opts[n] or M.tagged_decoders[n]
  if decoder then return decoder(v) end
  return M.tagged(n, v)
end

-- Decode one item; the state is restored after, so a tag decoder may decode too.
local function run(input, refill, options)
  local s0, at0, last0, more0, opts0 = s, at, last, more, opts
  s, at, last, more, opts = input, 1, #input, refill, options
  local ok, v = pcall(item)
  s, at, last, more, opts = s0, at0, last0, more0, opts0
  if not ok then error(v, 0) end
  return v
end

-- options: a table (options.more returns further input when it runs short, options.simple
-- decodes unknown simple values, options[tag] decodes a tag's value), or the more function alone.
function M.decode(input, options) -- string, options -- value
  local refill
  if type(options) == 'function' then refill, options = options, nil
  elseif type(options) == 'table' then refill = options.more
  elseif options ~= nil then
    error(("bad argument #2 to 'decode' (function or table expected, got %s)"):format(type(options)))
  end
  return run(input, refill, options)
end

function M.decode_file(reader, options) -- reader with read(n), options -- value; reads only the item's bytes
  return run('', function(n) return reader:read(n) end, options)
end

return M
