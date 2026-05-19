"""Prompt templates for memory update and injection."""

import re
from typing import Any

from src.agents.memory.store import MEMORY_SCOPE_GLOBAL, MEMORY_SCOPE_WORKSPACE
from src.agents.memory.vector_store import get_memory_vector_store
from src.config.memory_config import get_memory_config

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

# Prompt template for updating memory based on conversation
MEMORY_UPDATE_PROMPT = """You are a memory management system. Your task is to analyze a conversation and update the user's memory profile.

Current Memory State:
<current_memory>
{current_memory}
</current_memory>

New Conversation to Process:
<conversation>
{conversation}
</conversation>

Instructions:
1. Analyze the conversation for important information about the user
2. Extract relevant facts, preferences, and context with specific details (numbers, names, technologies)
3. Update the memory sections as needed following the detailed length guidelines below

Memory Section Guidelines:

**User Context** (Current state - concise summaries):
- workContext: Professional role, company, key projects, main technologies (2-3 sentences)
  Example: Core contributor, project names with metrics (16k+ stars), technical stack
- personalContext: Languages, communication preferences, key interests (1-2 sentences)
  Example: Bilingual capabilities, specific interest areas, expertise domains
- topOfMind: Multiple ongoing focus areas and priorities (3-5 sentences, detailed paragraph)
  Example: Primary project work, parallel technical investigations, ongoing learning/tracking
  Include: Active implementation work, troubleshooting issues, market/research interests
  Note: This captures SEVERAL concurrent focus areas, not just one task

**History** (Temporal context - rich paragraphs):
- recentMonths: Detailed summary of recent activities (4-6 sentences or 1-2 paragraphs)
  Timeline: Last 1-3 months of interactions
  Include: Technologies explored, projects worked on, problems solved, interests demonstrated
- earlierContext: Important historical patterns (3-5 sentences or 1 paragraph)
  Timeline: 3-12 months ago
  Include: Past projects, learning journeys, established patterns
- longTermBackground: Persistent background and foundational context (2-4 sentences)
  Timeline: Overall/foundational information
  Include: Core expertise, longstanding interests, fundamental working style

**Facts Extraction**:
- Extract specific, quantifiable details (e.g., "16k+ GitHub stars", "200+ datasets")
- Include proper nouns (company names, project names, technology names)
- Preserve technical terminology and version numbers
- Categories:
  * preference: Tools, styles, approaches user prefers/dislikes
  * knowledge: Specific expertise, technologies mastered, domain knowledge
  * context: Background facts (job title, projects, locations, languages)
  * behavior: Working patterns, communication habits, problem-solving approaches
  * goal: Stated objectives, learning targets, project ambitions
- Confidence levels:
  * 0.9-1.0: Explicitly stated facts ("I work on X", "My role is Y")
  * 0.7-0.8: Strongly implied from actions/discussions
  * 0.5-0.6: Inferred patterns (use sparingly, only for clear patterns)

**What Goes Where**:
- workContext: Current job, active projects, primary tech stack
- personalContext: Languages, personality, interests outside direct work tasks
- topOfMind: Multiple ongoing priorities and focus areas user cares about recently (gets updated most frequently)
  Should capture 3-5 concurrent themes: main work, side explorations, learning/tracking interests
- recentMonths: Detailed account of recent technical explorations and work
- earlierContext: Patterns from slightly older interactions still relevant
- longTermBackground: Unchanging foundational facts about the user

**Multilingual Content**:
- Preserve original language for proper nouns and company names
- Keep technical terms in their original form (DeepSeek, LangGraph, etc.)
- Note language capabilities in personalContext

Output Format (JSON):
{{
  "user": {{
    "workContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "personalContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "topOfMind": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "history": {{
    "recentMonths": {{ "summary": "...", "shouldUpdate": true/false }},
    "earlierContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "longTermBackground": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "newFacts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
  ],
  "factsToRemove": ["fact_id_1", "fact_id_2"]
}}

Important Rules:
- Only set shouldUpdate=true if there's meaningful new information
- Follow length guidelines: workContext/personalContext are concise (1-3 sentences), topOfMind and history sections are detailed (paragraphs)
- Include specific metrics, version numbers, and proper nouns in facts
- Only add facts that are clearly stated (0.9+) or strongly implied (0.7+)
- Remove facts that are contradicted by new information
- When updating topOfMind, integrate new focus areas while removing completed/abandoned ones
  Keep 3-5 concurrent focus themes that are still active and relevant
- Do NOT keep completed one-off requests in topOfMind (finished trip plans,
  product comparisons, temporary research summaries, checklist requests). Move
  only durable context to history, and remove stale completed items from active focus.
- For history sections, integrate new information chronologically into appropriate time period
- Preserve technical accuracy - keep exact names of technologies, companies, projects
- Focus on information useful for future interactions and personalization
- IMPORTANT: Do NOT record file upload events in memory. Uploaded files are
  session-specific and ephemeral — they will not be accessible in future sessions.
  Recording upload events causes confusion in subsequent conversations.

Return ONLY valid JSON, no explanation or markdown."""


