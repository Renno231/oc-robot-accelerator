from test_robot import RobotFixture


class ExecutorFixture(RobotFixture):
    def setUp(self):
        super().setUp()
        self.lua.execute("""
            CHEST, CRAFT_CALLS, CRAFT_BATCHES = {}, 0, {}
            CRAFT_INPUTS, CRAFT_PRODUCT, CRAFT_OUTPUT, OUTPUT_MAX = {[1]='t:raw'}, 't:target', 1, 64
            IC.getAllStacks=function() return {getAll=function()
                local result={};for i,s in ipairs(CHEST) do result[i]=copy(s) end;return result
            end} end
            IC.suckFromSlot=function(_,from,n)
                local s=CHEST[from];if not s then return false end
                local t=STACKS[SEL]
                local moved=math.min(n,s.size,t and t.maxSize-t.size or s.maxSize,PULL_LIMIT or n)
                if moved<=0 then return false end
                if not t then t=copy(s);t.size=0;STACKS[SEL]=t end
                t.size=t.size+moved;s.size=s.size-moved
                if s.size==0 then table.remove(CHEST,from) end
                return true
            end
            ROBOT.drop=function(_,n)
                if BLOCKED or (BLOCK_AFTER_CRAFT and CRAFT_CALLS>0) then return false end
                local s=STACKS[SEL];if not s then return false end
                local moved=math.min(n,s.size,DROP_LIMIT or n)
                local deposited=copy(s);deposited.size=moved;table.insert(CHEST,deposited)
                s.size=s.size-moved;if s.size==0 then STACKS[SEL]=nil end
                return moved>0
            end
            local grid={[1]=1,[2]=2,[3]=3,[4]=5,[5]=6,[6]=7,[7]=9,[8]=10,[9]=11}
            require('component').crafting.craft=function(limit)
                CRAFT_CALLS=CRAFT_CALLS+1
                local ops=math.floor(limit/CRAFT_OUTPUT)
                for i,name in pairs(CRAFT_INPUTS) do
                    local s=STACKS[grid[i]];if not s or s.name~=name then return false end
                    ops=math.min(ops,s.size)
                end
                if CRAFT_PARTIAL then ops=math.min(ops,1) end
                if CRAFT_WRONG then CRAFT_PRODUCT='t:wrong' end
                local out=STACKS[SEL]
                ops=math.min(ops,math.floor((out and out.maxSize-out.size or OUTPUT_MAX)/CRAFT_OUTPUT))
                if ops<1 then return false end
                table.insert(CRAFT_BATCHES,ops)
                for i in pairs(CRAFT_INPUTS) do
                    local s=STACKS[grid[i]]
                    if not RETAINED_TOOL or grid[i]~=RETAINED_TOOL then
                        s.size=s.size-ops;if s.size==0 then STACKS[grid[i]]=nil end
                    end
                end
                if not out then out=stack(CRAFT_PRODUCT,0,OUTPUT_MAX);STACKS[SEL]=out end
                out.size=out.size+ops*CRAFT_OUTPUT
                return true
            end
            function plan(qty,output)
                return {requestItem='t:target',requestQuantity=qty,inventory_needed={['t:raw']=qty},tasks={
                    {item='t:target',qty_produced=qty*(output or 1),recipeOutput=output or 1,recipe={'t:raw'}}}}
            end
            function chestCount(name) local n=0;for _,s in ipairs(CHEST) do if s.name==name then n=n+s.size end end;return n end
        """)
        self.module('craft_executor', 'lib/craft_executor.lua')
        self.lua.execute("EX=require('craft_executor')")

