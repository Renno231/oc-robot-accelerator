-- Service-owned persistent API/pubsub pairs. Public async RPC actions return
-- immediately; only install/reconnect may block in api.connect. Foreground
-- compatibility functions below may pull events while waiting for results.
local event = require("event")
local computer = require("computer")
local craftClient = {}
local pool = {}
local installed, factSink, installedRows=false,nil,nil
local serviceOptions={}
local outstanding={}
local waiters={}
local ticking=false
local fact,silence
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
            proxy:getConnection():onClose(function()
                if entry.row then entry.row.connected=false end
                for request in pairs(outstanding) do if request.entry==entry then
                    request.active=false;outstanding[request]=nil
                    if request.method=='status' then
                        local job=entry.jobs[request.token]
                        if job then job.inspectPending=false;silence(entry,job) end
                        fact(request.token,'robot_status',{address=entry.address,jobId=request.jobId,unknown=true,reason='Crafting connection dropped before status reply.'})
                    end
                end end
                fact(nil,'robot_transport',{address=entry.address,state='disconnected',unknown=true})
                -- The service reconnects on announce; a foreground session gets
                -- one reconnect attempt, not a repeating retry timer.
                if not installed and next(entry.jobs) then entry.requested=true end
                event.push('craft_client')
            end)
            assert(entry.sub:subscribe('state',function(data)
                if type(data)=='table' and type(data.busy)=='boolean' then
                    fact(nil,'robot_status',{address=address,busy=data.busy,currentJobId=data.currentJobId})
                end
            end),'Unable to subscribe to robot state')
            for topic in pairs(entry.observers) do assert(observe(entry,topic),"Unable to resubscribe to crafting job.") end
            entry.generation=(entry.generation or 0)+1
        end)
        entry.connecting=false;entry.error=not ok and tostring(err) or nil
        if not ok then error(err,0) end
    end
    return entry
end
local function existing(address,options)
    local key=keyFor(address,options)
    local entry=pool[key]
    if not options.existingOnly and not installed then return craftClient.prepare(address,options) end
    assert(entry,"Crafting transport was not prepared by the main program.")
    assert(entry.proxy and entry.proxy:getConnection().connected,
        "Crafting transport is disconnected; wait for the robot to announce.")
    return entry
end
fact=function(token,what,data)
    -- The service sink must enqueue only. Its non-reentrant pump owns decisions.
    data.at=computer.uptime()
    local sink=waiters[token] or factSink
    if sink then
        local ok,err=pcall(sink,token,what,data)
        if not ok then craftClient.factError=tostring(err) end
    end
end
function craftClient.reboot(a)
for _,e in pairs(pool)do if e.address==a and e.proxy then e.proxy:close() end end
fact(nil,"robot_transport",{address=a,state="rebooted"})
craftClient.announce(a)
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
    if not catchup then job.silent=nil end
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
silence=function(entry,job)
    if not job then return end
    job.silent=2
    job.idleAt=computer.uptime()
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
        if method=='status' then silence(entry,entry.jobs[token]) end
        fact(token,"robot_transport",{address=entry.address,jobId=request.jobId,state="unknown",unknown=true,reason=tostring(err)})
        return nil,tostring(err)
    end
    return true
