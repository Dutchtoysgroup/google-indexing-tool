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


TERMINAL = ("Success", "Failed", "Aborted")


def key_is_staged():
    """False zodra run.sh de sleutel heeft ingelezen en verwijderd."""
    try:
        request(SECRET_PATH, "HEAD").close()
        return True
    except RuntimeError:
        return False


def main():
    """Start één run en wacht hooguit WAIT_MINUTES op de uitkomst.

    Een volledige run duurt uren (URL Inspection is traag), langer dan een
    GitHub-job mag wachten. De nachtelijke workflow start de run daarom alleen
    en meldt de uitkomst van de vórige run: met REQUIRE_PREVIOUS_SUCCESS=1
    faalt de workflow als die mislukt is, zodat een stille storing opvalt.
    """
    key = os.environ["GOOGLE_SERVICE_ACCOUNT_KEY"].encode()
    if not key:
        raise RuntimeError("Google service account key ontbreekt")
    wait_seconds = float(os.environ.get("WAIT_MINUTES", "5")) * 60
    require_previous = os.environ.get("REQUIRE_PREVIOUS_SUCCESS") == "1"

    previous = latest_run()
    previous_id = previous.get("id") if previous else None
    previous_status = previous.get("status", "") if previous else ""
    if previous:
        print(f"Vorige run {previous_id}: {previous_status} "
              f"(gestart {previous.get('start_time', '?')}, duur {previous.get('duration', '?')})")
        if previous_status not in TERMINAL:
            raise RuntimeError(f"vorige run {previous_id} loopt nog ({previous_status})")
    previous_failed = require_previous and previous_status in ("Failed", "Aborted")

    request(SECRET_PATH, "PUT", key, {"Content-Type": "application/octet-stream", "If-Match": "*"}).close()
    try:
        request(JOB_PATH, "POST", b"").close()
    except Exception:
        delete_staged_key()
        raise
    print("Azure indexing WebJob gestart")

    deadline = time.monotonic() + wait_seconds
    status = ""
    while True:
        time.sleep(10)
        run = latest_run()
        if run and run.get("id") != previous_id:
            status = run.get("status", "")
            if status in TERMINAL:
                delete_staged_key()
                print(f"Azure indexing WebJob: {status}")
                return 0 if status == "Success" and not previous_failed else 1
            # Zodra de sleutel is ingelezen, loopt de pipeline echt.
            if status == "Running" and not key_is_staged() and time.monotonic() >= deadline:
                break
        if time.monotonic() >= deadline + 600:
            break
    if status != "Running":
        delete_staged_key()
        print("Azure indexing WebJob is niet gestart binnen de wachttijd")
        return 1
    if key_is_staged():
        print("Waarschuwing: de run loopt maar heeft de sleutel nog niet ingelezen")
    print("Azure indexing WebJob loopt; de uitkomst staat in de volgende run van deze workflow")
    if previous_failed:
        print(f"De vorige run {previous_id} is mislukt ({previous_status})")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Azure WebJob trigger mislukt: {exc}", file=sys.stderr)
        sys.exit(1)
