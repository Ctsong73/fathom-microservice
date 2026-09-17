#!/usr/bin/env python3
"""
Build the mining stocks universe (US + Canada).

US stocks:      pulled from the Nasdaq screener API (Basic Materials sector),
                filtered to mining-related names.
Canada stocks:  curated list of TSX (.TO) / TSXV (.V) miners grouped by commodity.

Every symbol is validated against Yahoo's chart API before being written to
data/mining_stocks.csv. Invalid/dead symbols are dropped automatically.

Usage:
    python scripts/build_universe.py            # rebuild + validate
    python scripts/build_universe.py --no-check # skip Yahoo validation
"""

import argparse
import csv
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

NASDAQ_API = "https://api.nasdaq.com/api/screener/stocks"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

OUTPUT = "data/mining_stocks.csv"

# Keywords that mark a Basic-Materials name as mining-related.
INCLUDE_WORDS = [
    "gold", "silver", "copper", "uranium", "lithium", "nickel", "zinc",
    "platinum", "palladium", "cobalt", "tin", "lead", "molybdenum",
    "tungsten", "vanadium", "potash", "rare earth", "metals", "metal",
    "mining", "mine", "minerals", "mineral", "mines", "coal",
    "iron ore", "precious", "aluminum", "aluminium", "titanium", "anthracite",
    "exploration", "resources", "resource",
]

# Words that disqualify a Basic-Materials name (non-mining companies).
EXCLUDE_WORDS = [
    "chemical", "linde", "paint", "paper", "plastic", "packaging", "packag",
    "glass", "cork", "fertilizer", "nitrogen", "wood", "forest", "timber",
    "cement", "concrete", "aggregate", "asphalt", "steel", "adhesive",
    "specialty", "mountain", "holdings", "battery", "recycling", "food",
]

# Symbols that turned out to be warrants, SPACs or non-miners.
DROP_SYMBOLS = {"BGLWW", "CRMLW", "NAMMW", "MTAL", "MTX", "SUZ", "ER", "TFI.TO"}

# Infer a commodity sector from a company name (used for screener results).
SECTOR_BY_NAME = [
    ("rare earth", "Rare Earth"),
    ("uranium", "Uranium"),
    ("lithium", "Lithium"),
    ("coal", "Coal"),
    ("potash", "Potash"),
    ("cobalt", "Nickel / Cobalt"),
    ("nickel", "Nickel / Cobalt"),
    ("iron", "Iron / Steel Ore"),
    ("silver", "Silver"),
    ("copper", "Copper"),
    ("zinc", "Zinc"),
    ("gold", "Gold"),
    ("precious metal", "Gold"),
    ("metal", "Diversified"),
    ("resource", "Diversified"),
    ("mining", "Diversified"),
    ("mineral", "Diversified"),
]

