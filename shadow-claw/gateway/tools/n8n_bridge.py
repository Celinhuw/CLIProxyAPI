"""n8n bridge: trigger and monitor n8n workflows from Shadow-Claw.

n8n (n8n-io/n8n, 108k stars) handles dumb data piping between services.
Shadow-Claw handles Claude-driven intelligence. This bridge connects them.

n8n workflows:
- Meta Ads → daily brief data
- PJe webhook → Attention Queue
- Google Calendar → briefing
- NT8 JSON export → ghostfolio update

Requires n8n running on VPS: docker-compose up n8n
"""

import json
import logging

import requests

import bot_state
from agent import tool

LOGGER = logging.getLogger("shadow_claw_gateway.tools.n8n_bridge")

_N8N_URL = "http://localhost:5678"


def _get_n8n_config() -> tuple[str, str | None]:
    """Get n8n URL and API key from config."""
    from config import get_config_value
    return get_config_value("N8N_URL", _N8N_URL), get_config_value("N8N_API_KEY")


def _n8n_request(endpoint: str, method: str = "GET", data: dict | None = None) -> dict:
    """Make authenticated request to n8n API."""
    url, api_key = _get_n8n_config()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-N8N-API-KEY"] = api_key

    try:
        if method == "POST":
            resp = requests.post(f"{url}/api/v1/{endpoint}", json=data, headers=headers, timeout=30)
        else:
            resp = requests.get(f"{url}/api/v1/{endpoint}", headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        return {"error": "n8n not running. Deploy with: docker-compose up n8n"}
    except requests.RequestException as e:
        return {"error": f"n8n API error: {e}"}


@tool(
    "n8n_list_workflows",
    "List all n8n workflows and their status (active/inactive).",
    {
        "type": "object",
        "properties": {},
    },
)
async def n8n_list_workflows() -> str:
    result = _n8n_request("workflows")
    if "error" in result:
        return result["error"]

    workflows = result.get("data", [])
    if not workflows:
        return "No n8n workflows found. Create one at http://localhost:5678"

    lines = ["⚡ **n8n Workflows:**\n"]
    for wf in workflows:
        status = "🟢" if wf.get("active") else "⚪"
        name = wf.get("name", "Unnamed")
        wf_id = wf.get("id", "?")
        lines.append(f"{status} [{wf_id}] {name}")

    return "\n".join(lines)


@tool(
    "n8n_trigger_workflow",
    "Trigger a specific n8n workflow by ID. "
    "Use for manual execution of automation pipelines.",
    {
        "type": "object",
        "properties": {
            "workflow_id": {
                "type": "string",
                "description": "n8n workflow ID to trigger",
            },
            "data": {
                "type": "string",
                "description": "Optional JSON data to pass to the workflow",
            },
        },
        "required": ["workflow_id"],
    },
)
async def n8n_trigger_workflow(workflow_id: str, data: str = "{}") -> str:
    # Validate workflow_id (numeric or short string)
    if not workflow_id.strip() or len(workflow_id) > 20:
        return "Invalid workflow ID."

    try:
        payload = json.loads(data) if data else {}
    except json.JSONDecodeError:
        return "Invalid JSON data. Provide valid JSON or leave empty."

    url, api_key = _get_n8n_config()
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if api_key:
        headers["X-N8N-API-KEY"] = api_key

    # n8n webhook trigger endpoint
    try:
        resp = requests.post(
            f"{url}/api/v1/workflows/{workflow_id}/activate",
            json=payload,
            headers=headers,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            return f"Workflow {workflow_id} triggered. ✅"
        return f"Failed to trigger workflow: {resp.status_code} {resp.text[:200]}"
    except requests.ConnectionError:
        return "n8n not running."
    except requests.RequestException as e:
        return f"n8n trigger error: {e}"


@tool(
    "n8n_status",
    "Check n8n service health and execution stats.",
    {
        "type": "object",
        "properties": {},
    },
)
async def n8n_status() -> str:
    url, _ = _get_n8n_config()
    try:
        resp = requests.get(f"{url}/healthz", timeout=10)
        if resp.status_code == 200:
            # Get execution stats
            exec_result = _n8n_request("executions?limit=5")
            recent = exec_result.get("data", [])

            lines = [f"⚡ **n8n Status:** Running at {url}\n"]
            if recent:
                lines.append("Recent executions:")
                for ex in recent[:5]:
                    status = "✅" if ex.get("finished") else "🔄"
                    wf_name = ex.get("workflowData", {}).get("name", "?")
                    lines.append(f"  {status} {wf_name}")
            return "\n".join(lines)
        return f"n8n unhealthy: status {resp.status_code}"
    except requests.ConnectionError:
        return f"n8n not running at {url}. Deploy with docker-compose."
