#!/usr/bin/env bash
set -euo pipefail

work_dir="$(mktemp -d /tmp/dtg-indexing-job.XXXXXX)"
trap 'rm -rf "$work_dir"' EXIT
tar --zstd -xf /home/site/wwwroot/output.tar.zst -C "$work_dir"
cd "$work_dir"
python_bin="$work_dir/antenv/bin/python"

if [[ "${WEBJOBS_COMMAND_ARGUMENTS:-}" == "smoke" ]]; then
  "$python_bin" - <<'PY'
from db.models import get_connection

connection = get_connection()
try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM urls")
        print("urls:", cursor.fetchone()["count"])
        cursor.execute("UPDATE push_priority SET priority = priority WHERE FALSE")
    connection.rollback()
    print("database read/write grants ok")
finally:
    connection.close()
PY
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
