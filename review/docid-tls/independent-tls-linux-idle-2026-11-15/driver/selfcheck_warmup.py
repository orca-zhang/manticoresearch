"""A warmup worker error must surface before waiting for its missing token."""
import queue
from types import SimpleNamespace
import run_tls

class FailedJob:
    def ready(self):
        return True
    def get(self):
        raise RuntimeError('warmup worker failed')

class Pool:
    def apply_async(self, *args):
        return FailedJob()

class Ready:
    def get(self, timeout):
        raise queue.Empty

try:
    run_tls.measure(SimpleNamespace(port=123), [[]], Pool(),
                    SimpleNamespace(clear=lambda: None), Ready(), 1)
except RuntimeError as error:
    assert str(error) == 'warmup worker failed'
else:
    raise AssertionError('Warmup failure was lost')
print('Warmup diagnostic selfcheck passed')
