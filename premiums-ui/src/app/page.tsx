"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";

/**
 * Options Premiums UI (5% delta steps)
 * - Reads API /api/premiums at runtime (no import)
 * - Sticky first 3 columns (Symbol, Underlying, Shares)
 * - Grouped headers per delta with STR / PRE / NET subcolumns
 * - Totals row (sum of NET per delta) — now placed in <tbody> so it does NOT stick under headers
 * - Pastel theme with high-contrast text
 * - Auto-scroll so Δ 0.15 is the first visible group
 */

type PremiumRow = {
  symbol: string;
  UnderlyingPrice: number | string;
  Shares: number | string;
  [k: string]: any;
};

// Use 5% steps: 0.05, 0.10, ..., 0.50
const DELTAS: number[] = Array.from({ length: 10 }, (_, i) => (i + 1) * 0.05);

// Sticky column widths (px)
const W_SYMBOL = 86; // 10% narrower than earlier
const W_UNDER = 52;  // 15% wider than compact
const W_SHARES = 39; // compact
const STICKY_LEFT_1 = 0;
const STICKY_LEFT_2 = W_SYMBOL;
const STICKY_LEFT_3 = W_SYMBOL + W_UNDER;
const STICKY_TOTAL = W_SYMBOL + W_UNDER + W_SHARES;

const fmt = (v: any) => {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  if (Math.abs(n) >= 1000 && Number.isInteger(n)) return n.toLocaleString();
  if (Math.abs(n) >= 100) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
};

const money = (v: any) => {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return "$" + n.toLocaleString(undefined, { maximumFractionDigits: 2 });
};

