#!/usr/bin/env bash
# Downloads the public datasets used by the F&O strategy research into backend/data/raw
# (gitignored). Commits are pinned so results are reproducible.
set -euo pipefail
RAW="$(cd "$(dirname "$0")/.." && pwd)/backend/data/raw"
mkdir -p "$RAW"
cd "$RAW"

fetch() { # repo commit dest [paths...]
  local repo=$1 commit=$2 dest=$3; shift 3
  if [[ -d "$dest/.git" ]]; then echo "$dest exists, skipping"; return; fi
  git clone -q --filter=blob:none --no-checkout "https://github.com/$repo" "$dest"
  git -C "$dest" checkout -q "$commit" -- "$@"
  echo "fetched $repo@$commit -> $dest"
}

fetch technovusin/nifty50-historical-data 6eb58d9 nifty50 1min LICENSE
fetch sandeepkapri/BankNifty-Data 6bdda6e banknifty bank-nifty-1m-data.csv LICENSE
fetch Rithvik-Rajesh/dynamic-portfolio-allocation 41ca7bb vixsrc data/raw/vix.csv
mkdir -p indiavix && cp vixsrc/data/raw/vix.csv indiavix/vix.csv
# One real NSE F&O bhavcopy (05-Jan-2024) used to validate the option-pricing model.
fetch nesarw/IndexVol 8f4fbde bhavsrc data/extracted/fo05JAN2024bhav.csv
mkdir -p bhavcopy && cp bhavsrc/data/extracted/fo05JAN2024bhav.csv bhavcopy/
# Daily NSE F&O bhavcopies (Apr 2020 onward). Only the git index is fetched here; the
# extractor (backend/research/build_option_eod.py) pulls one month at a time and keeps only
# NIFTY/BANKNIFTY rows.
if [[ ! -d fnobank/.git ]]; then
  git clone -q --filter=blob:none --no-checkout https://github.com/SantoshSrinivas79/NSE-FNO-Data-bank fnobank
  git -C fnobank checkout -q 66bbc7f -- README.md LICENSE
  echo "fetched NSE-FNO-Data-bank index -> fnobank"
fi
