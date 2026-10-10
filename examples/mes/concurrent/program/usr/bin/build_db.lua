-- Compile source .dblz recipes once, optionally install the same table in-memory.
local args, options = require("shell").parse(...)
if options.h or options.help or #args > 0 then
    print("Usage: build_db [--load]\nRebuild /usr/lib/recipes/compiled.cb; --load also populates the running recipes library.")
    return
end
local builder = require "recipes.build"
print("Building recipe database from " .. builder.directory .. "...")
local db = builder.build()
local saved, err = builder.save(db)
if not saved then error(err, 0) end
print("Saved compiled recipe database to " .. builder.compiledPath)
if options.load then
    require("recipes").install(db)
    print("Installed built database in the running recipes library.")
end
return true
