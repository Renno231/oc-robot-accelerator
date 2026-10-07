local event = require("event")
local component = require"component"
local inventory = require"inventory"
local sides = require"sides"
local tty = require"tty"
local keyboard = require "keyboard"
local keys = keyboard.keys
local qmenu = require "qmenu"
local shell = require('shell')
local handoff = require "craft_handoff"
local term = require("term")
local transposer = component.transposer
local gpu = component.gpu
local string = string

local w, h = component.gpu.getResolution()
local oV = {tty.getViewport()}

local running = true
local menu = qmenu.create()
local storageSide, invSide
if not storageSide then
    for i=0,5 do
        if storageSide and invSide then break end
        local inventoryName = transposer.getInventoryName(i)
        if inventoryName then
            if storageSide == nil and (inventoryName == "storagedrawers:controller" or inventoryName == "storagedrawers:controllerslave") then
                storageSide = i
            elseif inventoryName:sub(1,15) == "storagedrawers:" or inventoryName:sub(1,14) == "opencomputers:" then -- must be a drawer
                -- do nothing
            elseif not invSide then
                invSide = i
            end
        end
    end
end

local storageSnapshot = inventory.new(transposer, storageSide)
local invSnapshot = inventory.new(transposer, invSide)

local currentPage = 1
local itemsPerPage = 20
local maxPages  = 1
local listOptions = {}
local searchCriteria = ""

local print = print
local printf = function(...)
    print(string.format(...))
end

local clearScreen = function()
    gpu.fill(1,1,w,h," ")
end

local function getFilteredItemList(snapshot, filterCB)
    if not filterCB then filterCB = function(data) return data.name ~= "minecraft:air" end end
    local filteredList = {}
    local totalSlots = snapshot:getInventorySize()
    for i = 1, totalSlots do
        local itemData = snapshot:getItemInSlot(i)
        -- We check if itemData exists and is not air
        if itemData and filterCB(itemData) then
            table.insert(filteredList, i)
        end
    end
    return filteredList
end

local updatePageDisplay
local function goPrevPage()
    if currentPage > 1 then
        currentPage = currentPage - 1
        updatePageDisplay()
        menu:draw()
    end
end

local function goNextPage()
    if currentPage < maxPages then
        currentPage = currentPage + 1
        updatePageDisplay()
        menu:draw()
    end
end

local function linkMenuOptions(options)
    for i = 1, #options do
        if i > 1 then
            options[i]:bind(keys.up, options[i - 1].name)
        end
        if i < #options then
            options[i]:bind(keys.down, options[i + 1].name)
        end
    end
end

local function searchFilter(data)
    local lcase = searchCriteria:lower()
    return string.match(string.lower(data.label), lcase)
end

local getSearch = function(opt, override)
    local prevSearch = searchCriteria
    if keyboard.isShiftDown() and override == nil then override = "" end
    searchCriteria = type(override) == "string" and override or menu:read(opt)
    if override or searchCriteria ~= prevSearch then
        printf("Searched for '%s'", searchCriteria)
        updatePageDisplay()
    end
end

local export = function(opt)
    local amountToExport = math.max(0, tonumber(menu:read(opt)) or 1)
    if amountToExport == 0 then return end
    local itemToExport = opt.data.name..(opt.data.damage > 0 and ":"..opt.data.damage or "")
    local succ, err = xpcall(function() 
        repeat
            storageSnapshot:sync()
            local slotToExtractFrom = storageSnapshot:nextSlotContaining(itemToExport)
            if not slotToExtractFrom then printf("Unable to extract item %s", itemToExport) break end
            local moved = transposer.transferItem(storageSide, invSide, amountToExport, slotToExtractFrom)
            if moved == 0 then printf("Failed to move %s to output",itemToExport) break end
            printf("Transferred %s of %s to output", moved, itemToExport)
            amountToExport = amountToExport - moved
        until amountToExport == 0
        storageSnapshot:sync()
        updatePageDisplay()
    end, debug.traceback)
    if not succ then print(err) end
end

local import = function()
    local amountTransferred, totalItems = 0,0
    repeat
        amountTransferred = transposer.transferItem(invSide, storageSide, 64)
        totalItems = totalItems + amountTransferred
    until amountTransferred == 0
    printf("Imported %s items",totalItems)
    storageSnapshot:sync()
    updatePageDisplay()
end

local reload = function()
    storageSnapshot:sync()
    updatePageDisplay()
end

