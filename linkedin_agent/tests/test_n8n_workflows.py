import json
from pathlib import Path


WORKFLOW_DIR = Path(__file__).resolve().parents[2] / "n8n" / "workflows"


def _load_workflow(name: str) -> dict:
    return json.loads((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def _node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow["nodes"]:
        if node["name"] == name:
            return node
    raise AssertionError(f"Nodo `{name}` non trovato nel workflow `{workflow['name']}`.")


def test_expected_workflow_exports_exist():
    exported = sorted(path.name for path in WORKFLOW_DIR.glob("*.json"))
    assert exported == [
        "daily_refresh.json",
        "deep_bootstrap.json",
        "generate_daily_brief.json",
    ]


def test_workflows_route_exit_codes_and_capture_stdout_json():
    expected_modules = {
        "deep_bootstrap.json": "linkedin_agent.scripts.deep_bootstrap_knowledge",
        "daily_refresh.json": "linkedin_agent.scripts.daily_refresh_knowledge",
        "generate_daily_brief.json": "linkedin_agent.scripts.build_daily_brief",
    }
    for filename, module_name in expected_modules.items():
        workflow = _load_workflow(filename)
        execute = _node_by_name(workflow, "Execute CLI")
        parse = _node_by_name(workflow, "Parse Result")
        switch = _node_by_name(workflow, "Route Exit Code")

        command = execute["parameters"]["command"]
        assert module_name in command
        assert "LINKEDIN_AGENT_PROJECT_ROOT" in command

        js_code = parse["parameters"]["jsCode"]
        assert "JSON.parse(raw)" in js_code
        assert "exitCode" in js_code
        assert "stderr" in js_code

        values = switch["parameters"]["rules"]["values"]
        exit_codes = [
            item["conditions"]["conditions"][0]["rightValue"]
            for item in values
        ]
        assert exit_codes == [0, 1, 2]
