"""Knowledge vault learning manager — composed from focused mixins.

The public surface is `VaultLearningManager` plus the dataclasses/Pydantic
models that callers reach for. Internally the implementation lives in
sibling modules (`_base`, `_ingest`, `_compile`, …) and is composed via
multiple inheritance below.
"""

from __future__ import annotations

# Re-exported so tests/callers that patch `src.control_plane.vault_learning.UnifiedVaultSearchService`
# (or otherwise reach for it through this module path) keep working after the split.
from src.control_plane.services.unified_vault_search import UnifiedVaultSearchService

from ._analysis import AnalysisMixin
from ._base import _VaultLearningBase
from ._canonical import CanonicalMixin
from ._cleanup import CleanupMixin
from ._compile import CompileMixin
from ._documents import DocumentsMixin
from ._entities import EntitiesMixin
from ._ingest import IngestMixin
from ._lint import LintMixin
from ._loop_guard import LoopGuardMixin
from ._models import (
    _VAULT_COORDINATION,
    _VAULT_COORDINATION_GLOBAL_LOCK,
    PrefetchedIngest,
    VaultLoopGuardConfig,
    VaultManifest,
    _get_vault_coordination,
    _query_id_for_identity,
    _VaultCoordination,
)
from ._pages import PagesMixin
from ._queue import QueueMixin
from ._search_and_summary import SearchSummaryMixin
from ._synthesis import SynthesisMixin
from ._trust import TrustMixin
from ._urls import UrlsMixin


class VaultLearningManager(
    IngestMixin,
    CompileMixin,
    PagesMixin,
    AnalysisMixin,
    TrustMixin,
    QueueMixin,
    UrlsMixin,
    LoopGuardMixin,
    DocumentsMixin,
    EntitiesMixin,
    CanonicalMixin,
    LintMixin,
    SynthesisMixin,
    SearchSummaryMixin,
    CleanupMixin,
    _VaultLearningBase,
):
    """Composed from focused mixins; see vault_learning/ subpackage."""


__all__ = [
    "VaultLearningManager",
    "PrefetchedIngest",
    "VaultManifest",
    "VaultLoopGuardConfig",
    "UnifiedVaultSearchService",
    "_VaultCoordination",
    "_get_vault_coordination",
    "_query_id_for_identity",
    "_VAULT_COORDINATION",
    "_VAULT_COORDINATION_GLOBAL_LOCK",
]
