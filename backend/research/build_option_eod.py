"""Extract NIFTY / BANKNIFTY index option + futures EOD rows from NSE F&O bhavcopies.

Reads the partial clone at backend/data/raw/fnobank (see scripts/fetch_research_data.sh),
checks out one month at a time, keeps only the rows we need and deletes the raw ZIPs.
Output: backend/data/cache/option_eod.parquet

Handles both NSE formats: legacy (to 5 Jul 2024) and UDiFF (from 8 Jul 2024).
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1] / "data"
REPO = ROOT / "raw" / "fnobank"
OUT = ROOT / "cache" / "option_eod.parquet"
SYMBOLS = {"NIFTY", "BANKNIFTY"}
COLS = [
    "date",
    "symbol",
    "inst",
    "expiry",
    "strike",
    "opt",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "contracts",
    "oi",
    "underlying",
]


def _legacy(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["INSTRUMENT"].isin(["OPTIDX", "FUTIDX"]) & df["SYMBOL"].isin(SYMBOLS)]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["TIMESTAMP"], format="%d-%b-%Y").dt.date,
            "symbol": df["SYMBOL"],
            "inst": df["INSTRUMENT"].map({"OPTIDX": "OPT", "FUTIDX": "FUT"}),
            "expiry": pd.to_datetime(df["EXPIRY_DT"], format="%d-%b-%Y").dt.date,
            "strike": df["STRIKE_PR"].astype(float),
            "opt": df["OPTION_TYP"].replace("XX", ""),
            "open": df["OPEN"],
            "high": df["HIGH"],
            "low": df["LOW"],
            "close": df["CLOSE"],
            "settle": df["SETTLE_PR"],
            "contracts": df["CONTRACTS"],
            "oi": df["OPEN_INT"],
            "underlying": float("nan"),
        }
    )


def _udiff(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["FinInstrmTp"].isin(["IDO", "IDF"]) & df["TckrSymb"].isin(SYMBOLS)]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["TradDt"]).dt.date,
            "symbol": df["TckrSymb"],
            "inst": df["FinInstrmTp"].map({"IDO": "OPT", "IDF": "FUT"}),
            "expiry": pd.to_datetime(df["XpryDt"]).dt.date,
            "strike": pd.to_numeric(df["StrkPric"], errors="coerce").fillna(0.0),
            "opt": df["OptnTp"].fillna(""),
            "open": df["OpnPric"],
            "high": df["HghPric"],
            "low": df["LwPric"],
            "close": df["ClsPric"],
            "settle": df["SttlmPric"],
            "contracts": df["TtlTradgVol"],
            "oi": df["OpnIntrst"],
            "underlying": df["UndrlygPric"],
        }
    )


def parse(zpath: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(name) as fh:
            df = pd.read_csv(fh, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    return _udiff(df) if "TckrSymb" in df.columns else _legacy(df)


def main(start: str = "2020-04", end: str = "2025-12") -> None:
    months = sorted(
        {
            p.split("/")[1] + "/" + p.split("/")[2]
            for p in subprocess.run(
                ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", "HEAD", "data/"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
            if p.count("/") == 3
        }
    )
    months = [m for m in months if start.replace("-", "/") <= m <= end.replace("-", "/")]
    frames: list[pd.DataFrame] = []
    if OUT.exists():
        done = pd.read_parquet(OUT)
        frames.append(done)
        have = {d.strftime("%Y/%m") for d in pd.to_datetime(done["date"])}
        months = [m for m in months if m not in have]
    for m in months:
        subprocess.run(
            ["git", "-C", str(REPO), "checkout", "-q", "HEAD", "--", f"data/{m}"], check=True
        )
        month_rows = []
        for z in sorted((REPO / "data" / m).glob("*.zip")):
            try:
                month_rows.append(parse(z))
            except Exception as exc:
                print(f"skip {z.name}: {exc}", file=sys.stderr)
            z.unlink()
        if month_rows:
            frames.append(pd.concat(month_rows, ignore_index=True))
        pd.concat(frames, ignore_index=True)[COLS].to_parquet(OUT, index=False)
        print(f"{m}: {sum(len(r) for r in month_rows)} rows", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