# Curated Canadian (TSX/TSXV) miners. Format:
#   (symbol, name, exchange, country, sector)
CANADA = [
    # --- Gold producers / royalty ---
    ("ABX.TO", "Barrick Gold", "TSX", "Canada", "Gold"),
    ("AEM.TO", "Agnico Eagle Mines", "TSX", "Canada", "Gold"),
    ("K.TO", "Kinross Gold", "TSX", "Canada", "Gold"),
    ("BTO.TO", "B2Gold", "TSX", "Canada", "Gold"),
    ("AGI.TO", "Alamos Gold", "TSX", "Canada", "Gold"),
    ("CG.TO", "Centerra Gold", "TSX", "Canada", "Gold"),
    ("ELD.TO", "Eldorado Gold", "TSX", "Canada", "Gold"),
    ("EQX.TO", "Equinox Gold", "TSX", "Canada", "Gold"),
    ("OGC.TO", "OceanaGold", "TSX", "Canada", "Gold"),
    ("TXG.TO", "Torex Gold Resources", "TSX", "Canada", "Gold"),
    ("EDV.TO", "Endeavour Mining", "TSX", "Canada", "Gold"),
    ("LUG.TO", "Lundin Gold", "TSX", "Canada", "Gold"),
    ("IMG.TO", "IAMGOLD", "TSX", "Canada", "Gold"),
    ("NG.TO", "NovaGold Resources", "TSX", "Canada", "Gold"),
    ("OLA.TO", "Orla Mining", "TSX", "Canada", "Gold"),
    ("WDO.TO", "Wesdome Gold Mines", "TSX", "Canada", "Gold"),
    ("DPM.TO", "Dundee Precious Metals", "TSX", "Canada", "Gold"),
    ("KNT.TO", "K92 Mining", "TSX", "Canada", "Gold"),
    ("FNV.TO", "Franco-Nevada", "TSX", "Canada", "Gold"),
    ("WPM.TO", "Wheaton Precious Metals", "TSX", "Canada", "Gold"),
    ("ARTG.V", "Artemis Gold", "TSXV", "Canada", "Gold"),
    ("AOT.V", "Ascot Resources", "TSXV", "Canada", "Gold"),
    ("ORE.TO", "Orezone Gold", "TSX", "Canada", "Gold"),
    ("CXB.TO", "Calibre Mining", "TSX", "Canada", "Gold"),
    ("VGCX.V", "Victoria Gold", "TSXV", "Canada", "Gold"),
    # --- Silver / precious metals ---
    ("PAAS.TO", "Pan American Silver", "TSX", "Canada", "Silver"),
    ("FVI.TO", "Fortuna Mining", "TSX", "Canada", "Silver"),
    ("MAG.TO", "MAG Silver", "TSX", "Canada", "Silver"),
    ("FR.TO", "First Majestic Silver", "TSX", "Canada", "Silver"),
    ("EDR.TO", "Endeavour Silver", "TSX", "Canada", "Silver"),
    ("DSV.TO", "Discovery Silver", "TSX", "Canada", "Silver"),
    # --- Copper / base metals ---
    ("HBM.TO", "Hudbay Minerals", "TSX", "Canada", "Copper"),
    ("FM.TO", "First Quantum Minerals", "TSX", "Canada", "Copper"),
    ("IVN.TO", "Ivanhoe Mines", "TSX", "Canada", "Copper"),
    ("TKO.TO", "Taseko Mines", "TSX", "Canada", "Copper"),
    ("ERO.TO", "Ero Copper", "TSX", "Canada", "Copper"),
    ("LUN.TO", "Lundin Mining", "TSX", "Canada", "Copper"),
    ("NCU.TO", "Nevada Copper", "TSX", "Canada", "Copper"),
    ("CS.TO", "Capstone Copper", "TSX", "Canada", "Copper"),
    # --- Uranium ---
    ("CCO.TO", "Cameco", "TSX", "Canada", "Uranium"),
    ("DML.TO", "Denison Mines", "TSX", "Canada", "Uranium"),
    ("FCU.TO", "Fission Uranium", "TSX", "Canada", "Uranium"),
    ("ISO.TO", "IsoEnergy", "TSX", "Canada", "Uranium"),
    ("GLO.TO", "Global Atomic", "TSX", "Canada", "Uranium"),
    # --- Lithium ---
    ("LAC", "Lithium Americas", "NYSE", "Canada", "Lithium"),
    # --- Iron ore ---
    ("CIA.TO", "Champion Iron", "TSX", "Canada", "Iron / Steel Ore"),
    # --- Nickel / cobalt / other ---
    ("S.TO", "Sherritt International", "TSX", "Canada", "Nickel / Cobalt"),
    # --- Potash / fertilizer minerals ---
    ("NTR.TO", "Nutrien", "TSX", "Canada", "Potash"),
    # --- Zinc / lead ---
    ("NEXA", "Nexa Resources", "NYSE", "Peru", "Zinc"),
    ("TFI.TO", "Triumph Gold", "TSX", "Canada", "Zinc / Lead"),
]

