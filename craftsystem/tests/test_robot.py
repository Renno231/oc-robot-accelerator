from test_support import LuaCase


class RobotFixture(LuaCase):
    def setUp(self):
        super().setUp()
        self.lua.execute("""
            STACKS, SEL, DETAIL_CALLS, COUNT_CALLS = {}, 1, 0, 0
            function copy(s) if not s then return nil end;local t={};for k,v in pairs(s) do t[k]=v end;return t end
            function stack(name,n,max) return {name=name,damage=0,size=n,maxSize=max or 64,label=name} end
            ROBOT={select=function(i) if i then SEL=i end;return SEL end,inventorySize=function() return 85 end,
                count=function(i) COUNT_CALLS=COUNT_CALLS+1;return STACKS[i or SEL] and STACKS[i or SEL].size or 0 end,
                drop=function(_,n)
                    if BLOCKED then return false end
                    local s=STACKS[SEL];if not s then return false end
                    local moved=math.min(n,s.size,DROP_LIMIT or n);s.size=s.size-moved
                    if s.size==0 then STACKS[SEL]=nil end;return moved>0
                end,
                transferTo=function(to,n)
                    local s,t=STACKS[SEL],STACKS[to];if not s then return false end
                    if t and t.name~=s.name then STACKS[SEL],STACKS[to]=t,s;return true end
                    local moved=math.min(n,s.size,(t and t.maxSize-t.size or s.maxSize))
                    if moved==0 then return false end
                    if not t then t=copy(s);t.size=0;STACKS[to]=t end
                    t.size=t.size+moved;s.size=s.size-moved;if s.size==0 then STACKS[SEL]=nil end
                    return true
                end}
            IC={getStackInInternalSlot=function(i) DETAIL_CALLS=DETAIL_CALLS+1;return copy(STACKS[i]) end}
            package.preload.component=function() return {robot=ROBOT,inventory_controller=IC,crafting={}} end
            package.preload.sides=function() return {front=3} end
            package.preload.serialization=function() return {} end
            package.preload.event=function() return {} end
            package.preload.computer=function() return {} end
        """)
        self.module('robinv', 'lib/robinv.lua')
        self.lua.execute("RV=require('robinv')")


class RobotTests(RobotFixture):
    def test_count_existing_stacks(self):
        self.assertEqual(self.lua.execute("STACKS[13]=stack('t:wood',4);STACKS[16]=stack('t:wood',2);RV.sync();return RV.countItemByName('t:wood')"), 6)

    def test_freeing_high_buffer_slot_keeps_lookup_dense(self):
        self.assertEqual(self.lua.execute("""
            for i=13,85 do STACKS[i]=stack('t:wood',1) end;RV.sync();RV.transferToExternal(3,85)
            return RV.nextEmptyBufferSlot(),RV.countItemByName('t:wood')
        """), (85, 72))

    def test_full_stack_move_to_grid(self):
        self.assertEqual(self.lua.execute("""
            STACKS[13]=stack('t:wood',3);RV.sync();RV.transferInternal(13,1,3)
            return RV.getItemNameInSlot(1),RV.getItemNameInSlot(13),RV.countItemByName('t:wood')
        """), ('t:wood', 'air', 3))

    def test_partial_move_and_merge(self):
        self.assertEqual(self.lua.execute("""
            STACKS[13]=stack('t:wood',10);STACKS[1]=stack('t:wood',60);RV.sync();RV.transferInternal(13,1,8)
            return RV.getStack(13).size,RV.getStack(1).size,RV.countItemByName('t:wood')
        """), (6, 64, 70))

    def test_swapped_stack_identity(self):
        self.assertEqual(self.lua.execute("""
            STACKS[13]=stack('t:wood',2);STACKS[1]=stack('t:stone',4);RV.sync();RV.transferInternal(13,1,64)
            return RV.getItemNameInSlot(1),RV.getItemNameInSlot(13),RV.nextSlotContaining('t:wood')
        """), ('t:wood', 't:stone', 1))

    def test_grid_resync_preserves_tools_and_returned_containers(self):
        self.assertEqual(self.lua.execute("""
            STACKS[1]=stack('t:tool',1,1);STACKS[2]=stack('t:water_bucket',1,1);RV.sync()
            STACKS[2]=stack('t:bucket',1,16);RV.resyncCraftingGrid()
            return RV.getItemNameInSlot(1),RV.getItemNameInSlot(2),RV.countItemByName('t:water_bucket')
        """), ('t:tool', 't:bucket', 0))

    def test_empty_buffer(self):
        self.assertTrue(self.lua.execute('return RV.isBufferEmpty()'))

    def test_partial_drop_keeps_remaining_count(self):
        self.assertEqual(self.lua.execute("STACKS[16]=stack('t:wood',10);RV.sync();DROP_LIMIT=3;RV.transferToExternal(3,16,10);return RV.countItemByName('t:wood')"), 7)

    def test_blocked_drop_keeps_cache(self):
        self.assertEqual(self.lua.execute("STACKS[16]=stack('t:wood',10);RV.sync();BLOCKED=true;local ok=RV.transferToExternal(3,16);return ok,RV.countItemByName('t:wood')"), (False, 10))

    def test_empty_slots_use_count_without_stack_detail_calls(self):
        self.assertEqual(self.lua.execute('DETAIL_CALLS=0;COUNT_CALLS=0;RV.sync();return DETAIL_CALLS,COUNT_CALLS'), (0, 85))

    def test_stack_read_cannot_mutate_cache(self):
        self.assertEqual(self.lua.execute("STACKS[13]=stack('t:wood',4);RV.sync();local s=RV.getStack(13);s.size=999;return RV.countItemByName('t:wood')"), 4)
