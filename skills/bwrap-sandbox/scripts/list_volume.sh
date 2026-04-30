#!/usr/bin/env bash
set -euo pipefail

volume="${1:-}"
case "$volume" in
  thread) host="${THREAD_UPLOADS:-}" ;;
  room)   host="${ROOM_UPLOADS:-}" ;;
  *)
    echo "usage: list_volume.sh <thread|room>" >&2
    exit 2
    ;;
esac

if [[ -z "$host" ]]; then
  echo "error: volume '$volume' is not mounted — the runtime did not set \$${volume^^}_UPLOADS" >&2
  exit 1
fi

exec uvx --with='bubble-sandbox>=0.9.0' bubble-sandbox execute --agent-mode \
  -v "${volume},${host}" -- \
  find "/sandbox/volumes/${volume}" -type f
