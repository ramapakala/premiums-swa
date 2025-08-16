import json
import logging
import os
import sys
import subprocess
from typing import List, Dict, Any

import azure.functions as func
import traceback
from pathlib import Path
import csv

# --- TEMP: hardcoded symbols for testing ---
HARDCODED_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]

def get_symbols(req: func.HttpRequest) -> List[str]:
    """
    Priority for testing:
      1) ?symbols=AAPL,MSFT (optional override)
      2) HARDCODED_SYMBOLS (default)
    """
    qs = (req.params.get("symbols") or "").strip()
    if qs:
        return [s.strip().upper() for s in qs.split(",") if s.strip()]
    return HARDCODED_SYMBOLS
# -------------------------------------------

# Optional import of shared pure-Python core (safe if missing)
PREMIUMS_CORE = None
try:
    from ..shared import premiums_core as PREMIUMS_CORE  # type: ignore
except Exception:
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

def _read_csv_as_rows(csv_path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
    return rows

def _run_subprocess_generator(symbols: List[str]) -> List[Dict[str, Any]]:
    """
    Run polygon_options_delta_table.py and capture data.
    Strategy:
      1) Try `--emit-json` and parse stdout as JSON.
      2) If that fails, run without the flag and read `premiums.csv` from the function dir.
    """
    here = Path(__file__).resolve().parent
    script = here / "polygon_options_delta_table.py"
    if not script.exists():
        raise FileNotFoundError("Cannot find script at %s" % script)

    env = os.environ.copy()
    if symbols:
        env["SYMBOLS"] = ",".join(symbols)

    # 1) Try JSON-emitting mode
    try:
        cmd = [sys.executable, str(script), "--emit-json"]
        logging.info("Running subprocess (json mode): %s", " ".join(cmd))
        proc = subprocess.run(cmd, env=env, cwd=str(here), check=True,
                              capture_output=True, text=True)
        stdout = (proc.stdout or "").strip()
        if stdout:
            data = json.loads(stdout)
            if isinstance(data, list):
                return data
            logging.warning("stdout was not a list; type=%s", type(data))
        else:
            logging.warning("No JSON on stdout in --emit-json mode")
    except Exception as e:
        logging.info("JSON mode failed: %s", e)

    # 2) Fallback: run normally and read premiums.csv
    cmd2 = [sys.executable, str(script)]
    logging.info("Running subprocess (csv mode): %s", " ".join(cmd2))
    proc2 = subprocess.run(cmd2, env=env, cwd=str(here), check=True,
                           capture_output=True, text=True)

    # Look for a CSV the script produced in the function directory
    for candidate in ("premiums.csv", "output.csv"):
        csv_path = here / candidate
        if csv_path.exists():
            return _read_csv_as_rows(csv_path)

    # If we get here, we couldn't obtain data
    raise RuntimeError("Script ran but produced no JSON on stdout and no premiums.csv in %s" % here)

def main(req: func.HttpRequest) -> func.HttpResponse:
    # Diagnostics probe: /api/premiums?diag=runtime
    if req.params.get("diag") == "runtime":
        import platform
        here = Path(__file__).resolve().parent
        return _as_http({
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "func_dir": str(here),
            "files_in_func_dir": sorted(os.listdir(str(here))),
            "env": {
                "FUNCTIONS_WORKER_RUNTIME": os.getenv("FUNCTIONS_WORKER_RUNTIME", ""),
                "AzureWebJobsFeatureFlags": os.getenv("AzureWebJobsFeatureFlags", ""),
                "WEBSITE_SITE_NAME": os.getenv("WEBSITE_SITE_NAME", ""),
                "SYMBOLS": os.getenv("SYMBOLS", "")
            }
        }, 200)

    symbols = get_symbols(req)
    logging.info("GET /api/premiums (symbols=%s)", ",".join(symbols))

    # Expose to any code that reads env
    if symbols:
        os.environ["SYMBOLS"] = ",".join(symbols)

    try:
        # If you later add a pure-Python core that returns rows directly:
        if PREMIUMS_CORE and hasattr(PREMIUMS_CORE, "build_premiums"):
            try:
                rows = PREMIUMS_CORE.build_premiums(symbols=symbols)  # type: ignore
            except TypeError:
                rows = PREMIUMS_CORE.build_premiums()  # type: ignore
            if not isinstance(rows, list):
                raise TypeError("build_premiums() must return a list")
            return _as_http(rows, 200)

        # Subprocess path (works today)
        rows = _run_subprocess_generator(symbols)
        return _as_http(rows, 200)

    except subprocess.CalledProcessError as e:
        logging.exception("Generator subprocess failed")
        return _as_http({
            "error": "generator_failed",
            "stderr": e.stderr,
            "returncode": e.returncode,
            "cmd": getattr(e, "cmd", None)
        }, 500)

    except Exception as e:
        logging.exception("Error generating premiums")
        here = Path(__file__).resolve().parent
        script_path = here / "polygon_options_delta_table.py"
        return _as_http({
            "error": "internal_error",
            "detail": str(e),
            "traceback": traceback.format_exc(),
            "cwd": os.getcwd(),
            "func_dir": str(here),
            "script_exists": script_path.exists(),
            "dir_listing": sorted(os.listdir(str(here))),
            "env_SYMBOLS": os.getenv("SYMBOLS", "")
        }, 500)
