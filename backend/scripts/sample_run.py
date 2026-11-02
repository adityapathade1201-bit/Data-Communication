"""Run the engine headless (standard library only) and print the headline numbers.

    cd backend && python scripts/sample_run.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sim.experiments import run_experiments  # noqa: E402
from app.sim.presets import get_preset  # noqa: E402

out = run_experiments(get_preset("three-sender"))
ids = [e["id"] for e in out["experiments"]]
print(f"{'metric':<26}" + "".join(f"{i:>12}" for i in ids))
for r in out["comparison"]:
    print(f"{r['label'] + ' (' + r['unit'] + ')':<26}" + "".join(
        f"{(r['values'][i] if r['values'][i] is not None else float('nan')):>12.3f}" for i in ids))
print("\nVerdict:", out["verdict"])
