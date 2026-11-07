"""Market data loading for index F&O research.

Raw sources (fetched by ``scripts/fetch_research_data.sh`` into ``backend/data/raw``):
* NIFTY 50 1-minute candles (technovusin/nifty50-historical-data, MIT)
* NIFTY BANK 1-minute candles (sandeepkapri/BankNifty-Data, MIT)
* India VIX daily OHLC (Yahoo-derived, via Rithvik-Rajesh/dynamic-portfolio-allocation)

Everything is converted into a per-day minute grid of 375 bars (09:15–15:29 IST).
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BARS_PER_DAY = 375  # 09:15 .. 15:29
MAX_MISSING_BARS = 15

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    minute = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    df = df[(minute >= 9 * 60 + 15) & (minute <= 15 * 60 + 29)]
    df = df.drop_duplicates("ts").sort_values("ts")
    # Repair inconsistent bars (high/low must bracket open/close).
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    return df.reset_index(drop=True)


def load_nifty(raw: Path = RAW) -> pd.DataFrame:
    files = sorted(glob.glob(str(raw / "nifty50" / "1min" / "*" / "*.csv")))
    parts = [pd.read_csv(f, usecols=["Timestamp", "Open", "High", "Low", "Close"]) for f in files]
    df = pd.concat(parts, ignore_index=True)
    df.columns = ["ts", "open", "high", "low", "close"]
    df["ts"] = pd.to_datetime(df["ts"])
    return _clean(df)


def load_banknifty(raw: Path = RAW) -> pd.DataFrame:
    df = pd.read_csv(raw / "banknifty" / "bank-nifty-1m-data.csv")
    df["ts"] = pd.to_datetime(df["Date"] + " " + df["Time"], format="%d-%m-%Y %H:%M:%S")
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
    return _clean(df[["ts", "open", "high", "low", "close"]])


def load_vix(raw: Path = RAW) -> pd.DataFrame:
    df = pd.read_csv(raw / "indiavix" / "vix.csv", parse_dates=["Date"])
    df = df.rename(columns={"Date": "date", "Open": "open", "Close": "close"})[
        ["date", "open", "close"]
    ]
    df["date"] = df["date"].dt.date
    # Yahoo India VIX has occasional bad prints; clamp to the historically possible range.
    for c in ("open", "close"):
        df[c] = df[c].clip(8, 90)
    return df.drop_duplicates("date").set_index("date").sort_index()


@dataclass
class DayBars:
    day: date
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    missing: int


def to_days(df: pd.DataFrame) -> dict[date, DayBars]:
    """Reindex each session onto the 375-minute grid (forward-filling small gaps)."""
    out: dict[date, DayBars] = {}
    df = df.copy()
    df["day"] = df["ts"].dt.date
    df["i"] = (df["ts"].dt.hour * 60 + df["ts"].dt.minute) - (9 * 60 + 15)
    for day, g in df.groupby("day", sort=True):
        idx = g["i"].to_numpy()
        missing = BARS_PER_DAY - len(idx)
        if missing > MAX_MISSING_BARS or idx[0] > 5:
            continue  # bad / partial session (e.g. data gap, special session)
        arr = {}
        for c in ("open", "high", "low", "close"):
            a = np.full(BARS_PER_DAY, np.nan)
            a[idx] = g[c].to_numpy()
            arr[c] = a
        # Forward fill gaps; a gap bar is flat at the previous close.
        close = pd.Series(arr["close"]).ffill().bfill().to_numpy()
        for c in ("open", "high", "low"):
            a = arr[c]
            arr[c] = np.where(np.isnan(a), close, a)
        out[day] = DayBars(day, arr["open"], arr["high"], arr["low"], close, max(missing, 0))
    return out


def load_index_days(index: str, start: date, end: date) -> dict[date, DayBars]:
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{index}_1min.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
    else:
        df = load_nifty() if index == "NIFTY" else load_banknifty()
        df.to_parquet(cache, index=False)
    df = df[(df["ts"].dt.date >= start) & (df["ts"].dt.date <= end)]
    return to_days(df)
