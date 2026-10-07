-- craft.lua (Reworked for qmenu UI)
package.loaded.crafting = nil
package.loaded.craftingv4_3 = nil
package.loaded.craftingv4_4 = nil
package.loaded.inventory = nil
package.loaded.gatenet = nil
package.loaded.qmenu = nil

local serialization = require "serialization"
local component = require "component"
local sides = require "sides"
local event = require "event"
local inventory = require"inventory"
local shortHand = require"msyn"
local crafting = require "craftingv4_4"
local shell = require"shell"
local term = require "term"
local qmenu = require "qmenu"
local keyboard = require "keyboard"
local keys = keyboard.keys
local tty = require"tty"
local gpu = component.gpu

local craftPlans = require "craft_plans"

-- =============================================================================
-- SECTION 1: INITIALIZATION, CONSTANTS, & HELPERS
-- =============================================================================

-- UI Layout Constants
local w, h = gpu.getResolution()
local LEFT_PANE_WIDTH = math.floor(w / 2)

-- State Variables
local running = true
local craftSuccess = false
local storageSide, outputSide

-- =============================================================================
-- print & SCREEN MANAGEMENT
-- =============================================================================

-- Clear the entire terminal for the print area on startup
local oV = {tty.getViewport()}

--- Clears the left pane of the screen where menus are displayed.
local function clearLeftPane()
    gpu.fill(1, 1, LEFT_PANE_WIDTH, h, " ")
end

-- =============================================================================
-- CRAFT PLAN MANAGEMENT
-- =============================================================================

local function saveCraftPlan(plan, name)
    local saved, err = craftPlans.save(name, plan)
    if not saved then print("Error saving plan: " .. tostring(err)); return false end
    print("Craft plan saved as '" .. name .. "'")
    return true
end

local function listCraftPlans()
    local names, err = craftPlans.list()
    if not names then print("Unable to list plans: " .. tostring(err)); return {} end
    return names
end

-- =============================================================================
-- MENU BUILDING BLOCKS
-- =============================================================================

-- Helper function to link menu options for navigation
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

local function export(snapshot, desiredAmount, itemToExport)
    local amountToExport = desiredAmount
    snapshot:sync()
    repeat
        local slotToExtractFrom = snapshot:nextSlotContaining(itemToExport)
        if not slotToExtractFrom then print("Unable to extract item", itemToExport) break end
        local moved = component.transposer.transferItem(storageSide, outputSide, amountToExport, slotToExtractFrom)
        if moved == 0 then print("Failed to move",itemToExport,"to output") break end
        print(string.format("Transferred %s of %s to output", moved, itemToExport))
        amountToExport = amountToExport - moved
        snapshot:sync()
    until amountToExport <= 0
    return amountToExport <= 0
end

--- Creates a simple Yes/No prompt menu.
---@param prompt string The question to ask the user.
---@param defaultYes boolean If true, 'Yes' is the default selection.
---@param onYes function Callback function for 'Yes'.
---@param onNo function Callback function for 'No'.
local function createYesNoMenu(prompt, defaultYes, onYes, onNo, onPreview)
    clearLeftPane()
    local menu = qmenu.create()
    -- print(prompt)
    gpu.set(2,2,prompt)
    local yesOpt = menu:addOption("yes", 2, 3, "Yes")
    local noOpt = menu:addOption("no", 2, 4, "No")
    if onPreview then
        local previewOpt=menu:addOption("preview",2,5,"Explain this plan")
        previewOpt:onActivate(function() onPreview();clearLeftPane();gpu.set(2,2,prompt);menu:draw(true) end)
        noOpt:bind(keys.down,"preview");previewOpt:bind(keys.up,"no");previewOpt:bind(keys.down,"yes")
    end

    local menuRunning, submitted = true, false
    yesOpt:onActivate(function() menuRunning = false; submitted = true; onYes() end)
    noOpt:onActivate(function() menuRunning = false; submitted = true; onNo() end)

    yesOpt:bind(keys.right, "no")
    yesOpt:bind(keys.left, "no")
    yesOpt:bind(keys.down, "no")
    yesOpt:bind(keys.up, "no")
    noOpt:bind(keys.left, "yes")
    noOpt:bind(keys.right, "yes")
    noOpt:bind(keys.up, "yes")
    noOpt:bind(keys.down, "yes")
    if onPreview then noOpt:bind(keys.down,"preview") end

    menu:setSelected(defaultYes and "yes" or "no")
    menu:draw()

    while menuRunning and running do
        local _, _, _, key = event.pull(0.25, "key_down")
        if key == keys.q then
            menuRunning = false
        elseif key then
            menu:handleEvent(key)
            menu:draw()
        end
    end
    
    clearLeftPane()
    return submitted
