from test_support import LuaCase


class PlannerTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('inventory', 'lib/inventory.lua')
        self.lua.execute("""
            DB, STOCK, ORES = {}, {}, {}
            package.preload.recipes = function() return {getAll=function(name) return DB[name] end} end
            package.preload.oredict = function() return {
                get=function(name) return ORES[name] end, getByItemName=function() return nil end
            } end
            package.preload.serialization = function() return {} end
            PROFILES={}
            package.preload.craft_tools = function() return {list=function() return PROFILES end} end
            TP = {getAllStacks=function() return {getAll=function() return STOCK end} end}
            function stock(name, size, damage)
                table.insert(STOCK, {name=name,damage=damage or 0,size=size,maxSize=64})
            end
            function finish(target, quantity)
                local p=LIB.calculateCraftingPlan(target,quantity or 1,TP,0)
                for i=1,100 do
                    if not p.yield_data then return p end
                    LIB.resumeCalculation(p)
                end
                error('calculation did not terminate')
            end
        """)
        self.module('craftingv4_4', 'lib/craftingv4_4.lua')
        self.lua.execute("LIB=require('craftingv4_4')")

    def test_explicit_zero_metadata_uses_base_inventory_identity(self):
        self.assertEqual(self.lua.execute("""
            DB['t:target:0']={{'t:raw:0'}};stock('t:raw',1)
            local p=finish('t:target:0');return p.craftable,p.inventory_needed['t:raw'],p.tasks[1].item,p.tasks[1].recipe[1]
        """), (True, 1, 't:target', 't:raw'))

    def test_nonzero_metadata_remains_distinct(self):
        self.assertEqual(self.lua.execute("DB['t:target']={{'t:raw:3'}};stock('t:raw',1);return finish('t:target').craftable"), False)

    def test_malformed_coroutine_is_structured_failure(self):
        self.assertEqual(self.lua.execute("local p={coroutine=42};LIB.resumeCalculation(p);return p.success,p.coroutine==nil,p.error~=nil"), (False, True, True))

    def test_empty_and_invalid_recipes_fail_planning(self):
        for recipe in ['{}', '{[0]=\"t:raw\"}', '{[1]=42}', '{[10]=\"t:raw\"}']:
            with self.subTest(recipe=recipe):
                self.assertEqual(self.lua.execute("DB['t:target']={"+recipe+"};local p=finish('t:target');return p.success,p.craftable,p.error~=nil"), (False, False, True))

    def test_two_level_plan(self):
        self.assertEqual(self.lua.execute("""
            DB['t:target']={{'t:part'}}; DB['t:part']={{'t:raw'}}; stock('t:raw',1)
            local p=finish('t:target'); return p.craftable,#p.tasks,p.inventory_needed['t:raw'],p.tasks[1].item
        """), (True, 2, 1, 't:part'))

    def test_ordinary_multi_output_recipe(self):
        self.assertEqual(self.lua.execute("""
            DB['minecraft:planks']={{'minecraft:log',qty=4}};stock('minecraft:log',2)
            local p=finish('minecraft:planks',5);return p.craftable,p.tasks[1] and p.tasks[1].qty_produced,p.inventory_needed['minecraft:log']
        """), (True, 8, 2))

    def test_compacting_recipe(self):
        self.assertEqual(self.lua.execute("""
            DB['t:block']={{'t:ingot','t:ingot','t:ingot','t:ingot'}};stock('t:ingot',4)
            local p=finish('t:block');return p.craftable,#p.tasks
        """), (True, 1))

    def test_shared_processing_quantities(self):
        self.assertEqual(self.lua.execute("""
            DB['t:target']={{'t:x','t:y'}};DB['t:y']={{'t:x'}}
            DB['t:x']={{'t:raw,5',isProcessing=true,qty=1}};stock('t:raw',10)
            local p=finish('t:target');return p.craftable,p.inventory_needed['t:raw']
        """), (True, 10))

    def test_shared_dependency_batch_rounding(self):
        self.assertEqual(self.lua.execute("""
            DB['t:target']={{'t:x','t:y'}};DB['t:y']={{'t:x'}}
            DB['t:x']={{'t:raw',qty=4}};stock('t:raw',1)
            local p=finish('t:target');return p.craftable,p.inventory_needed['t:raw'],p.tasks[1].qty_produced
        """), (True, 1, 4))

    def test_cycle_fails_before_unbounded_demand(self):
        self.assertEqual(self.lua.execute("""
            DB['t:a']={{'t:b'}};DB['t:b']={{'t:a'}}
            local p=LIB.calculateCraftingPlan('t:a',1,TP,0)
            debug.sethook(p.coroutine,function() error('instruction budget exceeded') end,'',100000)
            for i=1,30 do if not p.yield_data then break end;LIB.resumeCalculation(p) end
            return p.success,p.craftable,p.yield_data==nil,p.error and p.error:find('cycle')~=nil
        """), (False, False, True, True))

    def test_exception_is_terminal_on_original_plan(self):
        self.assertEqual(self.lua.execute("""
            DB['t:target']={{'t:raw'}}
            local p=LIB.calculateCraftingPlan('t:target',1,TP,0)
            LIB.resumeCalculation(p,42)
            if p.yield_data then LIB.resumeCalculation(p) end
            return p.success,p.craftable,p.coroutine==nil,p.yield_data==nil,p.error~=nil
        """), (False, False, True, True, True))

    def test_cancellation_is_terminal(self):
        self.assertEqual(self.lua.execute("""
            DB['t:target']={{'t:raw'}}
            local p=LIB.calculateCraftingPlan('t:target',1,TP,0)
            LIB.cancelCalculation(p)
            return p.success,p.craftable,p.cancelled,p.yield_data==nil,p.coroutine==nil
        """), (False, False, True, True, True))

    def test_missing_inventory_is_explicit_failure(self):
        self.assertEqual(self.lua.execute("""
            local p=LIB.calculateCraftingPlan('t:target',1,{getAllStacks=function() return nil end},0)
            return p.success,p.error~=nil
        """), (False, True))

    def test_wildcard_binds_available_metadata(self):
        self.assertEqual(self.lua.execute("""
            DB['t:target']={{'t:wood:*'}};stock('t:wood',2,3)
            local p=finish('t:target');return p.craftable,p.tasks[1].recipe[1],p.inventory_needed['t:wood:3']
        """), (True, 't:wood:3', 1))

    def test_registered_tool_manufacture_is_an_ordinary_dependency(self):
        self.assertEqual(self.lua.execute("""
            PROFILES['t:hammer']={durability=3,durabilityPerUse=1}
            DB['t:target']={{'t:hammer'}};DB['t:hammer']={{'t:steel'}};stock('t:steel',2)
            local p=finish('t:target',5)
            return p.craftable,p.tasks[1].item,p.tasks[1].qty_produced,
                p.inventory_needed['t:steel'],p.tasks[2].tool_slots[1],p.blueprint~=nil
        """), (True, 't:hammer', 2, 2, 't:hammer', True))

    def test_stocked_intermediate_routes_are_captured_for_later_refresh(self):
        self.assertEqual(self.lua.execute("""
            DB['t:target']={{'t:part'}};DB['t:part']={{'t:raw'}};stock('t:part',1)
            local p=finish('t:target');return #p.tasks,p.blueprint.nodes['t:part'].recipe[1]
        """), (1, 't:raw'))

    def test_explicit_terminal_recipe_choice_cuts_a_database_cycle(self):
        self.assertEqual(self.lua.execute("""
            DB['t:target']={{'t:raw'}};DB['t:raw']={{'t:target'}};stock('t:raw',1)
            local p=LIB.calculateCraftingPlan('t:target',1,TP,0)
            for i=1,50 do
                if not p.yield_data then break end
                local v=p.yield_data
                if v[1]=='select_recipe' and v[2]=='t:raw' then LIB.resumeCalculation(p,false)
                else LIB.resumeCalculation(p) end
            end
            return p.craftable,p.blueprint.nodes['t:raw'].recipe==nil
        """), (True, True))