# Well-known US-/NYSE-listed miners added explicitly (beyond the Basic
# Materials screen, e.g. ADRs of foreign miners and royalty/diversified names).
US_EXTRA = [
    ("NEM", "Newmont", "NYSE", "USA", "Gold"),
    ("GOLD", "Barrick Gold (ADR)", "NYSE", "Canada", "Gold"),
    ("BTG", "B2Gold (ADR)", "NYSE", "Canada", "Gold"),
    ("AU", "AngloGold Ashanti", "NYSE", "South Africa", "Gold"),
    ("GFI", "Gold Fields", "NYSE", "South Africa", "Gold"),
    ("HMY", "Harmony Gold", "NYSE", "South Africa", "Gold"),
    ("RGLD", "Royal Gold", "NASDAQ", "USA", "Gold"),
    ("HL", "Hecla Mining", "NYSE", "USA", "Silver"),
    ("CDE", "Coeur Mining", "NYSE", "USA", "Silver"),
    ("AG", "First Majestic Silver", "NYSE", "Canada", "Silver"),
    ("EXK", "Endeavour Silver", "NYSE", "Canada", "Silver"),
    ("PAAS", "Pan American Silver", "NASDAQ", "Canada", "Silver"),
    ("SVM", "Silvercorp Metals", "NYSE", "Canada", "Silver"),
    ("SSRM", "SSR Mining", "NASDAQ", "Canada", "Gold"),
    ("FCX", "Freeport-McMoRan", "NYSE", "USA", "Copper"),
    ("TECK", "Teck Resources", "NYSE", "Canada", "Copper"),
    ("CCJ", "Cameco (ADR)", "NYSE", "Canada", "Uranium"),
    ("NXE", "NexGen Energy", "NYSE", "Canada", "Uranium"),
    ("UUUU", "Energy Fuels", "NYSE", "USA", "Uranium"),
    ("URG", "Ur-Energy", "NYSE", "USA", "Uranium"),
    ("ALB", "Albemarle", "NYSE", "USA", "Lithium"),
    ("SQM", "Sociedad Quimica y Minera", "NYSE", "Chile", "Lithium"),
    ("LAC", "Lithium Americas", "NYSE", "Canada", "Lithium"),
    ("VALE", "Vale", "NYSE", "Brazil", "Iron / Steel Ore"),
    ("RIO", "Rio Tinto", "NYSE", "UK", "Diversified"),
    ("BHP", "BHP Group", "NYSE", "Australia", "Diversified"),
    ("MP", "MP Materials", "NYSE", "USA", "Rare Earth"),
    ("AA", "Alcoa", "NYSE", "USA", "Aluminum"),
    ("SCCO", "Southern Copper", "NYSE", "Mexico", "Copper"),
    ("ARCH", "Arch Resources", "NYSE", "USA", "Coal"),
    ("BTU", "Peabody Energy", "NYSE", "USA", "Coal"),
    ("HCC", "Warrior Met Coal", "NYSE", "USA", "Coal"),
    ("CEIX", "CONSOL Energy", "NYSE", "USA", "Coal"),
    ("HNRG", "Hallador Energy", "NASDAQ", "USA", "Coal"),
    ("CLF", "Cleveland-Cliffs", "NYSE", "USA", "Iron / Steel Ore"),
    ("MOS", "Mosaic", "NYSE", "USA", "Potash"),
    ("GORO", "Gold Resource", "NYSE", "USA", "Gold"),
    ("VGZ", "Vista Gold", "NYSE", "USA", "Gold"),
    ("MUX", "McEwen Mining", "NYSE", "USA", "Gold"),
    ("ASM", "Avino Silver & Gold", "NYSE", "Canada", "Silver"),
    ("AUMN", "Golden Minerals", "NYSE", "USA", "Gold"),
    ("ER", "Eastmain Resources", "NYSE", "Canada", "Gold"),
    ("IAG", "IAMGOLD", "NYSE", "Canada", "Gold"),
    ("SLS", "Solaris Resources", "NYSE", "Canada", "Copper"),
]


