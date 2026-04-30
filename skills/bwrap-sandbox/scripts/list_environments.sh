#!/usr/bin/env bash
set -euo pipefail

exec uvx --with='bubble-sandbox>=0.9.0' bubble-sandbox list-environments --agent-mode
