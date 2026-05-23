# Sensitive Search (formerly "Privacy Lock") — Removed Feature Reference

> **Status: REMOVED on 2026-05-23.**
> This document preserves the full implementation surface so the feature can be
> revived cleanly if the threat model later justifies it. It is a *reference*,
> not active code.

---

## 1. What it was

A user-toggleable middleware that intercepted outgoing `web_search` tool calls
and rewrote each query through an LLM-based anonymizer before the request
reached the local SearXNG backend (and, via SearXNG, upstream search engines).

UI surface: a "Privacy Lock" item in the workspace input box's
`PrivacyAndAutoMenu` dropdown, alongside Plan Mode / Auto Mode / Autoresearch.

Runtime surface: a `mask_sensitive_search: boolean` flag on the
`AgentThreadContext` that the middleware read from `runtime.context`.

---

## 2. Why it existed

Concerns at the time of introduction:

1. SearXNG is a meta-search aggregator. Although the HTTP hop to
   `http://127.0.0.1:9000` is local, SearXNG forwards queries verbatim to
   upstream engines (Google, Bing, DuckDuckGo, …) unless restricted. So the
   IP/UA layer is anonymized but the *query string itself* still reaches
   third-party engines.
2. Enterprise / consulting deployments could enter client codenames,
   personnel names, or financial figures in chats and unintentionally surface
   those terms in upstream search logs.
3. Defense-in-depth posture: even if local LLMs are the default, the
   `web_search` egress path was the one outbound channel that always reaches
   external services.

---

## 3. Why it was removed

Re-evaluation on 2026-05-23 concluded the protective value was low relative
to its UX cost:

- **Most queries are inquiries, not disclosures.** Searching "Microsoft AI
  strategy" or "Project Stargate OpenAI" is research *into* something, not
  exposure *of* it. Upstream engines see billions of such queries; one more
  CapyHome user adds no actionable signal.
- **Named individual + role + figure** ("Julie Sweet $43M",
  "Clement Kok HSBC Independent Director") is indistinguishable from the kind
  of public-figure research that any analyst, journalist, or curious user
  performs. It's a Bloomberg-article query, not a leak.
- **Codename queries are usually research, not exposure.** If a user is
  searching a project codename, they're trying to learn what's publicly known
  about it — which by definition means information already exists outside
  the workspace.
- **Always-on masking actively degrades search quality.** The masker rewrites
  "Microsoft Copilot architecture" → "a major tech company's AI assistant
  architecture", which returns generic SEO content instead of MS docs.
- **LLM calls are local by default** (LM Studio / Ollama). The dominant
  egress channel for sensitive content is the LLM provider, not the search
  backend. If a user opts in to a remote LLM provider, that is the user's
  accepted risk; query masking on the search side does not change that
  threat model meaningfully.
- **The masker added latency and cost** (an extra LLM round-trip per search)
  for protection that is rarely needed.

Residual risks accepted on removal:

- **PII paste accidents.** A user pasting "John Smith DOB SSN…" into chat
  causing the agent to search it. This is a user-discipline issue, not
  reliably solved by query rewriting.
- **Audit/compliance optics.** Some enterprise procurement checklists ask
  for outbound-query masking. If this resurfaces, see §6 for guidance on
  reimplementation.

---

## 4. Reimplementation guidance (read this before reviving)

Do not revive the binary always-on toggle. The original design was the source
of every problem above. If you reintroduce this:

### 4.1 Smart triggering, not blanket masking

Three viable strategies, ranked by signal/cost:

1. **Memory-derived sensitive-term list (highest precision, near-zero cost)**
   The user's `memory.json` already contains client names, project codenames,
   and active engagement context. Build a set of sensitive tokens from
   memory and only mask queries that contain at least one match. Most
   queries skip masking entirely. Deterministic, fast, no extra LLM call.

2. **Lightweight pre-flight classifier (highest recall, ~1 cheap LLM call)**
   A fast model (Haiku-class, or a local LM Studio model with a tight
   prompt) answers a yes/no: "Does this query contain client-confidential
   or internal identifiers?" Only on `yes` → run the masker. Cache by query
   hash to amortize repeat searches.

3. **Work-mode coupling (zero cost, coarse gate)**
   Only consider masking when `mode == "work"`. Combine with (1) so the
   masker only fires on work-mode queries that hit a memory term.

The recommended composition is **(3) ∧ (1)**: in work mode, if the query
contains a token from the user's memory sensitive-term set, then mask.
Otherwise pass through untouched.

### 4.2 Naming

The feature should be called **"Sensitive Search"**, not "Privacy Lock".
The original name implied a broader scope (whole-app privacy) than it
delivered. "Sensitive Search" describes what it actually does.

### 4.3 Failure mode

The original raised a `ValueError` if the masking LLM call failed, blocking
the search. Keep that semantic on revive — silent fall-through to the
unmasked query would defeat the purpose.

### 4.4 What NOT to gate on this feature

Out of scope on any future revival:

