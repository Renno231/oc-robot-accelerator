local cbor=require("cbor")
local fs=require("filesystem")
local serialization=require("serialization")
local M={}
-- A computer has few file handles (16 by default) and a store is written from any
-- process, so a file is open only while one write or compaction runs. Opening a
-- file costs call budget (and a tick once spent), so the log variant keeps changes
-- in memory until flush and writes them with one open.
-- fill(out) passes the bytes to write to out, one piece at a time.
local function write(path,mode,fill)
  local f=assert(io.open(path,mode))
  local ok,err=pcall(function()
    fill(function(bytes) assert(f:write(bytes)) end)
    assert(f:flush())
  end)
  local closed,why=f:close()
  assert(ok,err);assert(closed~=false,why or "close failed")
end
function M.open(path,variant)
  local cfg=io.open("/etc/store.cfg","r")
  local settings={}
  if cfg then settings=serialization.unserialize(cfg:read("*a"));cfg:close() end
  variant=variant or settings.variant or "log"
  -- pending: the latest unwritten change of each key, in the order first changed.
  local current,rows,live,pending,slot={},0,0,{},{}
  local s={}
  local function filename(key)
    return path.."/"..key:gsub("[^%w_]",function(b) return string.format("%%%02X",b:byte()) end)
  end
  if variant=="files" then
    if not fs.exists(path) then assert(fs.makeDirectory(path)) end
  elseif fs.exists(path..".new") then assert(fs.remove(path..".new")) end
  function s:load()
    local records={};current={};rows=0;live=0;pending={};slot={}
    if variant=="files" then
      for name in fs.list(path) do
        local f=assert(io.open(path.."/"..name,"rb"));local bytes=f:read("*a");f:close()
        local key=name:gsub("%%(%x%x)",function(hex) return string.char(tonumber(hex,16)) end)
        records[key]=cbor.decode(bytes);current[key]=bytes;live=live+1
      end
    elseif fs.exists(path) then
      local f=assert(io.open(path,"rb"));local offset=0
      while true do
        local first=f:read(1);if not first then break end
        local start=offset;local reader={}
        function reader:read(n)
          local bytes=first or "";first=nil
          if #bytes<n then bytes=bytes..(f:read(n-#bytes) or "") end
          offset=offset+#bytes;assert(#bytes==n,"truncated CBOR")
          return bytes
        end
        local ok,r=pcall(cbor.decode_file,reader)
        if not ok then f:close();error(path.." at byte "..start..": "..tostring(r)) end
        rows=rows+1;records[r.k]=r.v
        if r.v==nil then if current[r.k] then live=live-1 end
        elseif not current[r.k] then live=live+1 end
        current[r.k]=r.v~=nil and cbor.encode(r.v) or nil
      end
      f:close()
    end
    return records
  end
  -- Rewrite the live records in one pass once the log is twice their size. Records
  -- are rebuilt from their stored bytes: {k=key,v=value} is a two-entry CBOR map.
  local function compact()
    local k,v,n=cbor.encode("k"),cbor.encode("v"),0
    write(path..".new","wb",function(out)
      for key,bytes in pairs(current) do out("\162"..k..cbor.encode(key)..v..bytes);n=n+1 end
    end)
    assert(os.rename(path..".new",path));rows=n
  end
  local function append(key,value)
    local i=slot[key] or #pending+1;slot[key]=i;pending[i]=cbor.encode({k=key,v=value})
  end
  function s:put(key,value)
    local bytes=cbor.encode(value);if current[key]==bytes then return end
    if not current[key] then live=live+1 end;current[key]=bytes
    if variant=="files" then write(filename(key),"wb",function(out) out(bytes) end) else append(key,value) end
  end
  function s:delete(key)
    if not current[key] then return end
    current[key]=nil;live=live-1
    if variant=="files" then assert(fs.remove(filename(key))) else append(key) end
  end
  -- Changes since the last flush are written in one open; the files variant writes
  -- each put or delete when it is made.
  function s:flush()
    if #pending==0 then return end
    write(path,"ab",function(out) for _,bytes in ipairs(pending) do out(bytes) end end)
    rows=rows+#pending;pending={};slot={}
    if rows>math.max(16,2*live) then compact() end
  end
  function s:close() s:flush() end
  return s
end
return M
