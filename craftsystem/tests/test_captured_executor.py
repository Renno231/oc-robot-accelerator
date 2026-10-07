from test_executor import ExecutorFixture


class CapturedExecutorTests(ExecutorFixture):
    def setUp(self):
        super().setUp()
        self.module('inventory', 'lib/inventory.lua')
        self.module('craft_plans', 'lib/craft_plans.lua')
        self.module('craft_store', 'lib/craft_store.lua')
        self.module('craft_kits', 'lib/craft_kits.lua')
        self.lua.execute('''
            package.preload.filesystem=function() return {} end
            SUBMISSIONS=0
            package.preload.craft_client=function() return {runDetailed=function(p)
                SUBMISSIONS=SUBMISSIONS+1;LAST_PAYLOAD=p
                local ok,e=EX.executePlan(p)
                return {status=ok and 'complete' or 'failed',success=ok,message=e,mayHaveExecuted=true}
            end} end
            BP=require('craft_blueprint');ID=require('item_identity');RULES=require('craft_tool_rules')
            GAME,PROFILES,USED={}, {}, {}
            function blueprint(target,qty)
                local b={roots={{node=target,quantity=qty or 1}},nodes={},tools={}}
                local todo={target}
                while #todo>0 do
                    local name=table.remove(todo)
                    if not b.nodes[name] then
                        local n={item=name,useStock=true};b.nodes[name]=n
                        local r=GAME[name]
                        if r then
                            n.recipeOutput=r.qty or 1;n.recipe={};n.deps={};n.tool_slots={}
                            for slot,item in pairs(r.inputs) do
                                n.recipe[slot]=item;n.deps[slot]=item;todo[#todo+1]=item
                                if PROFILES[item] then n.tool_slots[slot]=item;b.tools[item]=PROFILES[item] end
                            end
                        end
                    end
                end
                return b
            end
            function prepare(b)
                local inv=assert(require('inventory').new({getAllStacks=IC.getAllStacks},3))
                local p,e=BP.calculate(b,inv);assert(p,e);assert(p.craftable,'not craftable')
                local ok,why=EX.validatePlan(p);assert(ok,why)
                return p
            end
            function toolStock(damage)
                local s=stack('t:hammer',1,1);s.damage=damage or 0;return s
            end
            local grid={[1]=1,[2]=2,[3]=3,[4]=5,[5]=6,[6]=7,[7]=9,[8]=10,[9]=11}
            require('component').crafting.craft=function(limit)
                local selected,name
                for product,r in pairs(GAME) do
                    local matches=true
                    for i=1,9 do
                        local s=STACKS[grid[i]];local input=r.inputs[i]
                        if input then
                            if not s or s.size<1 or (PROFILES[input] and RULES.family(s)~=input) or
                                (not PROFILES[input] and ID.stackName(s)~=input) then matches=false end
                        elseif s then matches=false end
                    end
                    if matches then selected=r;name=product;break end
                end
                CRAFT_CALLS=CRAFT_CALLS+1
                if not selected then return false end
                local q=selected.qty or 1;local ops=math.floor(limit/q)
                for i,input in pairs(selected.inputs) do
                    local s=STACKS[grid[i]]
                    ops=math.min(ops,PROFILES[input] and 1 or s.size)
                end
                local out=STACKS[SEL];local max=PROFILES[name] and 1 or 64
                ops=math.min(ops,math.floor((out and out.maxSize-out.size or max)/q))
                if ops<1 then return false end
                USED[#USED+1]=name
                for i,input in pairs(selected.inputs) do
                    local s=STACKS[grid[i]];local profile=PROFILES[input]
                    if profile then
                        s.damage=s.damage+ops*(ACTUAL_WEAR or profile.durabilityPerUse)
                        if EAT_TOOL or s.damage>=profile.durability and not RETURN_BROKEN then STACKS[grid[i]]=nil end
                    else
                        s.size=s.size-ops;if s.size==0 then STACKS[grid[i]]=nil end
                    end
                end
                if not out then out=stack(name,0,max);STACKS[SEL]=out end
                out.size=out.size+ops*q
                return true
            end
        ''')

    def test_captured_plain_plan_uses_provenance_and_returns_output(self):
        self.assertEqual(self.lua.execute('''
            GAME['t:target']={inputs={'t:raw'}};CHEST={stack('t:raw',3)}
            local ok,e=EX.executePlan(prepare(blueprint('t:target',3)))
            return ok,chestCount('t:target'),RV.isBufferEmpty()
        '''), (True, 3, True))

    def test_worn_tool_and_new_tools_execute_without_exact_damage_matching(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=3,durabilityPerUse=1}
            GAME['t:target']={inputs={'t:hammer'}};GAME['t:hammer']={inputs={'t:steel'}}
            CHEST={toolStock(2),stack('t:steel',2)}
            local p=prepare(blueprint('t:target',5));local ok,e=EX.executePlan(p)
            assert(ok,e);return ok,chestCount('t:target'),chestCount('t:hammer')
        '''), (True, 5, 2))

    def test_two_simultaneous_slots_and_forward_wear_schedule(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=3,durabilityPerUse=1}
            GAME['t:part']={inputs={'t:hammer'}}
            GAME['t:target']={inputs={'t:hammer','t:hammer','t:part'}}
            GAME['t:hammer']={inputs={'t:steel'}}
            CHEST={toolStock(),toolStock(),stack('t:steel',1)}
            local p=prepare(blueprint('t:target',2));local ok,e=EX.executePlan(p)
            assert(ok,e);return ok,chestCount('t:target')
        '''), (True, 2))

    def test_unexpected_tool_consumption_is_failure_not_complete(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=10,durabilityPerUse=1}
            GAME['t:target']={inputs={'t:hammer'}};CHEST={toolStock()};EAT_TOOL=true
            local ok,e=EX.executePlan(prepare(blueprint('t:target')))
            return ok,e:find('unexpectedly consumed')~=nil
        '''), (False, True))

    def test_fresh_tool_groups_keep_a_feasible_later_simultaneous_budget(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=3,durabilityPerUse=1}
            GAME['t:hammer']={inputs={'t:steel'}}
            GAME['t:p1']={inputs={'t:hammer','t:hammer'}}
            GAME['t:p2']={inputs={'t:hammer','t:p1'}}
            GAME['t:p3']={inputs={'t:hammer','t:p2'}}
            GAME['t:target']={inputs={'t:hammer','t:hammer','t:p3'}}
            CHEST={stack('t:steel',2)}
            local p=prepare(blueprint('t:target'));local ok,e=EX.executePlan(p);assert(ok,e)
            return ok,p.inventory_needed['t:steel'],chestCount('t:target')
        '''), (True, 2, 1))

    def test_excessive_wear_and_zero_wear_mismatch_fail(self):
        for wear in (0, 1):
            with self.subTest(wear=wear):
                self.setUp()
                self.lua.globals().WEAR = wear
                self.assertEqual(self.lua.execute('''
                    PROFILES['t:hammer']={durability=10,durabilityPerUse=WEAR}
                    GAME['t:target']={inputs={'t:hammer'}};CHEST={toolStock()};ACTUAL_WEAR=2
                    local ok,e=EX.executePlan(prepare(blueprint('t:target')))
                    return ok,e:find('wear')~=nil
                '''), (False, True))

    def test_zero_wear_retained_tool_is_reused(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=1,durabilityPerUse=0}
            GAME['t:target']={inputs={'t:hammer'}};CHEST={toolStock()}
            local ok,e=EX.executePlan(prepare(blueprint('t:target',5)))
            assert(ok,e);return ok,chestCount('t:target'),chestCount('t:hammer')
        '''), (True, 5, 1))

    def test_all_merged_outputs_are_verified(self):
        self.assertEqual(self.lua.execute('''
            GAME['t:part']={inputs={'t:raw'},qty=4}
            GAME['t:a']={inputs={'t:part'}};GAME['t:b']={inputs={[2]='t:part'}};CHEST={stack('t:raw',1)}
            local b=assert(BP.merge({blueprint('t:a'),blueprint('t:b')}))
            local ok,e=EX.executePlan(prepare(b));assert(ok,e)
            return ok,chestCount('t:a'),chestCount('t:b')
        '''), (True, 1, 1))

    def test_requested_intermediate_is_protected_from_later_consumers(self):
        self.assertEqual(self.lua.execute('''
            GAME['t:part']={inputs={'t:raw'}};GAME['t:target']={inputs={'t:part'}};CHEST={stack('t:raw',2)}
            local b=assert(BP.merge({blueprint('t:part'),blueprint('t:target')}))
            local ok,e=EX.executePlan(prepare(b));assert(ok,e)
            return ok,chestCount('t:part'),chestCount('t:target')
        '''), (True, 1, 1))

    def test_tool_requested_as_an_output_remains_fresh(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=3,durabilityPerUse=1}
            GAME['t:hammer']={inputs={'t:steel'}};GAME['t:target']={inputs={'t:hammer'}}
            CHEST={stack('t:steel',2)}
            local b=assert(BP.merge({blueprint('t:hammer'),blueprint('t:target',2)}))
            local ok,e=EX.executePlan(prepare(b));assert(ok,e)
            local fresh=0;for _,s in ipairs(CHEST) do if s.name=='t:hammer' and s.damage==0 then fresh=fresh+s.size end end
            return ok,chestCount('t:target'),fresh
        '''), (True, 2, 1))

    def test_invalid_tool_metadata_is_rejected_before_inventory_moves(self):
        self.assertEqual(self.lua.execute('''
            GAME['t:target']={inputs={'t:raw'}};CHEST={stack('t:raw',1)}
            local p=prepare(blueprint('t:target'));p.tasks[1].tool_slots={[1]='t:raw'}
            STACKS[16]=stack('t:held',1);local ok=EX.executePlan(p)
            return ok,STACKS[16].name,CRAFT_CALLS
        '''), (False, 't:held', 0))

    def test_separate_refreshed_kit_preserves_every_component_in_storage(self):
        self.assertEqual(self.lua.execute('''
            GAME['t:part']={inputs={'t:raw'}};GAME['t:target']={inputs={'t:part'}}
            CHEST={stack('t:raw',2)}
            local kit={accounting='refresh',entries={
                {binding='pinned',plan=prepare(blueprint('t:part'))},
                {binding='pinned',plan=prepare(blueprint('t:target'))}}}
            local r=require('craft_kits').run(kit,{transposer={getAllStacks=IC.getAllStacks},storageSide=3})
            assert(r.success,r.message)
            return r.status,SUBMISSIONS,chestCount('t:part'),chestCount('t:target'),
                LAST_PAYLOAD.external_reserved['t:part'],r.outputs['t:part'],r.outputs['t:target']
        '''), ('complete', 2, 1, 1, 1, 1, 1))

    def test_separate_fixed_kit_cannot_spend_a_previous_component_as_missing_stock(self):
        self.assertEqual(self.lua.execute('''
            GAME['t:part']={inputs={'t:raw'}};GAME['t:target']={inputs={'t:part'}}
            CHEST={stack('t:raw',1),stack('t:part',1)}
            local kit={entries={{binding='pinned',plan=prepare(blueprint('t:part'))},
                {binding='pinned',plan=prepare(blueprint('t:target'))}}}
            table.remove(CHEST,2)
            local r=require('craft_kits').run(kit)
            return r.status,r.partial,r.completedEntries,chestCount('t:part'),chestCount('t:target'),CRAFT_CALLS
        '''), ('failed', True, 1, 1, 0, 1))

    def test_external_fresh_tool_is_reserved_but_worn_tools_remain_eligible(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=3,durabilityPerUse=1}
            GAME['t:target']={inputs={'t:hammer'}};CHEST={toolStock(),toolStock(1)}
            local p=prepare(blueprint('t:target'));p.external_reserved={['t:hammer:0']=1}
            local ok,e=EX.executePlan(p);assert(ok,e)
            local fresh,worn=0,0
            for _,s in ipairs(CHEST) do
                if s.name=='t:hammer' and s.damage==0 then fresh=fresh+s.size end
                if s.name=='t:hammer' and s.damage==2 then worn=worn+s.size end
            end
            return ok,fresh,worn,chestCount('t:target')
        '''), (True, 1, 1, 1))

    def test_saved_merge_executes_captured_profiles_and_all_roots(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=3,durabilityPerUse=1}
            GAME['t:a']={inputs={'t:hammer','t:raw'}}
            GAME['t:b']={inputs={[2]='t:hammer',[3]='t:raw'}}
            CHEST={toolStock(),toolStock(),stack('t:raw',2)}
            local kit={executionMode='merged',entries={
                {binding='pinned',plan=prepare(blueprint('t:a'))},
                {binding='pinned',plan=prepare(blueprint('t:b'))}}}
            local r=require('craft_kits').run(kit);assert(r.success,r.message)
            return r.status,SUBMISSIONS,chestCount('t:a'),chestCount('t:b')
        '''), ('complete', 1, 1, 1))

    def test_bad_fixed_wear_budget_fails_before_submission(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=10,durabilityPerUse=1}
            GAME['t:target']={inputs={'t:hammer'}};CHEST={toolStock()}
            local p=prepare(blueprint('t:target',5));p.tool_stock['t:hammer'][1]=1
            local r=require('craft_kits').run({executionMode='merged',entries={{binding='pinned',plan=p}}})
            return r.status,r.message:find('wear budget')~=nil,SUBMISSIONS,CRAFT_CALLS
        '''), ('failed', True, 0, 0))

    def test_outputs_dropped_outside_storage_never_complete(self):
        for captured in (False, True):
            with self.subTest(captured=captured):
                self.setUp()
                self.lua.globals().CAPTURED = captured
                self.assertEqual(self.lua.execute('''
                    GAME['t:target']={inputs={'t:raw'}};CHEST={stack('t:raw',1)}
                    local drop=ROBOT.drop
                    ROBOT.drop=function(...)
                        local ok=drop(...)
                        if CRAFT_CALLS>0 then CHEST={} end
                        return ok
                    end
                    local p=CAPTURED and prepare(blueprint('t:target')) or plan(1)
                    local ok,e=EX.executePlan(p)
                    return ok,e:find('missing from storage')~=nil,ROBOT.count(13)
                '''), (False, True, 0))

    def test_invalid_reservations_are_rejected_before_robot_movement(self):
        self.assertEqual(self.lua.execute('''
            STACKS[16]=stack('t:held',1);local p=plan(1);p.external_reserved={['t:part']=-1}
            local ok,e=EX.executePlan(p)
            return ok,e:find('reservation')~=nil,STACKS[16].name,CRAFT_CALLS
        '''), (False, True, 't:held', 0))

    def test_malformed_observed_damage_cannot_pass_final_tool_verification(self):
        self.assertEqual(self.lua.execute('''
            PROFILES['t:hammer']={durability=10,durabilityPerUse=1}
            GAME['t:target']={inputs={'t:hammer'}};CHEST={toolStock()}
            local craft=require('component').crafting.craft
            require('component').crafting.craft=function(...)
                local ok=craft(...);if STACKS[1] then STACKS[1].damage=0/0 end;return ok
            end
            local ok,e=EX.executePlan(prepare(blueprint('t:target')))
            return ok,e:find('wear')~=nil
        '''), (False, True))
