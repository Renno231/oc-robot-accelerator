"""Public recipes-library management with real CBOR/LZSS and atomic disk mocks."""
import unittest
from lupa.lua53 import LuaRuntime
from test_database import MOCKS, ROOT


class RecipeManagementTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'usr/lib').as_posix()
        self.lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        self.lua.execute(MOCKS)
        self.lua.execute('''
            failRename={};failFlush={};RENAMES={};FLUSH_CALLS=0
            local fs=require('filesystem')
            fs.rename=function(old,new)
                if failRename[new] then return nil,'injected rename failure' end
                assert(files[old]~=nil);files[new]=files[old];files[old]=nil
                RENAMES[#RENAMES+1]={old,new};return true
            end
            fs.remove=function(path) files[path]=nil;return true end
            local baseOpen=io.open
            io.open=function(path,mode)
                local durable=path:match('^(.*)%.tmp%.%d+$')
                if durable then
                    failOpen[path]=failOpen[durable]
                    failWrite[path]=failWrite[durable]
                    failClose[path]=failClose[durable]
                end
                local f,err=baseOpen(path,mode)
                if f then
                    local baseWrite=f.write
                    local buffered=''
                    if BUFFERED_OPEN and mode and mode:match('w') then
                        f.write=function(self,data) buffered=buffered..data;return self end
                    end
                    f.flush=function(self)
                        FLUSH_CALLS=FLUSH_CALLS+1
                        if failFlush[durable or path] then return nil,'injected flush failure' end
                        if #buffered>0 then
                            local data=buffered;buffered=''
                            return baseWrite(self,data)
                        end
                        return self
                    end
                end
                if f and CLOSE_NIL then
                    local close=f.close
                    f.close=function(self) local ok,why=close(self);if ok then return nil end;return ok,why end
                end
                return f,err
            end
            EVENTS={};package.preload.event=function() return {push=function(...) EVENTS[#EVENTS+1]={...} end} end
            listing['/usr/lib/recipes']={'t.dblz'}
            files['/usr/lib/recipes/t.dblz']='t:out\\t{[1]="t:raw",qty=2}\\nt:variant:3\\t{[2]="t:raw"}\\nt:variant:0\\t{[1]="t:raw"}\\n'
            local build=require('recipes.build');assert(build.save(build.build()))
            R=require('recipes');M=R
            ORES={wood={'t:raw:0','t:log:*'},logs={'t:log:2'},wrong={'other:log:2'}}
            package.preload.oredict=function() return {cache=ORES,get=function(n) return ORES[n] end} end
            S={[1]={name='t:raw',size=64,label='Raw'},[14]={name='t:out',size=2,label='Out'}}
            P={[1]={name='t:raw',size=5},[24]={name='t:processed',damage=2,size=3},[26]={name='t:extra',size=1}}
            function craft() return assert(M.recipeFromSlots('crafting',S,27)) end
            function process() return assert(M.recipeFromSlots('processing',P,27,'furnace')) end
        ''')

    def test_listing_copies_sparse_slots_and_ignores_air(self):
        self.lua.execute('''
            local slots,n=M.slotsFromListing({['2']={name='t:x',size=3,damage=2,label='X'},[5]={name='minecraft:air',size=0}},27)
            assert(n==27 and slots[1]==nil and slots[5]==nil and slots[2].damage==2)
            slots[2].size=4
            assert(M.slotsFromListing({},0)==nil)
        ''')

    def test_transposer_slots_discovery_and_hardware_errors(self):
        self.lua.execute('''
            package.preload.component=function() return {
              list=function() local sent=false;return function() if not sent then sent=true;return 'addr' end end end,
              proxy=function(a) assert(a=='addr');return {
                getInventorySize=function(s) if s<2 then return 27 end end,
                getAllStacks=function(s) return {getAll=function() return s==0 and S or {} end} end
              } end
            } end
            local slots,size=M.readSlots({transposer='addr',side=0})
            assert(size==27 and slots[1].size==64 and slots[14].label=='Out')
            slots[1].size=1;assert(S[1].size==64)
            local inv=M.transposerInventories();assert(#inv==1 and inv[1].address=='addr' and inv[1].side==0 and inv[1].used==2)
            assert(M.readSlots({storage='stock'})==nil)
            assert(M.readSlots({transposer='bad',side=0})==nil)
            assert(M.readSlots({transposer='addr',side=6})==nil)
            assert(M.readSlots({transposer='addr',side=2})==nil)
        ''')

    def test_crafting_layout_and_errors(self):
        self.lua.execute('''
            local d=craft();assert(d.kind=='crafting' and d.inputs[1].qty==1 and d.grid[1]=='t:raw' and d.outputs[1].qty==2)
            assert(M.recipeFromSlots('other',S,27)==nil)
            assert(M.recipeFromSlots('crafting',S,28)==nil)
            assert(M.recipeFromSlots('crafting',{},27)==nil)
            S[4]={name='t:bad',size=1};assert(M.recipeFromSlots('crafting',S,27)==nil);S[4]=nil
            S[14]=nil;assert(M.recipeFromSlots('crafting',S,27)==nil)
        ''')

    def test_processing_layout_limit_and_errors(self):
        self.lua.execute('''
            local d=process();assert(d.machineType=='furnace' and #d.outputs==2 and d.outputs[1].slot==24 and d.outputs[1].item=='t:processed:2' and d.inputs[1].qty==5)
            assert(M.recipeFromSlots('processing',P,27)==nil)
            assert(M.recipeFromSlots('processing',{},27,'furnace')==nil)
            local p={[1]={name='t:raw',size=1}};assert(M.recipeFromSlots('processing',p,27,'furnace')==nil)
            for k=1,17 do p[k]={name='t:raw',size=1} end;p[27]={name='t:out',size=1}
            assert(M.recipeFromSlots('processing',p,27,'furnace')==nil)
        ''')

    def test_user_overlay_precedes_db_persists_and_is_removable(self):
        self.lua.execute('''
            local d=craft();d.grid[1]='t:different';d.inputs[1].item='t:different'
            assert(M.save(d));assert(files['/usr/lib/recipes/user.cb'])
            local all=R.getAll('t:out');assert(#all==2 and all[1][1]=='t:different' and all[2][1]=='t:raw')
            all[1][1]='changed';assert(R.getAll('t:out')[1][1]=='t:different')
            local rr=M.list('t:out');assert(#rr==2 and rr[1].source=='user' and rr[2].source=='db')
            rr[1].inputs[1].item='changed';assert(M.list('t:out')[1].inputs[1].item=='t:different')
            assert(M.save(d)==nil);assert(M.remove('t:out',2)==nil)
            package.loaded.recipes=nil;package.loaded['recipes.management']=nil
            R=require('recipes');M=R;assert(R.getAll('t:out')[1][1]=='t:different')
            assert(M.remove('t:out',1));assert(R.getAll('t:out')[1][1]=='t:raw')
            assert(EVENTS[1][1]=='recipes' and EVENTS[1][2]=='changed')
        ''')

    def test_duplicate_against_db_and_invalid_drafts(self):
        self.lua.execute('''
            local ok,err=M.save(craft());assert(ok==nil and err=='duplicate')
            local d=craft();d.outputs[1].qty=0;assert(M.save(d)==nil)
            assert(M.save({})==nil)
            d=craft();d.grid[10]='t:bad';assert(M.save(d)==nil)
        ''')

    def test_processing_uses_registry_single_commit_with_byproducts(self):
        self.lua.execute('''
            local register=R.registerProcessingRecipe;local called=false
            R.registerProcessingRecipe=function(...) called=true;return register(...) end
            local before=#RENAMES
            assert(M.save(process()) and called and #RENAMES==before+1)
            local r=R.__processRecipes['t:processed:2'][1]
            assert(r.isProcessing and r.machineType=='furnace' and r[1]=='t:raw,5' and r.qty==3)
            assert(r.byproducts[1].item=='t:extra' and r.byproducts[1].qty==1)
            local persisted=require('cbor').decode(files['/usr/lib/recipes/process.cb'])
            assert(persisted['t:processed:2'][1].byproducts[1].item=='t:extra')
            local rr=M.list('t:processed:2');assert(rr[1].source=='processing' and rr[1].inputs[1].qty==5 and #rr[1].outputs==2)
            local ok,err=M.save(process());assert(ok==nil and err=='duplicate')
            assert(M.remove('t:processed:2',1));assert(R.__processRecipes['t:processed:2']==nil)
        ''')

    def test_mutations_report_persistence_errors(self):
        self.lua.execute('''
            local d=craft();d.outputs[1].item='t:new'
            failOpen['/usr/lib/recipes/user.cb']=true
            assert(M.save(d)==nil and R.__userRecipes['t:new']==nil)
            failOpen['/usr/lib/recipes/user.cb']=nil;assert(M.save(d))
            failOpen['/usr/lib/recipes/user.cb']=true
            assert(M.remove('t:new',1)==nil and #R.__userRecipes['t:new']==1)
            failOpen['/usr/lib/recipes/process.cb']=true
            assert(M.save(process())==nil and R.__processRecipes['t:processed:2']==nil)
        ''')

    def test_all_ore_families_use_exact_namespace_metadata_and_wildcards(self):
        self.lua.execute('''
            assert(M.oreFamilies('t:raw')[1]=='wood')
            local f=M.oreFamilies('t:log:2');assert(#f==2 and f[1]=='logs' and f[2]=='wood')
            assert(#M.oreFamilies('t:log:3')==1)
            assert(#M.oreFamilies('other:raw')==0)
        ''')

    def test_search_bounded_sorted_priority_metadata_without_recipe_decodes(self):
        self.lua.execute('''
            local d=craft();d.outputs[1].item='t:zzuser';assert(M.save(d));assert(M.save(process()))
            local s=M.search('T:',2);assert(#s==2 and s[1]=='t:processed:2' and s[2]=='t:zzuser')
            local s=M.search('variant',10);assert(#s==2 and s[1]=='t:variant:0' and s[2]=='t:variant:3')
            assert(M.list('t:variant:0')[1].inputs[1].item=='t:raw')
            assert(#M.search('',0)==0 and #M.search('not-found',2)==0)
            local n=#R._recipeCache
            for i=1,5 do assert(#M.search('',3)==3) end
            assert(#R._recipeCache==n)
            local db=R.__recipes;assert(type(db.t.out)=='string' and type(db.t.variant)=='string')
        ''')

    def test_search_large_compressed_database_keeps_only_requested_window(self):
        self.lua.execute('''
            local cbor,lz=require('cbor'),require('lzss')
            local dictionary=lz.compress(cbor.encode({base={cbor.encode({[1]='t:raw',qty=1})}}))
            local db={large={}}
            for i=1,1000 do db.large[string.format('part%04d',i)]=dictionary end
            R.install(db)
            local s=M.search('LARGE:',7)
            assert(#s==7 and s[1]=='large:part0001' and s[7]=='large:part0007')
            assert(#R._recipeCache==0 and R.__recipes==db)
            assert(#M.search('part0999',1)==1)
            assert(#R._recipeCache==0)
        ''')

    def test_canonical_processing_override_matches_display_and_raw_db_categories(self):
        self.lua.execute('''
            local d=process();d.outputs[1].item='t:variant:0';assert(M.save(d))
            assert(M.list('t:variant:0')[1].source=='processing')
            assert(M.list('t:variant')[1].source=='processing')
            assert(R.getAll('t:variant:0')[1].isProcessing and R.getAll('t:variant')[1].isProcessing)
            assert(R.getDatabase('t:variant:0')[1][1]=='t:raw')
            assert(R.getDatabase('t:variant:3')[1][2]=='t:raw')
            R.__processRecipes['t:variant:0']={{[1]='t:exact,1',qty=1,isProcessing=true,machineType='exact'}}
            assert(R.getAll('t:variant:0')[1].machineType=='exact')
            assert(R.getAll('t:variant')[1].machineType=='furnace')
        ''')

    def test_duplicate_db_zero_metadata_and_air_cells(self):
        self.lua.execute('''
            local cbor,lz=require('cbor'),require('lzss')
            local recipe={[1]='t:raw:0',[2]='minecraft:air:0',[9]='minecraft:air',qty=2}
            R.install({t={out=lz.compress(cbor.encode({base={cbor.encode(recipe)}}))}})
            local ok,err=M.save(craft());assert(ok==nil and err=='duplicate')
            assert(R.__userRecipes['t:out']==nil)
            R.__processRecipes['t:processed:2']={{[1]='t:raw:0,5.0',qty=3,isProcessing=true,machineType='furnace',byproducts={{item='t:extra:0',qty=1}}}}
            ok,err=M.save(process());assert(ok==nil and err=='duplicate')
        ''')

    def test_malformed_drafts_return_errors_and_grid_matches_inputs(self):
        self.lua.execute('''
            local function reject(d)
                local ok,result,err=pcall(M.save,d)
                assert(ok and result==nil and type(err)=='string')
            end
            local d=craft();d.grid[1]='not-an-item';reject(d)
            d=craft();d.grid[1]='t:other';reject(d)
            d=craft();d.grid[1]='minecraft:air';reject(d)
            d=craft();d.grid[1]='minecraft:air:0';reject(d)
            d=craft();d.inputs[1]=false;reject(d)
            d=craft();d.outputs[1]='not-a-row';reject(d)
            d=craft();d.inputs[1].item='t:raw:0:bad';reject(d)
            d=craft();d.inputs[1].slot=2;reject(d)
            d=craft();d.inputs[1].qty=2;reject(d)
            d=craft();d.grid[2]='t:raw';d.inputs[2]={slot=1,item='t:raw',qty=1};reject(d)
            d=craft();d.inputs[3]=d.inputs[1];reject(d)
            d=craft();d.outputs[1].item='minecraft:air:0';reject(d)
            d=craft();d.grid[1]='t:raw:0'
            local ok,err=M.save(d);assert(ok==nil and err=='duplicate')
            assert(next(R.__userRecipes)==nil)
        ''')

    def test_public_management_is_lazy_and_old_mes_module_is_absent(self):
        self.lua.execute('''
            assert(package.loaded['recipes.management']==nil)
            for _,name in ipairs({'save','list','remove','search','readSlots','transposerInventories',
                'slotsFromListing','recipeFromSlots','oreFamilies'}) do assert(type(R[name])=='function') end
            assert(package.loaded.component==nil and next(R.__recipes)==nil)
            assert(#R.slotsFromListing({},27)==0 and package.loaded['recipes.management'])
            assert(R.saveRecipe==nil and R.removeRecipe==nil and R.recipes==nil)
        ''')
        self.assertFalse((ROOT / 'usr/lib/mes_recipes.lua').exists())

    def test_atomic_add_failures_preserve_existing_files_and_reload(self):
        self.lua.execute('''
            local d=craft();d.outputs[1].item='t:saved';assert(R.save(d));assert(R.save(process()))
            local userPath,processPath='/usr/lib/recipes/user.cb','/usr/lib/recipes/process.cb'
            local userBefore,processBefore=files[userPath],files[processPath]
            local faults={failOpen,failWrite,failFlush,failClose,failRename}
            for _,fault in ipairs(faults) do
                for _,path in ipairs({userPath,processPath}) do
                    fault[path]=true
                    local d=path==userPath and craft() or process();d.outputs[1].item='t:failed'
                    local ok,err=R.save(d);assert(ok==nil and type(err)=='string')
                    fault[path]=nil
                    assert(files[userPath]==userBefore and files[processPath]==processBefore)
                    assert(R.__userRecipes['t:failed']==nil and R.__processRecipes['t:failed']==nil)
                    package.loaded.recipes=nil;package.loaded['recipes.management']=nil;R=require('recipes');M=R
                    assert(R.getAll('t:saved')[1][1]=='t:raw')
                    assert(R.getAll('t:processed:2')[1].byproducts[1].item=='t:extra')
                    assert(R.__userRecipes['t:failed']==nil and R.__processRecipes['t:failed']==nil)
                    for _,h in ipairs(handles) do assert(h.closed) end
                    for name in pairs(files) do assert(not name:find('.tmp.',1,true)) end
                end
            end
        ''')

    def test_atomic_removal_failures_preserve_existing_files_and_reload(self):
        self.lua.execute('''
            local d=craft();d.outputs[1].item='t:saved';assert(R.save(d));assert(R.save(process()))
            local userPath,processPath='/usr/lib/recipes/user.cb','/usr/lib/recipes/process.cb'
            local userBefore,processBefore=files[userPath],files[processPath]
            for _,fault in ipairs({failWrite,failFlush,failClose,failRename}) do
                for _,case in ipairs({{userPath,'t:saved'},{processPath,'t:processed:2'}}) do
                    fault[case[1]]=true
                    local ok,err=R.remove(case[2],1);assert(ok==nil and type(err)=='string')
                    fault[case[1]]=nil
                    assert(files[userPath]==userBefore and files[processPath]==processBefore)
                    assert(#R.list(case[2])==1)
                    package.loaded.recipes=nil;package.loaded['recipes.management']=nil;R=require('recipes');M=R
                    assert(R.getAll('t:saved')[1][1]=='t:raw')
                    assert(R.getAll('t:processed:2')[1].byproducts[1].item=='t:extra')
                end
            end
        ''')

    def test_buffered_flush_errors_block_rename_even_when_close_returns_nil_success(self):
        self.lua.execute('''
            local d=craft();d.outputs[1].item='t:saved';assert(R.save(d))
            local path='/usr/lib/recipes/user.cb';local before=files[path];local renames=#RENAMES
            BUFFERED_OPEN=true;CLOSE_NIL=true;failFlush[path]=true
            d.outputs[1].item='t:failed'
            local ok,err=R.save(d);assert(ok==nil and err:find('flush failure',1,true))
            assert(files[path]==before and #RENAMES==renames and R.__userRecipes['t:failed']==nil)
            failFlush[path]=nil;assert(R.save(d) and FLUSH_CALLS>0)
            package.loaded.recipes=nil;package.loaded['recipes.management']=nil;R=require('recipes');M=R
            assert(R.getAll('t:failed')[1][1]=='t:raw' and R.getAll('t:saved')[1][1]=='t:raw')
        ''')

    def test_encode_failure_never_opens_a_temporary_file(self):
        self.lua.execute('''
            local d=craft();d.outputs[1].item='t:saved';assert(R.save(d))
            local path='/usr/lib/recipes/user.cb';local before=files[path];local opened=#handles
            local cbor=require('cbor');local encode=cbor.encode;cbor.encode=function() error('encode failure') end
            d.outputs[1].item='t:failed'
            local ok,err=R.save(d);assert(ok==nil and err:find('encode failure',1,true))
            cbor.encode=encode
            assert(#handles==opened and files[path]==before and R.__userRecipes['t:failed']==nil)
            package.loaded.recipes=nil;package.loaded['recipes.management']=nil;R=require('recipes');M=R
            assert(R.getAll('t:saved')[1][1]=='t:raw')
        ''')

    def test_registry_single_commit_has_byproducts_and_failure_rolls_back_durably(self):
        self.lua.execute('''
            assert(R.save(process()))
            local path='/usr/lib/recipes/process.cb';local before=files[path]
            local previous=R.__processRecipes['t:processed:2'];local saver=R.saveProcessingRecipes;local calls=0
            R.saveProcessingRecipes=function()
                calls=calls+1
                local staged=R.__processRecipes['t:processed:2'];assert(#staged==2)
                assert(staged[2].byproducts[1].item=='t:changed')
                return false,'injected commit failure'
            end
            local d=process();d.outputs[2].item='t:changed'
            local ok,err=R.save(d);assert(ok==nil and err=='injected commit failure' and calls==1)
            R.saveProcessingRecipes=saver
            assert(files[path]==before and R.__processRecipes['t:processed:2']==previous)
            package.loaded.recipes=nil;package.loaded['recipes.management']=nil;R=require('recipes');M=R
            assert(#R.__processRecipes['t:processed:2']==1 and R.getAll('t:processed:2')[1].byproducts[1].item=='t:extra')
        ''')

    def test_registry_rejects_malformed_byproducts_without_writing(self):
        self.lua.execute('''
            local cases={'bad', {false}, {{item='bad',qty=1}}, {{item='t:extra',qty=0}},
                {{item='minecraft:air:0',qty=1}}, {[2]={item='t:extra',qty=1}}, {{item='t:extra',qty=math.huge}}}
            local opened=#handles
            for _,bad in ipairs(cases) do
                local ok,result,err=pcall(R.registerProcessingRecipe,'t:product','furnace',
                    {recipe={'t:raw,1'},qty=1,byproducts=bad})
                assert(ok and result==false and err=='invalid byproducts')
            end
            assert(#handles==opened and R.__processRecipes['t:product']==nil)
        ''')


if __name__ == '__main__':
    unittest.main()
