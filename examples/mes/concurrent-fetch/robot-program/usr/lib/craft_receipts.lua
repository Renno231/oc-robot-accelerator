-- Memory-only execution receipts. Active jobs are never evicted.
local receipts={}
local function encode(value,seen)
    local kind=type(value)
    if kind=="string" then return "s"..#value..":"..value end
    if kind=="number" then assert(value==value and math.abs(value)<math.huge,"Nonfinite request value.");return "n"..string.format("%.17g",value)..";" end
    if kind=="boolean" then return value and "t" or "f" end
    assert(kind=="table","Unsupported request value.")
    seen=seen or {};assert(not seen[value],"Cyclic request.");seen[value]=true
    local entries={}
    for k,v in pairs(value) do entries[#entries+1]=encode(k,seen)..encode(v,seen) end
    table.sort(entries);seen[value]=nil;return "{"..table.concat(entries).."}"
end
local function valid(id) return type(id)=="string" and #id>0 and #id<=160 and not id:find("%c") end
function receipts.new(options)
    options=options or {}
    local limit,maxBytes=options.limit or 16,options.maxBytes or 32768
    assert(type(limit)=="number" and limit>=1 and limit%1==0 and limit<math.huge,"Invalid receipt limit.")
    assert(type(maxBytes)=="number" and maxBytes>=1 and maxBytes<math.huge,"Invalid receipt memory budget.")
    local jobs,terminal,bytes={},{},0
    local registry={}
    local function view(job)
        return {jobId=job.id,status=job.status,message=job.message,receipt=true}
    end
    local function trim()
        while #terminal>limit or bytes>maxBytes do
            local id=table.remove(terminal,1);if not id then break end
            bytes=bytes-#jobs[id].request-#(jobs[id].message or "");jobs[id]=nil
        end
    end
    function registry.lookup(id,owner)
        if not valid(id) then return nil,"Invalid job ID." end
        local job=jobs[id]
        if not job then return {jobId=id,status="NOT_FOUND",message="No retained receipt; this does not prove the job never executed."} end
        if job.owner~=owner then return nil,"Receipt belongs to a different sender." end
        return view(job)
    end
    function registry.begin(id,owner,plan,retryOnly)
        if not valid(id) then return nil,"Invalid job ID." end
        local ok,request=pcall(encode,plan);if not ok then return nil,tostring(request) end
        local old=jobs[id]
        if old then
            if old.owner~=owner or old.request~=request then return nil,"Job ID already belongs to a different sender or request." end
            return false,view(old)
        end
        if retryOnly then return false,assert(registry.lookup(id,owner)) end
        -- A single active request may exceed the terminal budget; it remains
        -- available while running and is discarded only after completion.
        jobs[id]={id=id,owner=owner,request=request,status="RUNNING",message="Crafting job is running."}
        bytes=bytes+#request+#jobs[id].message;trim()
        return true,view(jobs[id])
    end
    function registry.finish(id,status,message)
        local job=assert(jobs[id],"Unknown active job.")
        assert(job.status=="RUNNING" and (status=="COMPLETE" or status=="FAILED"),"Invalid receipt transition.")
        local oldMessage=#(job.message or "")
        job.status=status;job.message=message and tostring(message):sub(1,2048) or nil
        bytes=bytes+#(job.message or "")-oldMessage
        local result=view(job);terminal[#terminal+1]=id;trim();return result
    end
    return registry
end
return receipts
