"""Render measured sequential runs, not extrapolated or simulated values."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
fig, axes = plt.subplots(2, 2, figsize=(12, 8))
colors = {'before': '#c23b22', 'after': '#1676b6'}
for variant in ('before', 'after'):
    traced = json.loads((root / f'{variant}-traced-sequential.json').read_text())['samples']
    native = json.loads((root / f'{variant}-native-sequential.json').read_text())['samples']
    x = [s['iterations'] for s in traced]
    axes[0, 0].plot(x, [s['retained_delta_bytes'] / 1024**2 for s in traced], 'o-', color=colors[variant], label=variant.title())
    axes[0, 1].plot(x, [s['cache_entries'] for s in traced], 'o-', color=colors[variant], label=variant.title())
    axes[1, 0].plot(x, [s['rss_delta_bytes'] / 1024**2 for s in native], 'o-', color=colors[variant], label=f'{variant.title()} RSS')
    axes[1, 0].plot(x, [s['pss_delta_bytes'] / 1024**2 for s in native], 'x--', color=colors[variant], label=f'{variant.title()} PSS')
    if variant == 'after':
        axes[1, 1].plot(x, [s['retained_delta_bytes'] / 1024 for s in traced], 'o-', color=colors[variant], label='After (zoom)')
for ax, title, ylabel in zip(axes.flat, ['Retained Python allocations after GC', 'Condition cache entries (absolute)', 'Native process memory (no tracemalloc)', 'Patched retained allocations: detail'], ['Delta from warmup baseline (MiB)', 'Entries', 'Delta from warmup baseline (MiB)', 'Delta from warmup baseline (KiB)']):
    ax.set(title=title, xlabel='Script runs after 100 warmup runs', ylabel=ylabel)
    ax.grid(alpha=.25)
    ax.legend()
    ax.ticklabel_format(axis='x', style='plain')
fig.suptitle('Script condition cache: measured before / after\nPython 3.14.4 | asyncio debug=False | fresh isolated processes', fontsize=14)
fig.text(.5, .015, 'Synthetic loop, not production telemetry. Current allocations, not peak. RSS/PSS include allocator effects.', ha='center', fontsize=10)
fig.tight_layout(rect=(0, .04, 1, .93))
fig.savefig(root / 'condition-cache-curve.png', dpi=160)
fig.savefig(root / 'condition-cache-curve.svg')
