#!/bin/bash
# Clone the pinned public repos used by the task suite into runs/repos/ (gitignored) and build
# the grader/agent venv (.venv, pytest only). Idempotent: an existing clone is verified, not recloned.
# Usage: scripts/setup_repos.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
D="$REPO/runs/repos"
mkdir -p "$D"
pin() {  # name url tag sha
  local name=$1 url=$2 tag=$3 sha=$4
  if [ ! -d "$D/$name/.git" ]; then
    git -c advice.detachedHead=false clone -q --branch "$tag" "$url" "$D/$name"
  fi
  local got
  got=$(git -C "$D/$name" rev-parse HEAD)
  if [ "$got" != "$sha" ]; then echo "PIN MISMATCH $name: $got != $sha" >&2; exit 1; fi
  if [ -n "$(git -C "$D/$name" status --porcelain)" ]; then echo "DIRTY $name" >&2; exit 1; fi
  echo "ok $name $sha"
}
pin click https://github.com/pallets/click.git 8.1.7 874ca2bc1c30d93a4ac6e36a15ed685eafe89097
pin httpx https://github.com/encode/httpx.git 0.27.0 326b9431c761e1ef1e00b9f760d1f654c8db48c6
pin rich https://github.com/Textualize/rich.git v13.7.1 7f580bdcf07a3b269a0e786b6a3aa9c804f393cf
if [ ! -x "$REPO/.venv/bin/python" ]; then
  uv venv -q "$REPO/.venv" --python 3.12
  uv pip install -q --python "$REPO/.venv/bin/python" pytest==8.3.3
fi
"$REPO/.venv/bin/python" -m pytest --version
