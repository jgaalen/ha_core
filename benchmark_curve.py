"""Sample actual Script.async_run in isolated processes; never modify Core files."""
import argparse
import asyncio
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time
import tracemalloc

parser = argparse.ArgumentParser()
parser.add_argument('--core', type=Path, required=True)
parser.add_argument('--variant', choices=['before', 'after'], required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--native', action='store_true')
args = parser.parse_args()
resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2,) * 2)
resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
sys.path.insert(0, str(args.core.resolve()))
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import script as script_module

FIX = '382b28ec8244d3ef3bee0f219b22b85860db4a6e'
revision = FIX + ('^' if args.variant == 'before' else '')
source = subprocess.check_output(['git', '-C', str(args.core), 'show', revision + ':homeassistant/helpers/script.py'])
commit = subprocess.check_output(['git', '-C', str(args.core), 'rev-parse', revision], text=True).strip()
# Execute the exact committed module in its normal namespace; no source patching.
exec(compile(source, script_module.__file__, 'exec'), script_module.__dict__)
Script = script_module.Script


def memory():
    fields = {}
    for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == 'kB' and parts[0] in ('Rss:', 'Pss:'):
            fields[parts[0][:-1].lower() + '_bytes'] = int(parts[1]) * 1024
    return fields


async def main():
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix='condition-curve-') as config_dir:
        hass = HomeAssistant(config_dir)
        passed = 0
        @callback
        def counted(event):
            nonlocal passed
            passed += 1
        hass.bus.async_listen('benchmark_passed', counted)
        script = Script(hass, cv.SCRIPT_SCHEMA([
            {'condition': 'template', 'value_template': '{{ (target_percentage | float - current_percentage | float) | abs >= 2 }}'},
            {'event': 'benchmark_passed'},
        ]), 'Isolated condition cache benchmark', 'script')
        async def run(n):
            for i in range(n):
                previous = passed
                await script.async_run({'target_percentage': 33 if i % 2 == 0 else 31,
                                        'current_percentage': 30}, Context())
                await hass.async_block_till_done()
                assert passed - previous == int(i % 2 == 0)
        await run(100)
        gc.collect()
        if not args.native:
            tracemalloc.start(1)
        samples = []
        baseline = None
        baseline_memory = None
        previous = 0
        start = time.perf_counter()
        for checkpoint in [0, 1000, 5000, 10000, 25000, 50000]:
            await run(checkpoint - previous)
            gc.collect()
            current = None if args.native else tracemalloc.get_traced_memory()[0]
            mem = memory()
            if baseline_memory is None:
                baseline, baseline_memory = current, mem.copy()
            samples.append({'iterations': checkpoint, 'cache_entries': len(script._condition_cache),
                            'traced_current_bytes': current,
                            'retained_delta_bytes': None if args.native else current - baseline,
                            **mem, 'rss_delta_bytes': mem['rss_bytes'] - baseline_memory['rss_bytes'],
                            'pss_delta_bytes': mem['pss_bytes'] - baseline_memory['pss_bytes'],
                            'elapsed_seconds': time.perf_counter() - start})
            result = {'variant': args.variant, 'commit': commit, 'source_sha256': hashlib.sha256(source).hexdigest(),
                      'python': platform.python_version(), 'asyncio_debug': asyncio.get_running_loop().get_debug(),
                      'tracemalloc_enabled': not args.native, 'warmup_iterations': 100,
                      'correctness_checks': checkpoint + 100, 'samples': samples,
                      'limits': {'address_space_bytes': 1536 * 1024**2, 'cpu_seconds': 90},
                      'method': 'Exact committed script module executed in normal module namespace; shared dependency environment; fresh process per variant and tracing mode.'}
            args.output.write_text(json.dumps(result, indent=2) + '\n')
            previous = checkpoint
        script._async_unload()
        assert not script._condition_cache
        print(json.dumps({'variant': args.variant, 'native': args.native, 'final': samples[-1]}))

asyncio.run(main(), debug=False)
