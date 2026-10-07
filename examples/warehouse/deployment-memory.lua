-- Non-recording GPU: a real GPU owns its framebuffer outside the Lua heap.
-- The full driver is compiled before the no-UI baseline is sampled.
return function(save)
  local computer=require('computer');local event=require('event');local component=require('component')
  local keys=require('keyboard').keys;local tty=require('tty')
  local function settle() for n=1,30 do event.pull(0) end end
  local function key(k) computer.pushSignal('key_down','memory-keyboard',0,k,'test') end
  local gpu={address='non-recording-gpu'};local fg,bg=0xffffff,0
  function gpu.getResolution() return 160,50 end
  function gpu.getViewport() return 160,50 end
  function gpu.getDepth() return 8 end
  function gpu.getForeground() return fg,false end
  function gpu.getBackground() return bg,false end
  function gpu.setForeground(v) local old=fg;fg=v;return old,false end
  function gpu.setBackground(v) local old=bg;bg=v;return old,false end
  function gpu.getScreen() return 'memory-screen' end
  function gpu.set() return true end
  function gpu.fill() return true end
  function gpu.copy() return true end
  function gpu.bind() return true end
  function gpu.setViewport() return true end
  function gpu.get() return ' ',fg,bg end
  settle()
  local result={total=computer.totalMemory(),withoutUI={steady=computer.freeMemory(),minimum=computer.freeMemory()},renders={}}
  for n=1,10 do result.withoutUI.minimum=math.min(result.withoutUI.minimum,computer.freeMemory());event.pull(0) end
  local oldGpu=rawget(component,'gpu');local oldTtyGpu=tty.window.gpu;local proxy=component.proxy
  component.proxy=function(address) if address==gpu.address then return gpu end;return proxy(address) end
  component.gpu=gpu;tty.bind(gpu)
  local ui=require('warehouse.ui');require('qmenu');settle();result.afterLoad=computer.freeMemory()
  local script={{kind='items',action='detail'},{kind='item',action='back'},
    {kind='items',action='tab'},{kind='storages',action='detail'},{kind='storage',action='back'},
    {kind='storages',action='tab'},{kind='machines',action='detail'},{kind='machine',action='back'},
    {kind='machines',action='tab'},{kind='jobs',action='detail'},{kind='job',action='back'},
    {kind='jobs',action='quit'}}
  local index=1;local minimum=computer.freeMemory();local pending
  local steadyOpen
  local ok,err=ui.show({onRender=function(model,screen,menu,cause)
    local free=computer.freeMemory();minimum=math.min(minimum,free);result.renders[#result.renders+1]={kind=screen.kind,free=free}
    if pending and cause~=pending then return end;pending=nil
    local step=assert(script[index],'unexpected UI render');assert(screen.kind==step.kind,'unexpected UI screen '..screen.kind)
    index=index+1;pending='key_down'
    if step.action=='detail' then
      for _,row in ipairs(model.rows) do if row.action=='item' or row.action=='storage' or row.action=='machine' or row.action=='job' then
        menu:setSelected(row.key);key(keys.enter);return
      end end;error('detail row missing')
    elseif step.action=='back' then key(keys.back)
    elseif step.action=='tab' then key(keys.right)
    else settle();steadyOpen=computer.freeMemory();key(keys.q) end
  end})
  assert(ok,err)
  assert(index==#script+1,'not all screens rendered');settle()
  result.withUI={steady=steadyOpen,minimum=minimum,afterClose=computer.freeMemory()}
  local fs=require('filesystem');result.codeBytes={}
  for _,path in ipairs({'/lib/warehouse/view.lua','/lib/warehouse/ui.lua','/lib/qmenu.lua','/lib/term.lua','/lib/tty.lua','/lib/core/term.lua','/lib/core/cursor.lua','/lib/core/full_cursor.lua','/lib/core/full_tty.lua','/lib/keyboard.lua'}) do
    if fs.exists(path) then result.codeBytes[path]=fs.size(path) end
  end
  component.gpu=oldGpu;component.proxy=proxy;tty.window.gpu=oldTtyGpu
  save('/home/warehouse-memory.lua',result)
end
