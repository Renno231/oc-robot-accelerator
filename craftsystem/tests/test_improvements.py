from test_support import LuaCase, ROOT


class HandoffTests(LuaCase):
    def test_consume_and_isolate_outcomes(self):
        self.assertEqual(self.lua.execute("""
            local h=require('craft_handoff');local a,b=h.begin(),h.begin()
            local r={status='unknown',outputs={['t:gear']=2}}
            assert(h.report(a,r));r.outputs['t:gear']=99
            assert(h.report(a,{status='complete'}))
            local x=h.finish(a);local y=h.finish(b)
            return x.total,x.counts.unknown,x.counts.complete,x.results[1].outputs['t:gear'],y.total,
                h.report(a,{status='complete'}),h.finish(nil)==nil
        """), (2, 1, 1, 2, 0, False, True))

    def test_bounded_details_do_not_forget_earlier_unknowns(self):
        self.assertEqual(self.lua.execute("""
            local h=require('craft_handoff');local id=h.begin();h.report(id,{status='unknown'})
            for i=1,40 do h.report(id,{status='complete'}) end
            local r=h.finish(id);h.release(nil)
            return #r.results,r.dropped,r.total,r.counts.unknown,r.counts.complete
        """), (32, 9, 41, 1, 40))


class PreviewEditTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('craft_plans', 'lib/craft_plans.lua')
        self.module('craftingv4_4', 'lib/craftingv4_4.lua')
        self.lua.execute("""
            WRITES,DB_CALLS=0,0
            package.preload.filesystem=function() return {concat=function(a,b) return a..b end} end
            package.preload.serialization=function() return {serialize=function() return 'missing inputs' end} end
            package.preload.recipes=function() return {getAll=function()
                DB_CALLS=DB_CALLS+1;return nil
            end} end
            package.preload.oredict=function() return {get=function() return {'t:raw','t:alt'} end} end
            package.preload.inventory=function() return {} end
            package.preload.craft_tools=function() return {list=function() return {} end} end
            io.open=function() WRITES=WRITES+1;error('unexpected file access') end
            STOCK={['t:raw']=64,['t:alt']=64,['t:rod']=8,['t:gear']=100}
            INV={countItemByName=function(self,n) return STOCK[n] or 0,{} end}
            BP={roots={{node='r',quantity=2}},tools={},nodes={
                r={item='t:gear',useStock=true,recipeOutput=1,recipe={[1]='t:rod'},deps={[1]='m'},ingredient_sources={[1]='t:rod'}},
                m={item='t:rod',useStock=true,recipeOutput=4,recipe={[1]='t:raw'},deps={[1]='l'},ingredient_sources={[1]='ore:raw'}},
                l={item='t:raw',useStock=true}}}
            PLANS=require('craft_plans');PLAN=assert(PLANS.prepare(assert(require('craft_blueprint').calculate(BP,INV))))
        """)

    def test_preview_is_read_only_and_explains_forced_root_and_stock(self):
        self.assertEqual(self.lua.execute("""
            local d=assert(PLANS.preview(PLAN));local lines=assert(require('craft_preview').lines(PLAN))
            return d.requested['t:gear'],d.manufactured['t:gear'],d.withdrawals['t:rod'],
                d.manufactured['t:rod']==nil,d.captured,#lines>5,DB_CALLS,WRITES,PLAN.blueprint.nodes.m.useStock
        """), (2, 2, 2, True, True, True, 0, 0, True))

    def test_stock_edit_recalculates_rounded_batches_without_database_or_save(self):
        self.assertEqual(self.lua.execute("""
            local p,diff=PLANS.edit(PLAN,{kind='stock',node='m',useStock=false},{inventory=INV})
            assert(p,diff);local d=assert(PLANS.preview(p))
            return p.inventory_needed['t:raw'],d.manufactured['t:rod'],d.remaining['t:rod'],
                p.blueprint.nodes.m.useStock,PLAN.blueprint.nodes.m.useStock,#diff>1,WRITES,DB_CALLS
        """), (1, 4, 2, False, True, True, 0, 0))

    def test_recipe_replacement_captures_new_subtree_and_preserves_other_branch(self):
        self.assertEqual(self.lua.execute("""
            PLAN=assert(PLANS.edit(PLAN,{kind='stock',node='m',useStock=false},{inventory=INV}))
            local p,err=PLANS.edit(PLAN,{kind='recipe',node='m',recipe={[1]='t:alt',qty=2}},{inventory=INV})
            assert(p,err)
            local n=p.blueprint.nodes.m
            return n.recipeOutput,n.recipe[1],p.blueprint.nodes[n.deps[1]].item,
                p.blueprint.nodes.r.recipe[1],p.inventory_needed['t:alt'],PLAN.blueprint.nodes.m.recipe[1],WRITES
        """), (2, 't:alt', 't:alt', 't:rod', 1, 't:raw', 0))

    def test_material_alternative_is_validated_and_grafted(self):
        self.assertEqual(self.lua.execute("""
            PLAN=assert(PLANS.edit(PLAN,{kind='stock',node='m',useStock=false},{inventory=INV}))
            local p,err=PLANS.edit(PLAN,{kind='material',node='m',slot=1,item='t:alt'},{inventory=INV})
            assert(p,err)
            local bad,why=PLANS.edit(PLAN,{kind='material',node='m',slot=1,item='t:invalid'},{inventory=INV})
            return p.blueprint.nodes.m.recipe[1],p.inventory_needed['t:alt'],PLAN.blueprint.nodes.m.recipe[1],
                bad==nil,why:find('not an allowed')~=nil,WRITES
        """), ('t:alt', 1, 't:raw', True, True, 0))

    def test_missing_stock_or_legacy_choices_do_not_produce_saveable_candidate(self):
        self.assertEqual(self.lua.execute("""
            STOCK['t:raw']=0
            local p,err=PLANS.edit(PLAN,{kind='stock',node='m',useStock=false},{inventory=INV})
            PLAN.blueprint=nil
            local q,why=PLANS.edit(PLAN,{kind='stock',node='m',useStock=false},{inventory=INV})
            return p==nil,err:find('Missing allowed')~=nil,q==nil,why:find('Legacy')~=nil,WRITES
        """), (True, True, True, True, 0))

    def test_cycle_replacement_is_rejected_without_mutating_original(self):
        self.assertEqual(self.lua.execute("""
            local p,err=PLANS.edit(PLAN,{kind='recipe',node='m',recipe={[1]='t:rod',qty=1}},{inventory=INV})
            return p==nil,err:find('cycle')~=nil,PLAN.blueprint.nodes.m.recipe[1],WRITES
        """), (True, True, 't:raw', 0))

    def test_new_route_tool_family_uses_registry_and_is_budgeted(self):
        self.assertEqual(self.lua.execute("""
            PLAN=assert(PLANS.edit(PLAN,{kind='stock',node='m',useStock=false},{inventory=INV}))
            require('craft_tools').list=function() return {['t:hammer']={durability=10,durabilityPerUse=1}} end
            local count=INV.countItemByName
            INV.countItemByName=function(self,n) if n=='t:hammer:*' then return 1,{1} end;return count(self,n) end
            INV.getItemInSlot=function() return {name='t:hammer',damage=0,size=1} end
            local p,err=PLANS.edit(PLAN,{kind='recipe',node='m',recipe={[1]='t:raw',[2]='t:hammer',qty=4}},{inventory=INV})
            assert(p,err)
            local d=assert(PLANS.preview(p))
            return p.blueprint.nodes.m.tool_slots[2],p.tools['t:hammer'].durability,
                #p.tool_stock['t:hammer'],d.tools['t:hammer'].wear,PLAN.tools==nil,WRITES
        """), ('t:hammer', 10, 1, 1, False, 0))

    def test_recipe_capture_does_not_reask_already_selected_root_recipe(self):
        self.assertEqual(self.lua.execute("""
            local asked=false
            local p,err=PLANS.edit(PLAN,{kind='recipe',node='m',recipe={[1]='t:alt',qty=2}},
                {inventory=INV},function(y) if y[1]=='select_recipe' and y[2]=='t:rod' then asked=true end end)
            assert(p,err);return asked,p.blueprint.nodes.m.recipe[1],WRITES
        """), (False, 't:alt', 0))

    def test_independent_same_item_branch_and_second_requested_output_are_preserved(self):
        self.assertEqual(self.lua.execute("""
            BP.roots[2]={node='other',quantity=1}
            BP.nodes.other={item='t:other',useStock=true,recipeOutput=1,recipe={[1]='t:rod'},deps={[1]='independent'}}
            BP.nodes.independent={item='t:rod',useStock=false,recipeOutput=2,recipe={[1]='t:alt'},deps={[1]='alt'}}
            BP.nodes.alt={item='t:alt',useStock=true}
            PLAN=assert(PLANS.prepare(assert(require('craft_blueprint').calculate(BP,INV))))
            local p,err=PLANS.edit(PLAN,{kind='recipe',node='m',recipe={[1]='t:raw',[2]='t:raw',qty=4}},{inventory=INV})
            assert(p,err)
            return p.blueprint.nodes.independent.recipeOutput,p.blueprint.nodes.independent.recipe[1],
                p.blueprint.nodes.independent.useStock,p.requestOutputs['t:other'],p.requestOutputs['t:gear'],
                PLAN.blueprint.nodes.m.recipe[2]==nil,WRITES
        """), (2, 't:alt', False, 1, 2, True, 0))