# Prompt template for extracting facts from a single message
FACT_EXTRACTION_PROMPT = """Extract factual information about the user from this message.

Message:
{message}

Extract facts in this JSON format:
{{
  "facts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
  ]
}}

Categories:
- preference: User preferences (likes/dislikes, styles, tools)
- knowledge: User's expertise or knowledge areas
- context: Background context (location, job, projects)
- behavior: Behavioral patterns
- goal: User's goals or objectives

Rules:
- Only extract clear, specific facts
- Confidence should reflect certainty (explicit statement = 0.9+, implied = 0.6-0.8)
- Skip vague or temporary information

Return ONLY valid JSON."""


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken.

    Args:
        text: The text to count tokens for.
        encoding_name: The encoding to use (default: cl100k_base for GPT-4/3.5).

    Returns:
        The number of tokens in the text.
    """
    if not TIKTOKEN_AVAILABLE:
        # Fallback to character-based estimation if tiktoken is not available
        return len(text) // 4

    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        # Fallback to character-based estimation on error
        return len(text) // 4


def _merge_memory_scopes(global_memory: dict[str, Any], workspace_memory: dict[str, Any] | None) -> dict[str, Any]:
    if workspace_memory is None:
        return global_memory
    merged = {
        "version": global_memory.get("version") or workspace_memory.get("version") or "2.0",
        "lastUpdated": workspace_memory.get("lastUpdated") or global_memory.get("lastUpdated") or "",
        "user": dict(global_memory.get("user") or {}),
        "history": dict(global_memory.get("history") or {}),
        "facts": list(global_memory.get("facts") or []),
        "behaviorRules": list(global_memory.get("behaviorRules") or []),
    }
    # Workspace facts/rules are appended first at retrieval stage; here we merge the
    # descriptive sections by overriding non-empty workspace summaries.
    for section in ("user", "history"):
        ws_data = workspace_memory.get(section) or {}
        for key, val in ws_data.items():
            if not isinstance(val, dict):
                continue
            summary = str(val.get("summary") or "").strip()
            if summary:
                merged.setdefault(section, {})
                merged[section][key] = val
    merged["facts"] = list(workspace_memory.get("facts") or []) + merged["facts"]
    merged["behaviorRules"] = list(workspace_memory.get("behaviorRules") or []) + merged["behaviorRules"]
    return merged


_INJECTION_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")
_INJECTION_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "help",
    "home",
    "how",
    "is",
    "me",
    "my",
    "of",
    "or",
    "the",
    "to",
    "versus",
    "vs",
    "with",
}


def _lexical_relevance(query: str, content: str) -> float:
    query_tokens = {token.lower() for token in _INJECTION_TOKEN_RE.findall(query or "") if token.lower() not in _INJECTION_STOPWORDS}
    if not query_tokens:
        return 0.0
    content_tokens = {token.lower() for token in _INJECTION_TOKEN_RE.findall(content or "") if token.lower() not in _INJECTION_STOPWORDS}
    if not content_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / max(1, len(query_tokens))


def _is_relevant_injection_fact(fact: dict[str, Any], *, current_turn_text: str, threshold: float) -> bool:
    content = str(fact.get("content") or "")
    score = float(fact.get("score", 0.0) or 0.0)
    lexical = _lexical_relevance(current_turn_text, content)
    query_lower = current_turn_text.lower()
    content_lower = content.lower()
    location_sensitive_query = any(token in query_lower for token in ("my city", "where i live", "location", "rent", "housing", "relocat", "move from", "move to"))
    location_like_fact = any(token in content_lower for token in ("city", "location", "relocat", "singapore", "london", "dubai", "sydney", "tasmania", "hobart", "based in", "lives in"))
    # The vector-store score blends lexical match with confidence/recency. Require
    # a direct lexical signal too so high-confidence but unrelated facts do not
    # leak into generic direct-answer turns. Location-sensitive requests get a
    # narrow exception because the user may ask "my city" while the fact contains
    # only the actual place name.
    return score >= threshold and (lexical >= 0.12 or (location_sensitive_query and location_like_fact))


def format_memory_for_injection(
    memory_data: dict[str, Any],
    max_tokens: int = 2000,
    *,
    current_turn_text: str = "",
    workspace_memory_data: dict[str, Any] | None = None,
    workspace_id: str | None = None,
) -> str:
    """Format memory data for injection into system prompt.

    Args:
        memory_data: The memory data dictionary.
        max_tokens: Maximum tokens to use (counted via tiktoken for accuracy).

    Returns:
        Formatted memory string for system prompt injection.
    """
    if not memory_data and not workspace_memory_data:
        return ""

    merged_memory = _merge_memory_scopes(memory_data or {}, workspace_memory_data)
    cfg = get_memory_config()
    has_relevance_query = bool(current_turn_text.strip())
    facts_for_injection: list[dict[str, Any]] = []
    if has_relevance_query:
        scopes = [
            (MEMORY_SCOPE_WORKSPACE, workspace_id),
            (MEMORY_SCOPE_GLOBAL, "global"),
        ]
        try:
            facts_for_injection = get_memory_vector_store().query(
                query=current_turn_text,
                scopes=scopes,
                top_k=max(1, cfg.recall_top_k * 2),
            )
            facts_for_injection = [
                fact
                for fact in facts_for_injection
                if _is_relevant_injection_fact(
                    fact,
                    current_turn_text=current_turn_text,
                    threshold=cfg.injection_relevance_threshold,
                )
            ]
        except Exception:
            facts_for_injection = []
    if not has_relevance_query:
        facts_for_injection = list(merged_memory.get("facts") or [])
        facts_for_injection.sort(key=lambda f: float(f.get("confidence", 0.0)), reverse=True)
        facts_for_injection = facts_for_injection[:10]

    sections = []
    include_broad_context = not has_relevance_query

    # Format user context
    user_data = merged_memory.get("user", {})
    if user_data and include_broad_context:
        user_sections = []

        work_ctx = user_data.get("workContext", {})
        if work_ctx.get("summary"):
            user_sections.append(f"Work: {work_ctx['summary']}")

        personal_ctx = user_data.get("personalContext", {})
        if personal_ctx.get("summary"):
            user_sections.append(f"Personal: {personal_ctx['summary']}")

        top_of_mind = user_data.get("topOfMind", {})
        if top_of_mind.get("summary"):
            user_sections.append(f"Current Focus: {top_of_mind['summary']}")

        if user_sections:
            sections.append("User Context:\n" + "\n".join(f"- {s}" for s in user_sections))

    # Format history
    history_data = merged_memory.get("history", {})
    if history_data and include_broad_context:
        history_sections = []

        recent = history_data.get("recentMonths", {})
        if recent.get("summary"):
            history_sections.append(f"Recent: {recent['summary']}")

        earlier = history_data.get("earlierContext", {})
        if earlier.get("summary"):
            history_sections.append(f"Earlier: {earlier['summary']}")

        if history_sections:
            sections.append("History:\n" + "\n".join(f"- {s}" for s in history_sections))

    scoped_rules = [
        rule
        for rule in (merged_memory.get("behaviorRules") or [])
        if isinstance(rule, dict) and bool(rule.get("active", True)) and str(rule.get("instruction", "")).strip()
    ]
    if scoped_rules:
        lines = [f"- {str(rule.get('instruction')).strip()}" for rule in scoped_rules[:10]]
        sections.append("Behavior Rules:\n" + "\n".join(lines))

    if facts_for_injection:
        lines = []
        for fact in facts_for_injection[:15]:
            category = str(fact.get("category") or "context")
            content = str(fact.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"- [{category}] {content}")
        if lines:
            sections.append("Relevant Facts:\n" + "\n".join(lines))

    if not sections:
        return ""

    result = "\n\n".join(sections)

    # Use accurate token counting with tiktoken
    token_count = _count_tokens(result)
    if token_count > max_tokens:
        # Truncate to fit within token limit
        # Estimate characters to remove based on token ratio
        char_per_token = len(result) / token_count
        target_chars = int(max_tokens * char_per_token * 0.95)  # 95% to leave margin
        result = result[:target_chars] + "\n..."

    return result


def format_conversation_for_update(messages: list[Any]) -> str:
    """Format conversation messages for memory update prompt.

    Args:
        messages: List of conversation messages.

    Returns:
        Formatted conversation string.
    """
    lines = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))

        # Handle content that might be a list (multimodal)
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
            content = " ".join(text_parts) if text_parts else str(content)

        # Strip uploaded_files tags from human messages to avoid persisting
        # ephemeral file path info into long-term memory.  Skip the turn entirely
        # when nothing remains after stripping (upload-only message).
        if role == "human":
            content = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", "", str(content)).strip()
            if not content:
                continue

        # Truncate very long messages
        if len(str(content)) > 1000:
            content = str(content)[:1000] + "..."

        if role == "human":
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
