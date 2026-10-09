"""Public MES forwarding boundary and recipe-ownership ruling."""
from test_support import LuaCase


class MesPublicApiTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('mes', 'lib/mes.lua')
        self.module('mes_state', 'lib/mes_state.lua')
        self.module('mes_service', 'lib/mes_service.lua')
        self.lua.execute('''
          CALLS={};CFG={crafters={cpu={robot='address',buffer='configured'}},
            machineTypes={furnace={blocking=false,roles={'input','output'},
              roleSlots={input={1},output={1}}}}}
          package.preload.event=function() return {push=function() end} end
          package.preload.computer=function() return {uptime=function() return 0 end} end
          package.preload.warehouse=function() return {groups=function() return {} end} end
          package.preload.mes_config=function()
            local c={config=function(opts) return opts and opts.config or CFG end}
            for _,name in ipairs({'setType','removeType','setCrafter','removeCrafter'}) do
              c[name]=function(...) CALLS[#CALLS+1]={name=name,args={...}};return name,'second return' end
            end
            c.robots=function(timeout)
              CALLS[#CALLS+1]={name='robots',args={timeout}}
              return {{address='address',busy=false}}
            end
            return c
          end
          package.preload.recipes=function() return {search=function(...)
            CALLS[#CALLS+1]={name='search',args={...}};return {'mod:one'}
          end} end
          M=require('mes')
        ''')

    def test_config_and_read_search_forward_all_arguments_and_returns(self):
        self.lua.execute('''
          for _,name in ipairs({'setType','removeType','setCrafter','removeCrafter'}) do
            local first,second=M[name]('a',{slot=1},3)
            assert(first==name and second=='second return')
            local call=CALLS[#CALLS];assert(call.name==name)
            assert(call.args[1]=='a' and call.args[2].slot==1 and call.args[3]==3)
          end
          local result=M.search('query',7);assert(result[1]=='mod:one')
          local call=CALLS[#CALLS]
          assert(call.name=='search' and call.args[1]=='query' and call.args[2]==7)
          local robots=M.robots(2)
          assert(robots[1].address=='address' and robots[1].busy==false)
          call=CALLS[#CALLS];assert(call.name=='robots' and call.args[1]==2)
        ''')

    def test_config_copies_are_faithful_without_group_or_resource_fields(self):
        self.lua.execute('''
          local c=M.crafters();assert(c.cpu.buffer=='configured' and c.cpu.status==nil)
          c.cpu.robot='changed';assert(M.crafters().cpu.robot=='address')
          local types=M.types();types.furnace.roleSlots.input[1]=99
          assert(M.types().furnace.roleSlots.input[1]==1)
        ''')

    def test_mes_has_no_recipe_management_or_write_facade(self):
        self.lua.execute('''
          for _,name in ipairs({'readSlots','transposerInventories','slotsFromListing',
              'recipeFromSlots','saveRecipe','recipes','removeRecipe','oreFamilies',
              'importRecipes','importProcessingRecipe'}) do
            assert(M[name]==nil,'recipe ownership leaked into MES: '..name)
          end
        ''')
