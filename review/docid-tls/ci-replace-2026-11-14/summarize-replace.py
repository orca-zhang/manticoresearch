import json,re,sys
from pathlib import Path

def measurements(path):
    s=path.read_text()
    s=re.sub(r'\x1b\[[0-9;]*m','',s)
    s=re.sub(r'^\d{4}-\d{2}-\d{2}T\S+Z ', '', s, flags=re.M)
    values=[]
    for m in re.finditer(r'^echo \$(elapsed_time2?|\(\(elapsed_time / elapsed_time2\)\))\r?\n[^\n]*output[^\n]*\n(\d+)\r?$',s,re.M):
        values.append((m.group(1),int(m.group(2))))
    expected=['elapsed_time','elapsed_time2','((elapsed_time / elapsed_time2))']*2
    assert [k for k,v in values]==expected,(path,values)
    out=[]
    for engine,start in [('rowwise',0),('columnar',3)]:
        a,b,c=[v for k,v in values[start:start+3]]
        assert a//b==c
        out.append({'engine':engine,'set_ms':a,'values_ms':b,'ratio':a/b,'integer_ratio':c,'ratio_pass':c<=12})
    return {'file':path.name,'measurements':out}

print(json.dumps([measurements(Path(p)) for p in sys.argv[1:]],indent=2))
