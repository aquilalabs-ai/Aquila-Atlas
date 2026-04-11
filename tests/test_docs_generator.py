from aquila_atlas.reasoning.docs_generator import generate_docs


class DummyLLM:
    def invoke(self, prompt):
        return type("LLMResponse", (), {"content": "# Flow doc\n\nGenerated content"})


class DummyService:
    def get_entry_points(self, repo_id: str):
        return [{"name": "main", "file_path": "app.py"}]

    def get_call_chain(self, repo_id: str, start_id: str, max_depth: int = 6):
        return [{"name": "helper", "file_path": "utils.py", "depth": 1}]

    def search(self, query: str, repo_id: str, top_k: int = 20):
        return []


def test_generate_docs_flows_accepts_exclude_extensions(monkeypatch) -> None:
    monkeypatch.setattr(
        "aquila_atlas.reasoning.docs_generator._make_llm",
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
