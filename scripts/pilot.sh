#!/bin/bash
# Pilot: for each model x task, run arms off/on/plain in a shuffled order, strictly sequentially.
# Usage: pilot.sh <model> [<model> ...]      Outputs: runs/pilot/<model>/<task>/<arm>/
# Decrypts the proxy key once here; homes must already exist and be warmed (see HANDOFF.md).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
source "$HOME/rig/bin/_proxy-env"
TASKS="g1_click_exceptions g2_click_completion"
for model in "$@"; do
  for task in $TASKS; do
    order=$(printf 'off\non\nplain\n' | /usr/bin/python3 -c 'import sys,random;l=sys.stdin.read().split();random.shuffle(l);print(" ".join(l))')
    echo "== $model $task order: $order"
    for arm in $order; do
      out="runs/pilot/$model/$task/$arm"
      /usr/bin/python3 scripts/run_one.py --home "runs/homes/$arm" --arm "$arm" --model "$model" \
        --cwd runs/repos/click --prompt-file "tasks/$task.txt" --out-dir "$out" --timeout 600
      echo "$order" > "runs/pilot/$model/$task/order.txt"
    done
  done
done
