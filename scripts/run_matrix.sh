#!/bin/bash
# Decrypt the proxy key ONCE (outside every timed window), then run the batch runner.
# Usage: scripts/run_matrix.sh --batch NAME [run_matrix.py args...]
set -euo pipefail
source "$HOME/rig/bin/_proxy-env"
exec /usr/bin/python3 "$(dirname "$0")/run_matrix.py" "$@"
