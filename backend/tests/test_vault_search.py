"""Unit tests for src.community.knowledge_vault_search."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from src.community.knowledge_vault_search.search import (
    VALID_CATEGORIES,
    VaultSearcher,
    _bm25_score,
    _excerpt,
    _tokenize,
)

# ---------------------------------------------------------------------------
# Pure-function tests (no disk I/O)
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_numbers_included(self):
        assert "2024" in _tokenize("report 2024")

    def test_punctuation_stripped(self):
        tokens = _tokenize("foo, bar! baz.")
        assert tokens == ["foo", "bar", "baz"]

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_lowercased(self):
        assert _tokenize("LangGraph") == ["langgraph"]


class TestBM25Score:
    def test_zero_for_no_match(self):
        score = _bm25_score(["python"], ["java", "kotlin"], avg_dl=2.0)
        assert score == 0.0

    def test_positive_for_match(self):
        score = _bm25_score(["python"], ["python", "is", "great"], avg_dl=3.0)
        assert score > 0.0

    def test_higher_freq_scores_higher(self):
        low = _bm25_score(["cat"], ["cat", "dog", "bird"], avg_dl=3.0)
        high = _bm25_score(["cat"], ["cat", "cat", "cat"], avg_dl=3.0)
        assert high > low

    def test_empty_query_returns_zero(self):
        assert _bm25_score([], ["cat", "dog"], avg_dl=2.0) == 0.0

    def test_empty_doc_returns_zero(self):
        assert _bm25_score(["cat"], [], avg_dl=2.0) == 0.0


class TestExcerpt:
    def test_returns_string(self):
        result = _excerpt("The quick brown fox jumps over the lazy dog", ["fox"])
        assert isinstance(result, str)

    def test_contains_context_around_match(self):
        body = "nothing here. The target word appears in the middle. nothing here."
        result = _excerpt(body, ["target"])
        assert "target" in result

    def test_falls_back_to_beginning_when_no_match(self):
        result = _excerpt("hello world this is a test", ["zzznomatch"])
        assert result.startswith("hello")

    def test_max_length(self):
        long_body = "word " * 1000
        result = _excerpt(long_body, ["word"])
        assert len(result) <= 400


# ---------------------------------------------------------------------------
# VaultSearcher tests (use tmp_path for fake vault)
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path) -> Path:
    """Create a minimal vault structure under tmp_path and return the root."""
    vault = tmp_path / "knowledge_vault"
    compiled = vault / "02_compiled"
    for cat in VALID_CATEGORIES:
        (compiled / cat).mkdir(parents=True, exist_ok=True)
    return vault


def _write_page(vault: Path, category: str, filename: str, title: str, body: str, tags: list[str] | None = None) -> Path:
    tags_str = json.dumps([str(t) for t in (tags or [])])
    content = f"---\ntitle: {json.dumps(title)}\ntags: {tags_str}\n---\n\n{body}"
    path = vault / "02_compiled" / category / filename
    path.write_text(content, encoding="utf-8")
    return path


class TestVaultSearcherEmptyVault:
    def test_returns_empty_list_when_no_pages(self, tmp_path):
        vault = _make_vault(tmp_path)
        searcher = VaultSearcher(vault)
        assert searcher.search("anything") == []

    def test_returns_empty_list_when_compiled_dir_missing(self, tmp_path):
        vault = tmp_path / "knowledge_vault"
        vault.mkdir(parents=True)
        searcher = VaultSearcher(vault)
        assert searcher.search("anything") == []


class TestVaultSearcherBasic:
    def test_finds_matching_page(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "sources", "langgraph.md", "LangGraph Overview", "LangGraph is a graph-based agent framework.")
        searcher = VaultSearcher(vault)
        results = searcher.search("LangGraph agent")
        assert len(results) == 1
        assert results[0]["title"] == "LangGraph Overview"

    def test_returns_no_results_for_zero_score(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "sources", "unrelated.md", "Cooking Tips", "Boil pasta until al dente.")
        searcher = VaultSearcher(vault)
        results = searcher.search("quantum physics semiconductor")
        assert results == []

    def test_result_fields_present(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "concepts", "memory.md", "Memory Systems", "Memory is important for agents.")
        searcher = VaultSearcher(vault)
        results = searcher.search("memory agents")
        assert len(results) == 1
        r = results[0]
        for key in ("title", "category", "score", "excerpt", "tags", "source_url", "path"):
            assert key in r, f"Missing field: {key}"

    def test_category_field_correct(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "syntheses", "ai_synthesis.md", "AI Research Synthesis", "AI is transforming many industries.")
        searcher = VaultSearcher(vault)
        results = searcher.search("AI industries")
        assert results[0]["category"] == "syntheses"

    def test_score_is_positive(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "sources", "doc.md", "Test Doc", "Python is a great programming language.")
        searcher = VaultSearcher(vault)
        results = searcher.search("Python programming")
        assert results[0]["score"] > 0


class TestVaultSearcherRanking:
    def test_more_relevant_page_ranks_higher(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "sources", "high.md", "High Relevance", "Python Python Python is the best language for data science.")
        _write_page(vault, "sources", "low.md", "Low Relevance", "Java is also a popular language for enterprise software.")
        searcher = VaultSearcher(vault)
        results = searcher.search("Python")
        assert results[0]["title"] == "High Relevance"

    def test_results_sorted_descending_by_score(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "sources", "a.md", "A", "machine learning machine learning machine learning deep learning")
        _write_page(vault, "sources", "b.md", "B", "machine learning introduction")
        _write_page(vault, "sources", "c.md", "C", "unrelated content about cooking and food")
        searcher = VaultSearcher(vault)
        results = searcher.search("machine learning")
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)


class TestVaultSearcherLimit:
    def test_respects_limit(self, tmp_path):
        vault = _make_vault(tmp_path)
        for i in range(10):
            _write_page(vault, "sources", f"doc{i}.md", f"Doc {i}", f"neural network deep learning model {i}")
        searcher = VaultSearcher(vault)
        results = searcher.search("neural network deep learning", limit=3)
        assert len(results) <= 3

    def test_limit_capped_at_20_by_tool(self, tmp_path):
        # The tool enforces min(20, limit); VaultSearcher itself respects whatever is passed.
        vault = _make_vault(tmp_path)
        for i in range(5):
            _write_page(vault, "sources", f"doc{i}.md", f"Doc {i}", f"content about topic {i}")
        searcher = VaultSearcher(vault)
        results = searcher.search("content topic", limit=100)
        assert len(results) <= 5  # only 5 pages exist


class TestVaultSearcherCategoryFilter:
    def test_only_searches_specified_categories(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "sources", "src.md", "Source Page", "blockchain distributed ledger technology")
        _write_page(vault, "concepts", "con.md", "Concept Page", "blockchain consensus mechanism")
        searcher = VaultSearcher(vault)
        results = searcher.search("blockchain", categories=["concepts"])
        assert all(r["category"] == "concepts" for r in results)

    def test_ignores_invalid_categories(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "sources", "page.md", "Page", "content about artificial intelligence")
        searcher = VaultSearcher(vault)
        # "nonexistent" is silently dropped; "sources" is valid
        results = searcher.search("artificial intelligence", categories=["sources", "nonexistent"])
        assert len(results) == 1

    def test_all_categories_searched_by_default(self, tmp_path):
        vault = _make_vault(tmp_path)
        for cat in VALID_CATEGORIES:
            _write_page(vault, cat, f"{cat}.md", f"{cat.title()} Page", f"renewable energy solar wind {cat}")
        searcher = VaultSearcher(vault)
        results = searcher.search("renewable energy solar")
        returned_cats = {r["category"] for r in results}
        assert returned_cats == set(VALID_CATEGORIES)


class TestVaultSearcherTags:
    def test_tags_returned_in_result(self, tmp_path):
        vault = _make_vault(tmp_path)
        _write_page(vault, "entities", "openai.md", "OpenAI", "OpenAI develops GPT models.", tags=["ai", "company"])
        searcher = VaultSearcher(vault)
        results = searcher.search("OpenAI GPT")
        assert results[0]["tags"] == ["ai", "company"]

    def test_tags_boost_relevance(self, tmp_path):
        vault = _make_vault(tmp_path)
        # One page has the query term in tags (boosted via text field), another only in body
        _write_page(vault, "entities", "tagged.md", "Tagged Page", "some general content here.", tags=["transformer"])
        _write_page(vault, "entities", "body.md", "Body Only", "transformer architecture is key to modern NLP.")
        searcher = VaultSearcher(vault)
        results = searcher.search("transformer")
        # Both should appear; tagged page should score because title repeated + tag text
        titles = [r["title"] for r in results]
        assert "Tagged Page" in titles
        assert "Body Only" in titles


# ---------------------------------------------------------------------------
# Tool-level tests (test the @tool wrapper)
# ---------------------------------------------------------------------------


class TestQueryKnowledgeVaultTool:
    """Test the LangChain tool wrapper in isolation by monkey-patching _get_searcher."""

    def _invoke(self, monkeypatch, results, **kwargs):
        """Helper: patch _get_searcher and invoke the tool."""
        from src.community.knowledge_vault_search import tool as tool_module

        mock_searcher = MagicMock()
        mock_searcher.search.return_value = results
        monkeypatch.setattr(tool_module, "_get_searcher", lambda: mock_searcher)
        monkeypatch.setattr(tool_module, "_searcher", None)

        from src.community.knowledge_vault_search.tool import query_knowledge_vault_tool

        return query_knowledge_vault_tool.invoke({"query": "test query", **kwargs})

    def test_returns_json_string(self, monkeypatch, tmp_path):
        raw = self._invoke(monkeypatch, [{"title": "T", "category": "sources", "score": 1.0, "excerpt": "x", "tags": [], "source_url": "", "path": "/p"}])
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_ok_true_with_results(self, monkeypatch, tmp_path):
        raw = self._invoke(monkeypatch, [{"title": "T", "category": "sources", "score": 1.0, "excerpt": "x", "tags": [], "source_url": "", "path": "/p"}])
        parsed = json.loads(raw)
        assert parsed["ok"] is True
        assert len(parsed["results"]) == 1

    def test_ok_true_empty_results(self, monkeypatch, tmp_path):
        raw = self._invoke(monkeypatch, [])
        parsed = json.loads(raw)
        assert parsed["ok"] is True
        assert parsed["results"] == []
        assert "message" in parsed

    def test_invalid_category_returns_error(self, monkeypatch, tmp_path):
        from src.community.knowledge_vault_search import tool as tool_module

        mock_searcher = MagicMock()
        monkeypatch.setattr(tool_module, "_get_searcher", lambda: mock_searcher)

        from src.community.knowledge_vault_search.tool import query_knowledge_vault_tool

        raw = query_knowledge_vault_tool.invoke({"query": "test", "categories": ["invalid_cat"]})
        parsed = json.loads(raw)
        assert parsed["ok"] is False
        assert parsed["error"] == "invalid_categories"

    def test_limit_clamped_to_1_minimum(self, monkeypatch):
        from src.community.knowledge_vault_search import tool as tool_module

        mock_searcher = MagicMock()
        mock_searcher.search.return_value = []
        monkeypatch.setattr(tool_module, "_get_searcher", lambda: mock_searcher)

        from src.community.knowledge_vault_search.tool import query_knowledge_vault_tool

        query_knowledge_vault_tool.invoke({"query": "test", "limit": -5})
        mock_searcher.search.assert_called_once()
        call_args = mock_searcher.search.call_args
        assert call_args.kwargs.get("limit", call_args.args[2] if len(call_args.args) > 2 else None) == 1

    def test_limit_clamped_to_20_maximum(self, monkeypatch):
        from src.community.knowledge_vault_search import tool as tool_module

        mock_searcher = MagicMock()
        mock_searcher.search.return_value = []
        monkeypatch.setattr(tool_module, "_get_searcher", lambda: mock_searcher)

        from src.community.knowledge_vault_search.tool import query_knowledge_vault_tool

        query_knowledge_vault_tool.invoke({"query": "test", "limit": 999})
        mock_searcher.search.assert_called_once()
        call_args = mock_searcher.search.call_args
        assert call_args.kwargs.get("limit", call_args.args[2] if len(call_args.args) > 2 else None) == 20

    def test_exception_returns_ok_false(self, monkeypatch):
        from src.community.knowledge_vault_search import tool as tool_module

        mock_searcher = MagicMock()
        mock_searcher.search.side_effect = RuntimeError("disk error")
        monkeypatch.setattr(tool_module, "_get_searcher", lambda: mock_searcher)

        from src.community.knowledge_vault_search.tool import query_knowledge_vault_tool

        raw = query_knowledge_vault_tool.invoke({"query": "test"})
        parsed = json.loads(raw)
        assert parsed["ok"] is False
        assert "disk error" in parsed["error"]
