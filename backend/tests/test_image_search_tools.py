import json
from unittest.mock import MagicMock, patch

from src.community.image_search import tools


def _mock_tool_config(model_extra: dict):
    cfg = MagicMock()
    cfg.model_extra = model_extra
    return cfg


@patch("src.community.image_search.tools.httpx.request")
@patch("src.community.image_search.tools.get_app_config")
def test_image_search_searxng_get_success(mock_get_app_config, mock_request):
    app_cfg = MagicMock()
    app_cfg.get_tool_config.side_effect = [
        _mock_tool_config({"base_url": "http://localhost:8080", "method": "GET", "max_results": 4}),
        _mock_tool_config({"base_url": "http://localhost:8080"}),
    ]
    mock_get_app_config.return_value = app_cfg

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "results": [
            {"title": "A", "img_src": "https://img-a", "thumbnail_src": "https://thumb-a", "url": "https://source-a"},
            {"title": "B", "img_src": "https://img-b", "url": "https://source-b"},
        ]
    }
    mock_request.return_value = response

    result = tools.image_search_tool.run("city skyline", max_results=2)
    parsed = json.loads(result)

    assert parsed["total_results"] == 2
    assert parsed["results"][0]["image_url"] == "https://img-a"
    assert parsed["results"][1]["thumbnail_url"] == "https://img-b"

    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["params"]["categories"] == "images"


@patch("src.community.image_search.tools.get_app_config")
def test_image_search_invalid_method(mock_get_app_config):
    app_cfg = MagicMock()
    app_cfg.get_tool_config.side_effect = [_mock_tool_config({"method": "PUT"}), _mock_tool_config({})]
    mock_get_app_config.return_value = app_cfg

    result = tools.image_search_tool.run("test")
    parsed = json.loads(result)
    assert "Unsupported SearXNG method" in parsed["error"]
