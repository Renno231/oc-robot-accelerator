local cbor=require("cbor")
local fs=require("filesystem")
local serialization=require("serialization")
local M={}
function M.open(path,variant)
  local cfg=io.open("/etc/store.cfg","r")
  local settings={}
  if cfg then settings=serialization.unserialize(cfg:read("*a"));cfg:close() end
  variant=variant or settings.variant or "log"
  local current,rows,live,handle,staging={},0,0
  local s={}
  local function filename(key)
    return path.."/"..key:gsub("[^%w_]",function(b) return string.format("%%%02X",b:byte()) end)
  end
  if variant=="files" then
    if not fs.exists(path) then assert(fs.makeDirectory(path)) end
  else
    if fs.exists(path..".new") then assert(fs.remove(path..".new")) end
    handle=assert(io.open(path,"ab"))
  end
  function s:load()
    local records={};current={};rows=0;live=0
    if variant=="files" then
      for name in fs.list(path) do
        local f=assert(io.open(path.."/"..name,"rb"));local bytes=f:read("*a");f:close()
        local key=name:gsub("%%(%x%x)",function(hex) return string.char(tonumber(hex,16)) end)
        records[key]=cbor.decode(bytes);current[key]=bytes;live=live+1
      end
    else
      assert(handle:flush())
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
  local function append(key,value)
    local bytes=cbor.encode({k=key,v=value})
    assert(handle:write(bytes));rows=rows+1
    if not staging and rows>math.max(16,2*live) then
      local keys={};for k in pairs(current) do keys[#keys+1]=k end
      staging={file=assert(io.open(path..".new","wb")),keys=keys,index=1,rows=0}
    end
    if staging then
      assert(staging.file:write(bytes));staging.rows=staging.rows+1
      local key=staging.keys[staging.index]
      while key and not current[key] do staging.index=staging.index+1;key=staging.keys[staging.index] end
      if key then
        assert(staging.file:write(cbor.encode({k=key,v=cbor.decode(current[key])})))
        staging.rows=staging.rows+1;staging.index=staging.index+1
      end
      if staging.index>#staging.keys then
        assert(staging.file:flush());staging.file:close();handle:close()
        assert(os.rename(path..".new",path));handle=assert(io.open(path,"ab"))
        rows=staging.rows;staging=nil
      end
    end
  end
  function s:put(key,value)
    local bytes=cbor.encode(value);if current[key]==bytes then return end
    if not current[key] then live=live+1 end;current[key]=bytes
    if variant=="files" then
      local f=assert(io.open(filename(key),"wb"));assert(f:write(bytes));f:close()
    else append(key,value) end
  end
  function s:delete(key)
    if not current[key] then return end
    current[key]=nil;live=live-1
    if variant=="files" then assert(fs.remove(filename(key))) else append(key) end
  end
  function s:flush() if handle then assert(handle:flush()) end end
  function s:close()
    if staging then staging.file:close() end
    if handle then handle:close() end
  end
  return s
end
return M
