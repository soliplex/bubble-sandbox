#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || "$2" != "--" ]]; then
  echo "usage: run.sh <env> -- <command> [args...]" >&2
  exit 2
fi

env_name="$1"
shift 2

workdir=()
[[ -n "${WORKDIR:-}" ]] && workdir+=(-w "${WORKDIR}")

volumes=()
[[ -n "${THREAD_UPLOADS:-}" ]] && volumes+=(-v "thread,${THREAD_UPLOADS}")
[[ -n "${ROOM_UPLOADS:-}"   ]] && volumes+=(-v "room,${ROOM_UPLOADS}")

exec uvx --with='bubble-sandbox>=0.9.0' bubble-sandbox execute --agent-mode \
  --environment "$env_name" "${workdir[@]}" "${volumes[@]}" -- "$@"
