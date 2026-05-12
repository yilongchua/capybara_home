"""Domain sub-services composed by :class:`ControlPlaneService`.

Each module here extracts a focused slice of the original monolithic
``ControlPlaneService`` (see ``backend/docs`` cleanup plan). Sub-services hold
references to shared dependencies (store, redaction, etc.) and expose the same
method names the facade used to expose, so behaviour is byte-identical.
"""

from src.control_plane.services.approvals import ApprovalsService
from src.control_plane.services.artifacts import ArtifactsService
from src.control_plane.services.feedback import FeedbackService
from src.control_plane.services.proposals import ProposalsService
from src.control_plane.services.scheduler import SchedulerService
from src.control_plane.services.templates import TemplatesService
from src.control_plane.services.triggers import TriggersService

__all__ = [
    "ApprovalsService",
    "ArtifactsService",
    "FeedbackService",
    "ProposalsService",
    "SchedulerService",
    "TemplatesService",
    "TriggersService",
]
