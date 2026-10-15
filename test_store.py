"""CBOR stores through a counted, buffered OpenOS-shaped filesystem."""
from pathlib import Path
import unittest

from lupa.lua53 import LuaRuntime


def install_store(lua, preserve_io=False):
    lua.globals().CBOR_SOURCE = Path('drone-logistics/lib/cbor.lua').read_text()
    lua.globals().STORE_SOURCE = Path('drone-logistics/lib/store.lua').read_text()
    lua.globals().PRESERVE_IO = preserve_io
    lua.execute('''
      package.preload.cbor=function() return assert(load(CBOR_SOURCE))() end
      package.preload.store=function() return assert(load(STORE_SOURCE))() end
      disk={};dirs={};calls={};renames=0;readWholeLog=false
      local function count(k) calls[k]=(calls[k] or 0)+1 end
      function resetCalls() calls={} end
      local fs={}
      function fs.exists(p) count('exists');return disk[p]~=nil or dirs[p]~=nil end
      function fs.makeDirectory(p) count('makeDirectory');dirs[p]=true;return true end
      function fs.remove(p) count('remove');disk[p]=nil;return true end
      function fs.list(p)
        count('list');local names={}
        for name in pairs(disk) do if name:sub(1,#p+1)==p..'/' then names[#names+1]=name:sub(#p+2) end end
        table.sort(names);local i=0;return function() i=i+1;return names[i] end
      end
      package.preload.filesystem=function() return fs end
      os.rename=function(a,b) count('rename');renames=renames+1;disk[b]=disk[a];disk[a]=nil;return true end
      fs.rename=os.rename
      local previous=io.open
      io.open=function(path,mode)
        if PRESERVE_IO and path~='/etc/store.cfg' and not path:match('^/etc/map%.db') and not path:match('^/etc/warehouse%.db')
          and not path:match('^/etc/warehouse%.flight') and not path:match('^/etc/logistics%.state')
          and not path:match('^/etc/mes%.state') and not path:match('^/etc/mes%.alerts') and not path:match('^/etc/stats') and not path:match('^/etc/housekeeping') and not path:match('^/etc/survey') then
          return previous(path,mode)
        end
        count('open');mode=mode or 'r'
        if mode:sub(1,1)=='r' and disk[path]==nil then return nil end
        if mode:sub(1,1)=='w' or mode:sub(1,1)=='a' and disk[path]==nil then disk[path]='' end
        local pending,pos='',1;local h={}
        function h:flush()
          if #pending>0 then count('write');disk[path]=disk[path]..pending;pending='' end
          return true
        end
        function h:write(...)
          for _,s in ipairs({...}) do pending=pending..s end
          if #pending>=8192 then self:flush() end
          return self
        end
        function h:read(n)
          count('read');local data=disk[path]
          if n=='*a' then
            if path:match('%.log$') or path=='/etc/warehouse.db' then readWholeLog=true end
            local s=data:sub(pos);pos=#data+1;return s
          end
          if n==0 then return '' end
          if pos>#data then return nil end
          local s=data:sub(pos,pos+n-1);pos=pos+#s;return s
        end
        function h:close() self:flush();count('close');return true end
        return h
      end
      package.preload.serialization=package.preload.serialization or function() return {
        serialize=function(t) return '{variant="'..t.variant..'"}' end,
        unserialize=function(s) return assert(load('return '..s))() end} end
      function variant(v) disk['/etc/store.cfg']=require('serialization').serialize({variant=v}) end
    ''')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        install_store(self.lua)

    def test_round_trip_and_unchanged_put_delete_both_variants(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.lua.globals().MODE = mode
                self.lua.execute('''
                  variant(MODE);local store=require('store');local path='/state_'..MODE..'.log'
                  local s=store.open(path);assert(not next(s:load()))
                  s:put('a',{value=7});s:put('false',false);s:put('number',3.25)
                  s:put('gone','bye');s:delete('gone');s:flush();s:close()
                  s=store.open(path);local r=s:load()
                  assert(r.a.value==7 and r['false']==false and r.number==3.25 and r.gone==nil)
                  resetCalls();s:put('a',{value=7});s:put('false',false);s:delete('gone');s:flush()
                  assert(not calls.write and not calls.remove and not calls.open)
                  s:close();assert(not readWholeLog)
                ''')

    def test_compaction_with_mutations_and_deletion(self):
        self.lua.execute('''
          local store=require('store');local s=store.open('/compact.log');s:load()
          for i=1,6 do s:put('k'..i,i) end
          for i=1,11 do s:put('k1',100+i) end
          assert(disk['/compact.log.new']~=nil)
          s:delete('k2');s:put('new',false)
          for i=1,12 do s:put('k3',i) end
          assert(renames>0);s:flush();s:close()
          s=store.open('/compact.log');local r=s:load()
          assert(r.k1==111 and r.k2==nil and r.k3==12 and r.new==false and r.k6==6)
          s:close()
        ''')

    def test_staging_is_discarded_on_restart(self):
        self.lua.execute('''
          local store=require('store');local s=store.open('/restart.log');s:load()
          for i=1,8 do s:put('k'..i,i) end
          for i=1,9 do s:put('k1',i+20) end
          assert(disk['/restart.log.new']~=nil and renames==0)
          s:flush();s:close()
          local s2=store.open('/restart.log');assert(disk['/restart.log.new']==nil)
          local r=s2:load();assert(r.k1==29 and r.k8==8);s2:close()
        ''')

    def test_files_escape_keys_and_replace_without_a_journal(self):
        self.lua.execute('''
          variant('files');local store=require('store');local s=store.open('/files')
          s:load();s:put('a:/ b','first')
          assert(disk['/files/a%3A%2F%20b']~=nil)
          for i=1,100 do s:put('a:/ b',i) end
          s:close();s=store.open('/files');assert(s:load()['a:/ b']==100)
          assert(renames==0);s:delete('a:/ b');s:close()
          s=store.open('/files');assert(not next(s:load()));s:close()
        ''')

    def test_decode_error_names_path_and_offset(self):
        self.lua.execute('''
          local c=require('cbor');disk['/broken.log']=c.encode({k='ok',v=1})..'\\161'
          local s=require('store').open('/broken.log')
          local ok,err=pcall(s.load,s)
          assert(not ok and err:find('/broken.log at byte '..#c.encode({k='ok',v=1}),1,true))
          s:close()
        ''')

    def test_component_calls_for_100_puts(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.lua.globals().MODE = mode
                self.lua.execute('''
                  variant(MODE);local s=require('store').open('/calls_'..MODE..'.log');s:load()
                  resetCalls();for i=1,100 do s:put('k'..i,i) end
                  if MODE=='log' then assert(not calls.write);s:flush()
                    assert(calls.write==1 and not calls.open and not calls.close)
                  else assert(calls.write==100 and calls.open==100 and calls.close==100) end
                  s:close()
                ''')
