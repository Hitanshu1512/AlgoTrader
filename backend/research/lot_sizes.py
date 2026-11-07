"""Derive the actual exchange lot size of every NIFTY / BANKNIFTY contract from bhavcopies.

* UDiFF files (Jul 2024 →) carry the lot size directly (``NewBrdLotQty``).
* Legacy files (→ Jul 2024) do not, so lot = traded value / (contracts × price), computed
  from index futures, whose value field is unambiguous (price × quantity).
Samples three files per month. Output: data/cache/lot_sizes.csv (symbol, expiry, lot).
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1] / "data" / "raw" / "fnobank"
OUT = Path(__file__).resolve().parents[1] / "data" / "cache" / "lot_sizes.csv"


def read(z: Path) -> pd.DataFrame:
    with zipfile.ZipFile(z) as f:
        name = next(n for n in f.namelist() if n.lower().endswith(".csv"))
        with f.open(name) as fh:
            df = pd.read_csv(fh, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    return df


def main() -> None:
    files = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", "HEAD", "data/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    by_month: dict[str, list[str]] = {}
    for f in files:
        if f.endswith(".zip") and "2020/04" <= f[5:12] <= "2026/04":
            by_month.setdefault(f[5:12], []).append(f)
    rows = []
    for _m, fs in sorted(by_month.items()):
        fs = sorted(fs)
        pick = sorted({fs[0], fs[len(fs) // 2], fs[-1]})
        subprocess.run(["git", "-C", str(REPO), "checkout", "-q", "HEAD", "--", *pick], check=True)
        for f in pick:
            df = read(REPO / f)
            if "TckrSymb" in df.columns:
                sub = df[
                    df["FinInstrmTp"].isin(["IDO", "IDF"])
                    & df["TckrSymb"].isin(["NIFTY", "BANKNIFTY"])
                ]
                for (sym, e), g in sub.groupby(["TckrSymb", "XpryDt"]):
                    rows.append(
                        (sym, pd.to_datetime(e).date(), int(g["NewBrdLotQty"].mode()[0]), "udiff")
                    )
            else:
                fut = df[
                    (df["INSTRUMENT"] == "FUTIDX")
                    & df["SYMBOL"].isin(["NIFTY", "BANKNIFTY"])
                    & (df["CONTRACTS"] > 0)
                ]
                for r in fut.itertuples():
                    px = np.mean([r.OPEN, r.HIGH, r.LOW, r.CLOSE])
                    lot = r.VAL_INLAKH * 1e5 / (r.CONTRACTS * px)
                    rows.append(
                        (
                            r.SYMBOL,
                            pd.to_datetime(r.EXPIRY_DT, format="%d-%b-%Y").date(),
                            int(round(lot / 5) * 5),
                            "legacy_fut",
                        )
                    )
            (REPO / f).unlink()
    out = pd.DataFrame(rows, columns=["symbol", "expiry", "lot", "source"])
    out = (
        out.groupby(["symbol", "expiry"])
        .agg(lot=("lot", lambda s: int(s.mode()[0])), source=("source", "first"))
        .reset_index()
    )
    OUT.write_text(out.to_csv(index=False))
    for sym, g in out.groupby("symbol"):
        g = g.sort_values("expiry")
        changes = g[g["lot"] != g["lot"].shift()]
        print(sym, "lot changes (by contract expiry):")
        for r in changes.itertuples():
            print(f"   from expiry {r.expiry}: {r.lot} ({r.source})")


if __name__ == "__main__":
    main()
