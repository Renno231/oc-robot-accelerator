-- qmenu 1.1.0: A lightweight, keyboard-navigated menu library
local component = require("component")
local keys = require("keyboard").keys
local unicode = require("unicode")
local tty = require("tty")
local io = require("io")

local qmenu = {}

local Option = {}
Option.__index = Option

function Option:new(name, x, y, text)
    local self = setmetatable({}, Option)

    self.name = name
    self.menu = nil -- This will be set by the parent Menu object.

    self._x = x
    self._y = y
    self._text = text
    self._isLocked = false
    self._bindings = {}
    self._isDirty = true -- New options always need to be drawn.
    self._oldTextLength = unicode.len(text) -- Track text length for cleanup

    self._visuals = {
        normal = {fg = 0xFFFFFF, bg = 0},
        selected = {fg = 0, bg = 0xFFFFFF},
        activated = {fg = 0, bg = 0x32CD32}, -- For momentary feedback
        locked = {fg = 0x333333, bg = 0}
    }

    return self
end

function Option:_queueRedraw()
    self._isDirty = true
    if self.menu then self.menu:_requestRedraw(self) end
end

function Option:x(newX)
    local oldX = self._x
    if newX ~= nil then
        self._x = newX
        self:_queueRedraw()
    end
    return oldX
end

function Option:y(newY)
    local oldY = self._y
    if newY ~= nil then
        self._y = newY
        self:_queueRedraw()
    end
    return oldY
end

function Option:text(newText)
    local oldText = self._text
    if newText ~= nil and newText ~= oldText then
        self._oldTextLength = unicode.len(oldText)
        self._text = newText
        self:_queueRedraw()
    end
    return oldText
end

function Option:lock(state)
    local oldState = self._isLocked
    if state ~= nil then
        self._isLocked = not not state -- Coerce to boolean
        self:_queueRedraw()
    end
    return oldState
end

function Option:bind(key, action)
    local oldBinding = self._bindings[key]
    if action == false then
        self._bindings[key] = nil
    elseif type(action) == "table" then -- option
        self._bindings[key] = action.name
    elseif action ~= nil then
        self._bindings[key] = action
    end
    return oldBinding
end

function Option:onSelect(callback)
    local oldcb = self._onSelectCallback
    if type(callback)=="function" then
        self._onSelectCallback = callback
    end
    return oldcb
end

function Option:onDeselect(callback)
    local oldcb = self._onDeselectCallback
    if type(callback)=="function" then
        self._onDeselectCallback = callback
    end
    return oldcb
end

function Option:onActivate(callback)
    return self:bind(keys.enter, callback)
end

function Option:setStyle(stateName, fg, bg)
    if not self._visuals[stateName] then self._visuals[stateName] = {} end
    if fg then self._visuals[stateName].fg = fg end
    if bg then self._visuals[stateName].bg = bg end
    self:_queueRedraw()
    return self
end

function Option:handleEvent(key)
    local action = self._bindings[key]
    if not action then return end
    if type(action) == "function" then
        if self._isLocked and key == keys.enter then
            return "ACTION_BLOCKED"
        end
        return "CALLBACK", action
    elseif type(action) == "table" and getmetatable(action) == Option then
        return "SELECT_OPTION", action.name
    elseif type(action) == "string" then
        return "SELECT_OPTION", action
    end
end

local Menu = {}
Menu.__index = Menu

function Menu:new()
    local self = setmetatable({}, Menu)

    self._options = {} -- A map of options, keyed by name.
    self._selectedOptionName = nil
    self._drawQueue = {}
    self._isVisible = true
    self._gpu = component.proxy(component.gpu.address)

    return self
end

function Menu:addOption(name, x, y, text)
    if self._options[name] then
        error("Option with name '" .. name .. "' already exists.", 2)
    end

    local newOption = Option:new(name, x, y, text)
    newOption.menu = self -- Assign the parent reference

    self._options[name] = newOption

    self:_requestRedraw(newOption)

    if not self._selectedOptionName then self:setSelected(newOption) end

    return newOption
end

function Menu:removeOption(name)
    local option = self._options[name]
    if not option then
        return nil
    end

    if self._selectedOptionName == name then
        local newSelection = nil
        local foundCurrent = false
        for optName, opt in pairs(self._options) do
            if foundCurrent then
                newSelection = optName
                break
            end
            if optName == name then
                foundCurrent = true
            end
        end
        if not newSelection then
            local prevOption = nil
            for optName, opt in pairs(self._options) do
                if optName == name then
                    if prevOption then
                        newSelection = prevOption
                    end
                    break
                end
                prevOption = optName
            end
        end
        if not newSelection then
            newSelection = next(self._options)
        end
        if newSelection then
            self:setSelected(newSelection)
        else
            self._selectedOptionName = nil
        end
    end

    if self._gpu then
        local clearText = string.rep(" ", math.max(option._oldTextLength or unicode.len(option._text), 1))
        self._gpu.set(option._x, option._y, clearText)
    end

    self._options[name] = nil
    for i = 1, #self._drawQueue do
        if self._drawQueue[i] == option then
            table.remove(self._drawQueue, i)
            break
        end
    end

    option.menu = nil

    return option