export default function Page() {
  const [rows, setRows] = useState<PremiumRow[]>([]);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<string>("symbol");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Fetch data from Functions API (runtime)
  useEffect(() => {
    fetch("/api/premiums", { cache: "no-store" })
      .then((r) => r.json())
      .then((data: PremiumRow[]) => setRows(Array.isArray(data) ? data : []))
      .catch(() => setRows([]));
  }, []);

  // Auto-scroll so Δ 0.15 is first visible
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || rows.length === 0) return;
    const target = el.querySelector('th[data-delta="0.15"]') as HTMLElement | null;
    if (!target) return;
    requestAnimationFrame(() => {
      const x = Math.max(0, target.offsetLeft - STICKY_TOTAL - 8);
      el.scrollTo({ left: x, behavior: "auto" });
    });
  }, [rows.length]);

  // Filter + Sort
  const filteredSorted = useMemo(() => {
    const q = query.trim().toLowerCase();
    let out = rows;
    if (q) out = rows.filter((r) => r.symbol?.toLowerCase().includes(q));
    const sorted = [...out].sort((a, b) => {
      const av = a[sortKey as keyof PremiumRow];
      const bv = b[sortKey as keyof PremiumRow];
      const an = Number(av);
      const bn = Number(bv);
      const aComp = Number.isNaN(an) ? String(av) : an;
      const bComp = Number.isNaN(bn) ? String(bv) : bn;
      if (aComp < bComp) return sortDir === "asc" ? -1 : 1;
      if (aComp > bComp) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [rows, query, sortKey, sortDir]);

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  // Totals per delta (sum of NET across all rows)
  const netTotalsByDelta = useMemo(() => {
    const totals: Record<string, number> = {};
    DELTAS.forEach((d) => (totals[d.toFixed(2)] = 0));
    for (const r of filteredSorted) {
      for (const d of DELTAS) {
        const key = `${d.toFixed(2)}N` as keyof PremiumRow;
        const val = Number(r[key] ?? 0);
        if (!Number.isNaN(val)) totals[d.toFixed(2)] += val;
      }
    }
    return totals;
  }, [filteredSorted]);

  // Pastel theme with high-contrast text
  const stickyHeaderClass = "bg-blue-50 text-gray-900";
  const stickyBodyClass = "bg-blue-50/95 text-gray-900";
  const groupHeaderBg = "bg-yellow-100 text-gray-900"; // Δ headers
  const spnHeaderBg = "bg-yellow-200 text-gray-900";   // STR / PRE / NET row
  const groupBg = (idx: number) => (idx % 2 === 0 ? "bg-pink-50" : "bg-slate-50");

  return (
    <div className="min-h-screen w-full bg-slate-50">
      <div className="mx-auto max-w-[1400px] p-6">
        <div className="mb-6 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Options Premiums (Next Friday)</h1>
            <p className="text-sm text-slate-600">Grouped by 5% delta with STR / PRE / NET subcolumns.</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              className="border rounded-xl px-3 py-2 text-sm outline-none focus:ring focus:ring-slate-300 bg-white"
              placeholder="Filter by symbol…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <span className="text-xs px-2 py-0.5 rounded-full border bg-white">Rows: {filteredSorted.length}</span>
          </div>
        </div>

        <div ref={scrollRef} className="overflow-auto rounded-2xl shadow-sm border bg-white">
          <table className="min-w-[900px] w-full text-sm border-separate border-spacing-0">
            <thead>
              {/* Group headers (Δ 0.xx) */}
              <tr className="sticky top-0 z-30">
                <th
                  onClick={() => toggleSort("symbol")}
                  className={`sticky ${stickyHeaderClass} p-3 text-left font-medium border-b border-r border-slate-300`}
                  style={{ left: STICKY_LEFT_1, minWidth: W_SYMBOL, width: W_SYMBOL }}
                >
                  Symbol
                </th>
                <th
                  onClick={() => toggleSort("UnderlyingPrice")}
                  className={`sticky ${stickyHeaderClass} p-3 text-left font-medium border-b border-r border-slate-300 cursor-pointer`}
                  style={{ left: STICKY_LEFT_2, minWidth: W_UNDER, width: W_UNDER }}
                >
                  Underlying
                </th>
                <th
                  onClick={() => toggleSort("Shares")}
                  className={`sticky ${stickyHeaderClass} p-3 text-right font-medium border-b border-slate-300 cursor-pointer`}
                  style={{ left: STICKY_LEFT_3, minWidth: W_SHARES, width: W_SHARES }}
                >
                  Shares
                </th>
                {DELTAS.map((d) => (
                  <th
                    key={`g-${d}`}
                    data-delta={d.toFixed(2)}
                    className={`text-center font-semibold ${groupHeaderBg} border-b border-slate-300 border-l-2 border-r-2`}
                    colSpan={3}
                    title={`Target Δ ${d.toFixed(2)}`}
                  >
                    Δ {d.toFixed(2)}
                  </th>
                ))}
              </tr>

              {/* STR / PRE / NET labels */}
              <tr className="sticky top-[41px] z-20">
                <th className={`sticky ${stickyHeaderClass} p-2 text-left border-b border-r border-slate-300`} style={{ left: STICKY_LEFT_1, width: W_SYMBOL }}></th>
                <th className={`sticky ${stickyHeaderClass} p-2 text-left border-b border-r border-slate-300`} style={{ left: STICKY_LEFT_2, width: W_UNDER }}></th>
                <th className={`sticky ${stickyHeaderClass} p-2 text-right border-b border-r border-slate-300`} style={{ left: STICKY_LEFT_3, width: W_SHARES }}></th>
                {DELTAS.map((_, idx) => (
                  <React.Fragment key={`sg-${idx}`}>
                    <th className={`p-2 text-center font-normal ${spnHeaderBg} border-b border-slate-300 border-l-2 border-r`}>STR</th>
                    <th className={`p-2 text-center font-normal ${spnHeaderBg} border-b border-slate-300 border-r`}>PRE</th>
                    <th className={`p-2 text-center font-normal ${spnHeaderBg} border-b border-slate-300 border-r-2`}>NET</th>
                  </React.Fragment>
                ))}
              </tr>
            </thead>

            <tbody>
              {/* Totals row moved to tbody so it scrolls with content (no sticky top) */}
              <tr className="bg-gray-100 text-xs font-semibold text-gray-900 border-b border-slate-300">
                <td
                  className={`sticky p-2 text-left border-r border-slate-300`}
                  style={{ left: STICKY_LEFT_1, width: W_SYMBOL }}
                >
                  Totals
                </td>
                <td
                  className={`sticky p-2 text-left border-r border-slate-300`}
                  style={{ left: STICKY_LEFT_2, width: W_UNDER }}
                />
                <td
                  className={`sticky p-2 text-right border-r border-slate-300`}
                  style={{ left: STICKY_LEFT_3, width: W_SHARES }}
                />
                {DELTAS.map((d) => (
                  <React.Fragment key={`tot-${d.toFixed(2)}`}>
                    <td className="p-2 text-center border-r border-slate-300" />
                    <td className="p-2 text-center border-r border-slate-300" />
                    <td className="p-2 text-right border-r-2 border-slate-400">
                      {money(netTotalsByDelta[d.toFixed(2)] ?? 0)}
                    </td>
                  </React.Fragment>
                ))}
              </tr>

              {filteredSorted.map((r, i) => (
                <motion.tr
                  key={r.symbol + i}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.005 }}
                  className="hover:bg-slate-50"
                >
                  <td
                    className={`sticky ${stickyBodyClass} p-2 border-b border-r border-slate-200 font-medium`}
                    style={{ left: STICKY_LEFT_1, minWidth: W_SYMBOL, width: W_SYMBOL }}
                  >
                    {r.symbol}
                  </td>
                  <td
                    className={`sticky ${stickyBodyClass} p-2 border-b border-r border-slate-200 text-left`}
                    style={{ left: STICKY_LEFT_2, minWidth: W_UNDER, width: W_UNDER }}
                  >
                    {fmt(r.UnderlyingPrice)}
                  </td>
                  <td
                    className={`sticky ${stickyBodyClass} p-2 border-b border-r border-slate-200 text-right`}
                    style={{ left: STICKY_LEFT_3, minWidth: W_SHARES, width: W_SHARES }}
                  >
                    {fmt(r.Shares)}
                  </td>

                  {DELTAS.map((d, idx) => {
                    const S = r[`${d.toFixed(2)}S`];
                    const P = r[`${d.toFixed(2)}P`];
                    const N = r[`${d.toFixed(2)}N`];
                    const cellBg = groupBg(idx);
                    return (
                      <React.Fragment key={`${r.symbol}-${d}`}>
                        <td className={`p-2 text-right text-gray-900 ${cellBg} border-b border-slate-200 border-l-2 border-r`}>{money(S)}</td>
                        <td className={`p-2 text-right text-gray-900 ${cellBg} border-b border-slate-200 border-r`}>{fmt(P)}</td>
                        <td className={`p-2 text-right font-semibold text-gray-900 ${cellBg} border-b border-slate-200 border-r-2`}>{money(N)}</td>
                      </React.Fragment>
                    );
                  })}
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