class ExecutorTests(ExecutorFixture):
    def test_explicit_zero_metadata_matches_source_and_output(self):
        self.assertEqual(self.lua.execute("""
            CHEST={stack('t:raw',1)};local p=plan(1)
            p.inventory_needed={['t:raw:0']=1};p.tasks[1].recipe={'t:raw:0'}
            p.tasks[1].item='t:target:0';p.requestItem='t:target:0'
            local ok=EX.executePlan(p);return ok,chestCount('t:target')
        """), (True, 1))

    def test_success_verifies_and_returns_output(self):
        self.assertEqual(self.lua.execute("CHEST={stack('t:raw',3)};local ok=EX.executePlan(plan(3));return ok,chestCount('t:target'),RV.isBufferEmpty(),CRAFT_CALLS"), (True, 3, True, 2))

    def test_live_source_slots_after_drawer_reindex(self):
        self.assertEqual(self.lua.execute("CHEST={stack('t:raw',1),stack('t:raw',2)};PULL_LIMIT=1;local ok=EX.executePlan(plan(3));return ok,chestCount('t:target')"), (True, 3))

    def test_missing_prerequisite_is_failure(self):
        self.assertEqual(self.lua.execute("local ok,err=EX.executePlan(plan(1));return ok,err:find('Missing prerequisite')~=nil,CRAFT_CALLS"), (False, True, 0))

    def test_machine_plan_rejected_before_moving_inventory(self):
        self.assertEqual(self.lua.execute("STACKS[16]=stack('t:held',1);RV.sync();local p=plan(1);p.tasks[1].isProcessing=true;local ok=EX.executePlan(p);return ok,STACKS[16].name,CRAFT_CALLS"), (False, 't:held', 0))

    def test_wrong_output_is_failure(self):
        self.assertEqual(self.lua.execute("CHEST={stack('t:raw',1)};CRAFT_WRONG=true;local ok,err=EX.executePlan(plan(1));return ok,err:find('verification')~=nil"), (False, True))

    def test_partial_craft_is_failure(self):
        self.assertEqual(self.lua.execute("CHEST={stack('t:raw',3)};CRAFT_PARTIAL=true;local ok,err=EX.executePlan(plan(3));return ok,err:find('verification')~=nil"), (False, True))

    def test_blocked_return_never_completes(self):
        self.assertEqual(self.lua.execute("CHEST={stack('t:raw',1)};BLOCK_AFTER_CRAFT=true;local ok,err=EX.executePlan(plan(1));return ok,err:find('return items')~=nil,RV.countItemByName('t:target')"), (False, True, 1))

    def test_nonstackable_output_uses_one_operation_batches(self):
        self.assertEqual(self.lua.execute("CHEST={stack('t:raw',3)};OUTPUT_MAX=1;local ok=EX.executePlan(plan(3));return ok,chestCount('t:target'),CRAFT_CALLS"), (True, 3, 3))

    def test_retained_tool_is_not_erased(self):
        self.assertEqual(self.lua.execute("CHEST={stack('t:raw',2)};RETAINED_TOOL=1;local ok=EX.executePlan(plan(2));return ok,chestCount('t:target'),chestCount('t:raw')"), (True, 2, 2))

    def test_cancelled_job_does_not_craft(self):
        self.assertEqual(self.lua.execute("CHEST={stack('t:raw',1)};local ok,err=EX.executePlan(plan(1),{shouldContinue=function() return false end});return ok,CRAFT_CALLS,#CHEST"), (False, 0, 1))

    def test_partial_dump_retries_until_empty(self):
        self.assertEqual(self.lua.execute("STACKS[16]=stack('t:held',10);RV.sync();DROP_LIMIT=3;local ok=EX.dumpInventory();return ok,chestCount('t:held'),ROBOT.count(16)"), (True, 10, 0))

    def test_insufficient_capacity_fails_with_explicit_reason(self):
        self.assertEqual(self.lua.execute("""
            local p=plan(1);p.inventory_needed={}
            for i=1,5 do local item='t:raw'..i;p.inventory_needed[item]=1;table.insert(CHEST,stack(item,1)) end
            local ok,err=EX.executePlan(p);return ok,err:find('capacity')~=nil,CRAFT_CALLS
        """), (False, True, 0))

    def test_existing_target_cannot_substitute_for_missing_planned_production(self):
        self.assertEqual(self.lua.execute('''
            STACKS[16]=stack('t:held',1);local p=plan(1)
            p.requestQuantity=2;p.inventory_needed['t:target']=2
            local ok,e=EX.executePlan(p)
            return ok,e:find('requested quantity')~=nil,STACKS[16].name,CRAFT_CALLS
        '''), (False, True, 't:held', 0))
