import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from hmac import compare_digest

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config.app_config import get_app_config
from src.gateway.config import get_gateway_config
from src.gateway.routers import (
    agents,
    approvals,
    artifacts,
    channels,
    community_tools,
    feedback,
    workspace_io,
    generation,
    handoff,
    harness,
    integrations,
    mcp,
    memory,
    models,
    onboarding,
    pipelines,
    runs,
    skills,
    steering,
    suggestions,
    threads,
    triggers,
    uploads,
    vault,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


def _mark_component_status(app: FastAPI, component: str, *, status: str, error: str | None = None) -> None:
    status_map = getattr(app.state, "component_status", {})
    status_map[component] = {"status": status, "error": error}
    app.state.component_status = status_map


def _health_payload(app: FastAPI) -> dict[str, object]:
    status_map = getattr(app.state, "component_status", {})
    degraded_components = [
        name for name, info in status_map.items() if isinstance(info, dict) and info.get("status") in {"failed", "stopped"}
    ]
    overall_status = "degraded" if degraded_components else "healthy"
    return {
        "status": overall_status,
        "service": "capyhome-gateway",
        "components": status_map,
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    app.state.component_status = {}

    # Load config and check necessary environment variables at startup
    try:
        get_app_config()
        logger.info("Configuration loaded successfully")
        _mark_component_status(app, "config", status="running")
    except Exception as e:
        error_msg = f"Failed to load configuration during gateway startup: {e}"
        logger.exception(error_msg)
        _mark_component_status(app, "config", status="failed", error=str(e))
        raise RuntimeError(error_msg) from e
    config = get_gateway_config()
    logger.info(f"Starting API Gateway on {config.host}:{config.port}")

    # NOTE: MCP tools initialization is NOT done here because:
    # 1. Gateway doesn't use MCP tools - they are used by Agents in the LangGraph Server
    # 2. Gateway and LangGraph Server are separate processes with independent caches
    # MCP tools are lazily initialized in LangGraph Server when first needed

    # Start IM channel service if any channels are configured
    try:
        from src.channels.service import start_channel_service

        channel_service = await start_channel_service()
        logger.info("Channel service started: %s", channel_service.get_status())
        _mark_component_status(app, "channels", status="running")
    except Exception as exc:
        logger.exception("No IM channels configured or channel service failed to start")
        _mark_component_status(app, "channels", status="failed", error=str(exc))

    # Start control-plane scheduler if enabled
    try:
        from src.control_plane.scheduler import start_control_plane_scheduler

        await start_control_plane_scheduler()
        _mark_component_status(app, "control_plane_scheduler", status="running")
    except Exception as exc:
        logger.exception("Control-plane scheduler failed to start")
        _mark_component_status(app, "control_plane_scheduler", status="failed", error=str(exc))

    # Recover pending repo overview refresh jobs (workspace_io router)
    try:
        await workspace_io.initialize_repo_overview_refresh_jobs()
        _mark_component_status(app, "repo_overview_recovery", status="running")
    except Exception as exc:
        logger.exception("Repo overview refresh recovery failed")
        _mark_component_status(app, "repo_overview_recovery", status="failed", error=str(exc))

    # Start generation poller if enabled
    try:
        from src.generation.poller import start_generation_poller

        await start_generation_poller()
        _mark_component_status(app, "generation_poller", status="running")
    except Exception as exc:
        logger.exception("Generation poller failed to start")
        _mark_component_status(app, "generation_poller", status="failed", error=str(exc))

    yield

    # Stop channel service on shutdown
    try:
        from src.channels.service import stop_channel_service

        await stop_channel_service()
        _mark_component_status(app, "channels", status="stopped")
    except Exception as exc:
        logger.exception("Failed to stop channel service")
        _mark_component_status(app, "channels", status="failed", error=str(exc))

    # Stop control-plane scheduler on shutdown
    try:
        from src.control_plane.scheduler import stop_control_plane_scheduler

        await stop_control_plane_scheduler()
        _mark_component_status(app, "control_plane_scheduler", status="stopped")
    except Exception as exc:
        logger.exception("Failed to stop control-plane scheduler")
        _mark_component_status(app, "control_plane_scheduler", status="failed", error=str(exc))
    # Stop generation poller on shutdown
    try:
        from src.generation.poller import stop_generation_poller

        await stop_generation_poller()
        _mark_component_status(app, "generation_poller", status="stopped")
    except Exception as exc:
        logger.exception("Failed to stop generation poller")
        _mark_component_status(app, "generation_poller", status="failed", error=str(exc))
    logger.info("Shutting down API Gateway")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """

    gateway_config = get_gateway_config()

    app = FastAPI(
        title="CapyHome API Gateway",
        description="""
## CapyHome API Gateway

API Gateway for CapyHome - A LangGraph-based AI agent backend with sandbox execution capabilities.

### Features

- **Models Management**: Query and retrieve available AI models
- **MCP Configuration**: Manage Model Context Protocol (MCP) server configurations
- **Memory Management**: Access and manage global memory data for personalized conversations
- **Skills Management**: Query and manage skills and their enabled status
- **Artifacts**: Access thread artifacts and generated files
- **Health Monitoring**: System health check endpoints

### Architecture

LangGraph requests are handled by nginx reverse proxy.
This gateway provides custom endpoints for models, MCP configuration, skills, and artifacts.
        """,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {
                "name": "models",
                "description": "Operations for querying available AI models and their configurations",
            },
            {
                "name": "mcp",
                "description": "Manage Model Context Protocol (MCP) server configurations",
            },
            {
                "name": "community-tools",
                "description": "Enable or disable built-in community tools",
            },
            {
                "name": "memory",
                "description": "Access and manage global memory data for personalized conversations",
            },
            {
                "name": "skills",
                "description": "Manage skills and their configurations",
            },
            {
                "name": "artifacts",
                "description": "Access and download thread artifacts and generated files",
            },
            {
                "name": "uploads",
                "description": "Upload and manage user files for threads",
            },
            {
                "name": "agents",
                "description": "Create and manage custom agents with per-agent config and prompts",
            },
            {
                "name": "suggestions",
                "description": "Generate follow-up question suggestions for conversations",
            },
            {
                "name": "channels",
                "description": "Manage IM channel integrations (Feishu, Slack, Telegram)",
            },
            {
                "name": "triggers",
                "description": "Capture inbound events that can draft or start local pipelines",
            },
            {
                "name": "pipelines",
                "description": "Create, approve, start, and inspect local pipeline runs",
            },
            {
                "name": "approvals",
                "description": "Resolve pending approval requests before a pipeline can execute",
            },
            {
                "name": "feedback",
                "description": "Record thumbs up/down feedback for runs, artifacts, and recommendations",
            },
            {
                "name": "integrations",
                "description": "Inspect Onyx, channels, tool backends, and local integration health",
            },
            {
                "name": "generation",
                "description": "Submit and track asynchronous ComfyUI generation jobs",
            },
            {
                "name": "runs",
                "description": "Run-control helpers such as resumable run endpoints",
            },
            {
                "name": "vault",
                "description": "Inspect knowledge vault status, sources, and search results",
            },
            {
                "name": "steering",
                "description": "Inject one-shot steering context into thread state before the next model turn",
            },
            {
                "name": "onboarding",
                "description": "Test connections to LLM, ComfyUI, and other external services from the settings UI",
            },
            {
                "name": "health",
                "description": "Health check and system status endpoints",
            },
        ],
    )

    # In local development, frontend may call gateway directly on :8001.
    # Keep CORS permissive by default unless explicitly disabled.
    if os.getenv("GATEWAY_ENABLE_CORS", "1") == "1":
        origins = os.getenv(
            "GATEWAY_CORS_ALLOW_ORIGINS",
            "http://localhost:2026,http://127.0.0.1:2026,http://localhost:3000,http://127.0.0.1:3000",
        )
        allow_origins = [origin.strip() for origin in origins.split(",") if origin.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins or ["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def optional_api_key_auth(request: Request, call_next):  # type: ignore[no-untyped-def]
        api_key = gateway_config.api_key
        if not api_key:
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        candidate = request.headers.get(gateway_config.api_key_header)
        if not candidate:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                candidate = auth_header[7:].strip()

        if not candidate or not compare_digest(candidate, api_key):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "Unauthorized. Provide API key via "
                        f"'{gateway_config.api_key_header}' header or 'Authorization: Bearer <key>'."
                    )
                },
            )

        return await call_next(request)

    # Include routers
    # Models API is mounted at /api/models
    app.include_router(models.router)

    # MCP API is mounted at /api/mcp
    app.include_router(mcp.router)

    # Community Tools API is mounted at /api/tools/community
    app.include_router(community_tools.router)

    # Harness kill-switch API is mounted at /api/harness
    app.include_router(harness.router)

    # Memory API is mounted at /api/memory
    app.include_router(memory.router)

    # Skills API is mounted at /api/skills
    app.include_router(skills.router)

    # Artifacts API is mounted at /api/threads/{thread_id}/artifacts
    app.include_router(artifacts.router)

    # Uploads API is mounted at /api/threads/{thread_id}/uploads
    app.include_router(uploads.router)

    # Agents API is mounted at /api/agents
    app.include_router(agents.router)

    # Suggestions API is mounted at /api/threads/{thread_id}/suggestions
    app.include_router(suggestions.router)

    # Channels API is mounted at /api/channels
    app.include_router(channels.router)

    # Control-plane APIs
    app.include_router(triggers.router)
    app.include_router(pipelines.router)
    app.include_router(approvals.router)
    app.include_router(feedback.router)
    app.include_router(integrations.router)
    app.include_router(onboarding.router)
    app.include_router(generation.router)
    app.include_router(handoff.router)
    app.include_router(runs.router)
    app.include_router(steering.router)
    app.include_router(threads.router)
    app.include_router(vault.router)
    app.include_router(workspace_io.router)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict:
        """Health check endpoint.

        Returns:
            Service health status information.
        """
        return _health_payload(app)

    return app


# Create app instance for uvicorn
app = create_app()
