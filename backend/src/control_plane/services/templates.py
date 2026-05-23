"""Pipeline template sub-service.

Owns:
- Listing and upserting :class:`PipelineTemplate` records.
- Producing the static built-in template catalogue (Knowledge Vault flows).
"""

from __future__ import annotations

from src.config import get_app_config
from src.control_plane.models import (
    PipelineStepDefinition,
    PipelineTemplate,
    utcnow,
)
from src.control_plane.store import ControlPlaneStore


class TemplatesService:
    def __init__(self, store: ControlPlaneStore) -> None:
        self._store = store

    def builtin_templates(self) -> list[PipelineTemplate]:
        config = get_app_config()
        if not config.knowledge_vault.enabled:
            return []

        continuous = PipelineTemplate(
            id="knowledge-vault-continuous",
            name="Knowledge Vault Continuous Learning",
            description="Discover, ingest, and compile article knowledge into the Obsidian vault.",
            enabled=True,
            requires_approval=False,
            trigger_sources=["manual", "scheduler"],
            default_inputs={"urls": [], "objective_id": "obj-general"},
            steps=[
                PipelineStepDefinition(
                    id="vault-discover",
                    name="Discover candidate URLs",
                    kind="vault_discover",
                    config={"input_key": "urls", "source": "pipeline"},
                ),
                PipelineStepDefinition(
                    id="vault-ingest",
                    name="Ingest approved sources",
                    kind="vault_ingest",
                    config={"input_key": "urls", "source": "pipeline"},
                ),
                PipelineStepDefinition(
                    id="vault-compile",
                    name="Compile vault indexes",
                    kind="vault_compile",
                    config={},
                ),
                PipelineStepDefinition(
                    id="vault-lint",
                    name="Lint vault maintenance",
                    kind="vault_lint",
                    config={"freshness_window_days": 30},
                ),
                PipelineStepDefinition(
                    id="vault-synthesize-graph",
                    name="Synthesize knowledge graph",
                    kind="synthesize_knowledge_graph",
                    config={"topic_input_key": "autoresearch_topic"},
                ),
                PipelineStepDefinition(
                    id="vault-sufficiency-evaluate",
                    name="Evaluate vault sufficiency",
                    kind="vault_sufficiency_evaluate",
                    config={"topic_input_key": "autoresearch_topic", "min_score": 78},
                ),
            ],
        )
        autoresearch_loop = PipelineTemplate(
            id="knowledge-vault-autoresearch-loop",
            name="Knowledge Vault Autoresearch Loop",
            description=(
                "One iteration of the agentic autoresearch loop: generate sub-questions, "
                "dedup, dispatch vault-source-researcher per question, reflect, update ledger."
            ),
            enabled=True,
            requires_approval=False,
            trigger_sources=["manual", "scheduler"],
            default_inputs={"autoresearch_topic": "", "objective_id": "", "endpoint_goal": ""},
            steps=[
                PipelineStepDefinition(
                    id="autoresearch-loop-iteration",
                    name="Autoresearch loop iteration",
                    kind="autoresearch_loop_iteration",
                    config={
                        "topic_input_key": "autoresearch_topic",
                        "objective_input_key": "objective_id",
                        "endpoint_goal_input_key": "endpoint_goal",
                    },
                ),
            ],
        )
        return [continuous, autoresearch_loop]

    def list_templates(self) -> list[PipelineTemplate]:
        snapshot = self._store.read()
        return sorted(snapshot.templates.values(), key=lambda item: (item.enabled, item.updated_at), reverse=True)

    def upsert_template(self, template: PipelineTemplate) -> PipelineTemplate:
        now = utcnow()
        template.updated_at = now
        if template.created_at is None:
            template.created_at = now

        def mutate(snapshot):
            existing = snapshot.templates.get(template.id)
            if existing is not None:
                template.created_at = existing.created_at
            snapshot.templates[template.id] = template
            return snapshot.templates[template.id]

        return self._store.mutate(mutate)
