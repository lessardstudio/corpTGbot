#!/usr/bin/env sh
set -eu

mkdir -p /app/data /app/logs

if command -v zerotier-one >/dev/null 2>&1; then
  zerotier-one -d || true

  i=0
  while [ $i -lt 30 ]; do
    if zerotier-cli info >/dev/null 2>&1; then
      break
    fi
    i=$((i+1))
    sleep 1
  done

  if [ "${ZT_NETWORK_ID:-}" != "" ]; then
    zerotier-cli join "$ZT_NETWORK_ID" >/dev/null 2>&1 || true
  fi
fi

exec python -m app.main

