from aquila_atlas.config import Settings


def test_settings_defaults() -> None:
    s = Settings()
    assert s.neo4j_uri == "bolt://localhost:7687"
    assert s.qdrant_port == 6333
    assert s.valkey_url == "valkey://localhost:6379"
