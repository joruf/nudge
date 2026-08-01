#!/usr/bin/env bash
# Linux launcher. Passes any arguments straight through, so both of these work:
#   ./nudge.sh
#   ./nudge.sh --list
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
exec python3 -m nudge "$@"
