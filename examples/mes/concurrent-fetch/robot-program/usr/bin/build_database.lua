-- Load required libraries

--build_database.lua shaped_recipes.csv shapeless_recipes.csv ore_dictionary.csv item_stacks.csv output_dir --e=animania,spartanshields,thaumicaugmentation,traverse,fairylights,dynamictreesbop,dynamictreesnatura,rusticthaumaturgy,dttraverse,dynamictreesforestry,inspirations,natura,pvj
package.loaded.csv = nil
package.loaded.liblz16 = nil
local csv = require "csv"
local shell = require"shell"
local serialization = require "serialization"
local cbor = require "cbor"
local lz16 = require "liblz16"
local filesystem = require"filesystem"
local computer = require"computer"

local used_ingredients = {}  -- Set to track all ingredients used in recipes
local modsToExclude = {}
local recipe_outputs = {}
local opened = {}
-- Track handles so failed parsing or writing still closes every resource.
local function open_checked(opener, path, mode)
    local file, err = opener(path, mode)
    if not file then error("cannot open "..path..": "..tostring(err or "no error returned"), 0) end
    local closed = false
    local proxy = {}
    opened[#opened + 1] = proxy
    function proxy:close()
        if closed then return true end
        closed = true
        local result, closeErr = file:close()
        if result == false or closeErr then error("cannot close "..path..": "..tostring(closeErr), 0) end
        return true
    end
    function proxy:write(data)
        local result, writeErr = file:write(data)
        if not result then error("cannot write "..path..": "..tostring(writeErr or "write failed"), 0) end
        return self
    end
    function proxy:read(size)
        local result, readErr = file:read(size)
        if readErr then error("cannot read "..path..": "..tostring(readErr), 0) end
        return result
    end
    function proxy:lines() return file:lines() end
    return proxy
end
-- Helper function to create directories
local function mkdir(path)
    if not filesystem.exists(path) then
        local ok, err = filesystem.makeDirectory(path)
        if not ok then error("cannot create "..path..": "..tostring(err), 0) end
    end
end

local function yield(amt, msg, duration)
    if amt % 2000 == 0 then if msg then print(msg) end os.sleep(duration or 0.01) end
end

-- Parse shaped recipes
local function parse_shaped_recipes(filename, recipes, nss)
    local f = open_checked(csv.open, filename)
    
    if not f then return print("could not open file "..filename) end
    local function xyts(x, y) return ((y - 1) * 3) + x end
    local skip = true
    local line = 0
    
    local malformed = 0
    for fields in f:lines() do
        if skip then
            skip = false
        else
            -- if not fields[1] then os.sleep(20)  end
            if fields[1] then
                local modname = fields[1]:match("^([^:]+)")
                if modname and modsToExclude[modname:lower()] then
                    goto continue
                end
            end
            if type(fields)=="string" then
                print("huh??? string??", fields)
                os.sleep(60)
            end
            -- Validate required fields exist
            if not fields[3] or not fields[4] or not fields[2] then
                malformed = malformed + 1
                yield(malformed, "malformed line "..line)
            else
                local recipe = {}
                local ingredients = {}
                for k, v in fields[3]:gmatch("(%a): ([^\n]+)") do
                    ingredients[k] = v
                end
                
                for char, itemId in pairs(ingredients) do
                    used_ingredients[itemId] = true  -- Mark ingredient as used
                end
                local output = fields[4]:match("^(%S+)")
                recipe_outputs[output] = true
                local ns = output:match("^(.-):")
                local qty = tonumber(fields[4]:match("^%S+ x(%d+)"))
                local irow = 1
                
                for row in fields[2]:gmatch("[^\n]+") do
                    local ic = 1
                    for c in row:gmatch(".") do
                        recipe[xyts(ic, irow)] = ingredients[c]
                        ic = ic + 1
                    end
                    irow = irow + 1
                end
                
                if qty ~= nil and qty > 1 then recipe.qty = qty end
                recipes[output] = recipe
                nss[ns] = nss[ns] or {}
                nss[ns][#nss[ns] + 1] = string.format("%s\t%s\n", output, serialization.serialize(recipe))
                
                yield(line)
            end
            
            ::continue::
        end
        line = line + 1
    end
    if malformed > 0 then
        print("Malformed shaped recipes: ", malformed)
    end
    print(("Processed %s shaped recipe lines"):format(line))
    f:close()
end

-- Parse shapeless recipes
local function parse_shapeless_recipes(filename, recipes, nss)
    local f, err = open_checked(csv.open, filename)
    if err then return print(err) end
    local skip = true
    local line = 0
    local malformed = 0
    for fields in f:lines() do
        -- Validate required fields exist
        if not fields[3] then
            malformed = malformed + 1
            yield(malformed, "malformed line "..line)
        else
            if fields[1] then
                local modname = fields[1]:match("^([^:]+)")
                if modname and modsToExclude[modname:lower()] then
                    goto continue
                end
            end
            local output = fields[3]:match("^(%S+)")
            if not skip and output then
                recipe_outputs[output] = true
                if not fields[2] then
                    malformed = malformed + 1        
                    yield(malformed, "malformed "..malformed)
                else
                    local ns = output:match("^(.-):")
                    local qty = tonumber(fields[3]:match("^%S+ x(%d+)"))
                    local recipe = {}
                    
                    for item in fields[2]:gmatch("[^\n]+") do
                        recipe[#recipe + 1] = item
                    end
                    for _, itemId in ipairs(recipe) do
                        used_ingredients[itemId] = true  -- Mark ingredient as used
                    end
                    if qty ~= nil and qty > 1 then recipe.qty = qty end
                    recipes[output] = recipe
                    nss[ns] = nss[ns] or {}
                    nss[ns][#nss[ns] + 1] = string.format("%s\t%s\n", output, serialization.serialize(recipe))
                    
                    yield(line)
                end
            else
                skip = false
            end
            
            ::continue::
        end
        line = line + 1
    end
    if malformed > 0 then
        print("Malformed shapeless recipes: ", malformed)
    end
    print(("Processed %s shapeless recipe lines"):format(line))
    f:close()
end

-- Parse ore dictionary
local function parse_ore_dictionary(filename, oredict)
    local f = open_checked(csv.open, filename)
    if not f then return print("could not open file "..filename) end
    local ctime = computer.uptime()
    local line = 0
    local malformed = 0
    
    for fields in f:lines() do
        if not fields[1] or not fields[2] then
            malformed = malformed + 1
            yield(malformed, "malformed line "..line)
        else
            local list = {}
            for item in fields[2]:gmatch("[^\n]+") do 
                -- Check if the item is from an excluded mod
                local modname = item:match("^([^:]+)")
                if modname and not modsToExclude[modname:lower()] then
                    list[#list + 1] = item
                end
            end
            -- Only add the ore dict entry if there are items left after filtering
            if #list > 0 then
                oredict[fields[1]] = list
            end
        end
        line = line + 1
        yield(line)
    end
    
    if malformed > 0 then
        print("Malformed oredictionary entries: ", malformed)
    end
    print("Ore dictionary processed in", computer.uptime() - ctime, "seconds for", line, "entries")
    f:close()
end

-- Parse item stacks for tool detection
local function parse_item_stacks(filename, tool_data)
    local f = open_checked(csv.open, filename)
    if not f then 
        print("Warning: item_stacks.csv not found, tool detection will not be available")
        return false
    end
    

    local malformed = 0
    local skip = true
    local total_items = 0

    for fields in f:lines() do
        if skip then
            skip = false
        else
            -- Validate all required fields exist
            if not fields[1] or not fields[4] or not fields[5] or not fields[7] or 
               not fields[9] or not fields[10] or not fields[11] then
                malformed = malformed + 1
                yield(malformed, "malformed "..malformed)
                goto continue
            end
            
            local id = fields[1]
            local max_stack_size = tonumber(fields[10]) or 64
            local enchantability = tonumber(fields[13]) or 0
            
            total_items = total_items + 1
            if id:match("tool") or max_stack_size == 1 or enchantability > 0 then
                tool_data[id] = {
                    max_stack_size = max_stack_size,
                    max_damage = tonumber(fields[11]) or 0,
                    enchantability = enchantability,
                    class_name = fields[7],
                    display_name = fields[4],
                    tooltip = fields[5]
                }
            end
            ::continue::
        end
    end
    if malformed > 0 then
        print("Malformed itemstack entries: ", malformed)
    end
    f:close()
    return true
end

-- Add this function to filter unused tools
local function filter_unused_tools(tool_data, used_ingredients, recipe_outputs)
    local filtered_tools = {}
    local removed_count = 0
    
    for tool_id, tool_info in pairs(tool_data) do
        -- Keep the tool if it's used as an ingredient OR if it has a crafting recipe
        if used_ingredients[tool_id] or recipe_outputs[tool_id] then
            filtered_tools[tool_id] = {mss = tool_info.max_stack_size}
        else
            removed_count = removed_count + 1
        end
    end
    
    if removed_count > 0 then
        print("Removed " .. removed_count .. " unused tools from database")
    else
        print("All tools in the database are used in recipes or have crafting recipes")
    end
    
    return filtered_tools
end

-- Write mod recipe files
local function write_mod_recipes(nss, output_dir)
    local sets = {}
    for k, v in pairs(nss) do sets[#sets + 1] = k end
    table.sort(sets, function(a, b) return #nss[a] < #nss[b] end)
    
    -- Create the misc file immediately
    local misc_file, misc_err = open_checked(io.open, filesystem.concat(output_dir, "misc.db"), "wb")
    if misc_err then return print(misc_err) end
    
    -- Process in batches to further reduce memory usage
    local batch_size = 100  -- Adjust based on your memory constraints
    for i = 1, #sets, batch_size do
        local batch_end = math.min(i + batch_size - 1, #sets)
        
        for j = i, batch_end do
            local v = sets[j]
            print(v, #nss[v])
            if #nss[v] <= 48 then
                -- Write directly to misc file
                for l, m in ipairs(nss[v]) do
                    misc_file:write(m)
                end
            else
                local f, err = open_checked(io.open, filesystem.concat(output_dir, v .. ".db"), "wb")
                if err then 
                    misc_file:close()
                    return print(err) 
                end
                for l, m in ipairs(nss[v]) do f:write(m) end
                f:close()
            end
        end
        
        -- Force garbage collection between batches
        for i=1,10 do os.sleep() end
    end
    
    misc_file:close()
end

-- Write ore dictionary
local function write_ore_dict(oredict, output_dir)
    local f, err = open_checked(io.open, filesystem.concat(output_dir, "oredict.db"), "wb")
    if err then return print(err) end
    for k, v in pairs(oredict) do
        f:write(string.format("%s\t%s\n", k, serialization.serialize(v)))
    end
    f:close()
end

-- Write tool data
local function write_tool_data(tool_data, output_dir)
    local f, err = open_checked(io.open, filesystem.concat(output_dir, "tool.db"), "wb")
    if err then return print(err) end
    for id, data in pairs(tool_data) do
        f:write(string.format("%s\t%s\n", id, serialization.serialize(data)))
    end
    f:close()
end

-- Compress database files
local function compress_dbs(db_path, compressed_path)
    if not filesystem.exists(db_path) then 
        print("Error: DB directory not found:", db_path)
        error("DB directory not found: "..db_path, 0)
    end
    
    if not filesystem.exists(compressed_path) then
        print("Creating compressed directory:", compressed_path)
        mkdir(compressed_path)
    end
    
    local function transformer(file_name)
        local input_path = filesystem.concat(db_path, file_name)
        local output_path = filesystem.concat(compressed_path, file_name .. "lz")
        
        print(string.format("Compressing %s to %s", input_path, output_path))
        local start_time = computer.uptime()
        
        local file_in, err = open_checked(io.open, input_path, "rb")
        if not file_in then 
            print("Error opening input file:", err)
            return
        end
        
        local file_out = open_checked(lz16.open, output_path, "wb")
        while true do
            local chunk = file_in:read(4096)
            if not chunk or chunk == "" then break end
            file_out:write(chunk)
        end
        
        file_in:close()
        file_out:close()
        
        print(string.format("Processed in %.2f seconds", computer.uptime() - start_time))
    end
    
    for file_name in filesystem.list(db_path) do
        if file_name:sub(-3) == ".db" then
            transformer(file_name)
        end
    end
end

-- Main function
local function main(args, opts)
    if #args < 3 then
        return print('Usage: lua build_database.lua <shaped_recipes.csv> <shapeless_recipes.csv> <ore_dictionary.csv> [item_stacks.csv] [output_dir]\nPaths are used as supplied; output_dir defaults to recipe_db. Use "" for item_stacks.csv to omit it with an explicit output_dir.')
    end
    -- Paths are used as supplied; output defaults to ./recipe_db.
    -- An empty fourth argument selects output_dir without item stacks.
    local shaped_file = args[1]
    local shapeless_file = args[2]
    local ore_dict_file = args[3]
    local item_stacks_file = args[4] ~= "" and args[4] or nil
    local output_dir = args[5] or "recipe_db"

    if opts.e and type(opts.e) == "string" then
        for mod in opts.e:gmatch("[^,]+") do
            if mod then
                modsToExclude[mod:lower()] = true
                print(("added mod '%s' to exclusion list"):format(mod)) 
            else
                print("error while parsing exclusion list")
            end
        end
    end
    -- Create output directories
    mkdir(output_dir)
    local raw_dir = filesystem.concat(output_dir, "raw")
    local compressed_dir = filesystem.concat(output_dir, "compressed")
    mkdir(raw_dir)
    mkdir(compressed_dir)
    
    -- Initialize data structures
    local recipes = {}
    local nss = {}
    local oredict = {}
    local tool_data = {}
    
    -- Parse input files
    print("Processing shaped recipes... "..shaped_file)
    parse_shaped_recipes(shaped_file, recipes, nss)
    
    print("Processing shapeless recipes... "..shapeless_file)
    parse_shapeless_recipes(shapeless_file, recipes, nss)
    
    -- Write output files
    print("Writing mod recipe files...")
    write_mod_recipes(nss, raw_dir)
    nss = nil
    for i=1,10 do os.sleep() end

    print("Processing ore dictionary... "..ore_dict_file)
    parse_ore_dictionary(ore_dict_file, oredict)

    
    print("Writing ore dictionary...")
    write_ore_dict(oredict, raw_dir)
    oredict = nil
    for i=1,10 do os.sleep() end
    
    if item_stacks_file then
        print("Processing item stacks for tool detection... "..item_stacks_file)
        parse_item_stacks(item_stacks_file, tool_data)
        print("Filtering unused tools...")
        tool_data = filter_unused_tools(tool_data, used_ingredients, recipe_outputs)
    end
    
    if next(tool_data) ~= nil then
        print("Writing tool data...")
        write_tool_data(tool_data, raw_dir)
            
        tool_data = nil
        for i=1,10 do os.sleep() end
    end
    used_ingredients = nil
    for i=1,10 do os.sleep() end
    -- Compress database files
    print("Compressing database files...")
    compress_dbs(raw_dir, compressed_dir)
    
    print("Database building complete!")
    print("Output directory:", output_dir)
end

-- Run main function with command line arguments
local args, opts = shell.parse(...)
local ok, failure = pcall(main, args, opts)
local closeFailure
for _, file in ipairs(opened) do
    local closed, err = pcall(file.close, file)
    if not closed then closeFailure = closeFailure or err end
end
if not ok then error(failure, 0) end
if closeFailure then error(closeFailure, 0) end