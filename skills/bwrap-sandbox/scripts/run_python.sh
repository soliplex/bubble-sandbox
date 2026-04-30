#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: run_python.sh <env> --code <source>" >&2
  echo "       run_python.sh <env> <script_path>" >&2
  echo "       run_python.sh <env>                  (reads script from stdin)" >&2
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

env_name="$1"
shift

workdir=()
[[ -n "${WORKDIR:-}" ]] && workdir+=(-w "${WORKDIR}")

volumes=()
[[ -n "${THREAD_UPLOADS:-}" ]] && volumes+=(-v "thread,${THREAD_UPLOADS}")
[[ -n "${ROOM_UPLOADS:-}"   ]] && volumes+=(-v "room,${ROOM_UPLOADS}")

if [[ $# -eq 0 ]]; then
  exec uvx --with='bubble-sandbox>=0.9.0' bubble-sandbox execute-python --agent-mode \
    --environment "$env_name" "${workdir[@]}" "${volumes[@]}"
elif [[ "$1" == "--code" ]]; then
  if [[ $# -ne 2 ]]; then
    usage
    exit 2
  fi
  exec uvx --with='bubble-sandbox>=0.9.0' bubble-sandbox execute-python --agent-mode \
    --environment "$env_name" "${workdir[@]}" "${volumes[@]}" \
    <<< "$2"
else
  if [[ $# -ne 1 ]]; then
    usage
    exit 2
  fi
  if [[ ! -f "$1" ]]; then
    echo "error: script not found: $1" >&2
    exit 1
  fi
  exec uvx --with='bubble-sandbox>=0.9.0' bubble-sandbox execute-python --agent-mode \
    --environment "$env_name" "${workdir[@]}" "${volumes[@]}" \
    < "$1"
fi
