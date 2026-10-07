-- One connection lifecycle per job: discovery, handshake, renewable idle timeout,
-- optional absolute job deadline, and cleanup on completion/error/interruption.
local event = require "event"
local craftClient = {}

local function sessionDetailed(plan, options, querying)
    options = options or {}
    -- Choice blueprints live on the client/filesystem, not in the single modem
    -- packet. The robot receives only the already prepared execution contract.
    if type(plan)=="table" and plan.blueprint then
        local payload={};for k,v in pairs(plan) do if k~="blueprint" then payload[k]=v end end
        plan=payload
    end
    local net = options.network or require("gatenet").new()
    local service = options.service or "craftServer"
    local jobId=options.jobId or require("uuid").next()
    local serverAddress=options.serverAddress
    local receiptStatus
    local port = options.port or 5990
    local done, completed, reason = false, false, nil
    local promise, discoveryTimer, jobTimer
    local found, submitted, terminalStatus = false, false, nil
    local cleanupErrors = {}
    local function log(message) if options.onMessage then options.onMessage(message) end end
    local function finish(success, message)
        if done then return end
        done, completed, reason = true, success, message
        if promise then
            local disconnectOk, disconnectError = pcall(function()
                if promise:isActive() then promise:disconnect({reason = message}) end
            end)
            if not disconnectOk then cleanupErrors[#cleanupErrors + 1] = "Disconnect failed: " .. tostring(disconnectError) end
        end
    end
    local function idleTimeout(self)
        self:timeout(options.idleTimeout or 60, function()
            finish(false, "Crafting server stopped responding (idle timeout).")
        end)
    end
    local function session()
        local function connect(sender)
            found = true
            serverAddress=sender
            if discoveryTimer then event.cancel(discoveryTimer); discoveryTimer = nil end
            promise = net:connect(sender, port, {clientInfo = "CraftingClient",receiptControl=querying or options.jobId~=nil})
            if not promise:isActive() then finish(false, "Unable to initiate connection."); return end
            promise:next(function(self)
                self:clearTimeout()
                idleTimeout(self)
                local deadline = options.jobTimeout == nil and 300 or options.jobTimeout
                if deadline > 0 then
                    jobTimer = event.timer(deadline, function()
                        finish(false, "Crafting job exceeded its total timeout.")
                    end)
                end
                -- A send attempt is conservatively ambiguous until terminal status.
                submitted = true
                self:sendData({command = querying and "job_status" or "craft",plan=plan,jobId=jobId,retryOnly=options.jobId~=nil})
            end):next(function(self, update)
                self:looping(true)
                if update.hdr[net.HDR_KEYS.TYP] ~= net.PACKET_TYPES.DATA then return end
                local data = update.pld
                if type(data) ~= "table" then log(tostring(data)); idleTimeout(self); return end
                if data.jobId and data.jobId~=jobId then return end
                if querying and data.jobId~=jobId then return end
                if data.status == "COMPLETE" then
                    terminalStatus = "complete"
                    finish(true, data.message or "Crafting complete.")
                elseif data.status == "FAILED" then
                    terminalStatus = querying and data.receipt~=true and "unknown" or "failed"
                    finish(false, data.message or "Crafting failed.")
                elseif data.status=="RUNNING" or data.status=="NOT_FOUND" then
                    receiptStatus=data.status=="RUNNING" and "running" or "not_found"
                    terminalStatus=querying and receiptStatus or "unknown"
                    finish(false,data.message or "Execution outcome is not terminal; do not blindly retry.")
                else
                    log(tostring(data.status or "UPDATE") .. ": " .. tostring(data.message or ""))
                    idleTimeout(self)
                end
            end):catch(function(_, message)
                finish(false, tostring(message))
            end):finally(function()
                if not done then finish(false, "Connection closed before crafting completed.") end
            end):timeout(options.connectTimeout or 10, function()
                finish(false, "Crafting server handshake timed out.")
            end)
        end
        if not serverAddress then
            net:listen(net.INTERNAL_EVENT_NAMES.DISCOVERY_ANNOUNCE, function(sender, receivedPort, packet)
                if done or found or receivedPort ~= port or
                    packet.hdr[net.HDR_KEYS.TYP] ~= net.PACKET_TYPES.DISC_ANN or
                    type(packet.pld) ~= "table" or packet.pld.serviceName ~= service then return end
                if packet.pld.status == "Busy" then log("Crafting robot is busy."); return end
                connect(sender)
            end)
        end
        if not net:startListener() then finish(false, "Unable to start network listener."); return end
        if serverAddress then connect(serverAddress)
        else
            discoveryTimer = event.timer(options.discoveryTimeout or 15, function()
                finish(false, "No ready crafting server found.")
            end)
            local sent, err = net:broadcastDiscoveryQuery(port, {service = service})
            if not sent then finish(false, err or "Discovery broadcast failed.") end
        end
        while not done do
            if options.shouldContinue and not options.shouldContinue() then
                finish(false, "Crafting cancelled.")
            else
                event.pull(0.1)
            end
        end
    end
    local ok, err = xpcall(session, debug.traceback)
    if not ok then finish(false, err) end
    for _, timer in pairs({discoveryTimer, jobTimer}) do
        local cancelOk, cancelError = pcall(event.cancel, timer)
        if not cancelOk then cleanupErrors[#cleanupErrors + 1] = tostring(cancelError) end
    end
    local cleanupOk, cleanupError = pcall(net.shutdown, net)
    if not cleanupOk then cleanupErrors[#cleanupErrors + 1] = "Network cleanup failed: " .. tostring(cleanupError) end
    return {status = terminalStatus or ((submitted or querying) and "unknown" or "failed"),
        success = completed, message = reason, mayHaveExecuted = submitted,
        jobId=jobId,serverAddress=serverAddress,receiptStatus=receiptStatus,queried=querying or nil,
        cleanupError = #cleanupErrors > 0 and table.concat(cleanupErrors, "; ") or nil}
end

function craftClient.runDetailed(plan,options)
    if options and options.jobId and not options.serverAddress then
        return {status="unknown",success=false,mayHaveExecuted=true,jobId=options.jobId,
            message="An existing job ID requires its original robot address; use a receipt query."}
    end
    return sessionDetailed(plan,options,false)
end
function craftClient.query(serverAddress,jobId,options)
    if type(serverAddress)~="string" or serverAddress=="" or type(jobId)~="string" or jobId=="" then
        return {status="unknown",success=false,mayHaveExecuted=true,message="Query requires the original robot address and job ID."}
    end
    local o={};for k,v in pairs(options or {}) do o[k]=v end
    o.serverAddress=serverAddress;o.jobId=jobId
    local result=sessionDetailed(nil,o,true);result.mayHaveExecuted=true
    return result
end

-- Keep the original two-return API for existing callers.
function craftClient.run(plan, options)
    local result = craftClient.runDetailed(plan, options)
    if result.cleanupError then return false, result.cleanupError end
    return result.success, result.message
end

return craftClient
