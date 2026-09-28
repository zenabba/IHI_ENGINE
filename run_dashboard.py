"""Start the local IHI dashboard.

    python run_dashboard.py              # http://127.0.0.1:8000
    python run_dashboard.py --port 8080
    python run_dashboard.py --reset      # discard saved measurements, restart from the demo fleet

The first start copies the synthetic demo fleet (data/demo/fleet.json) into
data/processed/fleet.json. Measurements you add in the UI are saved there.
That file is gitignored, so experimenting never touches the repo.

Config (config/*.yaml) is read at start-up: restart after editing it.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from ihi.dashboard.app import create_app  # noqa: E402

SEED = ROOT / "data" / "demo" / "fleet.json"
STORE = ROOT / "data" / "processed" / "fleet.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Local IHI dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reset", action="store_true", help="restart from the demo fleet")
    args = parser.parse_args()

    if args.reset and STORE.exists():
        STORE.unlink()
        print("Saved measurements discarded, restarting from the demo fleet.")

    app = create_app(STORE, seed_path=SEED)
    print(f"IHI dashboard: http://{args.host}:{args.port}   (Ctrl+C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