end

--- Creates a text input menu.
---@param prompt string The prompt for the input field.
---@param defaultValue string|nil The default value in the input field.
---@param onSubmit function Callback function with the user's input as an argument.
local function createTextInputMenu(prompt, defaultValue, onSubmit)
    clearLeftPane()
    local menu = qmenu.create()
    local promptOpt = menu:addOption("prompt", 2, 3, prompt)
    menu:draw()

    local input = menu:read(2, 4, math.max(1, math.min(40, LEFT_PANE_WIDTH - 4)))
    if input == "" and defaultValue then input = defaultValue end
    if input then
        onSubmit(input)
    end
    clearLeftPane()
end

--- Creates and runs the recipe selection menu.
---@param recipes table A table of recipe tables.
---@param onSelect function Callback with the selected recipe as an argument.
local function createRecipeSelectionMenu(itemName, recipes, onSelect)
    clearLeftPane()
    local menuRunning = true
    local menu = qmenu.create()
    local submitted = false
    local currentRecipeIndex = 1
    local gridStartX, gridStartY = 2, 6
    local listStartX = gridStartX + 12
    gpu.set(2, 2, string.format("Selecting recipe for %s", itemName))

    -- Helper to draw the recipe grid and list
    local function drawRecipe(recipe, highlightSlot)
        -- Clear previous drawing area
        gpu.fill(gridStartX, gridStartY - 1, LEFT_PANE_WIDTH - 2, 12, " ")

        -- Assign colors to unique items
        local itemColors = {}
        local colorIndex = 1
        local palette = {0xFF6B6B, 0x4ECDC4, 0x45B7D1, 0xF7DC6F, 0xBB8FCE, 0x85C88A}
        for i, slot in pairs(recipe) do
            if type(i) == "number" and slot ~= "minecraft:air" and not itemColors[slot] then
                itemColors[slot] = palette[colorIndex % #palette + 1]
                colorIndex = colorIndex + 1
            end
        end

        -- Draw grid
        local gridWidth, gridHeight = 3, 3
        if recipe.isProcessing then gridWidth, gridHeight = 1, 1 end

        for i = 0, 8 do
            local x = gridStartX + (i % gridWidth) * 4
            local y = gridStartY + math.floor(i / gridWidth) * 2
            local item = recipe[i + 1] or "minecraft:air"

            local bg, fg = 0x333333, 0xEEEEEE
            if item ~= "minecraft:air" then
                bg = itemColors[item] or 0xAAAAAA
                fg = 0x000000
            end
            if highlightSlot == i + 1 then
                fg, bg = bg, fg -- Invert colors for highlight
            end

            gpu.setBackground(bg)
            gpu.setForeground(fg)
            gpu.set(x, y, "   ")
            gpu.set(x + 1, y, string.format("%2d", i + 1))
        end
        gpu.setBackground(0)
        gpu.setForeground(0xFFFFFF)

        -- Draw item list
        local listY = gridStartY
        gpu.set(listStartX, listY - 1, "Items:")
        local sortedItems = {}
        for i, item in pairs(recipe) do
            if type(i) == "number" and item ~= "minecraft:air" then
                table.insert(sortedItems, {index = i, name = item})
            end
        end
        table.sort(sortedItems, function(a, b) return a.index < b.index end)

        for _, item in ipairs(sortedItems) do
            local color = itemColors[item.name] or 0xAAAAAA
            gpu.setForeground(color)
            gpu.set(listStartX, listY, string.format("%d: %s", item.index, item.name))
            listY = listY + 1
        end
        gpu.setForeground(0xFFFFFF)
    end

    -- Main navigation option
    local navOpt = menu:addOption("nav", 2, 3, "")
    local skipOpt = menu:addOption("skip", 2, 4, "Skip Selection")
    local terminalOpt = menu:addOption("terminal",2,h-3,"External material only")
    terminalOpt:onActivate(function()
        menuRunning=false;submitted=true;onSelect(false)
    end)
    local function updateNavText()
        navOpt:text(string.format("<- Recipe %d -> (%d total)", currentRecipeIndex, #recipes))
    end

    navOpt:bind(keyboard.keys.left, function()
        currentRecipeIndex = currentRecipeIndex - 1
        if currentRecipeIndex < 1 then currentRecipeIndex = #recipes end
        updateNavText()
        drawRecipe(recipes[currentRecipeIndex])
        menu:draw()
    end)

    navOpt:bind(keyboard.keys.right, function()
        currentRecipeIndex = currentRecipeIndex + 1
        if currentRecipeIndex > #recipes then currentRecipeIndex = 1 end
        updateNavText()
        drawRecipe(recipes[currentRecipeIndex])
        menu:draw()
    end)

    navOpt:onActivate(function()
        menuRunning = false
        submitted = true
        onSelect(recipes[currentRecipeIndex])
    end)

    skipOpt:onActivate(function()
        menuRunning = false
        submitted = true
        onSelect()
    end)

    skipOpt:bind(keys.up, "nav")
    skipOpt:bind(keys.down, "terminal")
    navOpt:bind(keys.down, "skip")
    navOpt:bind(keys.up, "terminal")
    terminalOpt:bind(keys.up,"skip")
    terminalOpt:bind(keys.down,"nav")

    updateNavText()
    drawRecipe(recipes[currentRecipeIndex])
    menu:draw(true)

    while menuRunning and running do
        local _, _, _, key = event.pull(0.25, "key_down")
        if key == keys.q then
            menuRunning = false
        elseif key then
            menu:handleEvent(key)
            menu:draw()
        end
    end
    clearLeftPane()
    return submitted
end

--- Creates and runs the ore dictionary selection menu.
--- This menu displays the recipe with a highlighted slot and a paginated list of replacement items.
---@param oredictOptions table A table of {name, count} pairs, sorted by count.
---@param recipe table The full recipe table being worked on.
---@param slotIndex number The index of the slot in the recipe to be resolved.
---@param onSelect function Callback with the selected option's name as an argument.
local function createOreDictSelectionMenu(originalDepName, oredictOptions, recipe, slotIndex, onSelect)
    clearLeftPane()
    local menu = qmenu.create()
    local menuRunning = true
    local submitted = false
    local itemsPerPage = math.max(1, math.min(10, h - 17))
    local currentPage = 1
    local maxPages = math.ceil(#oredictOptions / itemsPerPage)
    local listOptions = {} -- To hold the option objects for the current page

    -- Recipe visualization part (top of the screen)
    local gridStartX, gridStartY = 2, 6
    local listStartY = gridStartY + 12 -- Start list below the grid
    local pageTextY = 2

    -- Helper to draw the recipe grid and list (reused from createRecipeSelectionMenu)
    local function drawRecipe(recipe, highlightSlot)
        -- Clear previous drawing area
        gpu.fill(gridStartX, gridStartY - 2, LEFT_PANE_WIDTH - 2, 12, " ")

        -- Assign colors to unique items
        local itemColors = {}
        local colorIndex = 1
        local palette = {0xFF6B6B, 0x4ECDC4, 0x45B7D1, 0xF7DC6F, 0xBB8FCE, 0x85C88A}
        for i, slot in pairs(recipe) do
            if type(i) == "number" and slot ~= "minecraft:air" and not itemColors[slot] then
                itemColors[slot] = palette[colorIndex % #palette + 1]
                colorIndex = colorIndex + 1
            end
        end

        -- Draw grid
        local gridWidth, gridHeight = 3, 3
        if recipe.isProcessing then gridWidth, gridHeight = 1, 1 end

        for i = 0, 8 do
            local x = gridStartX + (i % gridWidth) * 4
            local y = gridStartY + math.floor(i / gridWidth) * 2
            local item = recipe[i + 1] or "minecraft:air"

            local bg, fg = 0x333333, 0xEEEEEE
            if item ~= "minecraft:air" then
                bg = itemColors[item] or 0xAAAAAA
                fg = 0x000000
            end
            if highlightSlot == i + 1 then
                fg, bg = bg, fg -- Invert colors for highlight
            end

            gpu.setBackground(bg)
            gpu.setForeground(fg)
            gpu.set(x, y, "   ")
            gpu.set(x + 1, y, string.format("%2d", i + 1))
        end
        gpu.setBackground(0)
        gpu.setForeground(0xFFFFFF)

        -- Draw item list
        local listY = gridStartY
        gpu.set(gridStartX + 12, listY - 2, "Items:")
        local sortedItems = {}
        for i, item in pairs(recipe) do
            if type(i) == "number" and item ~= "minecraft:air" then
                table.insert(sortedItems, {index = i, name = item})
            end
        end
        table.sort(sortedItems, function(a, b) return a.index < b.index end)

        for _, item in ipairs(sortedItems) do
            local color = itemColors[item.name] or 0xAAAAAA
            gpu.setForeground(color)
            gpu.set(gridStartX + 12, listY, string.format("%d: %s", item.index, item.name))
            listY = listY + 1
        end
        gpu.setForeground(0xFFFFFF)
    end

    -- Pagination functions
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

    -- Function to redraw the list of options for the current page
    function updatePageDisplay()
        -- Clear old options from the menu and the screen
        for _, opt in ipairs(listOptions) do
            menu:removeOption(opt.name)
        end
        listOptions = {}
        gpu.fill(2, listStartY, LEFT_PANE_WIDTH - 2, h - listStartY, " ") -- clear area

        local startIndex = (currentPage - 1) * itemsPerPage + 1
        local endIndex = math.min(currentPage * itemsPerPage, #oredictOptions)
        for i = startIndex, endIndex do
            local optData = oredictOptions[i]
            local y = listStartY + (i - startIndex)
            local name = "item" .. i
            local text = string.format("%-30s [%d]", optData.name:sub(1,20), optData.count)
            local option = menu:addOption(name, 2, y, text)
            option.data = optData.name
            -- KEY IMPLEMENTATION: Bind left/right to every option for pagination
            option:bind(keyboard.keys.left, goPrevPage)
            option:bind(keyboard.keys.right, goNextPage)

            -- Activation sends the selected item name back to the algorithm
            option:onActivate(function()
                menuRunning = false
                submitted = true
                onSelect(option.data)
            end)

            table.insert(listOptions, option)
        end
        linkMenuOptions(listOptions)
        -- Set selection to the first item on the new page
        if #listOptions > 0 then
            menu:setSelected(listOptions[1])
        end

        -- Update page text
        gpu.set(2, pageTextY, string.format("Oredict Resolution: %s", string.sub(originalDepName, 1, 20)))
        gpu.set(2, pageTextY+1, string.format("Items %d-%d of %d", startIndex, endIndex, #oredictOptions))
    end

    -- Initial draw
    drawRecipe(recipe, slotIndex) -- Highlight the slot in question
    updatePageDisplay()
    menu:draw(true)
    while menuRunning and running do
        local _, _, _, key = event.pull(0.25, "key_down")
        if key == keys.q then
            menuRunning = false
        elseif key then
            menu:handleEvent(key)
            menu:draw()
        end
    end
    clearLeftPane()
    return submitted
end

-- =============================================================================
-- MAIN APPLICATION LOGIC
-- =============================================================================

-- Argument parsing
local args, options = shell.parse(...)
local queryMode = options.q or #args == 0
local function report(result)
    if options["result-id"] then require("craft_handoff").report(options["result-id"],result) end
end
storageSide = options["storage-side"] == nil and sides.down or tonumber(options["storage-side"])
outputSide = options["output-side"] == nil and sides.south or tonumber(options["output-side"])
assert(type(storageSide) == "number" and storageSide >= 0 and storageSide <= 5 and storageSide % 1 == 0, "Invalid storage side.")
assert(type(outputSide) == "number" and outputSide >= 0 and outputSide <= 5 and outputSide % 1 == 0, "Invalid output side.")
local function timeoutOption(name, default, allowZero)
    local value = options[name] == nil and default or tonumber(options[name])
    assert(type(value) == "number" and value == value and value < math.huge and (allowZero and value >= 0 or value > 0), "Invalid " .. name)
    return value
end
local connectTimeout = timeoutOption("connect-timeout", 10)
local idleTimeout = timeoutOption("idle-timeout", 60)
local jobTimeout = timeoutOption("job-timeout", 300, true)

-- Component check
print("Checking components...")
if not component.transposer then error("Transposer component not found!") end

local startCraftingFlow
-- Main Menu
local function mainMenu()
    clearLeftPane()
    local menu = qmenu.create()
    local newCraftOpt = menu:addOption("new", 2, 3, "New Craft")
    local toolsOpt = menu:addOption("tools", 2, 4, "Tools")
    local plansOpt = menu:addOption("plans", 2, 5, "Craft Plans")
    local kitsOpt = menu:addOption("kits", 2, 6, "Craft Kits")
    local stockOpt = menu:addOption("stockkeeper", 2, 7, "Stockkeeper")

    newCraftOpt:onActivate(function()
        createTextInputMenu("Enter item name to craft:", nil, function(itemName)
            if not itemName or itemName == "" then print("invalid item name", itemName) return end
            createTextInputMenu("Enter quantity:", "1", function(qtyStr)
                local qty = math.max(tonumber(qtyStr) or 1, 1)
                print("quantity", qty)
                local succ, err = xpcall(function() 
                    startCraftingFlow(itemName, qty, true)
                end, debug.traceback)
                if not succ then print(err) end
            end)
        end)
        menu:draw(true)
    end)

    local function management(binary)
        local forwarded={"--interactive",
            "--storage-side="..storageSide,"--connect-timeout="..connectTimeout,
            "--idle-timeout="..idleTimeout,"--job-timeout="..jobTimeout}
        if options["result-id"] then forwarded[#forwarded+1]="--result-id="..options["result-id"] end
        local processOk,err=shell.execute(binary,nil,table.unpack(forwarded))
        if not processOk then print("Management command failed: "..tostring(err)) end
        clearLeftPane();menu:draw(true)
        -- Process return indicates menu exit, not a completed crafting job.
    end
    toolsOpt:onActivate(function() management("crafttools") end)
    plansOpt:onActivate(function() management("craftplan") end)
    kitsOpt:onActivate(function() management("craftkit") end)
    stockOpt:onActivate(function() management("stockkeeper") end)
    linkMenuOptions({newCraftOpt, toolsOpt, plansOpt, kitsOpt, stockOpt})
    menu:draw(true)
    local menuRunning = true
    while menuRunning and running do
        local _, _, _, key = event.pull(0.25, "key_down")
        if key == keys.q then
            menuRunning = false
        elseif key then
            menu:handleEvent(key)
            menu:draw()
        end
    end
    clearLeftPane()
end

--- The core crafting flow, handling both query and non-query modes.
---@param itemToCraft string The name of the item to craft.
---@param amountToCraft number The quantity to craft.
---@param isQueryMode boolean Whether to use interactive menus.
function startCraftingFlow(itemToCraft, amountToCraft, isQueryMode, savedPlan)
    craftSuccess = false
    clearLeftPane()
    print("Started crafting flow")
    itemToCraft = shortHand.convertItemName(itemToCraft)
    print(string.format("Starting craft for %dx %s (Query: %s)", amountToCraft, itemToCraft, tostring(isQueryMode)))

    local snapshot = inventory.new(component.transposer, storageSide)
    if not snapshot then report({status="failed",success=false,mayHaveExecuted=false,message="Unable to read storage inventory."});print("Unable to read storage inventory."); return end
    local existingCount = snapshot:countItemByName(itemToCraft)

    -- Initial inventory check
    if existingCount >= amountToCraft and not options.f then
        local shouldSkip = false
        if isQueryMode then
            if not createYesNoMenu(
                string.format("%s already exists (%d). Skip crafting?", itemToCraft, existingCount),
                false, -- Default to Yes
                function() shouldSkip = true end,
                function() shouldSkip = false end
            ) then return end
        else -- Quick craft mode
            print(string.format("%s already exists (%d). Skip crafting? (y/n)", itemToCraft, existingCount))
            shouldSkip = ((io.read() or "y") .. "n"):match("^%s*[Yy]")
        end

        if shouldSkip then
            print("Skipping craft, exporting from inventory.")
            local exported=export(snapshot, amountToCraft, itemToCraft)
            report({status="skipped",success=false,exported=exported,message=exported and "Exported existing stock; no craft executed." or "Existing-stock export incomplete."})
            return
        end
    end

    print("Calculating crafting plan...")
    local craftPlan = savedPlan or crafting.calculateCraftingPlan(itemToCraft, amountToCraft, component.transposer, storageSide)

    -- Handle coroutine yields for interactive mode
    if isQueryMode then
        local step = 1
        while craftPlan.yield_data and running do
            local yieldType = craftPlan.yield_data[1]
            local yieldItem = craftPlan.yield_data[2]

            if yieldType == "select_recipe" then -- coroutine.yield("select_recipe", itemName, allRecipes, inventoryCache)
                if craftPlan.yield_data[3] == nil then
                    crafting.resumeCalculation(craftPlan)
                else
                    if not createRecipeSelectionMenu(yieldItem, craftPlan.yield_data[3], function(selectedRecipe)
                        crafting.resumeCalculation(craftPlan, selectedRecipe)
                    end) then crafting.cancelCalculation(craftPlan) end
                end
            elseif yieldType == "select_oredict" then -- coroutine.yield("select_oredict", originalDepName, resolvedDeps, chosenRecipe, key, inventoryCache)
                -- Prepare options with inventory counts
                if craftPlan.yield_data[3] == nil or #craftPlan.yield_data[3] == 1 then
                    print(string.format("SKIPPED oreDict selection (only 1 available) at step %d for oreTag %s", step, yieldItem:sub(1,20)))
                    crafting.resumeCalculation(craftPlan)
                else
                    local optionsWithCounts = {}
                    for _, name in ipairs(craftPlan.yield_data[3]) do
                        local count = snapshot:countItemByName(name)
                        table.insert(optionsWithCounts, {name = name, count = count})
                    end
                    -- (oredictOptions, recipe, slotIndex, onSelect)
                    if not createOreDictSelectionMenu(yieldItem, optionsWithCounts, craftPlan.yield_data[4], craftPlan.yield_data[5], function(selectedOpt)
                        print("SELECTEDOPT", selectedOpt)
                        crafting.resumeCalculation(craftPlan, selectedOpt)
                    end) then crafting.cancelCalculation(craftPlan) end
                end
            elseif yieldType == "skip_inventory_check" then
                if not createYesNoMenu(
                    string.format("Skip inventory check for %s?", yieldItem),
                    false, -- Default to Yes
                    function() crafting.resumeCalculation(craftPlan, true) end,
                    function() crafting.resumeCalculation(craftPlan, false) end
                ) then crafting.cancelCalculation(craftPlan) end
            else
                print("Unknown yield type: " .. tostring(yieldType))
                crafting.resumeCalculation(craftPlan)
            end
            step = step + 1
        end
    else
        while craftPlan.yield_data and running do
            print(craftPlan.yield_data[1],craftPlan.yield_data[2])
            crafting.resumeCalculation(craftPlan)
        end
    end

    -- Final result handling
    if not running then crafting.cancelCalculation(craftPlan); return end
    if craftPlan.error then
        report({status=craftPlan.cancelled and "cancelled" or "failed",success=false,mayHaveExecuted=false,message=craftPlan.error})
        print("ERROR: " .. craftPlan.error)
        return
    end

    if not (craftPlan.success and craftPlan.craftable) then
        report({status="failed",success=false,mayHaveExecuted=false,message="Missing allowed inputs: "..serialization.serialize(craftPlan.external_needed)})
        print("Insufficient inventory to craft.")
        print("Missing: " .. serialization.serialize(craftPlan.external_needed, 100))
        -- TODO: Add prompt to export available items
        return
    end

    for _, task in ipairs(craftPlan.tasks or {}) do
        if task.isProcessing or task.machineType then
            report({status="failed",success=false,mayHaveExecuted=false,message="Machine processing is unsupported."})
            print("This plan requires machine processing, which the robot executor does not support.")
            return
        end
    end
    print("Crafting plan calculated successfully!")
    print("Cost: " .. serialization.serialize(craftPlan.inventory_needed))
    for _,line in ipairs(assert(require("craft_preview").lines(craftPlan))) do print(line) end

    -- A loaded plan can execute directly without another save/name prompt.
    if isQueryMode and not savedPlan then
        createYesNoMenu("Save this craft plan?", false, -- Default to No
            function() -- On Yes
                local plans = listCraftPlans()
                print("Existing plans: " .. table.concat(plans, ", "))
                createTextInputMenu("Enter name for new plan:", nil, function(name)
                    if name and name ~= "" then
                        saveCraftPlan(craftPlan, name)
                    end
                end)
            end,
            function() end -- On No, do nothing
        )
    end

    -- Prompt to execute craft
    local shouldExecute = false
    if isQueryMode then
        createYesNoMenu(
            string.format("Proceed with crafting %dx %s?", amountToCraft, itemToCraft),
            true, -- Default to Yes
            function() shouldExecute = true end,
            function() shouldExecute = false end,
            function() require("craft_management_ui").show("preview",{plan=craftPlan}) end
        )
    else -- Quick craft mode
        print(string.format("Craft %s x %s (y/n)?", amountToCraft, itemToCraft))
        shouldExecute = ((io.read() or "n") .. "y"):match("^%s*[Yy]")
    end

    local outcome
    if shouldExecute then
        print("Executing craft...")
    -- This block finds the crafting server, sends the plan, and monitors the process.
        local result = craftPlans.run(craftPlan, {
            connectTimeout = connectTimeout, idleTimeout = idleTimeout, jobTimeout = jobTimeout,
            shouldContinue = function() return running end,
            onMessage = function(update) print(update) end
        })
        craftSuccess = result.success
        outcome=result
        print(result.message or (craftSuccess and "Craft complete." or "Craft failed."))
        if result.status == "unknown" then print("Outcome unknown; check storage before retrying.") end
        if result.cleanupError then print(result.cleanupError) end
        if result.jobId and result.serverAddress then print("Receipt: craftplan status "..result.serverAddress.." "..result.jobId) end
    else
        print("Craft cancelled by user.")
        report({status="cancelled",success=false,message="Craft cancelled by user; no job submitted."})
    end

    if craftSuccess then
        local function exportResult()
            local exported,value=pcall(export,snapshot,amountToCraft,itemToCraft)
            outcome.exported=exported and value or false
            if not exported then outcome.exportError=tostring(value);print("Export failed: "..tostring(value)) end
        end
        if isQueryMode then
            createYesNoMenu("Export craft to output chest?", true,
                function() print("Exporting items...");exportResult() end,
                function() print("Not exporting.") end
            )
        else
            print("Export craft to output chest?")
            if ((io.read() or "n") .. "y"):match("^%s*[Yy]") then
                exportResult()
            end
        end
    end
    if outcome then report(outcome) end
end

-- =============================================================================
-- SCRIPT ENTRY POINT
-- =============================================================================

local function stopProgram()
    print("Interrupted! Shutting down...")
    running = false
    return false
end
event.listen("interrupted", stopProgram)

local ok, entryError = xpcall(function()
if #args == 0 then
    -- No arguments, start in main menu (query mode)
    term.clear()
    tty.setViewport(w - LEFT_PANE_WIDTH, h, LEFT_PANE_WIDTH, 0)
    mainMenu()
    tty.setViewport(table.unpack(oV))
else
    -- Arguments provided, start a quick craft
    local itemToCraft, amountToCraft = args[1], math.max(tonumber(args[2]) or 1, 1)
    if not itemToCraft or type(itemToCraft) ~= "string" or not string.find(itemToCraft, ":", 1, true) then
        print("Error: first argument must be a valid item ID.")
        return
    end
    startCraftingFlow(itemToCraft, amountToCraft, queryMode)
end

end, debug.traceback)
-- Restore terminal/event state even after interruption or callback errors.
local restored,restoreError=pcall(tty.setViewport,table.unpack(oV))
local ignored,ignoreError=pcall(event.ignore,"interrupted",stopProgram)
if not ok then print(entryError) end
if not restored then print("Viewport restore failed: "..tostring(restoreError)) end
if not ignored then print("Listener cleanup failed: "..tostring(ignoreError)) end
print("\nClient script exiting.")
