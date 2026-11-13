#!/usr/bin/env python3
"""Measure reader TLS on the latest shared block cache at 0/8/16 MiB."""
import hashlib
from pathlib import Path
from block_cache_budgets import main

if __name__ == '__main__':
    main({'scope': __doc__, 'comparison_kind': 'reader-tls',
          'baseline_source_commit': '376fbf9988b2458ee196a5d92135c35a5121edc7',
          'candidate_source_commit': '376fbf9988b2458ee196a5d92135c35a5121edc7',
          'candidate_production_patch_commit': '019868e9f79d1bb2bd1f96dafb88ef20acd45418',
          'arm_labels': {'baseline': 'latest shared block cache; reader TLS OFF',
                         'candidate': 'same block cache; reader TLS ON'},
          'reader_tls': {'baseline': False, 'candidate': True},
          'entry_script': Path(__file__).name,
          'entry_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