- LLM provider calls (those are governed by user choice of provider)
- Telemetry / analytics (separate concern)
- File-write paths or tool-output truncation (separate middleware)

---

## 5. Original architecture

### 5.1 Middleware chain position

Registered in `backend/src/agents/lead_agent/agent.py` as
`MiddlewareSpec("search_privacy", lambda: SearchPrivacyMiddleware(), after={"dangling_tool_call"})`.

Ordering constraints declared by neighbours:

- `work_mode` had `before={"search_privacy"}`
- `permissions` had `after={"search_privacy"}`
- `summarization` had `after={"search_privacy"}`
- `planner` had `after={"skill_disclosure", "search_privacy"}`

### 5.2 Runtime context flag

`AgentThreadContext.mask_sensitive_search: boolean` — flowed from the
frontend `LocalSettings.context` through thread context into
`runtime.context` where the middleware read it.

### 5.3 Tool gating

Only intercepted tool calls where `tool_call.name == "web_search"`. All
other tools passed through untouched.

---

## 6. File inventory (full contents for revival)

### 6.1 `backend/src/security/search_masking.py`

```python
from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.models.factory import create_chat_model

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_SURROUNDING_QUOTES_RE = re.compile(r'^(["\'`]+)(.*?)(\1)$')

_MASKING_SYSTEM_PROMPT = """You anonymize search queries before web search.

Rewrite the user query so it preserves search intent while masking sensitive specifics.

Rules:
- Replace company names, product names, personal names, internal project names, and exact identifiers with generic but descriptive phrases.
- Soften exact money values, counts, dates, and case-specific details into approximate language when possible.
- Keep the rewritten query useful for public web search.
- Do not mention that you are anonymizing or masking.
- Output exactly one rewritten query and nothing else.
"""


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        return " ".join(chunks).strip()
    return str(content).strip()


