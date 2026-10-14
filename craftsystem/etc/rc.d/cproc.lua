-- cproc owns a persistent thread; returning from rc must not stop the service.
function start()
  local run=assert(loadfile('/usr/bin/cproc.lua'))
  require('thread').create(function() if args then run(args) else run() end end):detach()
end
