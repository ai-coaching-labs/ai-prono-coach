#!/usr/bin/env bash
set -euo pipefail
PRONO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$PRONO_ROOT/scripts/install.py" "$@"
