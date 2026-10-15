package ocelot.spike;

import com.google.gson.*;

/** Data-only parser for OpenOS serialization tables. Never evaluates captured Lua. */
final class HostLuaTable {
    private final String text;
    private int pos, nodes;
    private HostLuaTable(String text) { this.text=text; }
    static JsonElement parse(String text) {
        if(text.length()>1024*1024) throw new IllegalArgumentException("serialization bound");
        HostLuaTable p=new HostLuaTable(text); JsonElement result=p.value(0); p.space();
        if(p.pos!=text.length()) throw new IllegalArgumentException("trailing serialization data");
        return result;
    }
    private void space() { while(pos<text.length() && Character.isWhitespace(text.charAt(pos))) pos++; }
    private char peek() { space(); return pos<text.length()?text.charAt(pos):'\0'; }
    private void expect(char c) { if(peek()!=c) throw new IllegalArgumentException("expected "+c); pos++; }
    private JsonElement value(int depth) {
        if(depth>32 || ++nodes>65536) throw new IllegalArgumentException("serialization complexity");
        char c=peek();
        if(c=='"' || c=='\'') return new JsonPrimitive(string());
        if(c=='{') {
            pos++; JsonObject table=new JsonObject(); int index=1;
            while(peek()!='}') {
                String key;
                if(peek()=='[') { pos++; JsonElement k=value(depth+1); expect(']'); expect('='); key=k.getAsString(); }
                else if(Character.isLetter(peek()) || peek()=='_') {
                    int start=pos; while(pos<text.length() && (Character.isLetterOrDigit(text.charAt(pos)) || text.charAt(pos)=='_')) pos++;
                    key=text.substring(start,pos);
                    if(peek()=='=') pos++; else { pos=start; key=Integer.toString(index++); }
                } else key=Integer.toString(index++);
                table.add(key,value(depth+1));
                if(peek()==',' || peek()==';') pos++; else if(peek()!='}') throw new IllegalArgumentException("table separator");
            }
            pos++; return table;
        }
        int start=pos;
        while(pos<text.length() && ",;} \r\n\t]".indexOf(text.charAt(pos))<0) pos++;
        String word=text.substring(start,pos);
        if(word.equals("nil")) return JsonNull.INSTANCE;
        if(word.equals("true") || word.equals("false")) return new JsonPrimitive(Boolean.parseBoolean(word));
        // Native Lua tostring(number) spelling observed on the drone report wire.
        // Preserve type and spelling; never coerce infinite fixture energy to a finite number.
        if(word.equals("inf") || word.equals("-inf") || word.equals("nan")) {
            JsonObject nonfinite=new JsonObject(); nonfinite.addProperty("$type","oc.nonfinite");
            nonfinite.addProperty("raw",word);
            nonfinite.addProperty("value",word.equals("inf")?"positiveInfinity":word.equals("-inf")?"negativeInfinity":"notANumber");
            return nonfinite;
        }
        try { return new JsonPrimitive(new java.math.BigDecimal(word)); }
        catch(NumberFormatException e) { throw new IllegalArgumentException("unsupported serialization value"); }
    }
    private String string() {
        char quote=text.charAt(pos++); StringBuilder out=new StringBuilder();
        while(pos<text.length()) {
            char c=text.charAt(pos++); if(c==quote) return out.toString();
            if(c=='\\') {
                if(pos==text.length()) break; c=text.charAt(pos++);
                if(c>='0' && c<='9') {
                    int n=c-'0', count=1;
                    while(count<3 && pos<text.length() && text.charAt(pos)>='0' && text.charAt(pos)<='9') { n=n*10+text.charAt(pos++)-'0'; count++; }
                    if(n>255) throw new IllegalArgumentException("escape bound"); c=(char)n;
                } else switch(c) {
                    case 'n': c='\n'; break; case 'r': c='\r'; break; case 't': c='\t'; break;
                    case 'a': c=7; break; case 'b': c=8; break; case 'f': c=12; break; case 'v': c=11; break;
                    case '\\': case '"': case '\'': case '\n': break;
                    default: throw new IllegalArgumentException("unsupported escape");
                }
            }
            out.append(c);
        }
        throw new IllegalArgumentException("unterminated string");
    }
}
