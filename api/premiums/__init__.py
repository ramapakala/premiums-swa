import json
import logging
import os
import sys
import subprocess
from typing import List, Dict, Any

import azure.functions as func

# --- TEMP: hardcoded symbols for testing ---
HARDCODED_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]

def get_symbols(req) -> list[str]:
    """
    Priority for testing:
    1) ?symbols=AAPL,MSFT (optional override from query string)
    2) HARDCODED_SYMBOLS (default)
    """
    qs = (req.params.get("symbols") or "").strip()
    if qs:
        return [s.strip().upper() for s in qs.split(",") if s.strip()]
    return HARDCODED_SYMBOLS
# -------------------------------------------


# Try to import pure-Python implementation first (recommended).
PREMIUMS_CORE = None
try:
    from ..shared import premiums_core as PREMIUMS_CORE  # type: ignore
except Exception:  # noqa
    PREMIUMS_CORE = None

def _as_http(data: Any, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, ensure_ascii=False),
        status_code=status,
        mimetype="application/json",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

def _run_subprocess_generator() -> List[Dict[str, Any]]:
    """
    Fallback path: run your existing polygon_options_delta_table.py and capture JSON from stdout.
    You will need to add a CLI flag in your script that prints the final JSON to stdout,
    e.g. `python polygon_options_delta_table.py --emit-json`.
    """
    script = os.path.join(os.getcwd(), "polygon_options_delta_table.py")
    if not os.path.isfile(script):
        raise FileNotFoundError(f"Cannot find {script}")

    # Ensure API key and any other env vars are passed through
    env = os.environ.copy()

    # Run the script; it should write JSON to stdout.
    # Modify the args if your script needs tickers, dates, etc.
    cmd = [sys.executable, script, "--emit-json"]
    logging.info("Running subprocess: %s", " ".join(cmd))
    proc = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
    stdout = proc.stdout.strip()
    if not stdout:
        raise RuntimeError("Script produced no output on stdout")
    data = json.loads(stdout)
    if not isinstance(data, list):
        raise ValueError("Expected list JSON from script")
    return data

def main(req: func.HttpRequest) -> func.HttpResponse:
    symbols = get_symbols(req)          # <-- use the hardcoded list (or ?symbols= override)

    logging.info("GET /api/premiums")
    try:
        # Prefer direct import (fast, no process spawn)
        if PREMIUMS_CORE and hasattr(PREMIUMS_CORE, "build_premiums"):
            rows = PREMIUMS_CORE.build_premiums()
            if not isinstance(rows, list):
                raise TypeError("build_premiums() must return a list")
            return _as_http(rows, 200)

        # Fallback to subprocess wrapper (no refactor)
        rows = _run_subprocess_generator()
        return _as_http(rows, 200)

    except subprocess.CalledProcessError as e:
        logging.exception("Generator subprocess failed")
        return _as_http({"error": "generator_failed", "detail": e.stderr}, 500)
    except Exception as e:
        logging.exception("Error generating premiums")
        return _as_http({"error": "internal_error", "detail": str(e)}, 500)
