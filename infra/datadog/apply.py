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


class Refused(Exception):
    """Datadog said no to one object; the others still go ahead."""


FAILED: list[str] = []


def check(response: httpx.Response) -> Any:
    if response.is_error:
        request = response.request
        raise Refused(f"{request.method} {request.url.path}: {response.status_code} {response.text[:400]}")
    return response.json() if response.content else {}


def send(client: httpx.Client, method: str, path: str, body: dict[str, Any]) -> Any:
    return check(client.request(method, path, json=body))


def attempt(what: str, action: Any, *args: Any) -> Any:
    """Run one call; if Datadog refuses it, say so and carry on with the rest."""
    try:
        return action(*args)
    except Refused as exc:
        FAILED.append(what)
        print(f"FAILED {what}: {exc}")
        return None


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
        if spec["type"] == "composite" and any(
            m[1] not in ids for m in re.finditer(r"\{(\w+)\}", spec["query"])
        ):
            FAILED.append(spec["name"])
            print(f"SKIPPED {spec['name']}: a monitor it combines was not created")
            continue
        current = existing.get(spec["name"])
        if current:
            result = attempt(spec["name"], send, client, "PUT", f"/api/v1/monitor/{current['id']}", body)
        else:
            result = attempt(spec["name"], send, client, "POST", "/api/v1/monitor", body)
        if result:
            ids[spec["key"]] = result["id"]
            print(f"monitor {result['id']}: {spec['name']}{' -> webhook' if spec.get('notify') else ''}")
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
        if any(k not in monitor_ids for k in spec["monitors"]):
            FAILED.append(spec["name"])
            print(f"SKIPPED {spec['name']}: its monitor was not created")
            continue
        current = existing.get(spec["name"])
        if current:
            result = attempt(spec["name"], send, client, "PUT", f"/api/v1/slo/{current['id']}", body)
        else:
            result = attempt(spec["name"], send, client, "POST", "/api/v1/slo", body)
        if result:
            ids[spec["key"]] = result["data"][0]["id"]
            print(f"slo {ids[spec['key']]}: {spec['name']}")
    return ids


def dashboards(client: httpx.Client, env: str, slo_ids: dict[str, str]) -> None:
    existing = {d["title"]: d for d in check(client.get("/api/v1/dashboard"))["dashboards"]}
    for file in sorted((HERE / "dashboards").glob("*.json")):
        body = json.loads(file.read_text())
        missing = set(re.findall(r"__SLO:(\w+)__", file.read_text())) - set(slo_ids)
        if missing:  # an SLO it shows was not created: leave its widget out rather than the whole dashboard
            body["widgets"] = [
                w for w in body["widgets"] if not any(f"__SLO:{k}__" in json.dumps(w) for k in missing)
            ]
        body = fill(body, env, slo_ids)
        current = existing.get(body["title"])
        if current:
            result = attempt(body["title"], send, client, "PUT", f"/api/v1/dashboard/{current['id']}", body)
        else:
            result = attempt(body["title"], send, client, "POST", "/api/v1/dashboard", body)
        if result:
            print(f"dashboard: {body['title']} https://{os.environ['DD_SITE']}{result['url']}")


def main() -> None:
    env = os.environ.get("DD_ENV") or "demo"
    headers = {"DD-API-KEY": os.environ["DD_API_KEY"], "DD-APPLICATION-KEY": os.environ["DD_APP_KEY"]}
    with httpx.Client(base_url=f"https://api.{os.environ['DD_SITE']}", headers=headers, timeout=30) as client:
        attempt("webhook", webhook, client)
        monitor_ids = monitors(client, env)
        dashboards(client, env, slos(client, env, monitor_ids))
    if FAILED:
        sys.exit(f"{len(FAILED)} not applied: {', '.join(FAILED)}")


if __name__ == "__main__":
    main()