end
-- Called once by the owning service outside its state-machine advance. This
-- loads paired robots and may block while the public API performs handshakes.
-- The owning service arms a one-shot timer for nextDue; no polling timer here.
function craftClient.install(onFact,options)
    assert(type(onFact)=="function","Transport fact sink required")
    if installed then return installedRows end
    options=options or {};serviceOptions=options
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
function craftClient.announce(address)
    if not installed then return end
    local host=paired(address,serviceOptions.service or 'craftServer')
    local entry=entryFor(host,serviceOptions)
    if not entry.row then
        entry.row={address=entry.address,name=host:getName(),connected=false}
        installedRows[#installedRows+1]=entry.row
    end
    entry.requested=not connected(entry)
    table.sort(installedRows,function(a,b) return a.address<b.address end)
    event.push('craft_client')
end
function craftClient.nextDue()
    local due=math.huge
    for request in pairs(outstanding) do due=math.min(due,request.due) end
    for _,entry in pairs(pool) do
        if entry.requested and not entry.connecting then due=math.min(due,computer.uptime()) end
        for _,job in pairs(entry.jobs) do
            due=math.min(due,job.idleAt,job.endAt or math.huge)
            if connected(entry) and not job.inspectPending then due=math.min(due,job.reconcileAt or math.huge) end
        end
    end
    return due<math.huge and due or nil
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
            event.push('craft_client')
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
local function begin(entry,token,plan,jobId,options)
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
function craftClient.begin(token,address,plan,jobId,options)
    options=options or {}
    local ok,entry=pcall(actionEntry,address,options)
    if not ok then return nil,tostring(entry) end
    return begin(entry,token,plan,jobId,options)
end
local function inspect(entry,token,jobId,options)
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
function craftClient.inspect(token,address,jobId,options)
    options=options or {}
    local ok,entry=pcall(actionEntry,address,options)
    if not ok then return nil,tostring(entry) end
    return inspect(entry,token,jobId,options)
end
function craftClient.tick(now)
    if ticking then return end
    ticking=true
    local ok,err=xpcall(function()
        now=now or computer.uptime()
        for request in pairs(outstanding) do if now>=request.due then
            request.active=false;outstanding[request]=nil
            fact(request.token,request.method=="status" and "robot_status" or "robot_transport",
                {address=request.entry.address,jobId=request.jobId,state="unknown",unknown=true,reason="Crafting RPC response deadline exceeded."})
            local job=request.entry.jobs[request.token]
            if job then
                job.inspectPending=false
                if request.method=='status' then silence(request.entry,job)
                else job.reconcileAt=now end
            end
        end end
        -- Consume each announce once; failed connections wait for a new announce.
        for _,entry in pairs(pool) do
            if entry.requested and not entry.connecting then
                entry.requested=false
                local ready,why=pcall(craftClient.prepare,entry.address,entry.options)
                now=computer.uptime()
                if entry.row then entry.row.connected=connected(entry) or false end
                fact(nil,"robot_transport",{address=entry.address,state=ready and "ready" or "unknown",unknown=not ready or nil,reason=not ready and tostring(why) or nil})
                for _,job in pairs(entry.jobs) do
                    job.inspectPending=false;job.reconcileAt=now
                    -- The new connection's status RPC owns the next response deadline.
                    if ready then job.idleAt=math.huge end
                end
                break -- Continue other announces in another service turn, after queued facts.
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
                    local sent=inspect(entry,job.token,job.id,job.options)
                    if not sent then job.inspectPending=false;job.idleAt=now end
                end
            end end
        end
    end,debug.traceback)
    ticking=false
    if not ok then error(err,0) end
end
local function sessionDetailed(plan, options, querying)
    local o={};for k,v in pairs(options or {}) do o[k]=v end
    local jobId=o.jobId or (not querying and require('uuid').next()) or nil
    local token={};local entry,result,submitted
    local address=o.serverAddress
    waiters[token]=function(_,what,data)
        if result then return end
        if what=='robot_terminal' then result=data
        elseif querying and (what=='robot_status' or what=='robot_transport') then
            result=data
            local r=data.receipt
            result.status=r and (r.status=='COMPLETE' and 'complete' or r.status=='RUNNING' and 'running'
                or r.status=='NOT_FOUND' and 'not_found' or r.status=='FAILED' and r.receipt==true and 'failed') or 'unknown'
            result.success=result.status=='complete';result.reason=r and r.message or data.reason
        elseif what=='robot_progress' and o.onMessage and data.receipt.status~='RUNNING' then
            local ok,why=pcall(o.onMessage,tostring(data.receipt.status or 'UPDATE')..': '..tostring(data.receipt.message or ''))
            if not ok then result={status='unknown',reason=tostring(why)} end
        end
    end
    local ok,why=xpcall(function()
        address=paired(address,o.service or 'craftServer'):getAddress()
        local started=computer.uptime()
        entry=existing(address,o)
        if o.shouldContinue and not o.shouldContinue() then error('Crafting cancelled.',0) end
        if querying then
            o.rpcTimeout=o.rpcTimeout or o.connectTimeout or 10
            assert(inspect(entry,token,jobId,o))
        else
            local limit=o.jobTimeout==nil and 300 or o.jobTimeout
            if limit>0 then
                o.jobTimeout=limit-(computer.uptime()-started)
                assert(o.jobTimeout>0,'Crafting job exceeded its total timeout.')
            end
            o.retryOnly=o.jobId~=nil
            local sent,err=begin(entry,token,plan,jobId,o)
            submitted=sent==true;assert(sent,err)
        end
        while not result do
            if o.shouldContinue and not o.shouldContinue() then error('Crafting cancelled.',0) end
            craftClient.tick()
            if not result then
                local due=craftClient.nextDue()
                local timeout=due and math.max(0,due-computer.uptime()) or math.huge
                event.pull(timeout)
            end
        end
    end,debug.traceback)
    result=result or {status=(submitted or querying) and 'unknown' or 'failed',reason=not ok and why or nil}
    if entry then
        local job=entry.jobs[token]
        if job then forgetJob(entry,job);result.cleanupError=job.cleanupError end
        for request in pairs(outstanding) do if request.token==token then request.active=false;outstanding[request]=nil end end
    end
    waiters[token]=nil
    local r=result.receipt
    local message=result.reason or (result.status=='complete' and 'Crafting complete.' or result.status=='failed' and 'Crafting failed.')
    if not message and r and (r.status=='RUNNING' or r.status=='NOT_FOUND') then message='Execution outcome is not terminal; do not blindly retry.' end
    return {status=result.status,success=result.success==true,message=message or nil,
        mayHaveExecuted=submitted==true,jobId=jobId,serverAddress=address,queried=querying or nil,
        receiptStatus=r and (r.status=='RUNNING' and 'running' or r.status=='NOT_FOUND' and 'not_found') or nil,
        cleanupError=result.cleanupError,receipt=querying=='status' and r or nil}
end
-- Existing cproc status RPC, not discovery traffic. No reply means unknown.
function craftClient.status(address,options)
    local o={};for k,v in pairs(options or {}) do o[k]=v end;o.serverAddress=address
    local r=sessionDetailed(nil,o,'status').receipt
    return type(r)=='table' and type(r.busy)=='boolean' and r or nil
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
