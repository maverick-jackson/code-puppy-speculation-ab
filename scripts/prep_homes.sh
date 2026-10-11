#!/bin/bash
# Rebuild the two TEMPLATE homes (runs/homes/off, runs/homes/on) with mkhome.sh, warm each once
# (one-time Flux bootstrap happens on the first start), then strip per-run state. run_matrix.py
# clones a template into a fresh per-run HOME for every run (arm plain = template "on" plus
# SPEC_ARM=codemode_plain), so no run ever sees another run's autosaves, spills or cfg writes.
# Usage: scripts/prep_homes.sh       (costs one tiny deepseek-flash request per template)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
source "$HOME/rig/bin/_proxy-env"
rm -rf runs/homes/plain runs/tmp/warm
mkdir -p runs/tmp/warm/cwd
for arm in off on; do
  scripts/mkhome.sh "runs/homes/$arm" "$arm"
  echo "Reply with the single word OK." > runs/tmp/warm/prompt.txt
  /usr/bin/python3 scripts/run_one.py --home "runs/homes/$arm" --arm "$arm" \
    --model proxy-deepseek-flash --cwd runs/tmp/warm/cwd --prompt-file runs/tmp/warm/prompt.txt \
    --out-dir "runs/tmp/warm/$arm" --timeout 120
  CP="runs/homes/$arm/.code_puppy"
  rm -rf "$CP/autosaves" "$CP/tool_output_spill" "$CP/dir_sessions" "$CP/logs" \
         "$CP/command_history.txt" "$CP"/*.lock
  grep -q "Flux\|flux" -r "$CP/commands" && echo "warm ok: $arm"
done
diff runs/homes/off/.code_puppy/puppy.cfg runs/homes/on/.code_puppy/puppy.cfg || true
diff -r runs/homes/off/.code_puppy/plugins/spec_capture plugin/spec_capture && echo "plugin current"
