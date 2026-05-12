from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from src.agents.middlewares.dreamy_bootstrap_middleware import DreamyBootstrapMiddleware
from src.config.paths import Paths


def test_bootstrap_creates_workflow_for_minimal_prompt(tmp_path):
    middleware = DreamyBootstrapMiddleware()
    paths = Paths(base_dir=str(tmp_path))
    thread_id = "thread-minimal"
    paths.ensure_thread_dirs(thread_id)

    runtime = SimpleNamespace(
        context={"thread_id": thread_id, "dreamy_mode": True},
    )
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "/workflow\n"
                    "- Find vessel owner details\n"
                    "- Validate IMO status"
                )
            )
        ],
        "dreamy_intent": {
            "shape": "free_text",
            "intent_class": "explicit_workflow",
            "confidence": 1.0,
            "extracted_fields": [],
            "inferred_goal": "analyze input and produce workflow",
            "workflow_requested": True,
        },
    }

    from src.agents.middlewares import dreamy_bootstrap_middleware as module

    original_get_paths = module.get_paths
    module.get_paths = lambda: paths
    try:
        result = middleware.before_agent(state, runtime)
    finally:
        module.get_paths = original_get_paths

    assert result is not None
    assert "/mnt/user-data/outputs/workflow.json" in result.get("artifacts", [])
    workflow_path = paths.sandbox_outputs_dir(thread_id) / "workflow.json"
    assert workflow_path.exists()
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    assert workflow["data_source"]["type"] == "inline"
    assert workflow["data_source"]["fields"] == ["task", "id"]
    assert isinstance(workflow.get("steps"), list) and len(workflow["steps"]) >= 1
    assert str(workflow["steps"][0].get("id", "")).startswith("step-")


def test_bootstrap_creates_structured_workflow_when_csv_detected(tmp_path):
    middleware = DreamyBootstrapMiddleware()
    paths = Paths(base_dir=str(tmp_path))
    thread_id = "thread-csv"
    paths.ensure_thread_dirs(thread_id)

    runtime = SimpleNamespace(context={"thread_id": thread_id, "dreamy_mode": True})
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "/workflow\n"
                    "Vessel Name,IMO Number,Vessel Type\n"
                    "CMA CGM TROCADERO,9839167,Container Ship\n"
                    "EVER ALOT,9893955,Container Ship"
                )
            )
        ],
        "dreamy_intent": {
            "shape": "csv",
            "intent_class": "explicit_workflow",
            "confidence": 1.0,
            "extracted_fields": ["Vessel Name", "IMO Number", "Vessel Type"],
            "inferred_goal": "classify records",
            "workflow_requested": True,
        },
    }

    from src.agents.middlewares import dreamy_bootstrap_middleware as module

    original_get_paths = module.get_paths
    module.get_paths = lambda: paths
    try:
        result = middleware.before_agent(state, runtime)
    finally:
        module.get_paths = original_get_paths

    assert result is not None
    workflow = json.loads((paths.sandbox_outputs_dir(thread_id) / "workflow.json").read_text(encoding="utf-8"))
    assert workflow["data_source"]["type"] == "inline"
    assert workflow["data_source"]["fields"] == ["Vessel Name", "IMO Number", "Vessel Type"]
