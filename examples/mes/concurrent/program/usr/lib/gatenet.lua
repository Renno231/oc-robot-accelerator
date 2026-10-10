--[[
    gatenet.lua - v2.1 (Internal Emitter)
    Abstraction layer for OpenComputers modem communication using CBOR,
    promises, internal events, and connection management.
--]]

local component = require("component")
local event = require("event") -- Still needed for the base modem_message listener
local computer = require("computer")
local gotCbor, cbor = pcall(require, "cbor")
if not gotCbor then
    local function a(b,c)local d,e=pcall(require,b)if not d then return end;if c then return e[c]end;return e end;local f=function(g)local d,h=load(function()local i=g;g=nil;return i end)if d and h then return h()end end;local setmetatable=setmetatable;local getmetatable=getmetatable;local j=debug.getmetatable;local assert=assert;local error=error;local type=type;local pairs=pairs;local ipairs=ipairs;local tostring=tostring;local k=string.char;local l=table.concat;local m=table.sort;local n=math.floor;local o=math.abs;local p=math.huge;local q=math.max;local r=math.maxinteger or 9007199254740992;local s=math.mininteger or-9007199254740992;local t=0/0;local u=math.frexp;local v=math.ldexp or function(w,x)return w*2.0^x end;local y=math.type or function(z)return z%1==0 and z<=r and z>=s and"integer"or"float"end;local A=string.pack or a("struct","pack")local B=string.unpack or a("struct","unpack")local C=a("bit32","rshift")or a("bit","rshift")or f"return function(a,b) return a >> b end"or function(D,E)return q(0,n(D/2^E))end;if A and A(">I2",0)~="\0\0"then A=nil end;if B and B(">I2","\1\2\3\4")~=0x102 then B=nil end;local F=nil;local G={}local function H(I,J)return G[type(I)](I,J)end;local function K(L,M)if M==0 and L<0 then L,M=-L-1,32 end;if L<24 then return k(M+L)elseif L<2^8 then return k(M+24,L)elseif L<2^16 then return k(M+25,C(L,8),L%0x100)elseif L<2^32 then return k(M+26,C(L,24)%0x100,C(L,16)%0x100,C(L,8)%0x100,L%0x100)elseif L<2^64 then local N=n(L/2^32)L=L%2^32;return k(M+27,C(N,24)%0x100,C(N,16)%0x100,C(N,8)%0x100,N%0x100,C(L,24)%0x100,C(L,16)%0x100,C(L,8)%0x100,L%0x100)end;error"int too large"end;if A then function K(L,M)local O;M=M or 0;if L<24 then O,M=">B",M+L elseif L<256 then O,M=">BB",M+24 elseif L<65536 then O,M=">BI2",M+25 elseif L<4294967296 then O,M=">BI4",M+26 else O,M=">BI8",M+27 end;return A(O,M,L)end end;local P={}function P:__tostring()return self.name or("simple(%d)"):format(self.value)end;function P:__tocbor()return self.cbor or K(self.value,224)end;local function Q(R,S,T)assert(R>=0 and R<=255,"bad argument #1 to 'simple' (integer in range 0..255 expected)")return setmetatable({value=R,name=S,cbor=T},P)end;local U={}function U:__tostring()return("%d(%s)"):format(self.tag,tostring(self.value))end;function U:__tocbor(J)return K(self.tag,192)..H(self.value,J)end;local function V(W,R)assert(W>=0,"bad argument #1 to 'tagged' (positive integer expected)")return setmetatable({tag=W,value=R},U)end;local X=Q(22,"null")local Y=Q(23,"undefined")local Z=Q(31,"break","\255")function G.number(L)return G[y(L)](L)end;function G.integer(L)if L<0 then return K(-1-L,32)end;return K(L,0)end;function G.float(L)if L~=L then return"\251\127\255\255\255\255\255\255\255"end;local _=(L>0 or 1/L>0)and 0 or 1;L=o(L)if L==p then return k(251,_*128+128-1).."\240\0\0\0\0\0\0"end;local a0,a1=u(L)if a0==0 then return k(251,_*128).."\0\0\0\0\0\0\0"end;a0=a0*2;a1=a1+1024-2;if a1<=0 then a0=a0*2^(a1-1)a1=0 else a0=a0-1 end;return k(251,_*2^7+n(a1/2^4)%2^7,a1%2^4*2^4+n(a0*2^4%0x100),n(a0*2^12%0x100),n(a0*2^20%0x100),n(a0*2^28%0x100),n(a0*2^36%0x100),n(a0*2^44%0x100),n(a0*2^52%0x100))end;if A then function G.float(L)return A(">Bd",251,L)end end;function G.bytestring(g)return K(#g,64)..g end;function G.utf8string(g)return K(#g,96)..g end;G.string=G.bytestring;function G.boolean(a2)return a2 and"\245"or"\244"end;G["nil"]=function()return"\246"end;function G.userdata(a3,J)local a4=j(a3)if a4 then local a5=J and J[a4]or a4.__tocbor;if a5 then return a5(a3,J)end end;error"can't encode userdata"end;function G.table(a6,J)local a4=getmetatable(a6)if a4 then local a7=J and J[a4]or a4.__tocbor;if a7 then return a7(a6,J)end end;local a8,a9,aa,ab={K(#a6,128)},{"\191"},1,2;local ac=true;for ad,ae in pairs(a6)do ac=ac and aa==ad;aa=aa+1;local af=H(ae,J)a8[aa]=af;a9[ab],ab=H(ad,J),ab+1;a9[ab],ab=af,ab+1 end;a9[1]=K(aa-1,160)return l(ac and a8 or a9)end;function G.array(a6,J)local a8={}for aa,ae in ipairs(a6)do a8[aa]=H(ae,J)end;return K(#a8,128)..l(a8)end;function G.map(a6,J)local a9,ab,ag={"\191"},2,0;for ad,ae in pairs(a6)do a9[ab],ab=H(ad,J),ab+1;a9[ab],ab=H(ae,J),ab+1;ag=ag+1 end;a9[1]=K(ag,160)return l(a9)end;G.dict=G.map;function G.ordered_map(a6,J)local a9={}if not a6[1]then local aa=0;for ad in pairs(a6)do aa=aa+1;a9[aa]=ad end;m(a9)end;for aa,ad in ipairs(a6[1]and a6 or a9)do a9[aa]=H(ad,J)..H(a6[ad],J)end;return K(#a9,160)..l(a9)end;G["function"]=function()error"can't encode function"end;local function ah(ai,ag)return ai:read(ag)end;local function aj(ai)return ai:read(1):byte()end;local function ak(ai,al)if al<24 then return al elseif al<28 then local am=0;for an=1,2^(al-24)do am=am*256+aj(ai)end;return am else error"invalid length"end end;local ao={}local function ap(ai)local aq=aj(ai)return C(aq,5),aq%32 end;local function ar(ai,J)local as,al=ap(ai)return ao[as](ai,al,J)end;local function at(ai,al)return ak(ai,al)end;local function au(ai,al)return-1-ak(ai,al)end;local function av(ai,al)if al~=31 then return ah(ai,ak(ai,al))end;local am={}local aa=1;local ae=ar(ai)while ae~=Z do am[aa],aa=ae,aa+1;ae=ar(ai)end;return l(am)end;local function aw(ai,al)return av(ai,al)end;local function ax(ai,al,J)local am={}if al==31 then local aa=1;local ae=ar(ai,J)while ae~=Z do am[aa],aa=ae,aa+1;ae=ar(ai,J)end else local ag=ak(ai,al)for aa=1,ag do am[aa]=ar(ai,J)end end;return am end;local function ay(ai,al,J)local am={}local ad;if al==31 then local aa=1;ad=ar(ai,J)while ad~=Z do am[ad],aa=ar(ai,J),aa+1;ad=ar(ai,J)end else local ag=ak(ai,al)for an=1,ag do ad=ar(ai,J)am[ad]=ar(ai,J)end end;return am end;local az={}local function aA(ai,al,J)local W=ak(ai,al)local R=ar(ai,J)local aB=J and J[W]or az[W]if aB then return aB(R)end;return V(W,R)end;local function aC(ai)local a1=aj(ai)local a0=aj(ai)local _=a1<128 and 1 or-1;a0=a0+a1*256%1024;a1=C(a1,2)%32;if a1==0 then return _*v(a0,-24)elseif a1~=31 then return _*v(a0+1024,a1-25)elseif a0==0 then return _*p else return t end end;local function aD(ai)local a1=aj(ai)local a0=aj(ai)local _=a1<128 and 1 or-1;a1=a1*2%256+C(a0,7)a0=a0%128;a0=a0*256+aj(ai)a0=a0*256+aj(ai)if a1==0 then return _*v(a1,-149)elseif a1~=0xff then return _*v(a0+2^23,a1-150)elseif a0==0 then return _*p else return t end end;local function aE(ai)local a1=aj(ai)local a0=aj(ai)local _=a1<128 and 1 or-1;a1=a1%128*16+C(a0,4)a0=a0%16;a0=a0*256+aj(ai)a0=a0*256+aj(ai)a0=a0*256+aj(ai)a0=a0*256+aj(ai)a0=a0*256+aj(ai)a0=a0*256+aj(ai)if a1==0 then return _*v(a1,-149)elseif a1~=0xff then return _*v(a0+2^52,a1-1075)elseif a0==0 then return _*p else return t end end;if B then function aD(ai)return B(">f",ah(ai,4))end;function aE(ai)return B(">d",ah(ai,8))end end;local function aF(ai,R,J)if R==24 then R=aj(ai)end;if R==20 then return false elseif R==21 then return true elseif R==22 then return X elseif R==23 then return Y elseif R==25 then return aC(ai)elseif R==26 then return aD(ai)elseif R==27 then return aE(ai)elseif R==31 then return Z end;if J and J.simple then return J.simple(R)end;return Q(R)end;ao[0]=at;ao[1]=au;ao[2]=av;ao[3]=aw;ao[4]=ax;ao[5]=ay;ao[6]=aA;ao[7]=aF;local function aG(g,J)local ai={}local aH=1;local aI;if type(J)=="function"then aI=J elseif type(J)=="table"then aI=J.more elseif J~=nil then error(("bad argument #2 to 'decode' (function or table expected, got %s)"):format(type(J)))end;if type(aI)~="function"then function aI()error"input too short"end end;function ai:read(aJ)local i=g:sub(aH,aH+aJ-1)if#i<aJ then i=aI(aJ-#i,ai,J)if i then self:write(i)end;return self:read(aJ)end;aH=aH+aJ;return i end;function ai:write(aJ)g=g..aJ;if aH>256 then g=g:sub(aH+1)aH=1 end;return#aJ end;return ar(ai,J)end; cbor = {encode=H,decode=aG,decode_file=ar,type_encoders=G,type_decoders=ao,tagged_decoders=az,simple=Q,tagged=V,null=X,undefined=Y}
end
local uuid = require("uuid")

-- Check for modem component
if not component.modem then
    error("gatenet requires a modem component", 0)
end
local modem = component.modem

-- --- Constants ---
local PROTO_VER = 1
local HDR_KEYS = { VER = "v", SRC = "s", CID = "c", PID = "p", TYP = "t", TS = "ts" }
local PKT_TYPES = { CON_REQ = "CRQ", CON_ACP = "CAC", CON_REJ = "CRJ", DISCON = "DIS", DATA = "DAT", PING = "PNG", PONG = "POG", DISC_QRY = "DQY", DISC_ANN = "DAN" }

-- Custom *Internal* Event Names (used with internal emitter)
local INTERNAL_EVENTS = {
    CONNECTION_REQUEST = "connection_request", -- args: sender_addr, port, request_packet, acceptor_func
    DISCOVERY_ANNOUNCE = "discovery_announce", -- args: sender_addr, port, announce_packet
    PROMISE_ERROR = "promise_error"            -- args: promise, error_message, packet_if_relevant (Maybe push as signal still?)
}

-- Global Signal Names (for errors etc.)
local SIGNAL_NAMES = {
    CALLBACK_ERROR = "gatenet_callback_error", -- args: eventName, errorMsg
    PROMISE_ERROR_SIGNAL = "gatenet_promise_error", -- args: promise, errorMsg, packet
    GATENET_ERROR = "gatenet_error"            -- args: errorMsg
}

-- --- Utility Functions ---
local function checkArg(n, val, ...)
    local types = {...}
    local typeOk = false
    for _, t in ipairs(types) do
        if type(val) == t then
            typeOk = true
            break
        end
    end
    if not typeOk then
        error(string.format("bad argument #%d (%s expected, got %s)", n, table.concat(types, " or "), type(val)), 3)
    end
end

local function deepCopy(obj, seen)
    if type(obj) ~= 'table' then return obj end
    if seen and seen[obj] then return seen[obj] end
    local s = seen or {}
    local res = {}
    s[obj] = res
    for k, v in next, obj do res[deepCopy(k, s)] = deepCopy(v, s) end
    return setmetatable(res, getmetatable(obj))
end

-- Creates a standard packet structure
local function createPacket(packetType, payloadData, connectionID, packetID)
    -- Simplified check assuming PKT_TYPES covers all valid types
    local isValidType = false
    for _, v in pairs(PKT_TYPES) do if v == packetType then isValidType = true; break end end
    if not isValidType then
        computer.pushSignal(SIGNAL_NAMES.GATENET_ERROR, "Invalid packet type in createPacket: " .. tostring(packetType))
        return nil
    end
    local packet = {
        hdr = {
            [HDR_KEYS.VER] = PROTO_VER,
            [HDR_KEYS.SRC] = modem.address, -- CORRECTED: Property access
            [HDR_KEYS.CID] = connectionID,
            [HDR_KEYS.PID] = packetID or uuid.next(),
            [HDR_KEYS.TYP] = packetType,
            [HDR_KEYS.TS]  = computer.uptime()
        },
        pld = payloadData
    }
    return packet
end

-- Safely encodes a packet table to CBOR string
local function encodePacket(packet)
    if type(packet) ~= 'table' or not packet.hdr or not packet.hdr[HDR_KEYS.TYP] then
        return nil, "Invalid packet structure for encoding"
    end
    return pcall(cbor.encode, packet)
end

-- Safely decodes a CBOR string into a packet table
local function decodePacket(cborString)
    if type(cborString) ~= "string" then
        return nil, "Invalid input type for decoding (expected string)"
    end
    local success, packetOrError = pcall(cbor.decode, cborString)
    if not success then
        return nil, "CBOR decoding failed: " .. tostring(packetOrError)
    end
    if type(packetOrError) ~= 'table' or type(packetOrError.hdr) ~= 'table' or type(packetOrError.hdr[HDR_KEYS.VER]) ~= "number" or packetOrError.hdr[HDR_KEYS.VER] ~= PROTO_VER then
        -- print(require"serialization".serialize(packetOrError))
        -- print(type(packetOrError.hdr[HDR_KEYS.VER]), PROTO_VER)
         return nil, "Decoded data is not a valid Gatenet packet structure or version mismatch"
    end
    local hdr = packetOrError.hdr
    if type(hdr[HDR_KEYS.TYP]) ~= "string" or type(hdr[HDR_KEYS.PID]) ~= "string" or
        type(hdr[HDR_KEYS.SRC]) ~= "string" or
        (hdr[HDR_KEYS.CID] ~= nil and type(hdr[HDR_KEYS.CID]) ~= "string") then
        return nil, "Invalid packet header fields"
    end
    return packetOrError, nil
end


-- --- Gatenet Instance Factory ---

local function makeGatestack()
    -- Instance data
    local instance = {
        _listeners = {},        -- Internal event listeners [eventName][listenerId] = callback
        _listenerCounter = 0,   -- Counter for unique listener IDs
        _modemListenerId = nil, -- ID for the global modem_message listener
        _activePromises = {},   -- [CID] = promise
        _pendingConnections = {}, -- [CON_REQ_PID] = clientPromise
        _blockList = {},
        _openPorts = {},
    }

    -- --- Internal Event Emitter ---
    function instance:listen(eventName, callback)
        checkArg(1, eventName, "string")
        checkArg(2, callback, "function")
        if not self._listeners[eventName] then
            self._listeners[eventName] = {}
        end
        self._listenerCounter = self._listenerCounter + 1
        local listenerId = self._listenerCounter
        self._listeners[eventName][listenerId] = callback
        return listenerId -- Return numerical ID
    end

    function instance:ignore(listenerId)
        checkArg(1, listenerId, "number")
        local found = false
        for eventName, listeners in pairs(self._listeners) do
            if listeners[listenerId] then
                listeners[listenerId] = nil -- Remove by setting to nil
                found = true
                -- break -- Assume IDs are globally unique, so we can stop searching
            end
        end
        return found
    end

    -- Internal trigger, protected with pcall
    function instance:_trigger(eventName, ...)
        if self._listeners[eventName] then
            local listenersToCall = {}
            -- Collect listeners first in case a callback calls :ignore()
            for id, cb in pairs(self._listeners[eventName]) do
                if cb then -- Check if listener wasn't removed concurrently
                   table.insert(listenersToCall, cb)
                end
            end
            -- Call collected listeners
            for _, cb in ipairs(listenersToCall) do
                local success, err = pcall(cb, ...) -- Pass arguments directly
                if not success then --adjust for return false (cancellation)
                    print("Error in Gatenet internal event handler for '"..eventName.."':", err)
                    computer.pushSignal(SIGNAL_NAMES.CALLBACK_ERROR, eventName, tostring(err))
                end
            end
        end
    end

    -- --- Promise Management ---
    -- (promiseMaid, promiseMetatable, makePromise remain largely the same,
    --  but adjust error reporting to use SIGNAL_NAMES if preferred)

    local function promiseMaid(promise)
        if promise.connectionID then
            instance._activePromises[promise.connectionID] = nil
        end
        if promise._pendingReqPID then
            instance._pendingConnections[promise._pendingReqPID] = nil
        end
        if promise._timeoutID then
            event.cancel(promise._timeoutID)
            promise._timeoutID = nil
        end
        promise._isActive = false
    end

    local function finalizePromise(promise, reason)
        if promise._finalized then return end
        promise._finalized = true
        promiseMaid(promise)
        for _, cb in ipairs(promise.finallyCallbacks) do pcall(cb, promise, reason) end
    end

    local internalSend -- Forward declare

    local promiseMetatable = {
        __index = {
            ["next"] = function(self, onFulfilled)
                if not self._isActive then return self end
                checkArg(2, onFulfilled, "function")
                table.insert(self.callbacks, onFulfilled)
                return self
            end,
            catch = function(self, onRejected)
                if not self._isActive then return self end
                checkArg(2, onRejected, "function")
                table.insert(self.errCallbacks, onRejected)
                return self
            end,
            finally = function(self, onFinally)
                if not self._isActive then return self end
                checkArg(2, onFinally, "function")
                table.insert(self.finallyCallbacks, onFinally)
                return self
            end,
            _reject = function(self, reason, packet)
                if not self._isActive or self._rejecting then return end
                self._rejecting = true
                local wasConnected = self.state == "ESTABLISHED"
                self.state = "REJECTED"
                -- Local callback/send failures must release the peer as well.
                -- Peer DIS handling already changes state, so it is not echoed.
                if wasConnected then
                    local disconnectPacket = createPacket(PKT_TYPES.DISCON, {reason = reason}, self.connectionID)
                    if disconnectPacket then pcall(internalSend, self.destination, self.port, disconnectPacket, self) end
                end
                for _, cb in ipairs(self.errCallbacks) do
                    pcall(cb, self, reason, packet)
                    if not self._isActive then break end
                end
                finalizePromise(self, reason)
            end,
            _resolve = function(self, packet)
                if not self._isActive then return end
                if self.state ~= "ESTABLISHED" and self.state ~= "RESOLVED" then self.state = "RESOLVED" end
                local cb = self.callbacks[self.callbacks.index]
                if cb then
                    local ok, err = pcall(cb, self, packet)
                    if not ok then
                        local reason = "Error in 'next' cb: " .. tostring(err)
                        computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, self, reason, packet)
                        self:_reject(reason, packet)
                        return
                    end
                    if not self._isActive then return end
                    if not self.loopingCallback then self.callbacks.index = self.callbacks.index + 1 end
                end
                if not self.loopingCallback and not self.callbacks[self.callbacks.index] and self._isActive then
                    finalizePromise(self)
                end
            end,
            timeout = function(self, timeoutDuration, timeoutCallback)
                if not self._isActive then return self end
                checkArg(2, timeoutDuration, "number")
                checkArg(3, timeoutCallback, "function", "nil")
                if self._timeoutID then event.cancel(self._timeoutID) end
                local function wrappedTimeoutCallback()
                    self._timeoutID = nil
                    local reason = "Timeout after " .. timeoutDuration .. " seconds"
                    if timeoutCallback then
                        local ok, err = pcall(timeoutCallback, self, timeoutDuration)
                        if not ok then computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, self, "Error in timeout cb: "..tostring(err)) end
                        if not self._isActive then return end -- Callback might have cancelled
                    end
                    if self._isActive then self:_reject(reason, nil) end
                end
                self._timeoutID = event.timer(timeoutDuration, wrappedTimeoutCallback)
                return self
            end,
            clearTimeout = function(self)
                if self._timeoutID then event.cancel(self._timeoutID); self._timeoutID = nil end
                return self
            end,
            looping = function(self, shouldLoop)
                if not self._isActive then return self end
                self.loopingCallback = shouldLoop and true or false
                return self
            end,
            sendData = function(self, payload)
                if not self._isActive or self.state ~= "ESTABLISHED" then computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, self, "Cannot send data: Promise inactive/not established."); return self end
                if not self.connectionID or not self.destination or not self.port then computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, self, "Cannot send data: Conn params missing."); return self end
                local packet = createPacket(PKT_TYPES.DATA, payload, self.connectionID)
                if packet then
                    local sent, err = internalSend(self.destination, self.port, packet, self)
                    if not sent then self:_reject(err); return self, err end
                end
                return self
            end,
            disconnect = function(self, reasonPayload)
                if not self._isActive then return self end
                local wasConnected = self.state == "ESTABLISHED"
                self.state = "CLOSING"
                if wasConnected and self.connectionID and self.destination and self.port then
                    local packet = createPacket(PKT_TYPES.DISCON, reasonPayload, self.connectionID)
                    if packet then internalSend(self.destination, self.port, packet, self) end
                end
                finalizePromise(self, "Disconnect called")
                return self
            end,
            ping = function(self)
                 if not self._isActive or self.state ~= "ESTABLISHED" then computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, self, "Cannot send ping: Promise inactive/not established."); return self end
                 if not self.connectionID or not self.destination or not self.port then computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, self, "Cannot send ping: Conn params missing."); return self end
                 local packet = createPacket(PKT_TYPES.PING, {ts = computer.uptime()}, self.connectionID)
                 if packet then internalSend(self.destination, self.port, packet, self) end
                 return self
            end,
            label = function(self, value)
                checkArg(2, value, 'string', 'nil')
                local oldValue = self._labelName or self.connectionID or "unidentified"
                if value then self._labelName = value end
                return oldValue
            end,
            ['cancel'] = function(self, reasonPayload)
                 if not self._isActive then return self end
                 local wasConnected = self.state == "ESTABLISHED"
                 local reason = "Operation cancelled by user"
                 if wasConnected then self:disconnect(reasonPayload or {msg=reason}) else self.state = "CANCELLED"; self:_reject(reason, nil) end
                 return self
            end,
            getConnectionID = function(self) return self.connectionID end,
            getDestination = function(self) return self.destination end,
            getPort = function(self) return self.port end,
            getState = function(self) return self.state end,
            isActive = function(self) return self._isActive end,
            getLastPacket = function(self) return self.lastReceivedPacket end,
            getLastSendTime = function(self) return self.lastSentTime end,
            getLastReceiveTime = function(self) return self.lastReceivedTime end,
            _isActive = true, _timeoutID = nil, _pendingReqPID = nil, _labelName = nil,
        },
        __metatable = "locked"
    }

    local function makePromise(destination, port, initialState, connectionID)
        local promise = {
            destination = destination, port = port, state = initialState or "PENDING",
            connectionID = connectionID, started = computer.uptime(),
            lastSentTime = nil, lastReceivedTime = nil, lastReceivedPacket = nil,
            loopingCallback = false, callbacks = {index = 1},
            errCallbacks = {}, finallyCallbacks = {}
        }
        setmetatable(promise, promiseMetatable)
        if connectionID then
            if instance._activePromises[connectionID] then
                 computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, promise, "Duplicate CID: " .. connectionID)
                 promise:_reject("Internal error: Duplicate Connection ID", nil)
            else
                instance._activePromises[connectionID] = promise
            end
        end
        return promise
    end

    -- --- Network Internals ---
    internalSend = function(destination, port, packet, promiseCtx)
        if not port then return false, "Port required" end
        if type(packet) ~= 'table' then return false, "Invalid packet data" end
        local encoded, packetOrErr = encodePacket(packet)
        if not encoded then computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, promiseCtx, "Encoding fail: " .. (packetOrErr or "?")); return false, "Encode fail" end
        if not modem.isOpen(port) then
            if modem.open(port) then instance._openPorts[port] = true else return false, "Port open fail: " .. port end
        end
        local ok, err
        local callOk
        if modem.maxPacketSize and #packetOrErr + 3 > modem.maxPacketSize() then
            return false, "Packet exceeds modem capacity; reduce the plan size."
        end
        if destination then
            callOk, ok, err = pcall(modem.send, destination, port, "gnt", packetOrErr)
        else
            callOk, ok, err = pcall(modem.broadcast, port, "gnt", packetOrErr)
        end
        if not callOk then err = ok; ok = false end
        if ok then if promiseCtx and promiseCtx._isActive then promiseCtx.lastSentTime = computer.uptime() end; return true
        else computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, promiseCtx, "Modem send fail: "..tostring(err)); return false, "Modem send fail: "..tostring(err) end
    end

    -- --- Acceptor Object Definition ---
    -- (Must be defined before handleModemMessage needs it)
    local acceptorMetatable -- Forward declare
    local function generateAcceptor(senderAddr, portNum, requestPacket)
        local acceptor = { requestPacket = requestPacket, port = portNum, handled = false }
        return setmetatable(acceptor, acceptorMetatable)
    end
    acceptorMetatable = {
        __call = function(self, accept, responsePayload)
            if self.handled then return nil, "Acceptor already handled" end; self.handled = true
            local reqPacket = self.requestPacket; local sender = reqPacket.hdr[HDR_KEYS.SRC]; local port = self.port; local reqPID = reqPacket.hdr[HDR_KEYS.PID]
            if accept then
                local newCID = uuid.next(); local serverPromise = makePromise(sender, port, "ESTABLISHED", newCID)
                if not serverPromise:isActive() then return nil, "Failed to create server promise" end
                local ackPacket = createPacket(PKT_TYPES.CON_ACP, responsePayload or {}, newCID); ackPacket.pld.ackPID = reqPID -- Always add ackPID
                local sent, err = internalSend(sender, port, ackPacket, serverPromise)
                if sent then return serverPromise else serverPromise:cancel(); return nil, "Failed to send CON_ACP: " .. (err or "?") end
            else
                local rejectPacket = createPacket(PKT_TYPES.CON_REJ, responsePayload or {}, nil); rejectPacket.pld.ackPID = reqPID -- Always add ackPID
                internalSend(sender, port, rejectPacket, nil); return nil
            end
        end,
        getRequestPacket = function(self) return self.requestPacket end,
        getSender = function(self) return self.requestPacket.hdr[HDR_KEYS.SRC] end,
        getPort = function(self) return self.port end,
        __metatable = "locked"
    }

    -- --- Main Modem Message Handler ---
    local function handleModemMessage(_, receiver, sender, port, distance, msgType, msg)
        -- Ignore if blocked or msg empty
        if msgType ~= "gnt" then return end
        if instance._blockList[sender] or not msg then return end
        -- Decode the packet
        local packet, decodeErr = decodePacket(msg)
        if not packet or packet.hdr[HDR_KEYS.SRC] ~= sender then return end
        
        local hdr = packet.hdr
        local pld = packet.pld
        local cid = hdr[HDR_KEYS.CID]
        local typ = hdr[HDR_KEYS.TYP]
        local pid = hdr[HDR_KEYS.PID]
        local promise = cid and instance._activePromises[cid] or nil
        
        -- 1. Handle messages for existing connections
        if promise and promise:isActive() then
            promise.lastReceivedTime = computer.uptime(); promise.lastReceivedPacket = packet
            
            if promise.destination ~= sender or promise.port ~= port then return end -- Ignore spoof/mismatch
    
            -- Create a unique deduplication key combining packet type, ID and timestamp
            local dedupKey = typ .. ":" .. pid
            
            -- Check against recently processed packets (within reasonable time window)
            if promise._processedPackets and promise._processedPackets[dedupKey] then
                -- A packet with this ID was already processed
                -- print(string.format("[GATENET WARN] Deduplicated packet: %s (PID: %s)", typ, tostring(pid)))
                return
            end
            
            -- Mark this packet as processed
            if not promise._processedPackets then promise._processedPackets = {} end
            promise._processedPackets[dedupKey] = computer.uptime()
            
            -- Cleanup old entries from deduplication table (optional, prevents memory growth)
            local currentTime = computer.uptime()
            local expireTime = 5 -- 5 seconds deduplication window 
            for k, timestamp in pairs(promise._processedPackets) do
                if currentTime - timestamp > expireTime then
                    promise._processedPackets[k] = nil
                end
            end
    
            if typ == PKT_TYPES.DATA then
                promise:_resolve(packet)
            elseif typ == PKT_TYPES.PING then 
                local pong = createPacket(PKT_TYPES.PONG, {ackPID = pid}, cid)
                if pong then internalSend(sender, port, pong, promise) end
            elseif typ == PKT_TYPES.PONG then
                promise:_resolve(packet)
            elseif typ == PKT_TYPES.DISCON then 
                promise.state = "CLOSED_BY_PEER"
                promise:_reject("Connection closed by peer", packet)
            else 
                computer.pushSignal(SIGNAL_NAMES.PROMISE_ERROR_SIGNAL, promise, "Unexpected packet type '"..typ.."' on established conn "..cid)
            end

        -- 2. Handle packets triggering internal events (no existing promise)
        elseif not cid and typ ~= PKT_TYPES.CON_REJ then
             if typ == PKT_TYPES.CON_REQ then
                 -- Create acceptor HERE
                 local acceptor = generateAcceptor(sender, port, packet)
                 -- Trigger internal event HERE, passing full objects
                 instance:_trigger(INTERNAL_EVENTS.CONNECTION_REQUEST, sender, port, packet, acceptor)

             elseif typ == PKT_TYPES.DISC_QRY or typ == PKT_TYPES.DISC_ANN then
                 -- Trigger internal event HERE, passing full packet
                 instance:_trigger(INTERNAL_EVENTS.DISCOVERY_ANNOUNCE, sender, port, packet)

             -- else ignore other initial packets without CID
             end

        -- 3. Handle packets for pending client connections
        else -- cid exists, but no active promise found
             if typ == PKT_TYPES.CON_ACP or typ == PKT_TYPES.CON_REJ then
                 local reqPID = type(pld) == "table" and pld.ackPID or nil
                 local clientPromise = reqPID and instance._pendingConnections[reqPID]
                 if clientPromise and clientPromise:isActive() then
                     if clientPromise.destination ~= sender or clientPromise.port ~= port then return end -- Ignore mismatch
                     clientPromise.lastReceivedTime = computer.uptime(); clientPromise.lastReceivedPacket = packet

                     if typ == PKT_TYPES.CON_ACP then
                         local confirmedCID = hdr[HDR_KEYS.CID]
                         if not confirmedCID then clientPromise:_reject("CON_ACP missing CID", packet); return end
                         clientPromise.connectionID = confirmedCID; clientPromise.state = "ESTABLISHED"
                         instance._pendingConnections[reqPID] = nil; instance._activePromises[confirmedCID] = clientPromise
                         
                        -- print(string.format("[GATENET DEBUG3] Calling _resolve for CID %s, PID %s", tostring(cid), tostring(packet.hdr[HDR_KEYS.PID])))
                         clientPromise:_resolve(packet)
                     elseif typ == PKT_TYPES.CON_REJ then
                         clientPromise.state = "REJECTED_BY_PEER"; clientPromise:_reject("Connection rejected by peer", packet)
                     end
                 -- else ignore orphan CON_ACP/REJ
                 end
             -- else ignore packet with unknown/inactive CID
             end
        end
    end

    -- --- Public API Methods ---
    function instance:startListener()
        if self._modemListenerId then -- If already true (or a non-nil ID from a previous system)
            -- Consider if it's truly listening. If _modemListenerId is just 'true',
            -- it might be from an older version or manual setting.
            -- For safety, if it's just 'true', we might try to ensure it's OUR listener.
            -- However, the robust closeListener should handle prior states.
            -- If _modemListenerId is not nil, we assume it's correctly set and active.
            return true
        end
        -- Try to register the listener
        -- event.listen now typically returns true on success, false on failure,
        -- rather than a numerical ID in modern OpenOS (though older versions might differ).
        -- We'll store 'true' if successful.
        local modemListenerId = event.listen("modem_message", handleModemMessage)
        if modemListenerId then
            self._modemListenerId = modemListenerId -- Mark as successfully listening
            return true
        else
            -- Failed to register the listener
            self._modemListenerId = nil -- Ensure it's nil if registration failed
            local errMessage = "gatenet: Failed to start modem_message listener via event.listen. "..tostring(modemListenerId)
            print(errMessage) -- Or computer.pushSignal
            computer.pushSignal(SIGNAL_NAMES.GATENET_ERROR, errMessage)
            return false
        end
    end

    function instance:closeListener() -- Renamed from 'shutdown' in prev version if confusing
        if self._modemListenerId then
            -- Use the stored ID to ignore the global listener
            local ok = event.ignore("modem_message", handleModemMessage)
            self._modemListenerId = nil
            return ok
        end
        return true
    end

    function instance:shutdown()
        local cleanupError
        local listenerOk, listenerError = pcall(self.closeListener, self)
        if not listenerOk then cleanupError = listenerError end
        -- Disconnect packets may open ports. Cancel connections BEFORE the final
        -- port closure, and keep closing resources even if a cancellation fails.
        local promises = {}
        for _, p in pairs(self._activePromises) do table.insert(promises, p) end
        for _, p in pairs(self._pendingConnections) do table.insert(promises, p) end
        for _, p in ipairs(promises) do
            local activeOk, active = pcall(p.isActive, p)
            if not activeOk then
                cleanupError = cleanupError or active
                pcall(promiseMaid, p)
            elseif active then
                local ok, err = pcall(p.cancel, p, "Gatenet shutdown")
                if not ok then
                    cleanupError = cleanupError or err
                    pcall(promiseMaid, p)
                end
            end
        end
        for port in pairs(self._openPorts) do
            local ok, err = pcall(modem.close, port)
            if not ok then cleanupError = cleanupError or err end
        end
        self._openPorts, self._activePromises, self._pendingConnections = {}, {}, {}
        self._listeners, self._blockList = {}, {}
        if cleanupError then error("Gatenet cleanup failed: " .. tostring(cleanupError)) end
        return true
    end

    function instance:openPort(port)
        checkArg(1, port, "number")
        if modem.isOpen(port) then self._openPorts[port] = true; return true end
        local ok = modem.open(port); if ok then self._openPorts[port] = true end
        return ok
    end

    function instance:closePort(port)
        checkArg(1, port, "number")
        if self._openPorts[port] then self._openPorts[port] = nil; return modem.close(port) end
        return false
    end

    function instance:connect(destination, port, initialPayload)
        checkArg(1, destination, "string"); checkArg(2, port, "number")
        local clientPromise = makePromise(destination, port, "CONNECTING")
        local reqPacket = createPacket(PKT_TYPES.CON_REQ, initialPayload, nil)
        if not reqPacket then clientPromise:_reject("Create CON_REQ fail"); return clientPromise end
        clientPromise._pendingReqPID = reqPacket.hdr[HDR_KEYS.PID]
        self._pendingConnections[clientPromise._pendingReqPID] = clientPromise
        local sent, err = internalSend(destination, port, reqPacket, clientPromise)
        if not sent then clientPromise:_reject("Send CON_REQ fail: "..(err or "?")) end
        return clientPromise
    end

    function instance:broadcastDiscoveryQuery(port, queryPayload)
        checkArg(1, port, "number")
        local queryPacket = createPacket(PKT_TYPES.DISC_QRY, queryPayload, nil)
        if not queryPacket then return false, "Create DISC_QRY fail" end
        return internalSend(nil, port, queryPacket, nil)
    end

    function instance:sendDiscoveryAnnounce(port, announcePayload, destination)
        checkArg(1, port, "number"); checkArg(3, destination, "string", "nil")
        local annPacket = createPacket(PKT_TYPES.DISC_ANN, announcePayload, nil)
        if not annPacket then return false, "Create DISC_ANN fail" end
        return internalSend(destination, port, annPacket, nil)
    end

    function instance:block(uuid) checkArg(1, uuid, 'string'); self._blockList[uuid] = true; return true end
    function instance:unblock(uuid) checkArg(1, uuid, 'string'); self._blockList[uuid] = nil; return true end
    function instance:isBlocked(uuid) checkArg(1, uuid, 'string'); return self._blockList[uuid] == true end

    -- Expose utilities if needed (decodePacket might be useful for user if dealing with raw msg somehow)
    instance.decodePacket = decodePacket
    instance.PACKET_TYPES = deepCopy(PKT_TYPES)
    instance.HDR_KEYS = deepCopy(HDR_KEYS)
    instance.INTERNAL_EVENT_NAMES = deepCopy(INTERNAL_EVENTS) -- Expose internal event names
    instance.PROTOCOL_VERSION = PROTO_VER

    -- For debugging:
    -- instance.getActivePromises = function() return self._activePromises end
    -- instance.getPendingConnections = function() return self._pendingConnections end
    -- instance.getListeners = function() return self._listeners end

    -- Return the instance table containing all public methods
    return instance
end

-- Return the factory function
return {
    new = makeGatestack
}