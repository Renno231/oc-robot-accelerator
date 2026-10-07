from test_support import LuaCase, ROOT


class InventoryHandoffTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('craft_commands', 'lib/craft_commands.lua')
        self.lua.execute("""
            KEYS={46,16};READS={'7'};SHIFT=true;SYNCS={};DRAWS=0;PRINTED={}
            print=function(...) local s={};for _,v in ipairs({...}) do s[#s+1]=tostring(v) end;PRINTED[#PRINTED+1]=table.concat(s,' ') end
            package.preload.event=function() return {pull=function() return 'key_down','kbd',0,table.remove(KEYS,1) end} end
            package.preload.keyboard=function() return {isShiftDown=function() return SHIFT end,keys={
                q=16,c=46,up=200,down=208,left=203,right=205,f=33,tab=15,i=23,r=19,e=18,h=35}} end
            local gpu={getResolution=function() return 160,50 end,fill=function() end,set=function() end}
            local tp={getInventoryName=function(side)
                if side==0 then return 'storagedrawers:controller' elseif side==2 then return 'minecraft:chest' end
            end}
            package.preload.component=function() return {gpu=gpu,transposer=tp} end
            package.preload.sides=function() return {} end
            package.preload.tty=function() return {getViewport=function() return 80,25,0,0 end,setViewport=function(...) LAST_VIEW={...} end} end
            package.preload.term=function() return {clear=function() end} end
            package.preload.inventory=function() return {new=function(_,side) return {
                sync=function() SYNCS[side]=(SYNCS[side] or 0)+1 end,
                getInventorySize=function() return 1 end,
                getItemInSlot=function() return {name='t:gear',damage=3,size=4,label='Gear'} end}
            end} end
            package.preload.qmenu=function() return {create=function()
                local menu={options={}}
                function menu:addOption(name,x,y,text)
                    local o={name=name,bindings={}}
                    function o:bind(key,cb) self.bindings[key]=cb;return self end
                    function o:onActivate(cb) self.activate=cb;return self end
                    self.options[name]=o;return o
                end
                function menu:draw() DRAWS=DRAWS+1 end
                function menu:getSelected() return self.options[self.selected] end
                function menu:setSelected(o) self.selected=type(o)=='table' and o.name or o;return self.options[self.selected]~=nil end
                function menu:removeOption(n) self.options[n]=nil end
                function menu:handleEvent(key) local o=self:getSelected();if o and type(o.bindings[key])=='function' then o.bindings[key](o) end end
                function menu:read() return table.remove(READS,1) end
                return menu
            end} end
            package.preload.shell=function() return {execute=function(command)
                COMMAND=command
                local id=assert(command:match('%-%-result%-id=(%S+)'))
                require('craft_handoff').report(id,{status='unknown',message='reply lost'})
                require('craft_handoff').report(id,{status='complete',message='later job completed'})
                if CHILD_THROW then error('child fault') end
                return true
            end} end
        """)

    def run_ui(self):
        self.lua.execute((ROOT.parent / 'inv.lua').read_text())

    def test_shift_quantity_sides_result_summary_and_refresh(self):
        self.run_ui()
        self.assertEqual(self.lua.execute("""
            return COMMAND:find('craft t:gear:3 7',1,true)~=nil,
                COMMAND:find('--storage-side=0',1,true)~=nil,COMMAND:find('--output-side=2',1,true)~=nil,
                SYNCS[0],SYNCS[2],table.concat(PRINTED,'|'):find('1 unknown',1,true)~=nil,DRAWS>1
        """), (True, True, True, 1, 1, True, True))

    def test_child_fault_still_consumes_outcomes_and_refreshes(self):
        self.lua.execute('CHILD_THROW=true')
        self.run_ui()
        self.assertEqual(self.lua.execute("""
            local id=COMMAND:match('%-%-result%-id=(%S+)')
            return SYNCS[0],SYNCS[2],require('craft_handoff').finish(id)==nil,
                table.concat(PRINTED,'|'):find('child fault',1,true)~=nil
        """), (1, 1, True, True))

    def test_bad_quantity_never_launches_child(self):
        self.lua.execute("READS={'-2'}")
        self.run_ui()
        self.assertEqual(self.lua.execute('return COMMAND==nil,SYNCS[0],SYNCS[2]'), (True, 1, 1))

    def test_typed_query_preserves_shell_composition(self):
        self.lua.execute("SHIFT=false;READS={'t:other 12 -q'}")
        self.run_ui()
        self.assertTrue(self.lua.execute("return COMMAND:find('craft t:other 12 -q',1,true)~=nil"))
