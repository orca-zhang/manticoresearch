"""Same HTTP bytes in one write; retain response validation and fail on errors."""
import http.client

BaseConnection=http.client.HTTPConnection

class SingleWriteConnection(BaseConnection):
    def _send_output(self,message_body=None,encode_chunked=False):
        # shortcut: CPython 3.12 byte-body requests only; recheck on Python upgrades.
        assert not encode_chunked and isinstance(message_body,(bytes,type(None)))
        wire=b'\r\n'.join([*self._buffer,b'',b''])+(message_body or b'')
        self._buffer.clear()
        self.send(wire)

def selfcheck():
    sent=[]
    for cls in (BaseConnection,SingleWriteConnection):
        connection=cls('127.0.0.1',123)
        writes=[];connection.send=writes.append
        connection.request('POST','/sql?mode=raw',b'query=SELECT+1',
                           {'Content-Type':'application/x-www-form-urlencoded','Connection':'keep-alive'})
        sent.append(writes)
    assert len(sent[0])==2 and len(sent[1])==1
    assert b''.join(sent[0])==sent[1][0]
    print('HTTP coalescing selfcheck passed: identical bytes, one write, no retry')

if __name__=='__main__':selfcheck()
