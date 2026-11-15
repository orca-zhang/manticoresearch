"""Matched 32-client variant: identical HTTP bytes sent in a single write."""
import hashlib,json,sys
from pathlib import Path
import benchmark,run_tls
from coalesced_http import SingleWriteConnection,selfcheck

# Spawned workers import this module, so they install the same client transport.
benchmark.http.client.HTTPConnection=SingleWriteConnection

if __name__=='__main__':
    selfcheck()
    output=Path(sys.argv[sys.argv.index('--output')+1])
    here=Path(__file__).parent
    transport={'mode':'One send() call per byte-body HTTP request; same wire bytes; no reconnect/retry on error',
               'reason':'Investigate high-concurrency HTTP receive/connection-reset failures while keeping engine binaries unchanged',
               'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),here/'coalesced_http.py']}}
    (output.parent/(output.name+'-protocol.json')).write_text(json.dumps(transport,indent=2)+'\n')
    try:
        run_tls.main()
    finally:
        for name in ['plan.json','results.json']:
            p=output/name
            if p.exists():
                data=json.loads(p.read_text());data['transport']=transport
                p.write_text(json.dumps(data,indent=2)+'\n')
