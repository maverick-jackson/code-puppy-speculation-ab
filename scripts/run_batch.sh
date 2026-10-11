#!/bin/bash
# Decrypt the proxy key ONCE (outside every timed window), then run run_one.py with the given args.
# Usage: run_batch.sh <run_one.py args...>   (call repeatedly, or wrap in a loop file)
set -euo pipefail
source "$HOME/rig/bin/_proxy-env"
exec /usr/bin/python3 "$(dirname "$0")/run_one.py" "$@"
