#!/usr/bin/env python3
"""
polygon_options_delta_table.py

- Only CLI arg: --type (call|put)
- Reads symbols (and optional shares) from symbols.txt
  Examples:
      I:SPX,50
      AAPL 200
      MSFT
- Uses next Friday as the sole expiration.
- Fetches underlying prices via grouped aggs for the latest trading day,
  with per-symbol fallback + retry/backoff to avoid 429s.
- Deltas: 0.02 .. 0.50 step 0.02.
- premiums.csv (wide): symbol, UnderlyingPrice, Shares, then for each delta:
      XXS = Strike, XXP = Premium, XXN = Shares * Premium
- details.csv (long): one row per symbol×delta with strike, premium, shares*premium.

Requires: requests, pandas
Env: set POLYGON_API_KEY in your environment (e.g., in ~/.zshrc)
"""

import os
import sys
import math
import time
import argparse
from datetime import date, timedelta
from typing import Dict, List, Tuple, Optional

import requests
import pandas as pd

API_KEY = os.getenv("POLYGON_API_KEY", "REPLACE_WITH_YOUR_KEY")
BASE = "https://api.polygon.io"

# ---- Fixed configuration ----
SYMBOLS_FILE = "symbols.txt"
DETAILS_FILE  = "details.csv"
PREMIUMS_FILE = "premiums.csv"

# Deltas from 0.02 to 0.50 inclusive (step 0.02)
TARGET_DELTAS = [i / 100 for i in range(5, 51, 5)]


# --------------------------- Helpers -----------------------------------
def require_key():
    if not API_KEY or API_KEY in {"REPLACE_WITH_YOUR_KEY", "YOUR_KEY"}:
        print("ERROR: Please set POLYGON_API_KEY in your environment to your REAL key.", file=sys.stderr)
        sys.exit(1)


def add_api_key_to_url(url: str) -> str:
    if "apiKey=" not in url:
        url += ("&" if "?" in url else "?") + f"apiKey={API_KEY}"
    return url


def next_friday_str() -> str:
    """Return YYYY-MM-DD for the upcoming Friday (today if Friday)."""
    today = date.today()
    weekday = today.weekday()  # Mon=0 ... Sun=6
    days_ahead = (4 - weekday) % 7
    return (today + timedelta(days=days_ahead)).isoformat()


def fnum(x):
    try:
        return float(x)
    except Exception:
        return math.nan


