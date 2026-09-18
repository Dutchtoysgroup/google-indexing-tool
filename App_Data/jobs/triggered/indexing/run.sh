#!/usr/bin/env bash
set -euo pipefail

work_dir="$(mktemp -d /tmp/dtg-indexing-job.XXXXXX)"
trap 'rm -rf "$work_dir"' EXIT
tar --zstd -xf /home/site/wwwroot/output.tar.zst -C "$work_dir"
cd "$work_dir"
python_bin="$work_dir/antenv/bin/python"

if [[ "${WEBJOBS_COMMAND_ARGUMENTS:-}" == "smoke" ]]; then
  "$python_bin" -c 'from db.models import get_connection; c=get_connection(); print(c.cursor().execute("SELECT 1") or "database ok"); c.close()'
  exit 0
fi

secret_file="/home/site/wwwroot/.google-service-account-key.runtime"
if [[ ! -s "$secret_file" ]]; then
  echo "Google service account credential missing" >&2
  exit 1
fi
export GOOGLE_SERVICE_ACCOUNT_KEY="$(cat "$secret_file")"
rm -f "$secret_file"

"$python_bin" main.py
