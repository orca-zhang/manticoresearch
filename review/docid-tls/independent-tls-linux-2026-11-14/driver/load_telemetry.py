"""Linux host CPU telemetry; read-only, with benchmark descendants excluded."""
from collections import deque
import json
import os
from pathlib import Path
import threading
import time


def cpu_ticks():
    v = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    # Guest time is already included in user/nice; never count it twice.
    return [v[0], v[2] + sum(v[5:8]), v[3] + v[4], v[1]]


def processes():
    result = {}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            line = path.read_text()
            command = line[line.index('(') + 1:line.rindex(')')]
            f = line.rsplit(')', 1)[1].split()
            result[int(path.parent.name)] = {'parent': int(f[1]), 'start': int(f[19]),
                'cpu_seconds': (int(f[11]) + int(f[12])) / os.sysconf('SC_CLK_TCK'), 'command': command}
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return result


def descendants(snapshot, root):
    result = {root}
    while True:
        more = {pid for pid, p in snapshot.items() if p['parent'] in result}
        if more <= result:
            return result
        result |= more


def own_cpu(previous, current, elapsed, root):
    included = descendants(previous, root) | descendants(current, root)
    delta = sum(current[pid]['cpu_seconds'] - previous[pid]['cpu_seconds']
                for pid in previous.keys() & current.keys() & included
                if previous[pid]['start'] == current[pid]['start'])
    return delta / elapsed * 100


def host_snapshot():
    paths = [Path('/proc/meminfo'), Path('/proc/pressure/cpu'), Path('/proc/pressure/memory')]
    paths += list(Path('/sys/class/thermal').glob('thermal_zone*/temp'))
    paths += list(Path('/sys/devices/system/cpu').glob('cpu*/cpufreq/scaling_governor'))
    return {str(p): p.read_text() for p in paths if p.exists()}


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
                    delta = [b - a for a, b in zip(previous_cpu, ticks)]
                    total = sum(delta)
                    assert total > 0
                    idle = delta[2] / total * 100
                    benchmark = own_cpu(previous_processes, current, now - previous_time, os.getpid())
                    # /proc/stat is host-wide, even in a PID namespace. The residual
                    # includes host services and any short-lived unobserved processes.
                    external = max(0, (100 - idle) * os.cpu_count() - benchmark)
                    sample = {'wall_time_ns': time.time_ns(), 'monotonic_seconds': now,
                              'interval_seconds': now - previous_time, 'cpu_idle_percent': idle,
                              'benchmark_cpu_percent_one_core': benchmark,
                              'external_cpu_percent_one_core': external,
                              'external_cpu_percent_machine': external / os.cpu_count(),
                              'load_average': os.getloadavg()}
                    output.write(json.dumps(sample) + '\n'); output.flush()
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
        self.stop.set(); self.thread.join(timeout=10)
        assert not self.thread.is_alive()
        self.thermal_after = host_snapshot()
        if self.error:
            raise self.error


def selfcheck():
    before = {1: {'parent': 0, 'start': 1, 'cpu_seconds': 5},
              2: {'parent': 1, 'start': 1, 'cpu_seconds': 1},
              3: {'parent': 2, 'start': 1, 'cpu_seconds': 1}}
    after = {pid: dict(p, cpu_seconds=p['cpu_seconds'] + 1) for pid, p in before.items()}
    assert own_cpu(before, after, 2, 2) == 100
    after[3]['start'] = 2
    assert own_cpu(before, after, 2, 2) == 50
    assert len(cpu_ticks()) == 4 and all(x >= 0 for x in cpu_ticks())
    assert os.getpid() in processes()
    print('Linux telemetry selfcheck passed', flush=True)


if __name__ == '__main__':
    selfcheck()
