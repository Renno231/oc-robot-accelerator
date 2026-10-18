"""Per-thing map persistence, migration and phase-boundary flushes."""
from pathlib import Path
import unittest

import test_stock_api
import test_stations
from test_store import install_store


class MapStoreTests(unittest.TestCase):
    def setUp(self):
        fixture = test_stock_api.LibraryApiTests()
        fixture.setUp()
        self.lua = fixture.lua
        install_store(self.lua)
        self.lua.globals().MAP_SOURCE = Path('drone-logistics/usr/lib/logistics/map.lua').read_text()
        self.lua.execute('''
          package.preload["logistics.map"]=function() return assert(load(MAP_SOURCE))() end
          writes={};errors='';whole=0
          io.stderr={write=function(_,s) errors=errors..s end}
          local ser=require('serialization');local serialize=ser.serialize
          ser.serialize=function(t,...)
            if type(t)=='table' and t.nodes and t.links then whole=whole+1 end
            return serialize(t,...)
          end
          local open=require('logistics.store').open
          require('logistics.store').open=function(path,...)
            local h=open(path,...)
            if path=='/etc/map.db' then
              local put,delete,flush=h.put,h.delete,h.flush
              h.put=function(self,k,v) writes[#writes+1]={'put',k};return put(self,k,v) end
              h.delete=function(self,k) writes[#writes+1]={'delete',k};return delete(self,k) end
              h.flush=function(self) writes[#writes+1]={'flush'};return flush(self) end
            end
            return h
          end
          function expect(...)
            local keys={...};assert(#writes==#keys,#writes..' calls instead of '..#keys)
            for _,w in ipairs(writes) do
              local found=false
              for i,k in ipairs(keys) do if w[1]..':'..(w[2] or '')==k then keys[i]='';found=true;break end end
              assert(found,w[1]..':'..tostring(w[2]))
            end
            writes={}
          end
          function equal(a,b)
            if type(a)~=type(b) then return false end
            if type(a)~='table' then return a==b end
            for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
            for k in pairs(b) do if a[k]==nil then return false end end
            return true
          end
        ''')

    def test_every_mutator_exact_affected_records_and_unchanged_fs(self):
        self.lua.execute('''
          map=require('logistics.map');writes={}
          map.add('a',0,0,0);expect('put:n:a')
          map.add('b',1,0,0,{faces={[0]=true}});expect('put:n:b')
          map.add('c',2,0,0);expect('put:n:c')
          map.link('b','a');expect('put:l:a|b')
          map.unlink('a','b');expect('delete:l:a|b')
          map.name('stock','a',0);expect('put:n:a','put:s:stock')
          map.name('stock2','b',0);expect('put:s:stock2')
          map.unname('stock');expect('delete:s:stock')
          assert(map.node('a').faces[0])
          map.name('stock','a',0);expect('put:s:stock')
          map.name('extra','a',1);expect('put:n:a','put:s:extra')
          map.link('a','b');expect('put:l:a|b')
          map.link('c','a');expect('put:l:a|c')
          map.remove('a');expect('delete:n:a','delete:l:a|b','delete:l:a|c','delete:s:stock','delete:s:extra')
          assert(#map.links('b')==0 and not map.storage('stock'))
          map.add('b',3,0,0);expect('put:n:b') -- update still one node, preserving storage face
          assert(map.node('b').faces[0])
          map.save();expect('flush:')
          resetCalls();map.add('b',3,0,0);map.name('stock2','b',0);map.unlink('b','c');map.unname('gone');map.save()
          assert(not calls.write and not calls.open and not calls.remove)
          assert(whole==0 and not disk['/etc/map.cfg'])
        ''')

    def test_migrate_once_flush_before_backup_db_wins_and_identical_restart(self):
        self.lua.execute('''
          local legacy={nodes={a={x=0,y=0,z=0,created=42,faces={[0]=true}},
            b={x=1,y=0,z=0,created=43,faces={}}},links={a={b=true},b={a=true}},
            storages={stock={node='a',side=0}}}
          local text=require('serialization').serialize(legacy);disk['/etc/map.cfg']=text
          local rename=require('filesystem').rename
          require('filesystem').rename=function(a,b)
            assert(disk['/etc/map.db'] and #disk['/etc/map.db']>0)
            assert(writes[#writes][1]=='flush');return rename(a,b)
          end
          map=require('logistics.map')
          expect('put:n:a','put:n:b','put:l:a|b','put:s:stock','flush:')
          assert(equal(map.nodes(),legacy.nodes) and equal(map.storages(),legacy.storages))
          assert(map.links('a')[1]=='b' and not disk['/etc/map.cfg'] and disk['/etc/map.cfg.bak']==text)
          local saved=map.nodes();map.save();expect('flush:')
          disk['/etc/map.cfg']='invalid old source must not override DB'
          package.loaded["logistics.map"]=nil;map=require('logistics.map');expect()
          assert(equal(saved,map.nodes()) and equal(map.storages(),legacy.storages))
          assert(map.route('a','b')[2]=='b' and renames==1 and errors=='')
          assert(disk['/etc/map.cfg']=='invalid old source must not override DB')
        ''')

    def test_empty_and_invalid_legacy_report_without_crash_or_new_db(self):
        for text in ('', 'garbage', '{}'):
            with self.subTest(text=text):
                self.setUp()
                self.lua.globals().TEXT = text
                self.lua.execute('''
                  disk['/etc/map.cfg']=TEXT
                  local ok,m=pcall(require,'logistics.map');assert(ok)
                  assert(m.loadError and #errors>0 and errors:find('map:',1,true))
                  assert(not disk['/etc/map.db'] and disk['/etc/map.cfg']==TEXT and renames==0)
                  local loaded,reason=m.load();assert(not loaded and reason==m.loadError)
                  assert(#m.names()==0 and #writes==0)
                ''')

    def test_restart_after_all_kinds_of_edits_preserves_full_graph(self):
        self.lua.execute('''
          map=require('logistics.map');map.add('a',0,0,0);map.add('b',1,0,0);map.add('c',2,0,0)
          map.link('a','b');map.link('c','b');map.name('stock','a',0);map.name('old','c',1)
          map.unname('old');map.unlink('b','c');map.remove('c');map.add('b',3,0,0,{charger=true})
          map.save();local n,s=map.nodes(),map.storages()
          package.loaded["logistics.map"]=nil;map=require('logistics.map')
          assert(equal(n,map.nodes()) and equal(s,map.storages()))
          assert(#map.links('a')==1 and map.links('a')[1]=='b' and #map.links('b')==1)
          assert(#map.names()==2 and map.node('b').charger and map.route('a','b')[2]=='b')
          assert(whole==0)
        ''')

    def test_four_commissioned_rows_ten_links_no_whole_map_serialization(self):
        fixture = test_stations.StationsTests()
        fixture.setUp()
        fixture.lua.execute('''
          local ser=require('serialization');local encode=ser.serialize
          ser.serialize=function(t,...)
            assert(not (type(t)=='table' and t.nodes and t.links),'whole map serialize')
            return encode(t,...)
          end
          local open=require('logistics.store').open;local phases=0;local mapFlushes=0
          require('logistics.store').open=function(path,...)
            local h=open(path,...);return h
          end
          local save=map.save
          map.save=function() mapFlushes=mapFlushes+1;return save() end
          local before=FLUSHES
          for i=1,4 do
            local spec=row('r'..i..'_',10,2);spec.x=5;spec.z=i*4+2
            assert(st.add('row',spec));finishAll()
            local r=st.get(spec.prefix);assert(r.state=='ready',r.reason)
            assert(#r.created.nodes==10 and #r.created.links==10)
          end
          assert(mapFlushes==FLUSHES-before and mapFlushes==16)
          assert(not files['/etc/map.cfg'])
          map.save();local nodes=map.nodes();local source=MAP
          package.loaded["logistics.map"]=nil;local fresh=assert(load(source))()
          local function eq(a,b)
            if type(a)~='table' then return a==b end
            if type(b)~='table' then return false end
            for k,v in pairs(a) do if not eq(v,b[k]) then return false end end
            for k in pairs(b) do if a[k]==nil then return false end end;return true
          end
          assert(eq(nodes,fresh.nodes()) and #fresh.storageNames()==40)
        ''')


if __name__ == '__main__':
    unittest.main()
