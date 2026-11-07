#!/usr/bin/env bash
# Creates local secret files (gitignored). Never commit anything under secrets/.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p secrets
chmod 700 secrets
if [[ -f secrets/master_key ]]; then
  chmod 644 secrets/master_key
  echo "secrets/master_key already exists; leaving it unchanged (rotating it makes stored MFA secrets unreadable)."
else
  head -c 32 /dev/urandom | base64 > secrets/master_key
  # The directory (700) keeps other host users out. The file itself must be readable by
  # the non-root user inside the containers, which receives it as a bind mount.
  chmod 644 secrets/master_key
  echo "Created secrets/master_key. Back it up somewhere safe: losing it means re-enrolling MFA."
fi