def fetch_us_basic_materials():
    """Pull every Basic Materials stock from the Nasdaq screener API."""
    stocks = {}
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json",
                            "Referer": "https://www.nasdaq.com/"})
    for exchange in ("NASDAQ", "NYSE"):
        offset = 0
        while True:
            resp = session.get(NASDAQ_API, params={
                "tableonly": "true", "limit": "100", "offset": offset,
                "exchange": exchange, "sector": "Basic Materials",
            }, timeout=30)
            resp.raise_for_status()
            payload = resp.json().get("data") or {}
            rows = (payload.get("table") or {}).get("rows") or []
            for r in rows:
                if r["symbol"] not in stocks:
                    stocks[r["symbol"]] = (r["name"], exchange)
            total = int(payload.get("totalrecords") or 0)
            offset += len(rows)
            if offset >= total or not rows:
                break
    return stocks


def is_mining_name(name):
    low = name.lower()
    if any(w in low for w in EXCLUDE_WORDS):
        return False
    return any(w in low for w in INCLUDE_WORDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-check", action="store_true",
                    help="skip Yahoo symbol validation")
    args = ap.parse_args()

    print("1. Pulling US Basic Materials from Nasdaq...")
    us = fetch_us_basic_materials()
    by_symbol = {}
    for symbol, (name, exchange) in us.items():
        if not is_mining_name(name) or symbol in DROP_SYMBOLS:
            continue
        country = "Canada" if "canada" in name.lower() else "USA"
        sector = next((s for kw, s in SECTOR_BY_NAME if kw in name.lower()),
                      "Diversified")
        by_symbol[symbol] = (symbol, name, exchange, country, sector)
    print(f"   -> {len(by_symbol)} mining candidates after filter")

    print("2. Adding curated Canadian + US extra miners...")
    added = 0
    for row in CANADA + US_EXTRA:
        sym = row[0]
        if sym in DROP_SYMBOLS:
            continue
        if sym not in by_symbol:
            by_symbol[sym] = row
            added += 1
        else:
            # A curated row is richer (proper country/sector), use it.
            if sym in {r[0] for r in US_EXTRA} or sym.endswith((".TO", ".V")):
                by_symbol[sym] = row
    print(f"   -> {added} curated entries added")
    print(f"   -> dropped junk symbols")

    rows = sorted(by_symbol.values(),
                  key=lambda r: (r[3], r[4], r[0]))
    print(f"   -> universe size: {len(rows)}")

    if not args.no_check:
        print("3. Validating symbols against Yahoo chart API...")

        def check(row):
            sym = row[0]
            try:
                r = requests.get(YAHOO_CHART.format(symbol=sym),
                                 params={"range": "5d", "interval": "1d"},
                                 headers={"User-Agent": UA}, timeout=15)
                return (r.status_code == 200
                        and (r.json().get("chart") or {}).get("result"))
            except Exception:
                return False

        valid = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(check, r): r for r in rows}
            for fut in as_completed(futs):
                row = futs[fut]
                ok = fut.result()
                print(f"   {'OK ' if ok else 'BAD'} {row[0]:12s} {row[1]}")
                if ok:
                    valid.append(row)
        rows = sorted(valid, key=lambda r: (r[3], r[4], r[0]))
        print(f"   -> {len(rows)} symbols validated")

    print(f"4. Writing {OUTPUT}...")
    with open(OUTPUT, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "name", "exchange", "country", "sector"])
        writer.writerows(rows)
    print(f"   -> done ({len(rows)} stocks, "
          f"generated {datetime.now():%Y-%m-%d %H:%M})")


if __name__ == "__main__":
    main()