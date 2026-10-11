#!/bin/bash
# Build an isolated code-puppy HOME so experiments never touch the owner's live ~/.code_puppy.
# Usage: mkhome.sh <home_dir> <on|off>
# The only difference between arms is enable_speculative_code_mode (arm C adds SPEC_ARM env at run time).
set -euo pipefail
H="$1"; SPEC="$2"
case "$SPEC" in on) V=true ;; off) V=false ;; *) echo "spec must be on|off" >&2; exit 2 ;; esac
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CP="$H/.code_puppy"
rm -rf "$H"
mkdir -p "$CP/plugins"
chmod 700 "$CP"
# Model catalog: copied verbatim (api_key is the literal "$LITELLM_MASTER_KEY" env reference, no secret).
cp "$HOME/.code_puppy/extra_models.json" "$CP/extra_models.json"
# Sandbox-only alias for GLM-4.7: the name avoids code-puppy's glm-<ver> detection, which injects
# extra_body.thinking; LiteLLM's zai route passes that as a kwarg and fails (500). Same upstream model.
/usr/bin/python3 - "$CP/extra_models.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
a = dict(d["proxy-zai-glm-4.7"]); d["proxy-zai-g47"] = a
json.dump(d, open(p, "w"), indent=2)
PY
touch "$CP/onboarding_complete"
cp -R "$REPO/plugin/spec_capture" "$CP/plugins/spec_capture"
cat > "$CP/puppy.cfg" <<EOF
[puppy]
puppy_name = Bench
owner_name = Bench
model = proxy-deepseek-flash
yolo_mode = true
auto_save_session = false
port_base = 9310
enable_speculative_code_mode = $V
frontend_emitter_enabled = false
disable_mcp = true
enable_universal_constructor = false
smooth_thinking_stream = false
smooth_response_stream = false
model_settings_proxy_zai_g47_custom = {"drop_params": true}
EOF
# GLM via LiteLLM rejects max_completion_tokens (400 UnsupportedParamsError) unless the request
# carries drop_params; code-puppy custom params ride in extra_body. Identical in every arm.
echo "built $H (speculation=$V)"
