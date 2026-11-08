"""Extract real NSE option prices (daily OHLC, volume, OI, lot size) from F&O bhavcopies.

v2 of ``build_option_eod``: adds FINNIFTY, the exchange lot size of every row, the
traded value (for liquidity checks) and data to the end of the archive (Nov 2026).
Liquid stock options are kept from Jul 2024 (UDiFF files carry their lot sizes).

* Legacy files (→ 5 Jul 2024) have no lot size: lot = traded value ÷ (contracts × price)
  of the index future of the same symbol and date (unambiguous for futures).
* UDiFF files (8 Jul 2024 →) carry ``NewBrdLotQty`` and the underlying price.

Output: backend/data/cache/option_eod_v2.parquet
Usage:  uv run python -m research.build_eod_v2 [YYYY-MM-start] [YYYY-MM-end]
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1] / "data"
REPO = ROOT / "raw" / "fnobank"
OUT = ROOT / "cache" / "option_eod_v2.parquet"
INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY"}
STOCKS = {"RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN", "INFY", "TCS", "AXISBANK", "BHARTIARTL"}
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
    "lot",
]


def _legacy(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["INSTRUMENT"].isin(["OPTIDX", "FUTIDX"]) & df["SYMBOL"].isin(INDICES)].copy()
    fut = df[(df["INSTRUMENT"] == "FUTIDX") & (df["CONTRACTS"] > 0)]
    px = fut[["OPEN", "HIGH", "LOW", "CLOSE"]].mean(axis=1)
    fut_lot = (fut["VAL_INLAKH"] * 1e5 / (fut["CONTRACTS"] * px)).round()
    lots = pd.DataFrame({"SYMBOL": fut["SYMBOL"], "EXPIRY_DT": fut["EXPIRY_DT"], "lot": fut_lot})
    by_exp = lots.groupby(["SYMBOL", "EXPIRY_DT"])["lot"].median()
    by_sym = lots.groupby("SYMBOL")["lot"].median()  # nearest-month dominates by volume

    def lot_of(r: pd.Series) -> float:
        v = by_exp.get((r["SYMBOL"], r["EXPIRY_DT"]))
        return (
            float(v) if v is not None and np.isfinite(v) else float(by_sym.get(r["SYMBOL"], np.nan))
        )

    keys = df[["SYMBOL", "EXPIRY_DT"]].drop_duplicates()
    keys["lot"] = keys.apply(lot_of, axis=1)
    df = df.merge(keys, on=["SYMBOL", "EXPIRY_DT"], how="left")
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
            "lot": df["lot"],
        }
    )


def _udiff(df: pd.DataFrame) -> pd.DataFrame:
    idx = df["FinInstrmTp"].isin(["IDO", "IDF"]) & df["TckrSymb"].isin(INDICES)
    stk = df["FinInstrmTp"].isin(["STO", "STF"]) & df["TckrSymb"].isin(STOCKS)
    df = df[idx | stk]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["TradDt"]).dt.date,
            "symbol": df["TckrSymb"],
            "inst": df["FinInstrmTp"].map({"IDO": "OPT", "IDF": "FUT", "STO": "OPT", "STF": "FUT"}),
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
            "lot": df["NewBrdLotQty"].astype(float),
        }
    )


def parse(zpath: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(name) as fh:
            df = pd.read_csv(fh, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    return _udiff(df) if "TckrSymb" in df.columns else _legacy(df)


def main(start: str = "2020-04", end: str = "2026-11") -> None:
    files = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", "HEAD", "data/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    months = sorted({f[5:12] for f in files if f.endswith(".zip")})
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
        rows = []
        for z in sorted((REPO / "data" / m).glob("*.zip")):
            try:
                rows.append(parse(z))
            except Exception as exc:
                print(f"skip {z.name}: {exc}", file=sys.stderr)
            z.unlink()
        if rows:
            frames.append(pd.concat(rows, ignore_index=True))
        pd.concat(frames, ignore_index=True)[COLS].to_parquet(OUT, index=False)
        print(f"{m}: {sum(len(r) for r in rows)} rows", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