def load_symbols_with_shares(path: str) -> List[Tuple[str, int]]:
    """Return list of (symbol, shares_int). Accepts 'SYM,shares' or 'SYM shares' or 'SYM'."""
    if not os.path.exists(path):
        print(f"ERROR: symbols file not found: {path}", file=sys.stderr)
        sys.exit(2)
    out: List[Tuple[str, int]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            shares = 0
            sym = raw
            if "," in raw:
                parts = [p.strip() for p in raw.split(",", 1)]
                sym = parts[0]
                if len(parts) > 1 and parts[1]:
                    try: shares = int(parts[1])
                    except: shares = 0
            else:
                parts = raw.split()
                if len(parts) >= 2:
                    sym = parts[0]
                    try: shares = int(parts[1])
                    except: shares = 0
            out.append((sym, shares))
    if not out:
        print(f"ERROR: no symbols found in {path}", file=sys.stderr)
        sys.exit(2)
    return out


# -------------------- HTTP with Retry/Backoff --------------------------
def get_json(url: str, params: Optional[dict] = None, timeout: int = 60, max_retries: int = 5):
    url = add_api_key_to_url(url)
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        r = requests.get(url, params=params, timeout=timeout)
        if 200 <= r.status_code < 300:
            return r.json()
        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            try:
                delay = float(ra) if ra and ra.isdigit() else backoff
            except Exception:
                delay = backoff
            print(f"[WARN] 429 Too Many Requests for {url}. Sleeping {delay:.2f}s (attempt {attempt}/{max_retries})")
            time.sleep(delay)
            backoff = min(backoff * 2, 8.0)
            continue
        print(f"[ERROR] HTTP {r.status_code} for {url}: {r.text}")
        r.raise_for_status()
    raise RuntimeError(f"Failed after {max_retries} retries: {url}")


# ----------------------- Prices (Bulk + Fallback) -----------------------
def find_latest_grouped_stock_closes(max_lookback: int = 7):
    """
    Try /v2/aggs/grouped/locale/us/market/stocks/{YYYY-MM-DD} going backward
    up to max_lookback days. Returns (date_str, {ticker: close}).
    """
    for i in range(max_lookback):
        ds = (date.today() - timedelta(days=i)).isoformat()
        url = f"{BASE}/v2/aggs/grouped/locale/us/market/stocks/{ds}"
        try:
            js = get_json(url, params=None, timeout=120)
            rows = js.get("results") or []
            if rows:
                out = {}
                for r in rows:
                    t = r.get("T")
                    c = r.get("c")
                    if t and c is not None:
                        out[str(t)] = float(c)
                print(f"[INFO] Using grouped stock closes for {ds} ({len(out)} tickers)")
                return ds, out
        except Exception as e:
            print(f"[WARN] Grouped fetch failed for {ds}: {e}")
            continue
    print("[WARN] Could not find grouped stock closes in lookback window; falling back per-symbol")
    return None, {}


def get_underlying_prices(symbols: List[str]) -> Dict[str, float]:
    """
    Map {symbol: prev_close}. Use grouped stocks first, then per-symbol fallback.
    Index tickers (prefix 'I:') and any missing names use /v2/aggs/ticker/{sym}/prev.
    """
    prices: Dict[str, float] = {}
    stockish = [s for s in symbols if not s.startswith("I:")]
    indexish = [s for s in symbols if s.startswith("I:")]

    _, grouped_map = find_latest_grouped_stock_closes()
    for s in stockish:
        if s in grouped_map:
            prices[s] = grouped_map[s]

    need_single = [s for s in symbols if s.startswith("I:") or s not in prices]
    for s in need_single:
        try:
            url = f"{BASE}/v2/aggs/ticker/{s}/prev"
            js = get_json(url, timeout=30)  # retry/backoff on 429
            res = js.get("results") or []
            if res and res[0].get("c") is not None:
                prices[s] = float(res[0]["c"])
            else:
                print(f"[WARN] No prev close in response for {s}")
        except Exception as e:
            print(f"[WARN] Prev close fetch failed for {s}: {e}")
    return prices


# ----------------------- Snapshots (Options) ----------------------------
def fetch_chain_snapshot(symbol: str, expiration: str, opt_type: str) -> List[dict]:
    """Fetch all snapshot pages for one underlying and (fixed) expiration."""
    print(f"[INFO] Fetching snapshot for {symbol}, expiration={expiration}, type={opt_type}")
    base_url = f"{BASE}/v3/snapshot/options/{symbol}"
    params = {"limit": 250, "expiration_date": expiration, "contract_type": opt_type, "apiKey": API_KEY}
    results, url = [], base_url
    while url:
        js = get_json(url, params=params if url == base_url else None, timeout=60)
        page = js.get("results") or []
        print(f"[DEBUG] Retrieved {len(page)} snapshot rows for {symbol}")
        results.extend(page)
        url, params = js.get("next_url"), None
    print(f"[INFO] Total snapshot rows for {symbol} @ {expiration}: {len(results)}")
    return results


def get_delta(snap: dict):
    d = (snap.get("greeks") or {}).get("delta")
    try:
        return float(d) if d is not None else None
    except Exception:
        return None


def get_details_field(snap: dict, key: str):
    return (snap.get("details") or {}).get(key)


def mid_price_from_snapshot(snap: dict) -> float:
    """Premium fallback: mid -> last -> ask -> bid -> day.close."""
    q = snap.get("last_quote") or {}
    t = snap.get("last_trade") or {}
    day = snap.get("day") or {}
    bid = q.get("bid") or q.get("bid_price")
    ask = q.get("ask") or q.get("ask_price")
    last = t.get("price")
    prev_close = day.get("close")
    b, a, l, pc = fnum(bid), fnum(ask), fnum(last), fnum(prev_close)
    if not math.isnan(b) and not math.isnan(a) and a > 0 and b >= 0:
        return (a + b) / 2.0
    if not math.isnan(l): return l
    if not math.isnan(a): return a
    if not math.isnan(b): return b
    if not math.isnan(pc): return pc
    return math.nan


# --------------------------- Core logic ---------------------------------
def pick_by_delta(snaps: List[dict], target_delta: float) -> Optional[dict]:
    """Pick the contract whose |delta| is closest to target_delta."""
    best, best_dist = None, float("inf")
    for s in snaps:
        d = get_delta(s)
        if d is None:
            continue
        dist = abs(abs(d) - target_delta)
        if dist < best_dist:
            best, best_dist = s, dist
    return best


def build_row_for_symbol(symbol: str, shares: int, opt_type: str, expiration: str, underlying_price: float) -> dict:
    """Wide row: symbol, UnderlyingPrice, Shares, then for each delta => {S,P,N}."""
    snaps = fetch_chain_snapshot(symbol, expiration, opt_type)
    row = {"symbol": symbol, "UnderlyingPrice": underlying_price, "Shares": shares}
    for d in TARGET_DELTAS:
        chosen = pick_by_delta(snaps, d)
        colS, colP, colN = f"{d:.2f}S", f"{d:.2f}P", f"{d:.2f}N"
        if chosen is None:
            row[colS] = ""
            row[colP] = ""
            row[colN] = ""
            continue
        strike = get_details_field(chosen, "strike_price")
        prem = mid_price_from_snapshot(chosen)
        row[colS] = strike if strike is not None else ""
        row[colP] = prem if not (isinstance(prem, float) and math.isnan(prem)) else ""
        row[colN] = "" if (row[colP] == "" or shares is None) else shares * prem
    return row


# ------------------------------ Main ------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Premiums table for next Friday with S/P/N columns per delta.")
    parser.add_argument("--type", choices=["call", "put"], required=True, help="Option type to fetch.")
    args = parser.parse_args()

    require_key()
    pairs = load_symbols_with_shares(SYMBOLS_FILE)
    expiration = next_friday_str()
    print(f"[INFO] Using expiration: {expiration}")
    print(f"[INFO] Loaded {len(pairs)} symbols from {SYMBOLS_FILE}")

    symbols_only = [s for s, _ in pairs]
    price_map = get_underlying_prices(symbols_only)

    rows = []
    for sym, shares in pairs:
        upx = price_map.get(sym, math.nan)
        print(f"[INFO] Processing {sym} (shares={shares})  UnderlyingPrice={upx}")
        try:
            rows.append(build_row_for_symbol(sym, shares, args.type, expiration, upx))
        except requests.HTTPError as e:
            print(f"[ERROR] {sym}: {e}")
        except Exception as e:
            print(f"[ERROR] {sym}: {e}")

    if not rows:
        print("[ERROR] No data collected.")
        sys.exit(2)

    # Write premiums.csv (wide)
    df = pd.DataFrame(rows)
    fixed = ["symbol", "UnderlyingPrice", "Shares"]
    delta_cols = []
    for d in TARGET_DELTAS:
        delta_cols.extend([f"{d:.2f}S", f"{d:.2f}P", f"{d:.2f}N"])
    cols = [c for c in (fixed + delta_cols) if c in df.columns]
    df = df.reindex(columns=cols)
    df.to_csv(PREMIUMS_FILE, index=False)
    print(f"[INFO] Wrote pivot to {PREMIUMS_FILE}")

    # after writing premiums.csv
    PREMIUMS_JSON = "premiums-ui/public/premiums.json"  # if bundling with the app’s /public folder
    df.to_json(PREMIUMS_JSON, orient="records")
    print(f"[INFO] Wrote JSON to {PREMIUMS_JSON}")

    # Write details.csv (long)
    detail_rows = []
    for r in rows:
        sym = r["symbol"]; px = r["UnderlyingPrice"]; sh = r["Shares"]
        for d in TARGET_DELTAS:
            S, P, N = r.get(f"{d:.2f}S"), r.get(f"{d:.2f}P"), r.get(f"{d:.2f}N")
            detail_rows.append({
                "symbol": sym, "UnderlyingPrice": px, "Shares": sh,
                "target_delta": float(f"{d:.2f}"),
                "strike": S, "premium": P, "shares_times_premium": N
            })
    pd.DataFrame(detail_rows).to_csv(DETAILS_FILE, index=False)
    print(f"[INFO] Wrote details to {DETAILS_FILE}")


# === REPLACE your current bottom guard with this ENTIRE block ===
if __name__ == "__main__":
    import argparse, json, sys, csv, io, contextlib
    from pathlib import Path

    def _num(v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except Exception:
            try:
                s = str(v).replace("$", "").replace(",", "")
                return float(s)
            except Exception:
                return None

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--emit-json", action="store_true")
    # Adjust these if your script writes elsewhere:
    parser.add_argument("--json-out", default=str(Path("premiums-ui") / "public" / "premiums.json"))
    parser.add_argument("--csv-out", default="premiums.csv")
    # If your main() reads its own args, leave them in sys.argv for main()
    args, _ = parser.parse_known_args()

    if not args.emit_json:
        # Normal behavior (unchanged)
        sys.exit(main())

    # --emit-json path: run main() first but silence its stdout so we can emit clean JSON
    stdout_sink = io.StringIO()
    with contextlib.redirect_stdout(stdout_sink):
        # If main() returns a code, respect it but keep going to try emitting JSON
        try:
            rc = main()
            if isinstance(rc, int) and rc not in (0, None):
                # continue anyway — we’ll try to emit whatever artifacts exist
                pass
        except SystemExit:
            # Allow main() to sys.exit(); keep going to emit JSON
            pass
        except Exception:
            # Swallow here; we’ll fall back to CSV/empty JSON
            pass

    json_path = Path(args.json_out)
    csv_path = Path(args.csv_out)

    # 1) Prefer the JSON your script already wrote
    if json_path.is_file():
        sys.stdout.write(json_path.read_text(encoding="utf-8"))
        sys.exit(0)

    # 2) Else convert CSV (wide format) to JSON list[dict] expected by the UI
    if csv_path.is_file():
        deltas = [f"{i*0.05:.2f}" for i in range(1, 11)]  # 0.05..0.50
        rows = []
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = {
                    "symbol": row.get("symbol") or row.get("Symbol") or row.get("SYMBOL"),
                    "UnderlyingPrice": _num(row.get("UnderlyingPrice") or row.get("Underlying") or row.get("Price")),
                    "Shares": _num(row.get("Shares") or row.get("Qty") or row.get("Quantity")),
                }
                for dk in deltas:
                    for suf in ("S", "P", "N"):
                        key = f"{dk}{suf}"
                        if key in row:
                            rec[key] = _num(row.get(key))
                rows.append(rec)
        sys.stdout.write(json.dumps(rows, ensure_ascii=False))
        sys.exit(0)

    # 3) Nothing to emit
    sys.stdout.write("[]")
    sys.exit(0)
# === END replacement ===

