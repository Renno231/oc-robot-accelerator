local hosts = {}
local fs = require("filesystem")
local io = require("io")
local serialization = require("serialization")
local computer = require("computer")
local HOSTS_FILE = "/etc/tnet.hosts"

local function hostname()
    if not fs.exists("/etc/hostname") then return nil end
    local f = io.open("/etc/hostname", "r")
    if not f then return nil end
    local name = f:read("*a")
    f:close()
    name = type(name) == "string" and name:match("^%s*(.-)%s*$") or nil
    return name ~= "" and name or nil
end

-- In-memory cache
local cachedHosts = {}
local selfHost, saveHosts = nil

-- Ensure directory and file exist
local function ensureHostsFile()
    if not fs.exists("/etc") then fs.makeDirectory("/etc") end
    if not fs.exists(HOSTS_FILE) then
        local f = fs.open(HOSTS_FILE, "w")
        f:write(serialization.serialize(cachedHosts))
        f:close()
    end
end

-- Load hosts from file (only called once at module load)
local function loadHosts()
    ensureHostsFile()
    local f = io.open(HOSTS_FILE, "r")
    local data = f:read("*a")
    f:close()
    if data == "" then 
        cachedHosts = {}
        return {} 
    end
    cachedHosts = serialization.unserialize(data) or {}
    return cachedHosts
end

-- Save hosts to file (only called when changes are made)
function saveHosts()
    ensureHostsFile()
    local f = fs.open(HOSTS_FILE, "w")
    f:write(serialization.serialize(cachedHosts))
    f:close()
end

-- Initialize cache when module loads
loadHosts()

-- Get the computer's own address
local function getSelfAddress()
    if computer.address then
        return computer.address()
    end
    return nil
end

-- Key merging function with collision detection
local function mergeKeys(existingKeys, newKeys, overwrite)
    existingKeys = existingKeys or {}
    newKeys = newKeys or {}
    local result = {}
    local conflict = false
    local conflictKey = nil

    -- Copy existing keys
    for k, v in pairs(existingKeys) do
        result[k] = v
    end

    -- Add new keys with collision detection
    for k, v in pairs(newKeys) do
        if existingKeys[k] then
            if overwrite then
                result[k] = v
            else
                conflict = true
                conflictKey = k
                break
            end
        else
            result[k] = v
        end
    end

    if conflict then
        return false, "Key collision on '" .. conflictKey .. "' and overwrite is false"
    end

    return true, result
end

-- Host object interface
local Host = {}
Host.__index = Host
function Host:getAddress() return self._data.address end
function Host:getName() return self._data.name end
function Host:getWakeKey() return self._data.wake end
function Host:getKeys() return self._data.keys or {} end
function Host:get(key) return self._data.keys and self._data.keys[key] end
function Host:getCID() return self._data.cid end

-- Main API
function hosts.getHost(addressOrName)
    for _, h in ipairs(cachedHosts) do
        if h.address == addressOrName or h.name == addressOrName then
            return setmetatable({_data = h}, Host)
        end
    end
    return nil
end

function hosts.getAll()
    local result = {}
    for i, h in ipairs(cachedHosts) do
        result[i] = setmetatable({_data = h}, Host)
    end
    return result
end

function hosts.addHost(address, cid, name, wake, keys, overwrite)
    if cid == getSelfAddress() and (name == nil or name == "") then
        name = hostname()
    end
    -- Check for duplicate name, address, or CID
    for _, h in ipairs(cachedHosts) do
        if h.name == name or h.address == address or h.cid == cid then
            if not overwrite then
                return false, "Host already exists. Use overwrite=true to replace."
            end
        end
    end

    -- Find existing host to merge keys
    local existingHost = nil
    for _, h in ipairs(cachedHosts) do
        if h.name == name or h.address == address or h.cid == cid then
            existingHost = h
            break
        end
    end

    -- Merge keys if existing host found
    local finalKeys = keys or {}
    if existingHost and existingHost.keys then
        local success, mergedKeys = mergeKeys(existingHost.keys, keys, overwrite)
        if not success then
            return false, mergedKeys -- mergedKeys contains error message
        end
        finalKeys = mergedKeys
    end

    -- Remove existing entry if overwriting
    if existingHost then
        for i, h in ipairs(cachedHosts) do
            if h.name == name or h.address == address or h.cid == cid then
                table.remove(cachedHosts, i)
                break
            end
        end
    end

    -- Add new host
    local newHost = {
        address = address,
        cid = cid,
        name = name,
        wake = wake,
        keys = finalKeys,
        paired_at = computer.uptime()
    }
    table.insert(cachedHosts, newHost)
    saveHosts()
    
    -- Update self host cache
    if selfHost and cid == getSelfAddress() then
        selfHost = setmetatable({_data = newHost}, Host)
    end
    
    return true
end

function hosts.removeHost(addressOrName)
    for i, h in ipairs(cachedHosts) do
        if h.address == addressOrName or h.name == addressOrName then
            table.remove(cachedHosts, i)
            saveHosts()
            
            -- Clear self host cache if needed
            if selfHost and (h.address == getSelfAddress() or h.name == addressOrName or h.cid == getSelfAddress()) then
                selfHost = nil
            end
            
            return true
        end
    end
    return false, "Host not found"
end

-- Get the device's own host information
function hosts.localhost()
    if selfHost then
        if not selfHost._data.name or selfHost._data.name == "" then
            selfHost._data.name = hostname()
        end
        return selfHost
    end
    
    local selfCID = getSelfAddress()
    if not selfCID then
        return nil
    end
    
    for _, h in ipairs(cachedHosts) do
        if h.cid == selfCID then
            if not h.name or h.name == "" then h.name = hostname() end
            selfHost = setmetatable({_data = h}, Host)
            return selfHost
        end
    end
    
    return nil
end

function hosts.reload()
    loadHosts()
    selfHost = nil
end

return hosts
