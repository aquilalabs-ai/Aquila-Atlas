from aquila_atlas.reasoning.tools import get_tools


def test_get_tools_includes_expected_tools() -> None:
    class DummyService:
        pass

    svc = DummyService()
    tools = get_tools(service=svc)
    tool_names = {tool.name for tool in tools}

    expected = {
        "semantic_search",
        "file_reader",
        "summarize",
        "generate_docstring",
        "generate_mermaid",
        "validate_mermaid",
    }
    assert tool_names == expected
