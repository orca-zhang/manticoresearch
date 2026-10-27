#!/usr/bin/env python3
"""Apply supported MANTICORE_* exports from this build's gtest log to a command."""
import argparse
import os
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('calibration', type=Path)
parser.add_argument('command', nargs=argparse.REMAINDER)
args = parser.parse_args()
assert args.command
values = dict(re.findall(r'^export (MANTICORE_[A-Z_]+)=(\d+)$', args.calibration.read_text(), re.M))
assert values, 'no supported stack-calibration exports in the supplied log'
env = os.environ.copy()
env.update(values)
raise SystemExit(subprocess.run(args.command, env=env).returncode)
