"""Send the existing GitHub secret to a single Azure WebJob run."""

import base64
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree


HOST = "https://dtg-google-indexing-pipeline-weu.scm.azurewebsites.net"
SECRET_PATH = "/api/vfs/site/wwwroot/.google-service-account-key.runtime"
JOB_PATH = "/api/triggeredwebjobs/indexing/run"


def credentials():
    xml = os.environ["AZURE_WEBAPP_PUBLISH_PROFILE"]
    root = ElementTree.fromstring(xml)
    profiles = root.findall(".//publishProfile")
    profile = next((p for p in profiles if p.get("publishMethod") == "MSDeploy"), None)
    if profile is None:
        raise RuntimeError("MSDeploy publishing profile ontbreekt")
    raw = f"{profile.attrib['userName']}:{profile.attrib['userPWD']}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def request(path, method="GET", data=None, headers=None):
    all_headers = {"Authorization": credentials(), **(headers or {})}
    req = Request(HOST + path, data=data, method=method, headers=all_headers)
    try:
        return urlopen(req, timeout=60)
    except HTTPError as exc:
        raise RuntimeError(f"Kudu {method} {path} gaf HTTP {exc.code}") from exc


def latest_run():
    with request("/api/triggeredwebjobs/indexing/history") as response:
        runs = json.load(response).get("runs", [])
    return runs[0] if runs else None


def delete_staged_key():
    try:
        request(SECRET_PATH, "DELETE", headers={"If-Match": "*"}).close()
    except RuntimeError:
        pass


def main():
    key = os.environ["GOOGLE_SERVICE_ACCOUNT_KEY"].encode()
    if not key:
        raise RuntimeError("Google service account key ontbreekt")
    previous = latest_run()
    previous_id = previous.get("id") if previous else None
    request(SECRET_PATH, "PUT", key, {"Content-Type": "application/octet-stream", "If-Match": "*"}).close()
    try:
        request(JOB_PATH, "POST", b"").close()
    except Exception:
        delete_staged_key()
        raise
    print("Azure indexing WebJob gestart")
    for _ in range(300):
        time.sleep(10)
        run = latest_run()
        if not run or run.get("id") == previous_id:
            continue
        status = run.get("status", "")
        if status in ("Success", "Failed", "Aborted"):
            delete_staged_key()
            print(f"Azure indexing WebJob: {status}")
            return 0 if status == "Success" else 1
    delete_staged_key()
    print("Azure indexing WebJob heeft de wachttijd overschreden")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Azure WebJob trigger mislukt: {exc}", file=sys.stderr)
        sys.exit(1)
