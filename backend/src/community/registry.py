"""Static registry of all known community tools.

Each entry maps a tool name to its import path and display metadata.
``source`` values:
  - ``"builtin"``  — always injected via BUILTIN_TOOLS in src/tools/tools.py
  - ``"config"``   — registered in config.yaml under the ``tools:`` section

The registry is the single source of truth consumed by the community-tools
Gateway API to tell the frontend what tools are available.
"""

from typing import TypedDict


class CommunityToolEntry(TypedDict):
    import_path: str
    display_name: str
    description: str
    source: str  # "builtin" | "config"


COMMUNITY_TOOL_REGISTRY: dict[str, CommunityToolEntry] = {
    "web_search": {
        "import_path": "src.community.web_search.tools:web_search_tool",
        "display_name": "Web Search",
        "description": "Search the web via a local SearXNG-compatible backend.",
        "source": "builtin",
    },
    "query_knowledge_vault": {
        "import_path": "src.community.knowledge_vault_search.tool:query_knowledge_vault_tool",
        "display_name": "Knowledge Vault Search",
        "description": "BM25 keyword search over compiled knowledge vault pages.",
        "source": "builtin",
    },
    "query_lightrag": {
        "import_path": "src.community.lightrag.tool:query_lightrag_tool",
        "display_name": "LightRAG Query",
        "description": "Graph-oriented evidence retrieval via a local LightRAG server.",
        "source": "builtin",
    },
    "comfyui_generate": {
        "import_path": "src.community.comfyui.tools:comfyui_generate_tool",
        "display_name": "ComfyUI Generate",
        "description": "Submit image/video generation requests to a local ComfyUI server.",
        "source": "config",
    },
    "image_search": {
        "import_path": "src.community.image_search.tools:image_search_tool",
        "display_name": "Image Search",
        "description": "Search for images via the local SearXNG-compatible backend.",
        "source": "config",
    },
}
