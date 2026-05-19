"""Built-in subagent configurations."""

from .bash_agent import BASH_AGENT_CONFIG
from .comparison_dimension_researcher import COMPARISON_DIMENSION_RESEARCHER_CONFIG
from .docs_explorer import DOCS_EXPLORER_CONFIG
from .general_purpose import GENERAL_PURPOSE_CONFIG
from .source_researcher import SOURCE_RESEARCHER_CONFIG
from .synthesis_reviewer import SYNTHESIS_REVIEWER_CONFIG

__all__ = [
    "GENERAL_PURPOSE_CONFIG",
    "BASH_AGENT_CONFIG",
    "SOURCE_RESEARCHER_CONFIG",
    "DOCS_EXPLORER_CONFIG",
    "COMPARISON_DIMENSION_RESEARCHER_CONFIG",
    "SYNTHESIS_REVIEWER_CONFIG",
]

# Registry of built-in subagents
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "source-researcher": SOURCE_RESEARCHER_CONFIG,
    "docs-explorer": DOCS_EXPLORER_CONFIG,
    "comparison-dimension-researcher": COMPARISON_DIMENSION_RESEARCHER_CONFIG,
    "synthesis-reviewer": SYNTHESIS_REVIEWER_CONFIG,
}