local craft = function(opt)
    local ticket,processError
    local viewport={tty.getViewport()}
    local succ, err = xpcall(function()
        local isShift = keyboard.isShiftDown()
        print("Entering crafting mode (leave blank to cancel)")
        print(isShift and "Enter quantity to craft" or "Enter the minecraft item name and quantity separated by a space (quantity defaults to 1 if nil)")
        local itemToCraft
        if isShift and opt.data then
            local text=menu:read(50,itemsPerPage+4,36)
            if not text or text=="" then print("Craft attempt cancelled");return end
            local quantity=tonumber(text)
            assert(quantity and quantity>0 and quantity<math.huge and quantity%1==0,"Quantity must be a positive integer.")
            itemToCraft=opt.data.name..((opt.data.damage or 0)>0 and ":"..opt.data.damage or "").." "..quantity
        else itemToCraft=menu:read(50,itemsPerPage+4,36) end
        if not itemToCraft or itemToCraft=="" then print("Craft attempt cancelled");return end
        ticket=handoff.begin()
        local command="craft "..itemToCraft.." --result-id="..ticket
        if storageSide~=nil then command=command.." --storage-side="..storageSide end
        if invSide~=nil then command=command.." --output-side="..invSide end
        clearScreen()
        local processOk,problem=shell.execute(command)
        if not processOk then processError="Craft command failed: "..tostring(problem) end
    end, debug.traceback)
    local results=ticket and handoff.finish(ticket)
    local refreshErrors={}
    local function attempt(label,fn)
        local ok,value=pcall(fn)
        if not ok or value==false then refreshErrors[#refreshErrors+1]=label..": "..tostring(value) end
    end
    attempt("Viewport restore",function() tty.setViewport(table.unpack(viewport)) end)
    attempt("Storage refresh",function() return storageSnapshot:sync() end)
    attempt("Output refresh",function() return invSnapshot:sync() end)
    attempt("Inventory redraw",function() clearScreen();updatePageDisplay();menu:draw(true) end)
    for _,why in ipairs(refreshErrors) do print(why) end
    if not succ then print(err) end
    if processError then print(processError) end
    if results then
        if results.total==0 then print("No crafting outcome reported (menu closed or no job executed).")
        else
            printf("Craft outcomes: %d complete, %d failed, %d unknown, %d skipped",
                results.counts.complete or 0,results.counts.failed or 0,results.counts.unknown or 0,results.counts.skipped or 0)
            local last=results.results[#results.results]
            if last then print(last.status..": "..tostring(last.message or "")) end
            for _,result in ipairs(results.results) do
                for _,line in ipairs(require("craft_commands").receiptLines(result)) do print(line) end
                if result.exported==false then print("Output export incomplete; crafting status is unchanged.") end
                if result.partial then print("Kit partially completed; check completed components before retrying.") end
            end
            if (results.counts.unknown or 0)>0 then print("Check storage before retrying unknown jobs.") end
        end
    end
end

local showUsage = function()
    print("== USAGE ==")
    print("H to show usage")
    print("Left arrow key to page left")
    print("Right arrow key to page right")
    print("F or TAB to search")
    print("I to import")
    print("R to refresh")
    print("E or ENTER to export")
    print("C to craft")
end

function updatePageDisplay()
    -- 1. Get the current, filtered list of all non-air items
    local allItems = searchCriteria == "" and getFilteredItemList(storageSnapshot) or getFilteredItemList(storageSnapshot, searchFilter) 

    -- 2. Recalculate maxPages based on the filtered list. This is now always accurate.
    maxPages = math.ceil(#allItems / itemsPerPage)
    if maxPages == 0 then maxPages = 1 end -- Handle the case of an empty inventory
    currentPage = math.min(math.max(1, currentPage), maxPages)
    -- 3. Clear old menu options from the previous page
    local lastSelected = menu:getSelected()
    lastSelected = lastSelected and lastSelected.name
    for _, opt in ipairs(listOptions) do
        menu:removeOption(opt.name)
    end
    listOptions = {}

    -- 4. Calculate the slice of the filtered list for the current page
    local startIndex = (currentPage - 1) * itemsPerPage + 1
    local endIndex = math.min(currentPage * itemsPerPage, #allItems)
    gpu.set(50, 2, string.format("Page %-2d  (%3d to %-3d)    (%-3d total)", currentPage, startIndex - 1, endIndex, #allItems))
    -- 5. Loop through the SLICE of the filtered list. No more iOffset or endIndex tricks!
    for i = startIndex, endIndex do
        local optData = storageSnapshot:getItemInSlot(allItems[i]) -- Get data directly from our pre-filtered list
        local y = 3 + (i - startIndex)
        local name = "item" .. (i - startIndex) -- Name is based on position on the page

        local text = string.format("%-30s [%d]", optData.label:sub(1,20), optData.size)
        local option = menu:addOption(name, 50, y, text)
        option.data = optData
        
        -- KEYBIND IMPLEMENTATION
        option:bind(keys.left, goPrevPage)
        option:bind(keys.right, goNextPage)
        option:bind(keys.f, getSearch)
        option:bind(keys.tab, getSearch)
        option:bind(keys.i, import)
        option:bind(keys.r, reload)
        option:bind(keys.e, export)
        option:bind(keys.c, craft)
        option:bind(keys.h, showUsage)
        option:onActivate(export)
        table.insert(listOptions, option)
    end

    -- 6. Relink menu options and restore selection (this part remains the same)
    linkMenuOptions(listOptions)
    if #listOptions == 0 then
        local noRes = menu:addOption("noResult", 50, 3 + 1 - startIndex, "No search results                   ")
        table.insert(listOptions, noRes)
        noRes:bind(keys.f, getSearch)
        noRes:bind(keys.tab, getSearch)
        noRes:bind(keys.i, import)
        noRes:bind(keys.r, reload)
        noRes:bind(keys.h, showUsage)
        noRes:bind(keys.c, craft)
        noRes:onActivate(getSearch)
    end
    if lastSelected then
        if not menu:setSelected(lastSelected) and #listOptions > 0 then
            menu:setSelected(listOptions[#listOptions])
        end
    elseif #listOptions > 0 then
        menu:setSelected(listOptions[1])
    end
end

term.clear()
showUsage()
tty.setViewport(w, h/2, 0, h/2)
updatePageDisplay()
menu:draw(true)

while running do
    local _, _, _, key = event.pull("key_down")
    if key == keys.q then
        running = false
    else
        menu:handleEvent(key)
        menu:draw()
    end
end
print(tty.setViewport(table.unpack(oV)))
