-- Service-owned persistent API/pubsub pairs. Public async RPC actions return
-- immediately; only install/reconnect may block in api.connect. Foreground
-- compatibility functions below may pull events while waiting for results.
local event = require("event")
local computer = require("computer")
local craftClient = {}
local pool = {}
local installed, factSink, installedRows=false,nil,nil
local serviceOptions, reconnectCursor={},0
local outstanding={}
local ticking=false
local function paired(address,service)
    local hosts=require("hosts")
    local host=address and hosts.getHost(address) or nil
    if not address then
        local candidates={}
        for _,h in ipairs(hosts.getAll()) do
            if h:getKeys().service==service and h:getWakeKey() and h:getWakeKey()~="" then candidates[#candidates+1]=h end
        end
        table.sort(candidates,function(a,b) return a:getAddress()<b:getAddress() end)
        host=candidates[1]
    end
    assert(host and host:getKeys().service==service and type(host:getWakeKey())=="string" and host:getWakeKey()~="",
        "Crafting robot is not paired; use pair before crafting.")
    return host
end
local function keyFor(address,options)
    return address..":"..(options.port or 5990).."/"..(options.service or "craftServer")
end
local function observe(entry,topic)
    return entry.sub:subscribe(topic,function(data)
        for fn in pairs(entry.observers[topic] or {}) do fn(data) end
    end)
end
local function entryFor(host,options)
    local address=host:getAddress()
    local key=keyFor(address,options)
    local entry=pool[key]
    if not entry then
        entry={address=address,options={service=options.service,port=options.port,connectTimeout=options.connectTimeout},observers={},jobs={}}
        pool[key]=entry
    end
    return entry
end
function craftClient.prepare(address,options)
    options=options or {}
    local host=paired(address,options.service or "craftServer")
    address=host:getAddress()
    local entry=entryFor(host,options)
    if entry.connecting then return nil,"Crafting transport is being prepared" end
    if not entry.proxy or not entry.proxy:getConnection().connected then
        entry.connecting=true
        local ok,err=pcall(function()
            local proxy=require("api").connect(options.service or "craftServer",options.port or 5990,
                address,host:getWakeKey(),options.connectTimeout or 10)
            entry.proxy=proxy;entry.sub=require("pubsub").client(proxy:getConnection())
            for topic in pairs(entry.observers) do assert(observe(entry,topic),"Unable to resubscribe to crafting job.") end
            entry.generation=(entry.generation or 0)+1
        end)
        entry.connecting=false;entry.error=not ok and tostring(err) or nil
        if not ok then error(err,0) end
    end
    return entry
end
local function existing(address,options,check)
    local key=keyFor(address,options)
    local entry=pool[key]
    if not options.existingOnly and not installed then return craftClient.prepare(address,options) end
    assert(entry,"Crafting transport was not prepared by the main program.")
    if not entry.proxy or not entry.proxy:getConnection().connected then
        entry.requested=true
        local deadline=computer.uptime()+(options.connectTimeout or 10)
        while not entry.proxy or not entry.proxy:getConnection().connected do
            if check and not check() then return nil end
            if computer.uptime()>=deadline then error(entry.error or "Crafting transport reconnect deadline exceeded.",0) end
            event.pull(0.05)
        end
    end
    return entry
end
local function foregroundRPC(entry,name,check,...)
    local response
    entry.proxy:async(function(...) response=table.pack(...) end)[name](...)
    local deadline=computer.uptime()+10
    while not response and computer.uptime()<deadline do
        if check and not check() then return false,"Crafting request interrupted" end
        event.pull(0.01)
    end
    if not response then return false,"Timeout calling remote function: "..name end
    return table.unpack(response,1,response.n)
end
local function fact(token,what,data)
    -- The service sink must enqueue only. Its non-reentrant pump owns decisions.
    data.at=computer.uptime()
    if factSink then
        local ok,err=pcall(factSink,token,what,data)
        if not ok then craftClient.factError=tostring(err) end
    end
end
function craftClient.reboot(a)
for _,e in pairs(pool)do if e.address==a and e.proxy then e.proxy:close();e.reconnectAt=0 end end
fact(nil,"robot_transport",{address=a,state="rebooted"})
end
local function connected(entry)
    return entry and entry.proxy and entry.proxy:getConnection().connected
end
local function forgetJob(entry,job)
    if job.ended then return end
    job.ended=true;entry.jobs[job.token]=nil
    for request in pairs(outstanding) do
        if request.entry==entry and request.token==job.token and request.jobId==job.id then
            request.active=false;outstanding[request]=nil
        end
    end
    local topic="job:"..job.id
    local observers=entry.observers[topic]
    if observers then
        observers[job.observer]=nil
        if not next(observers) then
            entry.observers[topic]=nil
            local ok,err=pcall(entry.sub.unsubscribe,entry.sub,topic)
            if not ok then job.cleanupError="Unsubscribe failed: "..tostring(err) end
        end
    end
end
local function jobReceipt(entry,job,receipt,catchup)
    if job.ended or type(receipt)~="table" or receipt.jobId~=job.id then return end
    job.idleAt=computer.uptime()+(job.options.idleTimeout or 60)
    job.silent=nil
    local data={address=entry.address,jobId=job.id,receipt=receipt,mayHaveExecuted=job.submitted}
    if receipt.status=="COMPLETE" or receipt.status=="FAILED" or receipt.status=="NOT_FOUND" then
        data.status=receipt.status=="COMPLETE" and "complete" or
            (receipt.status=="NOT_FOUND" or (catchup and receipt.receipt~=true)) and "unknown" or "failed"
        data.success=data.status=="complete";data.unknown=data.status=="unknown" or nil
        data.reason=receipt.message
        forgetJob(entry,job);data.cleanupError=job.cleanupError
        fact(job.token,"robot_terminal",data)
    else fact(job.token,"robot_progress",data) end
end
local function ownedReceipt(entry,job,receipt,catchup)
    -- Only an admission or owner-scoped status RPC can prove ownership. The
    -- public job:<id> topic is shared by every paired controller.
    if type(receipt)=="table" and receipt.jobId==job.id and receipt.receipt==true then
        job.ownerConfirmed=true
    end
    jobReceipt(entry,job,receipt,catchup)
    if job.ownerConfirmed and not job.ended and job.candidate then
        local candidate=job.candidate;job.candidate=nil
        jobReceipt(entry,job,candidate,false)
    end
end
local function silence(entry,job)
    if not job or not job.silent then return end
    if job.silent==1 then job.silent=2;entry.proxy:close();job.idleAt=math.huge
    else job.idleAt=computer.uptime() end
end
local function asyncCall(entry,token,method,args,options,callback)
    local request={entry=entry,token=token,method=method,jobId=args[method=="craft" and 2 or 1],
        due=computer.uptime()+(options.rpcTimeout or 10),active=true,options=options}
    outstanding[request]=true
    local ok,err=pcall(function()
        entry.proxy:async(function(...)
            if not request.active then return end
            request.active=false;outstanding[request]=nil
            callback(...)
        end)[method](table.unpack(args,1,args.n))
    end)
    if not ok then
        request.active=false;outstanding[request]=nil
        silence(entry,entry.jobs[token])
        fact(token,"robot_transport",{address=entry.address,jobId=request.jobId,state="unknown",unknown=true,reason=tostring(err)})
        return nil,tostring(err)
    end
    return true
end
-- Called once by the owning service outside its state-machine advance. This
-- loads paired robots and may block while the public API performs handshakes.
-- The caller's one service timer subsequently drives tick; no second timer here.
function craftClient.install(onFact,options)
    assert(type(onFact)=="function","Transport fact sink required")
    if installed then return installedRows end
    options=options or {};serviceOptions=options
    local budget=options.reconnectAttemptsPerTick or 1
    assert(type(budget)=="number" and budget>=1 and budget<math.huge and budget%1==0,"Reconnect work budget must be a positive integer")
    local hosts={}
    for _,host in ipairs(require("hosts").getAll()) do
        if host:getKeys().service==(options.service or "craftServer") and host:getWakeKey() and host:getWakeKey()~="" then
            hosts[#hosts+1]=host
        end
    end
    table.sort(hosts,function(a,b) return a:getAddress()<b:getAddress() end)
    installed=true;factSink=onFact;installedRows={}
    for _,host in ipairs(hosts) do
        local address=host:getAddress()
        local ok,entry=pcall(craftClient.prepare,address,options)
        local row={address=address,name=host:getName(),connected=ok and connected(entry) or false}
        entryFor(host,options).row=row
        installedRows[#installedRows+1]=row
        fact(nil,"robot_transport",{address=address,state=row.connected and "ready" or "unknown",unknown=not row.connected or nil,
            reason=not ok and tostring(entry) or nil})
    end
    return installedRows
end
local function refreshPaired()
    -- Pairing can happen after the service was first required. Discover data
    -- here, but only the service tick's bounded connection work opens links.
    for _,host in ipairs(require("hosts").getAll()) do
        if host:getKeys().service==(serviceOptions.service or "craftServer") and host:getWakeKey() and host:getWakeKey()~="" then
            local entry=entryFor(host,serviceOptions)
            if not entry.row then
                entry.row={address=entry.address,name=host:getName(),connected=connected(entry) or false}
                installedRows[#installedRows+1]=entry.row
                fact(nil,"robot_transport",{address=entry.address,state="disconnected",unknown=true})
            end
        end
    end
    table.sort(installedRows,function(a,b) return a.address<b.address end)
end
local function actionEntry(address,options)
    assert(installed,"Install crafting transport service before submitting actions")
    local connectionOptions={service=options.service or serviceOptions.service,port=options.port or serviceOptions.port}
    local host=paired(address,connectionOptions.service or "craftServer")
    return assert(pool[keyFor(host:getAddress(),connectionOptions)],"Robot was not loaded by transport service installation")
end
local function registerJob(entry,token,jobId,options)
    if token==nil or type(jobId)~="string" or jobId=="" then return nil,"Request token and job ID required" end
    if entry.jobs[token] then return nil,"Request token already has a crafting job" end
    local now=computer.uptime()
    local job={token=token,id=jobId,options=options,idleAt=now+(options.idleTimeout or 60),submitted=false}
    local limit=options.jobTimeout==nil and 300 or options.jobTimeout
    if limit>0 then job.endAt=now+limit end
    job.observer=function(receipt)
        if job.ended or type(receipt)~="table" or receipt.jobId~=job.id then return end
        if not job.ownerConfirmed then
            -- An unverified publication must not renew idle time, emit success
            -- or cancel admission deadlines. Retain it until RPC proof arrives;
            -- the service tick reconciles using status only, never craft replay.
            if not job.candidate or (job.candidate.status~="COMPLETE" and job.candidate.status~="FAILED") then
                job.candidate=receipt
            end
            job.reconcileAt=computer.uptime()
            return
        end
        jobReceipt(entry,job,receipt,false)
    end
    local topic="job:"..jobId
    entry.observers[topic]=entry.observers[topic] or {};entry.observers[topic][job.observer]=true
    if connected(entry) then
        local subscribed,result=pcall(observe,entry,topic)
        if not subscribed or not result then
            forgetJob(entry,job);return nil,"Unable to subscribe to crafting job: "..tostring(result)
        end
    end
    entry.jobs[token]=job;job.submitted=true
    return job
end
function craftClient.adopt(token,address,jobId,options)
    options=options or {}
    local ok,entry=pcall(actionEntry,address,options)
    if not ok then return nil,tostring(entry) end
    local job,err=registerJob(entry,token,jobId,options)
    if not job then return nil,err end
    job.reconcileAt=computer.uptime()
    return true
end
function craftClient.begin(token,address,plan,jobId,options)
    options=options or {}
    local ok,entry=pcall(actionEntry,address,options)
    if not ok then return nil,tostring(entry) end
    if not connected(entry) then return nil,"Crafting transport is disconnected; robot state is unknown" end
    if type(plan)=="table" and plan.blueprint then
        local payload={};for k,v in pairs(plan) do if k~="blueprint" then payload[k]=v end end;plan=payload
    end
    local job,why=registerJob(entry,token,jobId,options)
    if not job then return nil,why end
    local now=computer.uptime()
    local sent,err=asyncCall(entry,token,"craft",table.pack(plan,jobId,options.retryOnly==true),options,function(rpcOK,disposition,receipt)
        if job.ended then return end
        if not rpcOK then
            job.reconcileAt=computer.uptime()
            fact(token,"robot_transport",{address=entry.address,jobId=jobId,state="unknown",unknown=true,reason=tostring(disposition)})
            return
        end
        fact(token,"robot_admitted",{address=entry.address,jobId=jobId,disposition=disposition,receipt=receipt,mayHaveExecuted=true})
        if disposition=="accepted" or disposition=="status" then
            ownedReceipt(entry,job,receipt,disposition=="status")
        else jobReceipt(entry,job,receipt,false) end
    end)
    if not sent then job.reconcileAt=now end
    -- Once attempted, this request may have executed even if send threw.
    return true,err
end
function craftClient.inspect(token,address,jobId,options)
    options=options or {}
    local ok,entry=pcall(actionEntry,address,options)
    if not ok then return nil,tostring(entry) end
    if not connected(entry) then return nil,"Crafting transport is disconnected; robot state is unknown" end
    return asyncCall(entry,token,"status",table.pack(jobId),options,function(rpcOK,receipt)
        local data={address=entry.address,jobId=jobId,receipt=rpcOK and receipt or nil}
        if not rpcOK or type(receipt)~="table" then
            data.unknown=true;data.reason=tostring(receipt)
        elseif jobId==nil then
            if type(receipt.busy)=="boolean" then data.busy=receipt.busy end
            if type(receipt.busy)~="boolean" then data.unknown=true end
            data.currentJobId=receipt.currentJobId
        end
        fact(token,"robot_status",data)
        local job=entry.jobs[token]
        if job and job.id==jobId then
            job.inspectPending=false
            if not rpcOK or type(receipt)~="table" then silence(entry,job) end
            if rpcOK then ownedReceipt(entry,job,receipt,true) end
        end
    end)
end
function craftClient.tick(now)
    if not installed or ticking then return end
    ticking=true
    local ok,err=xpcall(function()
        now=now or computer.uptime()
        refreshPaired()
        for request in pairs(outstanding) do if now>=request.due then
            request.active=false;outstanding[request]=nil
            fact(request.token,request.method=="status" and "robot_status" or "robot_transport",
                {address=request.entry.address,jobId=request.jobId,state="unknown",unknown=true,reason="Crafting RPC response deadline exceeded."})
            local job=request.entry.jobs[request.token]
            if job then silence(request.entry,job);job.inspectPending=false;job.reconcileAt=now end
        end end
        -- A work budget, not a fleet-size limit: one slow/offline robot cannot
        -- turn a tick into N sequential handshake waits. Rotate fairly over
        -- every paired robot, including those added after install.
        local entries={};for key,entry in pairs(pool) do entries[#entries+1]={key=key,entry=entry} end
        table.sort(entries,function(a,b) return a.key<b.key end)
        local budget=serviceOptions.reconnectAttemptsPerTick or 1
        local attempted=0
        for _=1,#entries do
            if attempted>=budget then break end
            reconnectCursor=reconnectCursor%#entries+1
            local entry=entries[reconnectCursor].entry
            if not connected(entry) and not entry.connecting and now>=(entry.reconnectAt or 0) then
                attempted=attempted+1
                fact(nil,"robot_transport",{address=entry.address,state="disconnected",unknown=true})
                for request in pairs(outstanding) do if request.entry==entry then
                    request.active=false;outstanding[request]=nil
                    if request.method=="status" then
                        fact(request.token,"robot_status",{address=entry.address,jobId=request.jobId,unknown=true,reason="Crafting connection dropped before status reply."})
                    end
                end end
                local ready,why=pcall(craftClient.prepare,entry.address,entry.options)
                now=computer.uptime()
                entry.reconnectAt=now+1;entry.requested=false
                if entry.row then entry.row.connected=connected(entry) or false end
                fact(nil,"robot_transport",{address=entry.address,state=ready and "ready" or "unknown",unknown=not ready or nil,reason=not ready and tostring(why) or nil})
                for _,job in pairs(entry.jobs) do job.inspectPending=false;job.reconcileAt=now end
            end
        end
        for _,entry in pairs(pool) do
            -- Snapshot because receipt callbacks can finish jobs during nested
            -- connect pulls. No state-machine decisions occur in this module.
            local jobs={};for _,job in pairs(entry.jobs) do jobs[#jobs+1]=job end
            for _,job in ipairs(jobs) do if not job.ended then
                if (job.endAt and now>=job.endAt) or now>=job.idleAt then
                    if not job.silent and not (job.endAt and now>=job.endAt) then
                        job.silent=1;job.idleAt=math.huge;job.reconcileAt=now
                    else
                    local reason=job.endAt and now>=job.endAt and "Crafting job exceeded its total timeout." or "Crafting server stopped responding (idle timeout)."
                    forgetJob(entry,job)
                    fact(job.token,"robot_terminal",{address=entry.address,jobId=job.id,status="unknown",unknown=true,success=false,
                        mayHaveExecuted=true,reason=reason,cleanupError=job.cleanupError})
                    end
                elseif job.reconcileAt and now>=job.reconcileAt and connected(entry) and not job.inspectPending then
                    job.reconcileAt=nil;job.inspectPending=true
                    local sent=craftClient.inspect(job.token,entry.address,job.id,job.options)
                    if not sent then job.inspectPending=false;job.reconcileAt=now+1 end
                end
            end end
        end
    end,debug.traceback)
    ticking=false
    if not ok then error(err,0) end
end
-- Existing cproc status RPC, not discovery traffic. No reply means unknown.
function craftClient.status(address,options)
    options=options or {}
    local ok,data=pcall(function()
        local host=paired(address,options.service or "craftServer")
        local entry=existing(host:getAddress(),options)
        local deadline=computer.uptime()+(options.rpcTimeout or options.connectTimeout or 10)
        local rpcOK,status=foregroundRPC(entry,"status",function() return computer.uptime()<deadline end)
        if rpcOK and type(status)=="table" and type(status.busy)=="boolean" then return status end
    end)
    return ok and data or nil
end

local function sessionDetailed(plan, options, querying)
    options = options or {}
    if type(plan)=="table" and plan.blueprint then
        local payload={};for k,v in pairs(plan) do if k~="blueprint" then payload[k]=v end end
        plan=payload
    end
    local service,port=options.service or "craftServer",options.port or 5990
    local jobId=options.jobId or require("uuid").next()
    local serverAddress=options.serverAddress
    local done,completed,reason=false,false,nil
    local submitted,terminalStatus,receiptStatus=false,nil,nil
    local entry,subscribed
    local idleUntil,jobUntil
    local ownerConfirmed,candidate=false,nil
    local cleanupErrors={}
    local function finish(success,message)
        if not done then done,completed,reason=true,success,message end
    end
    local function renew() idleUntil=computer.uptime()+(options.idleTimeout or 60) end
    local function check()
        if done then return false end
        if options.shouldContinue and not options.shouldContinue() then finish(false,"Crafting cancelled.")
        elseif jobUntil and computer.uptime()>=jobUntil then finish(false,"Crafting job exceeded its total timeout.")
        elseif idleUntil and computer.uptime()>=idleUntil then finish(false,"Crafting server stopped responding (idle timeout).") end
        return not done
    end
    local function update(data,catchup)
        if not check() or type(data)~="table" or data.jobId~=jobId then return end
        if data.status=="COMPLETE" then terminalStatus="complete";finish(true,data.message or "Crafting complete.")
        elseif data.status=="FAILED" then
            terminalStatus=(querying or catchup) and data.receipt~=true and "unknown" or "failed"
            finish(false,data.message or "Crafting failed.")
        elseif data.status=="NOT_FOUND" or data.status=="RUNNING" then
            receiptStatus=data.status=="RUNNING" and "running" or "not_found"
            if querying or data.status=="NOT_FOUND" then
                terminalStatus=querying and receiptStatus or "unknown"
                finish(false,data.message or "Execution outcome is not terminal; do not blindly retry.")
            else renew() end
        else
            if options.onMessage then
                local ok,err=pcall(options.onMessage,tostring(data.status or "UPDATE")..": "..tostring(data.message or ""))
                if not ok then finish(false,tostring(err));return end
            end
            renew()
        end
    end
    local function publication(data)
        if done or type(data)~="table" or data.jobId~=jobId then return end
        if not ownerConfirmed then
            if not candidate or (candidate.status~="COMPLETE" and candidate.status~="FAILED") then candidate=data end
            return
        end
        update(data,false)
    end
    local function ownedUpdate(data,catchup)
        if type(data)=="table" and data.jobId==jobId and data.receipt==true then ownerConfirmed=true end
        update(data,catchup)
        if ownerConfirmed and not done and candidate then
            local receipt=candidate;candidate=nil;update(receipt,false)
        end
    end
    local function rpc(name,...)
        if not check() then return false,reason end
        return foregroundRPC(entry,name,check,...)
    end
    local function connect()
        entry=existing(serverAddress,options,check)
        if not entry or not check() then return false end
        if not querying then
            -- Only one run observer per job; status queries never replace it.
            local topic="job:"..jobId
            entry.observers[topic]=entry.observers[topic] or {}
            entry.observers[topic][publication]=true
            subscribed=topic
            assert(observe(entry,topic),"Unable to subscribe to crafting job.")
        end
        return true
    end
    local function session()
        local host=paired(serverAddress,service)
        serverAddress=host:getAddress()
        renew()
        local deadline=options.jobTimeout==nil and 300 or options.jobTimeout
        if deadline>0 then jobUntil=computer.uptime()+deadline end
        if not connect() or not check() then return end
        if querying then
            local ok,data=rpc("status",jobId)
            if ok then update(data,true) else finish(false,tostring(data)) end
            return
        end
        -- Any attempted RPC may have executed. Never issue craft again automatically.
        submitted=true
        local ok,disposition,data=foregroundRPC(entry,"craft",function() return check() and not candidate end,
            plan,jobId,options.jobId~=nil)
        if ok then
            if disposition=="accepted" or disposition=="status" then ownedUpdate(data,disposition=="status")
            else update(data,false) end
        elseif check() and entry.proxy:getConnection().connected then
            -- A publication can arrive before (or instead of) admission. The
            -- foreground caller, not the pubsub callback, verifies its owner.
            local statusOk,receipt=rpc("status",jobId)
            if statusOk then ownedUpdate(receipt,true) else finish(false,tostring(receipt)) end
        end
        while check() do
            if not entry.proxy:getConnection().connected then
                if not connect() then return end
                local statusOk,receipt=rpc("status",jobId)
                if statusOk then ownedUpdate(receipt,true) else finish(false,tostring(receipt)) end
            else event.pull(0.1) end
        end
    end
    local ok,err=xpcall(session,debug.traceback)
    if not ok then finish(false,err) end
    if subscribed then
        local closed,why=pcall(function()
            local observers=entry.observers[subscribed]
            if observers then
                observers[publication]=nil
                if not next(observers) then entry.observers[subscribed]=nil;entry.sub:unsubscribe(subscribed) end
            end
        end)
        if not closed then cleanupErrors[#cleanupErrors+1]="Unsubscribe failed: "..tostring(why) end
    end
    return {status=terminalStatus or ((submitted or querying) and "unknown" or "failed"),
        success=completed,message=reason,mayHaveExecuted=submitted,jobId=jobId,
        serverAddress=serverAddress,receiptStatus=receiptStatus,queried=querying or nil,
        cleanupError=#cleanupErrors>0 and table.concat(cleanupErrors,"; ") or nil}
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
    local result=sessionDetailed(nil,o,true);result.mayHaveExecuted=true;return result
end
function craftClient.run(plan, options)
    local result=craftClient.runDetailed(plan,options)
    if result.cleanupError then return false,result.cleanupError end
    return result.success,result.message
end
return craftClient
