from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from src.agents.middlewares.dreamy_intent_middleware import DreamyIntentMiddleware


def test_detects_csv_classification_intent():
    middleware = DreamyIntentMiddleware()
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "/workflow\n"
                    "Vessel Name,IMO Number,Vessel Type\n"
                    "CMA CGM TROCADERO,9839167,Container Ship\n"
                    "EVER ALOT,9893955,Container Ship\n"
                    "need workflow to classify vessel types"
                )
            )
        ]
    }
    runtime = SimpleNamespace(context={"thread_id": "t1", "dreamy_mode": True})

    result = middleware.before_agent(state, runtime)
    assert result is not None
    intent = result["dreamy_intent"]
    assert intent["shape"] in {"csv", "mixed"}
    assert intent["intent_class"] == "explicit_workflow"
    assert intent["confidence"] == 1.0
    assert "Vessel Name" in intent["extracted_fields"]
    assert intent["workflow_requested"] is True


def test_non_dreamy_noop():
    middleware = DreamyIntentMiddleware()
    state = {"messages": [HumanMessage(content="need workflow")]}
    runtime = SimpleNamespace(context={"thread_id": "t1", "dreamy_mode": False})
    assert middleware.before_agent(state, runtime) is None
