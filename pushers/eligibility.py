"""Fail-closed page-type verification before sending any notification."""

import json

import requests
from bs4 import BeautifulSoup


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def has_type(node, name):
    types = node.get("@type", [])
    if isinstance(types, str):
        types = [types]
    return any(t in {name, "https://schema.org/" + name, "http://schema.org/" + name} for t in types)


def verify_page_type(url, expected_type):
    """Require JSON-LD for the configured type; redirects and uncertainty block.

    This is a type guard, not certification of Google's rich-result guidelines.
    """
    response = requests.get(url, timeout=30, allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200:
        return False, "Page did not return HTTP 200 without redirects"
    soup = BeautifulSoup(response.content, "html.parser")
    all_nodes = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            all_nodes.extend(nodes(json.loads(script.get_text())))
        except (ValueError, TypeError):
            return False, "Invalid JSON-LD; eligibility cannot be established"
    if any(has_type(node, "Product") or has_type(node, "ProductGroup") for node in all_nodes):
        return False, "Product pages are not supported by the Indexing API"
    if expected_type == "JobPosting":
        if any(has_type(node, "JobPosting") for node in all_nodes):
            return True, "JobPosting verified"
    elif expected_type == "BroadcastEvent":
        by_id = {node["@id"]: node for node in all_nodes if isinstance(node.get("@id"), str) and "@type" in node}
        for video in all_nodes:
            if not has_type(video, "VideoObject"):
                continue
            publication = video.get("publication", [])
            events = publication if isinstance(publication, list) else [publication]
            for event in events:
                if not isinstance(event, dict):
                    continue
                event = by_id.get(event.get("@id"), event)
                if has_type(event, "BroadcastEvent") and event.get("isLiveBroadcast") is True:
                    return True, "Live BroadcastEvent in VideoObject verified"
    return False, f"Required structured data for {expected_type} not found"
