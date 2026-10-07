from test_support import LuaCase


class ClientUIFixture(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('craft_plans', 'lib/craft_plans.lua')
        self.module('craft_commands', 'lib/craft_commands.lua')
        self.module('craft_management_ui', 'lib/craft_management_ui.lua')
        self.module('craft_store', 'lib/craft_store.lua')
        self.module('craft_kits', 'lib/craft_kits.lua')
        self.module('stockkeeper', 'lib/stockkeeper.lua')
        self.lua.execute("""
            ARGS,OPTS,KEYS={}, {}, {};LISTENED,IGNORED=false,false;VIEWPORTS={};NET_CALLS=0
            local keycodes={q=16,up=200,down=208,left=203,right=205}
            package.preload.keyboard=function() return {keys=keycodes} end
            GPU={getResolution=function() return 160,50 end,fill=function() end,set=function() end,
                 setBackground=function() end,setForeground=function() end}
            package.preload.component=function() return {gpu=GPU,transposer={}} end
            package.preload.sides=function() return {down=0,south=3} end
            SHELL_CALLS={}
            package.preload.shell=function() return {parse=function(...)
                if select('#',...)==0 then return ARGS,OPTS end
                local args,opts={},{}
                for _,v in ipairs({...}) do
                    if type(v)=='string' and v:sub(1,2)=='--' then
                        local k,val=v:match('^%-%-(.-)=(.*)$');opts[k or v:sub(3)]=val or true
                    else args[#args+1]=v end
                end
                return args,opts
            end,execute=function(binary,env,...)
                SHELL_CALLS[#SHELL_CALLS+1]={binary=binary,args={...},env=env}
                local kind=({craftplan='plans',craftkit='kits',crafttools='tools',stockkeeper='stockkeeper'})[binary]
                local code,msg=require('craft_commands').main(kind,...)
                LAST_PROCESS_CODE=code;return code==0,msg
            end} end
            package.preload.term=function() return {clear=function() end} end
            package.preload.tty=function() return {
                getViewport=function() return 80,25,0,0 end,
                setViewport=function(...) table.insert(VIEWPORTS,{...}) end
            } end
            package.preload.event=function() return {
                listen=function() LISTENED=true end,ignore=function() IGNORED=true end,
                pull=function() local key=table.remove(KEYS,1);assert(key,'test exhausted keys');return 'key_down','keyboard',0,key end
            } end
            package.preload.qmenu=function() return {create=function()
                local menu={options={}}
                function menu:addOption(name,x,y,text)
                    local o={name=name}
                    function o:bind() return self end
                    function o:onActivate(cb) self.activate=cb;return self end
                    function o:text() return self end
                    self.options[name]=o;self.selected=self.selected or name;return o
                end
                function menu:draw() end
                function menu:setSelected(o) self.selected=type(o)=='table' and o.name or o end
                function menu:handleEvent(key)
                    local o=self.options[key] or self.options[self.selected]
                    if o and o.activate then o.activate() end
                end
                function menu:removeOption(name) self.options[name]=nil end
                function menu:read()
                    if READ_VALUES then return table.remove(READ_VALUES,1) end
                    return READ_TEXT
                end
                return menu
            end} end
            package.preload.inventory=function() return {new=function(_,side)
                LAST_STORAGE_SIDE=side
                return {countItemByName=function() return 0 end}
            end} end
            package.preload.msyn=function() return {convertItemName=function(n) return n end} end
            package.preload.serialization=function() return {
                serialize=function() return '{}' end,unserialize=function() return SAVED end
            } end
            package.preload.filesystem=function() return {
                exists=function() return true end,concat=function(a,b) return a..b end,
                makeDirectory=function() return true end,
                list=function() local sent=false;return function() if not sent then sent=true;return 'saved.plan' end end end
            } end
            package.preload.craftingv4_4=function() return {
                calculateCraftingPlan=function() return PLAN end,
                resumeCalculation=function() error('unexpected calculation resume') end,
                cancelCalculation=function(p) p.cancelled=true;p.success=false;p.error='cancelled';p.yield_data=nil end
            } end
            package.preload.craft_client=function() return {runDetailed=function()
                NET_CALLS=NET_CALLS+1;if NETWORK_THROW then error('network exception') end
                return {status='complete',success=true,message='done'}
            end} end
            io.read=function() return 'y' end
            OPEN_CALLS=0
            io.open=function(path) OPEN_CALLS=OPEN_CALLS+1;FILE_PATH=path;return {
                read=function() return 'saved' end,write=function() WRITTEN=true;return true end,
                close=function() FILE_CLOSED=true end} end
            PLAN={success=true,craftable=true,requestItem='t:target',requestQuantity=1,
                tasks={{item='t:target',recipeOutput=1,qty_produced=1,recipe={'t:raw'}}},inventory_needed={['t:raw']=1}}
        """)

class ClientUITests(ClientUIFixture):
    def test_parent_craft_forwards_ticket_into_purpose_binary(self):
        self.lua.execute("""
            TICKET=require('craft_handoff').begin();OPTS={['result-id']=TICKET};SAVED=PLAN
            KEYS={'plans','plan1','run','saved','yes','ok',16,16,16}
        """)
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute("local r=require('craft_handoff').finish(TICKET);return r.total,r.counts.complete,NET_CALLS,#KEYS"), (1, 1, 1, 0))

    def test_quick_craft_export_error_preserves_verified_completion_handoff(self):
        self.lua.execute("""
            TICKET=require('craft_handoff').begin();ARGS={'t:target',1};OPTS={['result-id']=TICKET}
            require('component').transposer.transferItem=function() error('export fault') end
            local preload=package.preload.inventory
            package.preload.inventory=function()
                local lib=preload();local new=lib.new
                lib.new=function(...) local i=new(...);i.sync=function() end;i.nextSlotContaining=function() return 1 end;return i end
                return lib
            end
        """)
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute("local r=require('craft_handoff').finish(TICKET);return r.total,r.results[1].status,r.results[1].success,r.results[1].exported,r.results[1].exportError:find('export fault')~=nil"),
                         (1, 'complete', True, False, True))

    def test_recipe_menu_q_cancels_instead_of_reopening(self):
        self.lua.execute("ARGS={'t:target',1};OPTS={q=true};KEYS={16};PLAN.yield_data={'select_recipe','t:target',{{'t:raw'},{'t:other'}}}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return PLAN.cancelled,NET_CALLS,IGNORED'), (True, 0, True))

    def test_runtime_error_restores_viewport_and_event_listener(self):
        self.lua.execute("ARGS={'t:target',1};NETWORK_THROW=true")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return table.unpack(VIEWPORTS[#VIEWPORTS])'), (80, 25, 0, 0))
        self.assertTrue(self.lua.execute('return IGNORED'))

    def test_saved_plan_menu_loads_and_runs_confirmation_flow(self):
        self.lua.execute("SAVED=PLAN;KEYS={'plans','plan1','run','saved','no',16,16,16}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return OPEN_CALLS,NET_CALLS,IGNORED,#KEYS'), (0, 0, True, 0))

    def test_saved_plan_menu_lists_without_opening_plans(self):
        self.lua.execute("KEYS={'plans',16,16}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return OPEN_CALLS,NET_CALLS,IGNORED,#KEYS'), (0, 0, True, 0))

    def test_saved_plan_executes_without_resave_prompt(self):
        self.lua.execute("SAVED=PLAN;KEYS={'plans','plan1','run','saved','yes','ok',16,16,16}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return OPEN_CALLS,NET_CALLS,IGNORED,#KEYS'), (1, 1, True, 0))

    def many_plans(self):
        self.lua.execute("""
            GPU.getResolution=function() return 80,25 end;LIST_CALLS=0
            require('filesystem').list=function()
                LIST_CALLS=LIST_CALLS+1;local i=0
                return function() i=i+1;if i<=50 then return string.format('plan%02d.plan',i) end end
            end
            SAVED=PLAN
        """)

    def test_plan_beyond_first_page_is_selectable_and_executable(self):
        self.many_plans()
        self.lua.execute("KEYS={'plans','nextPage','plan23','run','saved','yes','ok',16,16,16}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return FILE_PATH,OPEN_CALLS,NET_CALLS,LIST_CALLS,#KEYS,IGNORED'), ('/usr/craftplans/plan23.plan', 1, 1, 1, 0, True))

    def test_previous_page_returns_to_first_page_without_relisting_or_extra_opens(self):
        self.many_plans()
        self.lua.execute("KEYS={'plans','nextPage','nextPage','previousPage','previousPage','plan1','run','saved','no',16,16,16}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return OPEN_CALLS,NET_CALLS,LIST_CALLS,#KEYS'), (0, 0, 1, 0))

    def test_page_navigation_alone_never_opens_plans(self):
        self.many_plans()
        self.lua.execute("KEYS={'plans','nextPage','nextPage',16,16}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return OPEN_CALLS,NET_CALLS,LIST_CALLS,#KEYS'), (0, 0, 1, 0))

    def test_new_plan_can_save_only_or_save_then_execute(self):
        for execute in (False, True):
            with self.subTest(execute=execute):
                self.setUp()
                self.lua.execute("ARGS={'t:target',1};OPTS={q=true};READ_TEXT='Daily gears';KEYS=" + ("{'yes','yes','no'}" if execute else "{'yes','no'}"))
                self.script('bin/craft.lua')
                self.assertEqual(self.lua.execute('return WRITTEN,FILE_CLOSED,FILE_PATH,NET_CALLS,#KEYS'), (True, True, '/usr/craftplans/Daily gears.plan', int(execute), 0))

    def test_storage_side_option_is_used_for_snapshot(self):
        self.lua.execute("ARGS={'t:target',1};OPTS={['storage-side']='2'}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return LAST_STORAGE_SIDE'), 2)

    def test_management_menus_use_independent_shell_binaries_with_settings(self):
        self.lua.execute("KEYS={'plans',16,'kits',16,16};OPTS={['storage-side']='2',['job-timeout']='0'}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute("return #SHELL_CALLS,SHELL_CALLS[1].binary,SHELL_CALLS[2].binary,SHELL_CALLS[1].args[1],SHELL_CALLS[1].args[2],LAST_PROCESS_CODE,#KEYS"),
                         (2, 'craftplan', 'craftkit', '--interactive', '--storage-side=2', 0, 0))

    def test_stockkeeper_menu_uses_standalone_shell_binary(self):
        self.lua.execute("KEYS={'stockkeeper',16,16};OPTS={['storage-side']='2'}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute("return #SHELL_CALLS,SHELL_CALLS[1].binary,SHELL_CALLS[1].args[2],LAST_PROCESS_CODE,#KEYS,OPEN_CALLS"),
                         (1, 'stockkeeper', '--storage-side=2', 0, 0, 0))

    def test_child_ui_error_restores_parent_viewport_and_listeners(self):
        self.lua.execute("KEYS={'plans',16,16};require('filesystem').list=function() error('listing failed') end")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return table.unpack(VIEWPORTS[#VIEWPORTS])'), (80, 25, 0, 0))
        self.assertTrue(self.lua.execute('return IGNORED'))

    def test_parent_listener_cleanup_runs_even_when_viewport_restore_throws(self):
        self.lua.execute('''
            local set=require('tty').setViewport;local calls=0
            require('tty').setViewport=function(...)
                calls=calls+1;if calls>=2 then error('viewport broken') end;return set(...)
            end
            KEYS={16}
        ''')
        self.script('bin/craft.lua')
        self.assertTrue(self.lua.execute('return IGNORED'))


class ManagementUITests(ClientUIFixture):
    def editable_plan(self):
        self.lua.execute('''
            INV={countItemByName=function(self,item) return item=='t:raw' and 64 or item=='t:rod' and 4 or 0,{} end}
            local b={roots={{node='r',quantity=2}},tools={},nodes={
                r={item='t:target',useStock=true,recipeOutput=1,recipe={[1]='t:rod'},deps={[1]='m'}},
                m={item='t:rod',useStock=true,recipeOutput=4,recipe={[1]='t:raw'},deps={[1]='l'}},
                l={item='t:raw',useStock=true}}}
            PLAN=assert(require('craft_plans').prepare(assert(require('craft_blueprint').calculate(b,INV))))
            SAVED=PLAN
        ''')

    def test_preview_opens_only_selected_plan_and_never_executes(self):
        self.lua.execute("SAVED=PLAN;KEYS={'plan1','preview',16,16,16}")
        self.assertEqual(self.lua.execute("local c=require('craft_management_ui').show('plans',{});return c,OPEN_CALLS,NET_CALLS,#KEYS,IGNORED"),
                         (0, 1, 0, 0, True))

    def test_preview_pages_long_explanations(self):
        self.editable_plan()
        self.lua.execute("""
            GPU.getResolution=function() return 80,25 end
            for i=1,30 do PLAN.blueprint.nodes['extra'..i]={item='t:extra'..i,useStock=true} end
            KEYS={'plan1','preview','nextPage','nextPage','previousPage',16,16,16}
        """)
        self.assertEqual(self.lua.execute("local c=require('craft_management_ui').show('plans',{});return c,OPEN_CALLS,NET_CALLS,#KEYS"), (0, 1, 0, 0))

    def test_stock_edit_review_cancel_never_writes_or_executes(self):
        self.editable_plan()
        self.lua.execute("KEYS={'plan1','edit','node2','stock','make',16,'review',16,'no',16,16,16}")
        self.assertEqual(self.lua.execute("local c=require('craft_management_ui').show('plans',{inventory=INV});return c,WRITTEN==nil,NET_CALLS,SAVED.blueprint.nodes.m.useStock,#KEYS"),
                         (0, True, 0, True, 0))

    def test_stock_edit_confirm_saves_recalculated_candidate(self):
        self.editable_plan()
        self.lua.execute("""
            require('serialization').serialize=function(p) SAVED_CANDIDATE=p;return '{}' end
            KEYS={'plan1','edit','node2','stock','make',16,'review',16,'yes','ok',16,16}
        """)
        self.assertEqual(self.lua.execute("local c=require('craft_management_ui').show('plans',{inventory=INV});return c,WRITTEN,SAVED_CANDIDATE.blueprint.nodes.m.useStock,SAVED_CANDIDATE.inventory_needed['t:raw'],SAVED.blueprint.nodes.m.useStock,NET_CALLS,#KEYS"),
                         (0, True, False, 1, True, 0, 0))

    def test_purpose_menu_reports_actual_result_to_parent_ticket(self):
        self.lua.execute("SAVED=PLAN;KEYS={'plan1','run','saved','yes','ok',16,16};TICKET=require('craft_handoff').begin()")
        self.assertEqual(self.lua.execute("local c=require('craft_management_ui').show('plans',{resultId=TICKET});local r=require('craft_handoff').finish(TICKET);return c,r.total,r.counts.complete,NET_CALLS,#KEYS"),
                         (0, 1, 1, 1, 0))

    def test_receipt_query_ui_does_not_report_another_crafting_execution(self):
        self.lua.execute("""
            require('craft_client').query=function(address,id) QUERY_ADDRESS=address;QUERY_ID=id;return {status='complete',success=true,message='done'} end
            KEYS={'plan1','receipt','ok',16,16};READ_VALUES={'robot','oldjob'}
            TICKET=require('craft_handoff').begin()
        """)
        self.assertEqual(self.lua.execute("local c=require('craft_management_ui').show('plans',{resultId=TICKET});local r=require('craft_handoff').finish(TICKET);return c,QUERY_ADDRESS,QUERY_ID,r.total,NET_CALLS,#KEYS"),
                         (0, 'robot', 'oldjob', 0, 0, 0))

    def test_child_listener_cleanup_runs_even_when_viewport_restore_throws(self):
        self.lua.execute('''
            local set=require('tty').setViewport;local calls=0
            require('tty').setViewport=function(...)
                calls=calls+1;if calls>=2 then error('viewport broken') end;return set(...)
            end
            KEYS={16}
        ''')
        self.assertEqual(self.lua.execute("local c,e=require('craft_management_ui').show('plans',{});return c,e:find('Viewport restore failed')~=nil,IGNORED"), (2, True, True))

    def test_interrupt_during_final_profile_input_does_not_save(self):
        self.lua.execute('''
            SET_CALLS=0
            package.preload.craft_tools=function() return {list=function() return {} end,
                get=function() end,set=function() SET_CALLS=SET_CALLS+1;return true end} end
            require('event').listen=function(_,fn) INTERRUPT=fn end
            local create=require('qmenu').create;local reads=0
            require('qmenu').create=function()
                local menu=create()
                menu.read=function()
                    reads=reads+1
                    if reads==3 then INTERRUPT() end
                    return ({'t:hammer','10','1'})[reads]
                end
                return menu
            end
            KEYS={'register'}
        ''')
        self.assertEqual(self.lua.execute("local c=require('craft_management_ui').show('tools',{});return c,SET_CALLS,IGNORED"), (0, 0, True))

    def test_multibyte_label_clipping_preserves_valid_utf8(self):
        self.lua.execute("""
            require('filesystem').list=function()
                local done=false;return function()
                    if not done then done=true;return string.rep('a',75)..'€ name.plan' end
                end
            end
            local add=require('qmenu').create
            require('qmenu').create=function()
                local menu=add();local option=menu.addOption
                menu.addOption=function(self,id,x,y,text)
                    assert(utf8.len(text),'invalid UTF-8 label');return option(self,id,x,y,text)
                end
                return menu
            end
            KEYS={16}
        """)
        self.assertEqual(self.lua.execute("return require('craft_management_ui').show('plans',{})"), 0)

    def test_manual_tool_profile_entry_is_available_from_tools_binary_ui(self):
        self.lua.execute("""
            PROFILES={};package.preload.craft_tools=function() return {
                list=function() return PROFILES end,get=function(n) return PROFILES[n] end,
                set=function(n,d,w)
                    assert(require('craft_tool_rules').validate({durability=d,durabilityPerUse=w}))
                    PROFILES[n]={durability=d,durabilityPerUse=w};return true
                end} end
            READ_VALUES={'t:hammer','10','2'};KEYS={'tools','register','ok',16,16}
        """)
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute("return PROFILES['t:hammer'].durability,PROFILES['t:hammer'].durabilityPerUse,SHELL_CALLS[1].binary,LAST_PROCESS_CODE,#KEYS"),
                         (10, 2, 'crafttools', 0, 0))

    def test_legacy_refresh_error_does_not_submit_or_modify_saved_plan(self):
        self.lua.execute("SAVED=PLAN;KEYS={'plans','plan1','run','refresh','yes','ok',16,16,16}")
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return NET_CALLS,WRITTEN==nil,LAST_PROCESS_CODE,#KEYS'), (0, True, 0, 0))

    def test_plan_named_new_is_not_confused_with_create_action(self):
        self.lua.execute("""
            require('filesystem').list=function()
                local done=false;return function() if not done then done=true;return 'new.plan' end end
            end
            KEYS={'plans','plan1',16,16,16};READ_TEXT='should not be used'
        """)
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return OPEN_CALLS,WRITTEN==nil,LAST_PROCESS_CODE,#KEYS'), (0, True, 0, 0))

    def test_kit_run_override_and_visible_bindings_leave_defaults_unchanged(self):
        self.lua.execute("""
            SAVED_KIT={executionMode='merged',accounting='saved',entries={{binding='live',planName='saved'}}}
            require('serialization').unserialize=function(data) if data=='kit' then return SAVED_KIT end;return PLAN end
            io.open=function(path)
                OPEN_CALLS=OPEN_CALLS+1;return {read=function() return path:sub(-4)=='.kit' and 'kit' or 'plan' end,
                    close=function() FILE_CLOSED=true end}
            end
            require('filesystem').list=function(dir)
                local done=false;return function() if not done then done=true;return dir:find('craftkits') and 'Computer.kit' or 'saved.plan' end end
            end
            KEYS={'kits','kit1','run','separate','saved','yes','ok',16,16,16}
        """)
        self.script('bin/craft.lua')
        self.assertEqual(self.lua.execute('return NET_CALLS,SAVED_KIT.executionMode,SAVED_KIT.entries[1].binding,LAST_PROCESS_CODE,#KEYS'), (1, 'merged', 'live', 0, 0))

    def test_direct_ui_exception_restores_viewport_and_listener(self):
        self.lua.execute("require('qmenu').create=function() error('UI exception') end")
        self.assertEqual(self.lua.execute("local c,m=require('craft_management_ui').show('plans',{});return c,m:find('UI exception')~=nil,IGNORED"), (2, True, True))
        self.assertEqual(self.lua.execute('return table.unpack(VIEWPORTS[#VIEWPORTS])'), (80, 25, 0, 0))
