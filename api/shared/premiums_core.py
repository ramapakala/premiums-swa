from __future__ import annotations

import json
import os
import sys
import csv
from typing import List, Dict, Any, Optional
from pathlib import Path
import subprocess
import logging

# ---- Configuration ---------------------------------------------------------

# Where your legacy generator lives relative to the repo root / Functions app.
DEFAULT_GENERATOR_PATHS = [
    # common locations in your repo
    Path.cwd() / "polygon_options_delta_table.py",
    Path.cwd().parent / "polygon_options_delta_table.py",
    Path("/home/site/wwwroot") / "polygon_options_delta_table.py",  # Azure Linux
]

# If the legacy script writes these files, we can parse them as a fallback.
PUBLIC_JSON_PATHS = [
    Path.cwd() / "premiums-ui" / "public" / "premiums.json",
    Path.cwd().parent / "premiums-ui" / "public" / "premiums.json",
    Path("/home/site/wwwroot") / "premiums-ui" / "public" / "premiums.json",
]

CSV_PATHS = [
    Path.cwd() / "premiums.csv",
    Path.cwd().parent / "premiums.csv",
    Path("/home/site/wwwroot") / "premiums.csv",
]

# Deltas the UI expects (5% steps)
TARGET_DELTAS = [round(i * 0.05, 2) for i in range(1, 11)]  # 0.05..0.50


# ---- Helpers ---------------------------------------------------------------

def _log_where(paths: List[Path]) -> Optional[Path]:
    for p in paths:
        if p.is_file():
            logging.info("Found: %s", p)
            return p
    logging.info("None of these paths exist: %s", [str(p) for p in paths])
    return None


def _load_json_file(p: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logging.warning("JSON at %s was not a list; type=%s", p, type(data))
    except Exception as e:
        logging.info("Could not read JSON at %s: %s", p, e)
    return None


def _csv_to_rows(p: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Parse a 'wide' premiums.csv into the list[dict] shape the UI expects.
    Expected columns include: symbol, UnderlyingPrice, Shares, and for each delta:
      "<delta>S", "<delta>P", "<delta>N"
    We'll accept both 0.05 or 0.05 formatted strings (two decimals).
    """
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            out: List[Dict[str, Any]] = []
            for row in reader:
                rec: Dict[str, Any] = {
                    "symbol": row.get("symbol"),
                    "UnderlyingPrice": _num(row.get("UnderlyingPrice")),
                    "Shares": _num(row.get("Shares")),
                }
                # Map any of 0.05S/0.05P/0.05N etc.
                for d in TARGET_DELTAS:
                    dkey = f"{d:.2f}"
                    for suf in ("S", "P", "N"):
                        key = f"{dkey}{suf}"
                        val = row.get(key)
                        rec[key] = _num(val)
                out.append(rec)
        return out
    except Exception as e:
        logging.info("CSV parse failed at %s: %s", p, e)
        return None


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        try:
            # strip $ or commas if present
            s = str(v).replace("$", "").replace(",", "")
            return float(s)
        except Exception:
            return None


def _run_generator_subprocess(generator: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Try to run the legacy generator so that it prints premiums JSON to stdout.
    We attempt two strategies:
      1) Call with --emit-json (if you added this flag).
      2) Call without flags, then try to read PUBLIC_JSON_PATHS.
    """
    env = os.environ.copy()
    python = sys.executable or "python3"

    # Strategy 1: --emit-json to stdout
    try:
        cmd = [python, str(generator), "--emit-json"]
        logging.info("Running generator with --emit-json: %s", " ".join(cmd))
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env, timeout=120)
        stdout = (proc.stdout or "").strip()
        if stdout:
            data = json.loads(stdout)
            if isinstance(data, list):
                return data
            logging.warning("Generator stdout was not a list JSON")
    except subprocess.CalledProcessError as e:
        logging.warning("Generator --emit-json failed (rc=%s): %s", e.returncode, e.stderr or e.stdout)
    except FileNotFoundError:
        logging.warning("Python executable not found while running generator")
    except Exception as e:
        logging.warning("Generator --emit-json errored: %s", e)

    # Strategy 2: run 'normally', then try to read JSON the script writes
    try:
        cmd = [python, str(generator)]
        logging.info("Running generator normally: %s", " ".join(cmd))
        subprocess.run(cmd, check=True, env=env, timeout=180)
        for json_path in PUBLIC_JSON_PATHS:
            if json_path.is_file():
                data = _load_json_file(json_path)
                if data is not None:
                    return data
        # As a last resort, try CSV
        for csv_path in CSV_PATHS:
            if csv_path.is_file():
                rows = _csv_to_rows(csv_path)
                if rows is not None:
                    return rows
    except subprocess.CalledProcessError as e:
        logging.warning("Generator normal run failed (rc=%s): %s", e.returncode, e.stderr if hasattr(e, "stderr") else e)
    except Exception as e:
        logging.warning("Generator normal run errored: %s", e)

    return None


# ---- Public API ------------------------------------------------------------

def build_premiums() -> List[Dict[str, Any]]:
    """
    Returns a list of dicts that your UI consumes, with keys:
      symbol, UnderlyingPrice, Shares, and for each delta in TARGET_DELTAS:
      "<delta>S", "<delta>P", "<delta>N"
    Resolution order:
      1) If PREMIUMS_JSON_PATH env var points to a readable file, use it.
      2) If a baked premiums.json exists at a known path, use it.
      3) If PREMIUMS_CSV_PATH env var points to a readable CSV, parse it.
      4) If a baked premiums.csv exists at a known path, parse it.
      5) If the legacy generator script exists, try to run it and capture JSON.
      6) Otherwise, return an empty list (UI will show 0 rows gracefully).
    """
    # 1) Explicit JSON path from env
    p = os.getenv("PREMIUMS_JSON_PATH")
    if p:
        path = Path(p)
        if path.is_file():
            data = _load_json_file(path)
            if data is not None:
                return data

    # 2) Common baked JSON paths
    json_path = _log_where(PUBLIC_JSON_PATHS)
    if json_path:
        data = _load_json_file(json_path)
        if data is not None:
            return data

    # 3) Explicit CSV path from env
    c = os.getenv("PREMIUMS_CSV_PATH")
    if c:
        cpath = Path(c)
        if cpath.is_file():
            rows = _csv_to_rows(cpath)
            if rows is not None:
                return rows

    # 4) Common baked CSV paths
    csv_path = _log_where(CSV_PATHS)
    if csv_path:
        rows = _csv_to_rows(csv_path)
        if rows is not None:
            return rows

    # 5) Try running the legacy generator
    generator = _log_where(DEFAULT_GENERATOR_PATHS)
    if generator:
        rows = _run_generator_subprocess(generator)
        if rows is not None:
            return rows

    logging.warning("No premiums data available from JSON/CSV/generator; returning []")
    return []
