"""Create or update Firstlight's Datadog setup in an org: the webhook, monitors, SLOs and dashboards.

Everything is matched by name and tagged firstlight:managed, so running it again updates in place, and the
same files rebuild the whole setup in another org. It reads DD_API_KEY, DD_APP_KEY, DD_SITE, DD_ENV,
PUBLIC_HOST and WEBHOOK_SECRET from the environment: scripts/datadog-apply.sh runs it on the demo host
with the server's .env, so no key leaves the server.

In the definitions, __ENV__ stands for DD_ENV and __SLO:key__ for the id of the SLO with that key.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
TAG = "firstlight:managed"
WEBHOOK = "firstlight"
# What the API's /v1/hooks/datadog reads (see src/firstlight/api/hooks.py).
PAYLOAD = {
    "alert_id": "$ALERT_CYCLE_KEY",
    "transition": "$ALERT_TRANSITION",
    "monitor_id": "$ALERT_ID",
    "title": "$EVENT_TITLE",
    "scope": "$ALERT_SCOPE",
    "tags": "$TAGS",
    "link": "$LINK",
    "date": "$DATE",
}


def fill(value: Any, env: str, slos: dict[str, str]) -> Any:
    if isinstance(value, str):
        value = re.sub(r"__SLO:(\w+)__", lambda m: slos[m[1]], value)
        return value.replace("__ENV__", env)
    if isinstance(value, list):
        return [fill(v, env, slos) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, env, slos) for k, v in value.items()}
    return value


def check(response: httpx.Response) -> dict[str, Any]:
    if response.is_error:
        request = response.request
        sys.exit(f"{request.method} {request.url.path}: {response.status_code} {response.text[:400]}")
    return response.json() if response.content else {}


def webhook(client: httpx.Client) -> None:
    body = {
        "name": WEBHOOK,
        "url": f"https://{os.environ['PUBLIC_HOST']}/v1/hooks/datadog",
        "encode_as": "json",
        "payload": json.dumps(PAYLOAD),
        "custom_headers": json.dumps({"X-Firstlight-Signature": os.environ["WEBHOOK_SECRET"]}),
    }
    path = "/api/v1/integration/webhooks/configuration/webhooks"
    if client.get(f"{path}/{WEBHOOK}").status_code == 200:
        check(client.put(f"{path}/{WEBHOOK}", json=body))
        print(f"webhook @webhook-{WEBHOOK}: updated")
    else:
        check(client.post(path, json=body))
        print(f"webhook @webhook-{WEBHOOK}: created")


def monitors(client: httpx.Client, env: str) -> dict[str, int]:
    specs = fill(json.loads((HERE / "monitors.json").read_text()), env, {})
    existing = {m["name"]: m for m in check(client.get("/api/v1/monitor", params={"monitor_tags": TAG}))}
    ids: dict[str, int] = {}
    for spec in sorted(specs, key=lambda s: s["type"] == "composite"):  # composites refer to the others
        body = {k: v for k, v in spec.items() if k not in ("key", "notify")}
        body["tags"] = [TAG, f"env:{env}", "service:firstlight"]
        if spec.get("notify"):
            body["message"] += f"\n\n@webhook-{WEBHOOK}"
        if spec["type"] == "composite":
            body["query"] = re.sub(r"\{(\w+)\}", lambda m: str(ids[m[1]]), spec["query"])
        current = existing.get(spec["name"])
        if current:
            ids[spec["key"]] = check(client.put(f"/api/v1/monitor/{current['id']}", json=body))["id"]
        else:
            ids[spec["key"]] = check(client.post("/api/v1/monitor", json=body))["id"]
        print(f"monitor {ids[spec['key']]}: {spec['name']}{' -> webhook' if spec.get('notify') else ''}")
    return ids


def slos(client: httpx.Client, env: str, monitor_ids: dict[str, int]) -> dict[str, str]:
    specs = json.loads((HERE / "slos.json").read_text())
    listed = check(client.get("/api/v1/slo", params={"tags_query": TAG})).get("data") or []
    existing = {s["name"]: s for s in listed}
    ids: dict[str, str] = {}
    for spec in specs:
        body = {
            "name": spec["name"],
            "description": spec["description"],
            "type": "monitor",
            "monitor_ids": [monitor_ids[k] for k in spec["monitors"]],
            "thresholds": [{"timeframe": spec["timeframe"], "target": spec["target"]}],
            "tags": [TAG, f"env:{env}"],
        }
        current = existing.get(spec["name"])
        if current:
            ids[spec["key"]] = check(client.put(f"/api/v1/slo/{current['id']}", json=body))["data"][0]["id"]
        else:
            ids[spec["key"]] = check(client.post("/api/v1/slo", json=body))["data"][0]["id"]
        print(f"slo {ids[spec['key']]}: {spec['name']}")
    return ids


def dashboards(client: httpx.Client, env: str, slo_ids: dict[str, str]) -> None:
    existing = {d["title"]: d for d in check(client.get("/api/v1/dashboard"))["dashboards"]}
    for file in sorted((HERE / "dashboards").glob("*.json")):
        body = fill(json.loads(file.read_text()), env, slo_ids)
        current = existing.get(body["title"])
        if current:
            result = check(client.put(f"/api/v1/dashboard/{current['id']}", json=body))
        else:
            result = check(client.post("/api/v1/dashboard", json=body))
        print(f"dashboard: {body['title']} https://{os.environ['DD_SITE']}{result['url']}")


def main() -> None:
    env = os.environ.get("DD_ENV") or "demo"
    headers = {"DD-API-KEY": os.environ["DD_API_KEY"], "DD-APPLICATION-KEY": os.environ["DD_APP_KEY"]}
    with httpx.Client(base_url=f"https://api.{os.environ['DD_SITE']}", headers=headers, timeout=30) as client:
        webhook(client)
        monitor_ids = monitors(client, env)
        dashboards(client, env, slos(client, env, monitor_ids))


if __name__ == "__main__":
    main()
