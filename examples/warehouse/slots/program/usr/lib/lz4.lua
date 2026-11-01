-- LZ4 blocks (the LZ4 block format, without the frame format around it).
--
-- A block is a run of sequences. Each starts with a token byte: high nibble the literal count, low
-- nibble the match length minus 4; a nibble of 15 continues in following bytes, each added, until
-- one is below 255. Then the literals, then a 16-bit little-endian offset back into the output
-- (1..65535) and the match, which may overlap what it is copying. The last sequence is literals
-- only: matches stop 5 bytes before the end and start at least 12 bytes before it.
local M = {}
local byte, char, sub, rep, concat = string.byte, string.char, string.sub, string.rep, table.concat

local WINDOW, MINMATCH, LASTLITERALS, MFLIMIT = 65535, 4, 5, 12
local DEPTH = 32   -- earlier occurrences of a 4-byte prefix tried per position

local function extra(n)   -- a length's continuation bytes past the 15 in its nibble
  return rep('\255', (n - 15) // 255) .. char((n - 15) % 255)
end

function M.compress(input)
  local n, out, k = #input, {}, 0
  -- Positions by their 4-byte prefix: head[prefix] is the latest, before[p % 65536] the one before p.
  local head, before = {}, {}
  local function index(p)
    local a, b, c, d = byte(input, p, p + 3)
    local key = a << 24 | b << 16 | c << 8 | d
    before[p % 65536] = head[key]; head[key] = p
  end
  local function emit(from, to, offset, len)   -- literals input[from, to), then a match if any
    local lits, ml = to - from, len and len - MINMATCH or 0
    k = k + 1; out[k] = char((lits < 15 and lits or 15) << 4 | (ml < 15 and ml or 15))
    if lits >= 15 then k = k + 1; out[k] = extra(lits) end
    if lits > 0 then k = k + 1; out[k] = sub(input, from, to - 1) end
    if len then
      k = k + 1; out[k] = char(offset & 255, offset >> 8)
      if ml >= 15 then k = k + 1; out[k] = extra(ml) end
    end
  end
  local anchor, at, limit = 1, 1, n - MFLIMIT + 1
  while at <= limit do
    local a, b, c, d = byte(input, at, at + 3)
    local p, tries = head[a << 24 | b << 16 | c << 8 | d], DEPTH
    local most, len, from = n - LASTLITERALS - at + 1, 0, nil
    -- A slot is only reused 65536 positions later, so the chain is intact across the window.
    while p and p >= at - WINDOW and tries > 0 do
      if len == 0 or byte(input, p + len) == byte(input, at + len) then
        local m = MINMATCH
        while m < most and byte(input, p + m) == byte(input, at + m) do m = m + 1 end
        if m > len then
          len, from = m, p
          if len == most then break end
        end
      end
      p, tries = before[p % 65536], tries - 1
    end
    index(at)
    if len >= MINMATCH then
      emit(anchor, at, at - from, len)
      for q = at + 1, at + len - 1 do if q + 3 <= n then index(q) end end
      at = at + len; anchor = at
    else
      at = at + 1
    end
  end
  emit(anchor, n + 1)
  return concat(out)
end

local function length(input, at)   -- continuation bytes of a length nibble of 15
  local add = 0
  repeat
    local b = byte(input, at)
    if not b then error('Truncated LZ4 length', 0) end
    at, add = at + 1, add + b
  until b < 255
  return add, at
end

function M.decompress(input)
  local n, at = #input, 1
  local done = {}                             -- the output so far, merged into chunks
  local out, starts, k, size = {}, {}, 0, 0   -- newer pieces, and where each starts in the output
  -- The window as one string, holding output [held, held + #window). Merging is deferred until a
  -- match reaches past it and enough pieces have built up; until then such matches read the pieces.
  local window, held = '', 1
  local function put(s)
    k = k + 1; out[k], starts[k], size = s, size + 1, size + #s
  end
  local function merge()
    local chunk = concat(out, '', 1, k)
    done[#done + 1], window = chunk, sub(window .. chunk, -WINDOW)
    held, out, starts, k = size - #window + 1, {}, {}, 0
  end
  local function source(from, last)
    if last >= held + #window and k > 32 then merge() end
    if last < held + #window then return sub(window, from - held + 1, last - held + 1) end
    local j = k
    while j > 1 and starts[j] > from do j = j - 1 end
    local base, s = starts[j], concat(out, '', j, k)
    if from < base then s, base = sub(window, from - held + 1) .. s, from end
    return sub(s, from - base + 1, last - base + 1)
  end
  while true do
    local token = byte(input, at)
    if not token then error('Truncated LZ4 block', 0) end
    at = at + 1
    local lits = token >> 4
    if lits == 15 then local add; add, at = length(input, at); lits = lits + add end
    if lits > 0 then
      if at + lits - 1 > n then error('Truncated LZ4 literals', 0) end
      put(sub(input, at, at + lits - 1))
      at = at + lits
    end
    if at > n then break end
    if at + 1 > n then error('Truncated LZ4 offset', 0) end
    local lo, hi = byte(input, at, at + 1)
    at = at + 2
    local offset, len = lo | hi << 8, (token & 15) + MINMATCH
    if len == 19 then local add; add, at = length(input, at); len = len + add end
    if offset == 0 or offset > size then error('Invalid LZ4 offset', 0) end
    local from = size - offset + 1
    local copy = source(from, from + len - 1 < size and from + len - 1 or size)
    if #copy < len then copy = sub(rep(copy, len // #copy + 1), 1, len) end
    put(copy)
  end
  done[#done + 1] = concat(out, '', 1, k)
  return concat(done)
end

return M