class ReceiptTests(LuaCase):
    def test_identity_duplicate_conflict_and_terminal_copy(self):
        self.assertEqual(self.lua.execute("""
            local r=require('craft_receipts').new()
            assert(r.begin('one','sender',{a=1,b={2}}))
            local fresh,x=r.begin('one','sender',{b={2},a=1})
            local bad,why=r.begin('one','sender',{a=2})
            local denied=r.lookup('one','other')
            r.finish('one','COMPLETE','done');local done=r.lookup('one','sender');done.status='FAILED'
            return fresh,x.status,bad==nil,why:find('different')~=nil,denied==nil,r.lookup('one','sender').status
        """), (False, 'RUNNING', True, True, True, 'COMPLETE'))

    def test_retention_and_retry_of_expired_job_never_admits_new_work(self):
        self.assertEqual(self.lua.execute("""
            local r=require('craft_receipts').new({limit=1})
            r.begin('active','s',{});r.begin('old','s',{});r.finish('old','COMPLETE')
            r.begin('new','s',{});r.finish('new','FAILED')
            local admitted,x=r.begin('old','s',{},true)
            return r.lookup('active','s').status,r.lookup('old','s').status,
                r.lookup('new','s').status,admitted,x.status
        """), ('RUNNING', 'NOT_FOUND', 'FAILED', False, 'NOT_FOUND'))

    def test_byte_budget_never_evicts_active_job(self):
        self.assertEqual(self.lua.execute("""
            local r=require('craft_receipts').new({maxBytes=1})
            r.begin('x','s',{large=string.rep('a',100)})
            local active=r.lookup('x','s').status
            local result=r.finish('x','COMPLETE','done')
            return active,result.status,r.lookup('x','s').status
        """), ('RUNNING', 'COMPLETE', 'NOT_FOUND'))
