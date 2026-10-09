-- One labelled data file per object. Listing is directory enumeration only.
local filesystem=require "filesystem"
local serialization=require "serialization"
local store={}
function store.validName(name)
    return type(name)=="string" and #name>0 and #name<=120 and name:match("%S") and
        name~="." and name~=".." and not name:find("/",1,true) and not name:find("\\",1,true) and not name:find("%c")
end
function store.new(directory,extension)
    local self={directory=directory,extension=extension}
    local function path(name)
        if not store.validName(name) then return nil,"Invalid saved-object label." end
        return filesystem.concat(self.directory,name..extension)
    end
    local function fileOperation(name,mode,fn)
        local p,err=path(name);if not p then return nil,err end
        local opened,f,why=pcall(io.open,p,mode)
        if not opened or not f then return nil,"Cannot open "..p..": "..tostring(why or f) end
        local ok,value,problem=pcall(fn,f)
        local closeOk,closed,closeError=pcall(f.close,f)
        if not ok then return nil,tostring(value) end
        if not closeOk or closed==false or closeError then return nil,"Cannot close "..p..": "..tostring(closeError or closed) end
        return value,problem
    end
    function self.save(name,value)
        local p,err=path(name);if not p then return nil,err end
        local ok,data=pcall(serialization.serialize,value)
        if not ok or type(data)~="string" then return nil,"Cannot serialize saved object: "..tostring(data) end
        local dirOk,made,problem=pcall(function()
            return filesystem.exists(self.directory) or filesystem.makeDirectory(self.directory)
        end)
        if not dirOk or not made then return nil,"Cannot create directory: "..tostring(problem or made) end
        return fileOperation(name,"w",function(f)
            local written,why=f:write(data);if not written then error(why or "Write failed.") end
            return true
        end)
    end
    function self.load(name)
        return fileOperation(name,"r",function(f)
            local data,err=f:read(math.huge);if not data then error(err or "Read failed.") end
            local value,why=serialization.unserialize(data)
            if type(value)~="table" then error(why or "Invalid saved data.") end
            return value
        end)
    end
    function self.list()
        local ok,result=pcall(function()
            if not filesystem.exists(self.directory) then return {} end
            local iterator,err=filesystem.list(self.directory);if not iterator then error(err or "List failed.") end
            local names={}
            for file in iterator do
                if file:sub(-#extension)==extension then
                    local name=file:sub(1,-#extension-1)
                    if store.validName(name) then names[#names+1]=name end
                end
            end
            table.sort(names);return names
        end)
        if not ok then return nil,tostring(result) end
        return result
    end
    function self.remove(name)
        local p,err=path(name);if not p then return nil,err end
        local ok,removed,why=pcall(filesystem.remove,p)
        if not ok or not removed then return nil,tostring(why or removed) end
        return true
    end
    return self
end
return store
