"""Tests for the documentation generator."""

from __future__ import annotations

from aquila_atlas.reasoning.docs_generator import generate_docs


class _DummyLLMResponse:
    content = "# Flow doc\n\nGenerated content"


class DummyLLM:
    def invoke(self, prompt: object) -> _DummyLLMResponse:
        return _DummyLLMResponse()


class DummyService:
    def get_entry_points(self, repo_id: str) -> list[dict]:
        return [{"name": "main", "file_path": "app.py", "out_degree": 2}]

    def get_call_chain(self, repo_id: str, start_id: str, max_depth: int = 6) -> list[dict]:
        return [{"name": "helper", "file_path": "utils.py", "depth": 1}]

    def search(self, query: str, repo_id: str, top_k: int = 20) -> list:
        return []


def test_generate_docs_flows_accepts_exclude_extensions(monkeypatch) -> None:
    monkeypatch.setattr(
        "aquila_atlas.reasoning.docs._llm._make_llm",
        lambda: DummyLLM(),
    )

    svc = DummyService()
    result = generate_docs(
        svc,
        repo_id="repo1",
        scope="flows",
        style="technical",
        language="en",
        exclude_extensions=[".md"],
    )

    assert result["flows/app/main.md"].startswith("# Flow doc")


def test_generate_docs_flows_no_entry_points(monkeypatch) -> None:
    """When no entry points exist the generator returns a placeholder doc."""
    monkeypatch.setattr(
        "aquila_atlas.reasoning.docs._llm._make_llm",
        lambda: DummyLLM(),
    )

    class EmptyService(DummyService):
        def get_entry_points(self, repo_id: str) -> list[dict]:
            return []

    result = generate_docs(EmptyService(), repo_id="repo1", scope="flows")

    assert "flows/no_entry_points.md" in result
    assert "No meaningful entry points" in result["flows/no_entry_points.md"]