def _normalize_masked_query(text: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", text).strip()
    match = _SURROUNDING_QUOTES_RE.match(normalized)
    if match:
        normalized = match.group(2).strip()
    return normalized


def rewrite_search_query_for_privacy(
    query: str,
    *,
    model_name: str | None = None,
) -> str:
    normalized_query = _WHITESPACE_RE.sub(" ", query).strip()
    if not normalized_query:
        return normalized_query

    try:
        try:
            model = create_chat_model(
                name=model_name,
                thinking_enabled=False,
                reasoning_effort="minimal",
            )
        except Exception:
            logger.warning(
                "Falling back to default model for search masking",
                exc_info=True,
            )
            model = create_chat_model(
                thinking_enabled=False,
                reasoning_effort="minimal",
            )

        response = model.invoke(
            [
                SystemMessage(content=_MASKING_SYSTEM_PROMPT),
                HumanMessage(content=normalized_query),
            ]
        )
        masked_query = _normalize_masked_query(_extract_text(response.content))
        if not masked_query:
            raise ValueError("Masking model returned an empty query.")
        return masked_query
    except Exception as exc:
        raise ValueError(
            "Failed to mask the web search query while privacy lock is enabled."
        ) from exc
```

### 6.2 `backend/src/agents/middlewares/search_privacy_middleware.py`

```python
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.security.search_masking import rewrite_search_query_for_privacy

logger = logging.getLogger(__name__)


def _is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


class SearchPrivacyMiddleware(AgentMiddleware):
    """Rewrite outgoing web_search queries when workspace privacy lock is enabled."""

    def _should_mask_search(self, request: ToolCallRequest) -> bool:
        if request.tool_call.get("name") != "web_search":
            return False
        runtime_context = getattr(request.runtime, "context", {}) or {}
        return _is_enabled(runtime_context.get("mask_sensitive_search"))

    def _rewrite_request(self, request: ToolCallRequest) -> ToolCallRequest:
        if not self._should_mask_search(request):
            return request

        args = request.tool_call.get("args", {})
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return request

        runtime_context = getattr(request.runtime, "context", {}) or {}
        masked_query = rewrite_search_query_for_privacy(
            query,
            model_name=runtime_context.get("model_name"),
        )
        if masked_query == query:
            return request

        logger.info("Masked web_search query before provider request")
        return request.override(
            tool_call={
                **request.tool_call,
                "args": {
                    **args,
                    "query": masked_query,
                },
            }
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        return handler(self._rewrite_request(request))

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        rewritten_request = await asyncio.to_thread(self._rewrite_request, request)
        return await handler(rewritten_request)
```

### 6.3 `backend/src/security/__init__.py` (exported symbol)

The module previously exported `rewrite_search_query_for_privacy` alongside
the still-present `enforce_query_guardrails` / `enforce_fetch_url_guardrails`.
To revive, re-add:

```python
from .search_masking import rewrite_search_query_for_privacy
# and add "rewrite_search_query_for_privacy" to __all__
```

### 6.4 `backend/src/agents/lead_agent/agent.py` (registration)

Restore the import:

```python
from src.agents.middlewares.search_privacy_middleware import SearchPrivacyMiddleware
```

Restore the spec (must sit between `work_mode` and `permissions`):

```python
MiddlewareSpec("search_privacy", lambda: SearchPrivacyMiddleware(), after={"dangling_tool_call"}),
```

And restore the `before={"search_privacy"}` constraint on `work_mode`,
and the `after={"search_privacy"}` constraints on `permissions`,
`summarization`, and `planner`.

### 6.5 `backend/tests/test_search_privacy_middleware.py`

```python
from types import SimpleNamespace

from langgraph.prebuilt.tool_node import ToolCallRequest

from src.agents.middlewares.search_privacy_middleware import SearchPrivacyMiddleware


def _request(*, enabled: bool, query: str = "original query") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={
            "id": "call-1",
            "name": "web_search",
            "args": {"query": query},
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=SimpleNamespace(
            context={
                "mask_sensitive_search": enabled,
                "model_name": "local-model",
            }
        ),
    )


def test_search_privacy_middleware_rewrites_query(monkeypatch):
    middleware = SearchPrivacyMiddleware()
    seen: dict[str, str] = {}

    monkeypatch.setattr(
        "src.agents.middlewares.search_privacy_middleware.rewrite_search_query_for_privacy",
        lambda query, model_name=None: "masked query",
    )

    def handler(request: ToolCallRequest) -> str:
        seen["query"] = request.tool_call["args"]["query"]
        return "ok"

    result = middleware.wrap_tool_call(_request(enabled=True), handler)

    assert result == "ok"
    assert seen["query"] == "masked query"


def test_search_privacy_middleware_leaves_query_unchanged_when_disabled():
    middleware = SearchPrivacyMiddleware()
    seen: dict[str, str] = {}

    def handler(request: ToolCallRequest) -> str:
        seen["query"] = request.tool_call["args"]["query"]
        return "ok"

    result = middleware.wrap_tool_call(_request(enabled=False), handler)

    assert result == "ok"
    assert seen["query"] == "original query"
```

### 6.6 `backend/tests/test_middleware_registry.py` (ordering assertions)

```python
assert names.index("search_privacy") < names.index("permissions")
assert names.index("search_privacy") < names.index("plan_execution_gate")
```

---

## 7. Frontend integration points

### 7.1 `frontend/src/core/i18n/locales/en-US.ts`

```ts
searchPrivacy: "Privacy Lock",
searchPrivacyDescription:
  "When enabled, CapyHome anonymizes each web search query before sending it to SearXNG for this workspace.",
searchPrivacyEnabled: "Privacy lock is on",
searchPrivacyDisabled: "Privacy lock is off",
```

On revival, rename to `sensitiveSearch` (or similar) per §4.2.

### 7.2 `frontend/src/core/threads/types.ts`

```ts
export interface AgentThreadContext extends Record<string, unknown> {
  // ...
  mask_sensitive_search?: boolean;
  // ...
}
```

### 7.3 `frontend/src/core/settings/local.ts`

```ts
DEFAULT_LOCAL_SETTINGS.context = {
  // ...
  mask_sensitive_search: false,
};
```

### 7.4 `frontend/src/components/workspace/input-box.tsx`

- Add `mask_sensitive_search?: boolean` to the `context` and `onContextChange`
  types.
- Add a `handleToggleSearchPrivacy` callback that flips
  `context.mask_sensitive_search`.
- Pass `maskSensitiveSearch={context.mask_sensitive_search}` and
  `onToggleSearchPrivacy={handleToggleSearchPrivacy}` to the dropdown menu
  component.

### 7.5 `frontend/src/components/workspace/input-box-left-toolbar.tsx`

Component was named `PrivacyAndAutoMenu` (held Plan Mode + Auto Mode +
Privacy Lock + Autoresearch). On removal the component was simplified and
the privacy item / `LockIcon` were dropped. On revival, re-add the
`DropdownMenuItem` block with the `searchPrivacy` strings and a switch
bound to `maskSensitiveSearch` + `onToggleSearchPrivacy`. Re-import
`LockIcon` from `lucide-react` if you want the visual indicator back.

---

## 8. End-to-end data path (for revival)

```
LocalSettings.context.mask_sensitive_search   (frontend localStorage)
  ↓
AgentThreadContext.mask_sensitive_search      (thread context)
  ↓
runtime.context["mask_sensitive_search"]      (LangGraph runtime)
  ↓
SearchPrivacyMiddleware._should_mask_search   (middleware check)
  ↓
rewrite_search_query_for_privacy(query, ...)  (LLM rewrite)
  ↓
ToolCallRequest.override(tool_call={..., "args": {"query": masked_query}})
  ↓
web_search tool → SearXNG @ 127.0.0.1:9000 → upstream engines
```

---

## 9. Git history pointer

The removal commit on 2026-05-23 contains the full deletion diff. Use
`git log --all --diff-filter=D -- backend/src/security/search_masking.py`
or `git log -- backend/src/agents/middlewares/search_privacy_middleware.py`
to locate it. The original implementation predates that commit; check
`git log --follow` on either file to trace its evolution.
