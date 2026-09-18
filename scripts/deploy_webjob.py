"""Register the Python WebJob after Oryx packs the web app into output.tar.zst."""

import base64
import io
import os
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import ZipFile, ZIP_DEFLATED


root = ElementTree.fromstring(os.environ["AZURE_WEBAPP_PUBLISH_PROFILE"])
profile = next(p for p in root.findall(".//publishProfile") if p.get("publishMethod") == "MSDeploy")
auth = base64.b64encode(f"{profile.attrib['userName']}:{profile.attrib['userPWD']}".encode()).decode()

buffer = io.BytesIO()
with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
    archive.write("App_Data/jobs/triggered/indexing/run.sh", "run.sh")

request = Request(
    "https://dtg-google-indexing-pipeline-weu.scm.azurewebsites.net/api/triggeredwebjobs/indexing",
    data=buffer.getvalue(),
    method="PUT",
    headers={
        "Authorization": "Basic " + auth,
        "Content-Type": "application/zip",
        "Content-Disposition": "attachment; filename=indexing.zip",
    },
)
with urlopen(request, timeout=60) as response:
    print("WebJob geregistreerd:", response.status)
