"""macOS CPU telemetry for the shared-workstation rerun; no process is stopped."""
from collections import deque
import ctypes
import json
import os
from pathlib import Path
import statistics
import subprocess
import threading
import time

LIB = ctypes.CDLL(None)
LIB.mach_host_self.restype = ctypes.c_uint
LIB.host_statistics.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]


def cpu_ticks():
    ticks = (ctypes.c_uint * 4)()
    count = ctypes.c_uint(4)
    assert LIB.host_statistics(LIB.mach_host_self(), 3, ticks, ctypes.byref(count)) == 0
    return list(ticks)  # CPU_STATE_USER, SYSTEM, IDLE, NICE


def cpu_seconds(value):
    days, clock = value.split('-') if '-' in value else ('0', value)
    parts = list(map(float, clock.split(':')))
    assert len(parts) in (2, 3), value
    return float(days) * 86400 + sum(n * 60 ** i for i, n in enumerate(reversed(parts)))


def processes():
    output = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,time=,comm='], text=True)
    result = {}
    for line in output.splitlines():
        pid, parent, cpu, command = line.strip().split(None, 3)
        result[int(pid)] = {'parent': int(parent), 'cpu_seconds': cpu_seconds(cpu), 'command': command}
    return result


def descendants(snapshot, root):
    result = {root}
    while True:
        more = {pid for pid, p in snapshot.items() if p['parent'] in result}
        if more <= result:
            return result
        result |= more


def external_cpu(previous, current, elapsed, root):
    excluded = descendants(previous, root) | descendants(current, root)
    rows = []
    for pid in previous.keys() & current.keys() - excluded:
        p = current[pid]
        if p['command'] != previous[pid]['command']:
            continue
        delta = p['cpu_seconds'] - previous[pid]['cpu_seconds']
        if delta > 0:
            rows.append({'pid': pid, 'command': p['command'], 'cpu_percent_one_core': delta / elapsed * 100})
    rows.sort(key=lambda p: p['cpu_percent_one_core'], reverse=True)
    return sum(p['cpu_percent_one_core'] for p in rows), rows[:10]


def host_snapshot():
    return {name: subprocess.check_output(cmd, text=True) for name, cmd in {
        'thermal': ['pmset', '-g', 'therm'],
        'swap': ['sysctl', 'vm.swapusage'],
        'vm': ['vm_stat'],
    }.items()}


class LoadMonitor:
    def __init__(self, path):
        self.path = Path(path)
        self.stop = threading.Event()
        self.samples = deque(maxlen=120)
        self.error = None

    def __enter__(self):
        self.thermal_before = host_snapshot()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def run(self):
        try:
            previous_cpu, previous_processes = cpu_ticks(), processes()
            previous_time = time.monotonic()
            with self.path.open('w') as output:
                while not self.stop.wait(1):
                    ticks, current = cpu_ticks(), processes()
                    now = time.monotonic()
                    delta = [(b - a) % 2**32 for a, b in zip(previous_cpu, ticks)]
                    total = sum(delta)
                    assert total > 0
                    external, top = external_cpu(previous_processes, current, now - previous_time, os.getpid())
                    sample = {'wall_time_ns': time.time_ns(), 'monotonic_seconds': now,
                              'interval_seconds': now - previous_time, 'cpu_idle_percent': delta[2] / total * 100,
                              'external_cpu_percent_one_core': external,
                              'external_cpu_percent_machine': external / os.cpu_count(),
                              'load_average': os.getloadavg(), 'top_external_processes': top}
                    output.write(json.dumps(sample) + '\n')
                    output.flush()
                    self.samples.append(sample)
                    previous_cpu, previous_processes, previous_time = ticks, current, now
        except BaseException as error:
            self.error = error

    def wait_idle(self, seconds, mean_idle, min_idle, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error:
                raise self.error
            recent = [s for s in list(self.samples) if s['monotonic_seconds'] >= time.monotonic() - seconds - 2]
            duration = sum(s['interval_seconds'] for s in recent)
            if duration >= seconds:
                mean = sum(s['cpu_idle_percent'] * s['interval_seconds'] for s in recent) / duration
                minimum = min(s['cpu_idle_percent'] for s in recent)
                if mean >= mean_idle and minimum >= min_idle:
                    return {'interval_seconds': duration, 'idle_percent_mean': mean, 'idle_percent_min': minimum,
                            'from_monotonic_seconds': recent[0]['monotonic_seconds'] - recent[0]['interval_seconds'],
                            'to_monotonic_seconds': recent[-1]['monotonic_seconds']}
            if self.stop.wait(1):
                break
        raise RuntimeError('Idle gate not reached; preserve logs and defer the timed rerun.')

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=10)
        assert not self.thread.is_alive()
        self.thermal_after = host_snapshot()
        if self.error:
            raise self.error


def selfcheck():
    assert cpu_seconds('02:03.50') == 123.5
    assert cpu_seconds('1-02:03:04') == 93784
    before = {1: {'parent': 0, 'cpu_seconds': 5, 'command': 'external'},
              2: {'parent': 1, 'cpu_seconds': 1, 'command': 'driver'},
              3: {'parent': 2, 'cpu_seconds': 1, 'command': 'client'}}
    after = {pid: dict(p, cpu_seconds=p['cpu_seconds'] + 1) for pid, p in before.items()}
    total, top = external_cpu(before, after, 2, 2)
    assert total == 50 and [p['pid'] for p in top] == [1]
    assert len(cpu_ticks()) == 4
    print('load telemetry selfcheck passed', flush=True)


if __name__ == '__main__':
    selfcheck()
