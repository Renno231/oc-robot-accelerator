"""Concurrent requests: shared robots and machines, stock claims, fairness, isolation."""
from test_support import LuaCase
import test_mes_graph as graph


class MesConcurrentTests(LuaCase):
    def setUp(self):
        fixture = graph.MesGraphTests()
        fixture.setUp()
        self.lua = fixture.lua
        self.lua.execute('''
          function submit(tasks,opts)
            opts=opts or {};opts.config=CFG
            return assert(M.run({tasks=tasks,requestItem=tasks[#tasks].item,requestQuantity=tasks[#tasks].qty_produced},opts))
          end
          -- Robot jobs per robot never overlap in time.
          function exclusive()
            for i,a in ipairs(CLIENTS) do for j,b in ipairs(CLIENTS) do
              if i<j and a.robot==b.robot and b.start<(a.finish or math.huge) and a.start<(b.finish or math.huge) then return false end
            end end
            return true
          end
        ''')

    def test_two_runs_share_one_robot_and_one_furnace(self):
        self.assertEqual(self.lua.execute('''
          put('stock','t:ore',4)
          MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
          local function plan(out) return {task('t:metal',{'t:ore'},nil,nil,'furnace',2),task(out,{'t:metal','t:metal'})} end
          local a=submit(plan('t:plateA'),{crafter='cpu1'});local b=submit(plan('t:plateB'),{crafter='cpu1'})
          local ra,rb=M.wait(a),M.wait(b)
          assert(ra.status=='complete',ra.reason);assert(rb.status=='complete',rb.reason)
          local runs={};for _,s in ipairs({ra.stages[1],rb.stages[1]}) do for _,l in ipairs(s.loadLedger) do runs[l.run]=true;assert(l.state=='done') end end
          local robots=0;for _,c in ipairs(CLIENTS) do assert(c.robot=='robot1');robots=robots+1 end
          local r=M.resources{config=CFG}
          return robots,exclusive(),runs[a] and runs[b],held('stock','t:plateA'),held('stock','t:plateB'),r.crafters.cpu1.state,r.machines.kiln.state
        '''), (2, True, True, 1, 1, 'idle', 'idle'))

    def test_claims_withhold_stock_from_later_plans_until_the_run_ends(self):
        self.assertEqual(self.lua.execute('''
          put('stock','t:iron',15);DB['t:gear']={{'t:iron'}}
          local first=assert(M.plan('t:gear',10,{config=CFG}));assert(first.craftable)
          local id=assert(M.run(first,{config=CFG}))
          local claimed=require('mes_service').claims()['t:iron']
          local second=assert(M.plan('t:gear',10,{config=CFG}))
          local m=second.missing[1]
          local r=M.wait(id);assert(r.status=='complete',r.reason)
          local after=assert(M.plan('t:gear',5,{config=CFG}))
          return claimed,second.craftable,m.item,m.need-m.have,next(require('mes_service').claims())==nil,after.craftable
        '''), (10, False, 't:iron', 5, True, True))

    def test_three_runs_take_turns_on_one_robot(self):
        self.assertEqual(self.lua.execute('''
          put('stock','t:raw',6)
          local ids={}
          for n=1,3 do ids[n]=submit({task('t:a'..n,{'t:raw'}),task('t:b'..n,{'t:raw'})},{crafter='cpu1'}) end
          for n=1,3 do local r=M.wait(ids[n]);assert(r.status=='complete',r.reason) end
          local order={};for _,c in ipairs(CLIENTS) do order[#order+1]=c.plan.tasks[1].item:sub(-1) end
          return table.concat(order),exclusive()
        '''), ('123123', True))

    def test_one_run_fails_and_the_other_completes_with_holdings_released(self):
        self.assertEqual(self.lua.execute('''
          put('stock','t:ore',4)
          MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
          OUTCOMES.robot1='failed'
          local function plan(out) return {task('t:metal',{'t:ore'},nil,nil,'furnace',2),task(out,{'t:metal','t:metal'})} end
          local a=submit(plan('t:plateA'),{crafter='cpu1'});local b=submit(plan('t:plateB'),{crafter='cpu2'})
          local ra,rb=M.wait(a),M.wait(b)
          local r=M.resources{config=CFG}
          return ra.status,rb.status,held('stock','t:plateB'),r.crafters.cpu1.state,r.crafters.cpu2.state,r.machines.kiln.state,next(require('mes_service').claims())==nil
        '''), ('failed', 'complete', 1, 'idle', 'idle', 'idle', True))

    def test_request_blocked_behind_another_runs_loads_waits_for_collection_not_a_time_limit(self):
        self.assertEqual(self.lua.execute('''
          put('stock','t:ore',2);put('stock','t:sand',2);CONSUME_DELAY=90;OUTPUT_DELAY=95;CFG.machineTypes.furnace.seconds=48
          MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}},{inputs={input={['t:sand']=1}},outputs={['t:glass']=1}}}
          local a=submit({task('t:metal',{'t:ore'},nil,nil,'furnace',2)})
          local b=submit({task('t:glass',{'t:sand'},nil,nil,'furnace',2)})
          local ra,rb=M.wait(a),M.wait(b)
          return ra.status,rb.status,rb.reason,held('stock','t:glass'),rb.finished-rb.started>60
        '''), ('complete', 'complete', None, 2, True))

    def test_nonblocking_furnace_defers_a_refused_recipe_until_collection(self):
        self.assertEqual(self.lua.execute('''
          CAPACITY.in1=1;CONSUME_DELAY=30;OUTPUT_DELAY=32
          CFG.machineTypes.furnace.seconds=16
          put('stock','t:clay',2);put('stock','t:log',2)
          MACHINE_RECIPES.kiln={
            {inputs={input={['t:clay']=1}},outputs={['t:brick']=1}},
            {inputs={input={['t:log']=1}},outputs={['t:charcoal']=1}}}
          local a=submit({task('t:brick',{'t:clay'},nil,nil,'furnace',2)})
          local b=submit({task('t:charcoal',{'t:log'},nil,nil,'furnace',2)})
          local ra,rb=M.wait(a),M.wait(b)
          return ra.status,rb.status,held('stock','t:brick'),held('stock','t:charcoal')
        '''), ('complete', 'complete', 2, 2))

    def test_exhausted_machine_recovery_fails_queued_work_without_reloading(self):
        self.assertEqual(self.lua.execute('''
          CFG.machineTypes.furnace.blocking=true;CFG.machineTypes.furnace.seconds=0
          CONSUME_DELAY=0;OUTPUT_DELAY=200
          put('stock','t:ore',1);put('stock','t:sand',1)
          MACHINE_RECIPES.kiln={
            {inputs={input={['t:ore']=1}},outputs={['t:metal']=1}},
            {inputs={input={['t:sand']=1}},outputs={['t:glass']=1}}}
          local a=submit({task('t:metal',{'t:ore'},nil,nil,'furnace')})
          local b=submit({task('t:glass',{'t:sand'},nil,nil,'furnace')})
          local ra,rb=M.wait(a),M.wait(b)
          local fetches=0;for _,m in ipairs(MOVES) do if m.kind=='fetch' then fetches=fetches+1 end end
          return ra.status,rb.status,fetches,#SCANS,held('stock','t:sand'),M.resources{config=CFG}.machines.kiln.state
        '''), ('failed', 'failed', 1, 1, 1, 'unknown'))