end

function Menu:clearOptions()
    self._options = {}
    self._selectedOptionName = nil
    self._drawQueue = {}
    return self
end

function Menu:getOption(name)
    return self._options[name]
end

function Menu:setSelected(optionOrName)
    local targetName
    if type(optionOrName) == "table" and getmetatable(optionOrName) == Option then
        targetName = optionOrName.name
    elseif type(optionOrName) == "string" then
        targetName = optionOrName
    end
    if not targetName or not self._options[targetName] then
        return false -- Target doesn't exist.
    end
    if self._selectedOptionName == targetName then
        return true -- Already selected.
    end

    local oldOption = self._options[self._selectedOptionName]
    
    if oldOption then
        oldOption:_queueRedraw()
        if oldOption._onDeselectCallback then
            local ok, err = pcall(oldOption._onDeselectCallback, oldOption)
            if not ok and self._onError then
                self._onError(err)
            end
        end
    end

    self._selectedOptionName = targetName
    local newOption = self._options[targetName]

    if newOption then
        newOption:_queueRedraw()
        if newOption._onSelectCallback then
            local ok, err = pcall(newOption._onSelectCallback, newOption)
            if not ok and self._onError then
                self._onError(err)
            end
        end
    else
        return false
    end

    return true
end

function Menu:getSelected()
    return self._options[self._selectedOptionName]
end

function Menu:_requestRedraw(option)
    for i = 1, #self._drawQueue do
        if self._drawQueue[i] == option then return end
    end
    table.insert(self._drawQueue, option)
    return true
end

function Menu:draw(forceRedraw)
    if not self._isVisible then return end
    
    if forceRedraw then
        self._drawQueue = {}
        for _, option in pairs(self._options) do
            option._isDirty = true
            table.insert(self._drawQueue, option)
        end
    end
    
    if #self._drawQueue == 0 then return end

    local oldFg, oldBg = self._gpu.getForeground(), self._gpu.getBackground()
    for i = 1, #self._drawQueue do
        local option = self._drawQueue[i]
        local state = "normal"

        if option:lock() then
            state = "locked"
        elseif option.name == self._selectedOptionName then
            state = "selected"
        end

        local style = option._visuals[state]
        if style then
            local currentTextLength = unicode.len(option._text)
            if currentTextLength < option._oldTextLength then
                local cleanupText = string.rep(" ", option._oldTextLength - currentTextLength)
                self._gpu.set(option._x + currentTextLength, option._y, cleanupText)
            end
            self._gpu.setForeground(style.fg)
            self._gpu.setBackground(style.bg)
            self._gpu.set(option._x, option._y, option._text)
            option._oldTextLength = currentTextLength
            option._isDirty = false
        end
    end

    self._drawQueue = {}
    self._gpu.setForeground(oldFg)
    self._gpu.setBackground(oldBg)
    return true
end

function Menu:handleEvent(keyCode) -- rework
    if not self._isVisible or not self._selectedOptionName then return end

    local selectedOption = self._options[self._selectedOptionName]
    if not selectedOption then return end

    local actionType, returned = selectedOption:handleEvent(keyCode)

    if actionType == "CALLBACK" then
        local ok, err = pcall(returned, selectedOption)
        if not ok and self._onError then self._onError(err) end
    elseif actionType == "SELECT_OPTION" then
        self:setSelected(returned)
    end
end

function Menu:read(arg1, arg2, arg3)
    local x,y, option, maxLength
    if type(arg1) =="number" and type(arg2) == "number" then
        x,y,maxLength = tonumber(arg1),tonumber(arg2),tonumber(arg3)
    elseif type(arg1) == "table" and getmetatable(arg1) == Option then
        option = arg1
        maxLength = tonumber(arg2) or unicode.len(option:text())
        x,y = option:x(),option:y()
    end
    if not (x and y) then return end
    local oV = {tty.getViewport()}
    if not maxLength then
        maxLength = oV[1] - x
    end
    
    tty.setViewport(maxLength, 1, x-1,y-1)
    local core = require("core/cursor")
    local oldC = core.vertical.clear
    core.vertical.clear = "\27[K"
    io.write("\27[7m\27[2J")
    local read = io.read()
    io.write("\27[0m")
    core.vertical.clear = oldC
    tty.setViewport(table.unpack(oV))
    if option then option:_queueRedraw() end
    return read
end

qmenu.Menu = Menu
qmenu.Option = Option
function qmenu.create() return Menu:new() end

return qmenu