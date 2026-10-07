from test_support import LuaCase


class BlueprintTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('craft_tool_budget', 'lib/craft_tool_budget.lua')
        self.module('craft_blueprint', 'lib/craft_blueprint.lua')
        self.module('inventory', 'lib/inventory.lua')
        self.lua.execute('''
            B=require('craft_blueprint'); STOCK={}
            function stock(name,qty,damage)
                STOCK[#STOCK+1]={name=name,size=qty or 1,damage=damage or 0,maxSize=64}
            end
            function inv() return assert(require('inventory').new({getAllStacks=function()
                return {getAll=function() return STOCK end} end},0)) end
            function base(qty)
                return {roots={{node='target',quantity=qty or 1}},tools={},nodes={
                    target={item='t:target',useStock=true,recipeOutput=1,
                        recipe={'t:part'},deps={'part'}},
                    part={item='t:part',useStock=true,recipeOutput=4,
                        recipe={'t:raw'},deps={'raw'}},
                    raw={item='t:raw',useStock=true},
                }}
            end
            function toolPlan(qty,slots,life,wear)
                local b=base(qty); b.nodes.target.recipe={};b.nodes.target.deps={};b.nodes.target.tool_slots={}
                for s=1,slots or 1 do
                    b.nodes.target.recipe[s]='t:hammer';b.nodes.target.deps[s]='hammer'
                    b.nodes.target.tool_slots[s]='t:hammer'
                end
                b.nodes.hammer={item='t:hammer',useStock=true,recipeOutput=1,
                    recipe={'t:steel'},deps={'steel'}}
                b.nodes.steel={item='t:steel',useStock=true}
                b.tools['t:hammer']={durability=life or 3,durabilityPerUse=wear or 1}
                return b
            end
        ''')

    def test_refresh_is_pure_and_copies_choices(self):
        self.assertEqual(self.lua.execute('''
            stock('t:raw',1);local b=base(2);b.extra=function() end
            local p=assert(B.calculate(b,inv()));p.blueprint.nodes.part.recipe[1]='t:changed'
            return p.craftable,#p.tasks,p.inventory_needed['t:raw'],b.nodes.part.recipe[1],
                p.blueprint.extra==nil,package.loaded.recipes==nil
        '''), (True, 2, 1, 't:raw', True, True))

    def test_currently_stocked_intermediate_has_a_captured_fallback(self):
        self.assertEqual(self.lua.execute('''
            stock('t:part',1);local b=base();local p=assert(B.calculate(b,inv()))
            STOCK={};stock('t:raw',1);local refreshed=assert(B.calculate(p.blueprint,inv()))
            return #p.tasks,p.inventory_needed['t:part'],#refreshed.tasks,refreshed.inventory_needed['t:raw']
        '''), (1, 1, 2, 1))

    def test_forced_manufacture_and_explicit_leaf_boundary(self):
        self.assertEqual(self.lua.execute('''
            stock('t:part',10);local b=base();b.nodes.part.useStock=false
            local p=assert(B.calculate(b,inv()));b.nodes.part={item='t:part',useStock=true};STOCK={}
            local terminal=assert(B.calculate(b,inv()))
            return p.craftable,p.external_needed['t:raw'],terminal.external_needed['t:part']
        '''), (False, 1, 1))

    def test_targets_are_new_production_and_batch_rounding_is_shared(self):
        self.assertEqual(self.lua.execute('''
            stock('t:target',10);stock('t:raw',1);local b=base(2)
            b.roots[2]={node='target',quantity=1};local p=assert(B.calculate(b,inv()))
            return p.requestQuantity,p.tasks[1].qty_produced,p.tasks[2].qty_produced,p.inventory_needed['t:target']==nil
        '''), (3, 4, 3, True))

    def test_missing_tools_expand_normal_manufacturing_materials(self):
        self.assertEqual(self.lua.execute('''
            local b=toolPlan(7,1,3);local p=assert(B.calculate(b,inv()))
            stock('t:steel',3);local supplied=assert(B.calculate(b,inv()))
            return p.external_needed['t:steel'],p.external_needed['t:hammer']==nil,
                supplied.craftable,supplied.tasks[1].item,supplied.tasks[1].qty_produced
        '''), (3, True, True, 't:hammer', 3))

    def test_worn_units_and_fresh_replacements_share_a_budget(self):
        self.assertEqual(self.lua.execute('''
            stock('t:hammer',1,2);stock('t:steel',2)
            local p=assert(B.calculate(toolPlan(5,1,3),inv()))
            return p.craftable,p.tool_stock['t:hammer'][1],p.tool_stock_nodes['t:hammer'][1],
                p.tasks[1].qty_produced,p.inventory_needed['t:hammer']==nil,p.inventory_needed['t:steel']
        '''), (True, 1, 'hammer', 2, True, 2))

    def test_wear_charged_per_operation_not_output(self):
        self.assertEqual(self.lua.execute('''
            stock('t:hammer',1);local b=toolPlan(8,1,3);b.nodes.target.recipeOutput=4
            local p=assert(B.calculate(b,inv()));return p.craftable,#p.tasks,p.tool_stock['t:hammer'][1]
        '''), (True, 1, 2))

    def test_wear_schedule_uses_forward_dependency_order(self):
        self.assertEqual(self.lua.execute('''
            stock('t:hammer',2);stock('t:steel',1)
            local b=toolPlan(2,2,3)
            b.nodes.target.recipe[3]='t:part';b.nodes.target.deps[3]='part'
            b.nodes.part={item='t:part',useStock=true,recipeOutput=1,
                recipe={'t:hammer'},deps={'hammer'},tool_slots={[1]='t:hammer'}}
            local p=assert(B.calculate(b,inv()))
            return p.craftable,p.inventory_needed['t:steel'],p.tasks[1].item,p.tasks[1].qty_produced
        '''), (True, 1, 't:hammer', 1))

    def test_simultaneous_slots_require_distinct_tools(self):
        self.assertEqual(self.lua.execute('''
            stock('t:hammer',1);local p=assert(B.calculate(toolPlan(1,2,100),inv()))
            return p.craftable,p.external_needed['t:steel'],#p.tool_stock['t:hammer']
        '''), (False, 1, 1))

    def test_zero_wear_and_large_operation_counts_are_bounded(self):
        self.assertEqual(self.lua.execute('''
            stock('t:steel',2);local b=toolPlan(1000000000,2,1,0)
            debug.sethook(function() error('instruction budget exceeded') end,'',500000)
            local p,e=B.calculate(b,inv());debug.sethook()
            assert(p,e);return p.craftable,p.tasks[1].qty_produced,p.tasks[2].qty_produced
        '''), (True, 2, 1000000000))

    def test_cycles_invalid_refs_and_sparse_roots_are_rejected(self):
        for change in ("b.nodes.raw.recipe={'t:target'};b.nodes.raw.recipeOutput=1;b.nodes.raw.deps={'target'}",
                       "b.nodes.target.deps[1]='missing'", "b.roots[3]=b.roots[1]",
                       "b.nodes.part.recipeOutput=0", "b.nodes.part.recipe[1]='ore:raw'"):
            with self.subTest(change=change):
                self.assertEqual(self.lua.execute('local b=base();'+change+';local p,e=B.calculate(b,inv());return p==nil,type(e)'), (True, 'string'))

    def test_merge_shares_equivalent_descendant_choices(self):
        self.assertEqual(self.lua.execute('''
            stock('t:raw',1);local a=base();local b=base()
            b.nodes.target.item='t:other';local combined=assert(B.merge({a,b}));local p=assert(B.calculate(combined,inv()))
            return p.craftable,p.inventory_needed['t:raw'],#p.tasks,p.requestOutputs['t:target'],p.requestOutputs['t:other']
        '''), (True, 1, 3, 1, 1))

    def test_merge_keeps_different_descendant_material_routes_separate(self):
        self.assertEqual(self.lua.execute('''
            stock('t:raw',1);stock('t:other_raw',1);local a=base();local b=base()
            b.nodes.target.item='t:other';b.nodes.part.recipe={'t:other_raw'};b.nodes.raw.item='t:other_raw'
            local p=assert(B.calculate(assert(B.merge({a,b})),inv()))
            return p.craftable,#p.tasks,p.inventory_needed['t:raw'],p.inventory_needed['t:other_raw'],
                p.tasks[1].node~=p.tasks[2].node
        '''), (True, 4, 1, 1, True))

    def test_conflicting_profile_rules_are_not_silently_overwritten(self):
        self.assertEqual(self.lua.execute('''
            local a=toolPlan(1);local b=toolPlan(1);b.tools['t:hammer'].durability=9
            local merged,e=B.merge({a,b});return merged==nil,e:find('Conflicting')~=nil
        '''), (True, True))

    def test_replacement_tool_manufacture_can_require_another_tool(self):
        self.assertEqual(self.lua.execute('''
            local b=toolPlan(5,1,3)
            b.nodes.hammer.recipe[2]='t:file';b.nodes.hammer.deps[2]='file';b.nodes.hammer.tool_slots={[2]='t:file'}
            b.nodes.file={item='t:file',useStock=true,recipeOutput=1,recipe={'t:wood'},deps={'wood'}}
            b.nodes.wood={item='t:wood',useStock=true}
            b.tools['t:file']={durability=1,durabilityPerUse=1}
            stock('t:wood',2);stock('t:steel',2)
            local p=assert(B.calculate(b,inv()))
            return p.craftable,p.inventory_needed['t:wood'],p.inventory_needed['t:steel'],
                p.tasks[1].item,p.tasks[2].item,p.tasks[3].item
        '''), (True, 2, 2, 't:file', 't:hammer', 't:target'))

    def test_mixed_width_wear_budgets_are_feasible_with_payload_grants(self):
        self.assertTrue(self.lua.execute('''
            math.randomseed(173)
            for case=1,200 do
                STOCK={};local life=math.random(1,12)
                for i=1,math.random(0,5) do stock('t:hammer',1,math.random(0,life-1)) end
                local pool=require('craft_tool_budget').new(inv(),{['t:hammer']={durability=life,durabilityPerUse=1}})
                local phases,fresh={},0
                for phase=1,8 do
                    local slots,ops=math.random(1,4),math.random(1,8)
                    phases[#phases+1]={slots,ops};fresh=fresh+pool.charge('t:hammer',slots,ops,'hammer',true)
                end
                local _,stock=pool.snapshot();local grants={}
                for _,n in ipairs(stock['t:hammer'] or {}) do grants[#grants+1]={left=n,stock=true} end
                for i=1,fresh do grants[#grants+1]={left=life,stock=false} end
                for _,phase in ipairs(phases) do
                    for operation=1,phase[2] do
                        local picked={};local count=0
                        for i,g in ipairs(grants) do
                            if count<phase[1] and g.stock and g.left>0 then picked[i]=true;count=count+1 end
                        end
                        while count<phase[1] do
                            local best
                            for i,g in ipairs(grants) do
                                if not picked[i] and not g.stock and g.left>0 and (not best or g.left>grants[best].left) then best=i end
                            end
                            assert(best,'infeasible wear budget in case '..case)
                            picked[best]=true;count=count+1
                        end
                        for i in pairs(picked) do grants[i].left=grants[i].left-1 end
                    end
                end
            end
            return true
        '''))

    def test_large_unneeded_tool_stock_is_not_expanded_per_unit(self):
        self.assertEqual(self.lua.execute('''
            stock('t:hammer',1000000000)
            debug.sethook(function() error('tool stock expanded eagerly') end,'',100000)
            local p,e=B.calculate(toolPlan(1,1,10),inv())
            debug.sethook();assert(p,e)
            return p.craftable,#p.tool_stock['t:hammer'],p.tool_stock['t:hammer'][1]
        '''), (True, 1, 1))

    def test_different_branches_cannot_double_reserve_stocked_tools(self):
        self.assertEqual(self.lua.execute('''
            stock('t:hammer',1);local a=toolPlan(1);local b=toolPlan(1)
            b.nodes.hammer.useStock=false;b.nodes.target.item='t:other'
            local p=assert(B.calculate(assert(B.merge({a,b})),inv()))
            return p.external_needed['t:steel'],#p.tool_stock['t:hammer']
        '''), (1, 1))
