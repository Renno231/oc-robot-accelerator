from test_support import LuaCase


class ArchiveTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('lzss', 'lib/lzss.lua')
        self.lua.execute("""
            CLOSED, WRITES, CONTENT, OFFSET = 0, {}, '', 1
            package.preload.buffer=function() return {new=function(_,stream) return stream end} end
            io.open=function(_,mode)
                return {mode={w=mode=='wb',r=mode~='wb'},
                    close=function() CLOSED=CLOSED+1;return true end,
                    write=function(self,s)
                        if FAIL_WRITE then return nil,'disk full' end
                        table.insert(WRITES,s);return self
                    end,
                    read=function(_,n)
                        if OFFSET>#CONTENT then return nil end
                        local s=CONTENT:sub(OFFSET,OFFSET+n-1);OFFSET=OFFSET+#s;return s
                    end}
            end
        """)
        self.module('liblz16', 'lib/liblz16.lua')
        self.lua.execute("ARCHIVE=require('liblz16')")

    def test_invalid_header_closes_file(self):
        self.assertEqual(self.lua.execute("CONTENT='wrong';local f,err=ARCHIVE.open('x','rb');return f,CLOSED,err~=nil"), (False, 1, True))

    def test_header_write_failure_closes_file(self):
        self.assertEqual(self.lua.execute("FAIL_WRITE=true;local f,err=ARCHIVE.open('x','wb');return f,CLOSED,err:find('disk full')~=nil"), (False, 1, True))

    def test_block_write_failure_is_not_hidden(self):
        self.assertEqual(self.lua.execute("local f=ARCHIVE.open('x','wb');FAIL_WRITE=true;local ok=pcall(f.write,f,'hello');f:close();return ok,CLOSED"), (False, 1))

    def test_truncated_block_fails(self):
        self.assertEqual(self.lua.execute("CONTENT='lz16'..string.pack('>I2',10)..'abc';local f=ARCHIVE.open('x','rb');local ok=pcall(f.read);f:close();return ok,CLOSED"), (False, 1))

    def test_truncated_block_length_fails(self):
        self.assertEqual(self.lua.execute("CONTENT='lz16'..'x';local f=ARCHIVE.open('x','rb');local ok=pcall(f.read);f:close();return ok,CLOSED"), (False, 1))

    def test_malformed_lzss_tokens_fail_instead_of_decoding_empty_data(self):
        for data in ['string.char(0)', 'string.char(1)', 'string.char(0,0)', 'string.char(0,0,0)']:
            with self.subTest(data=data):
                self.assertFalse(self.lua.execute("return pcall(require('lzss').decompress,"+data+")")[0])

    def test_many_valid_lzss_roundtrips(self):
        self.assertTrue(self.lua.execute("""
            local lz=require('lzss')
            math.randomseed(17)
            for n=1,300 do
                local chars={};for i=1,n do chars[i]=string.char(math.random(0,255)) end
                local s=table.concat(chars);assert(lz.decompress(lz.compress(s))==s)
            end
            for _,s in ipairs({'',string.rep('abcdef',500),string.rep('a',20000)}) do
                assert(lz.decompress(lz.compress(s))==s)
            end
            return true
        """))

    def test_roundtrip_and_normal_eof(self):
        self.assertEqual(self.lua.execute("local f=ARCHIVE.open('x','wb');f:write('hello hello');f:close();CONTENT=table.concat(WRITES);OFFSET=1;local r=ARCHIVE.open('x','rb');local s=r:read();local eof=r:read();r:close();return s,eof==nil,CLOSED"), ('hello hello', True, 2))
