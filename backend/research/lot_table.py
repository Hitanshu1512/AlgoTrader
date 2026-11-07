"""Exact lot size per (trade date, symbol, option expiry) for the sampled months.

Legacy bhavcopies (→ Jul 2024): option VAL_INLAKH is notional = (strike + premium) × qty,
so lot = VAL_INLAKH·1e5 / (CONTRACTS · (strike + avg premium)).
UDiFF bhavcopies (Jul 2024 →): lot size is published per contract (NewBrdLotQty).
Output: data/cache/lot_by_date.csv
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

from research.lot_sizes import REPO, read
from research.sample_months import draw

OUT = Path(__file__).resolve().parents[1] / "data" / "cache" / "lot_by_date.csv"


def months_needed() -> list[str]:
    out = []
    for y, m in draw().items():
        out.append(f"{y}/{m:02d}")
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append(f"{ny}/{nm:02d}")  # positional trades may exit in the next month
        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        out.append(f"{py}/{pm:02d}")  # previous session (option-surface anchor)
    return sorted(set(out))


def main() -> None:
    files = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", "HEAD", "data/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    rows = []
    for m in months_needed():
        fs = sorted(f for f in files if f.startswith(f"data/{m}/") and f.endswith(".zip"))
        if not fs:
            continue
        subprocess.run(["git", "-C", str(REPO), "checkout", "-q", "HEAD", "--", *fs], check=True)
        for f in fs:
            df = read(REPO / f)
            if "TckrSymb" in df.columns:
                sub = df[(df["FinInstrmTp"] == "IDO") & df["TckrSymb"].isin(["NIFTY", "BANKNIFTY"])]
                d = pd.to_datetime(sub["TradDt"].iloc[0]).date()
                for (sym, e), g in sub.groupby(["TckrSymb", "XpryDt"]):
                    rows.append(
                        (d, sym, pd.to_datetime(e).date(), int(g["NewBrdLotQty"].mode()[0]))
                    )
            else:
                sub = df[
                    (df["INSTRUMENT"] == "OPTIDX")
                    & df["SYMBOL"].isin(["NIFTY", "BANKNIFTY"])
                    & (df["CONTRACTS"] > 0)
                ]
                d = pd.to_datetime(sub["TIMESTAMP"].iloc[0], format="%d-%b-%Y").date()
                prem = (sub["OPEN"] + sub["HIGH"] + sub["LOW"] + sub["CLOSE"]) / 4
                lot = sub["VAL_INLAKH"] * 1e5 / (sub["CONTRACTS"] * (sub["STRIKE_PR"] + prem))
                tmp = pd.DataFrame({"sym": sub["SYMBOL"], "e": sub["EXPIRY_DT"], "lot": lot})
                for (sym, e), g in tmp.groupby(["sym", "e"]):
                    rows.append(
                        (
                            d,
                            sym,
                            pd.to_datetime(e, format="%d-%b-%Y").date(),
                            round(g["lot"].median()),
                        )
                    )
            (REPO / f).unlink()
        print(m, "done", flush=True)
    out = pd.DataFrame(rows, columns=["date", "symbol", "expiry", "lot"])
    OUT.write_text(out.to_csv(index=False))
    print(
        out.groupby(["symbol", out["date"].astype(str).str[:7]])["lot"]
        .agg(lambda s: sorted(set(s)))
        .to_string()
    )


if __name__ == "__main__":
    main()
