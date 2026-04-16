from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # GitHub (optional — only needed for GitHub source loader)
    github_token: str = ""

    # LLM — OpenAI-compatible endpoint (default: Ollama local)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "llama3.2"

    # Embeddings — OpenAI-compatible endpoint (default: Ollama local)
    embeddings_base_url: str = "http://localhost:11434/v1"
    embeddings_api_key: str = "ollama"
    embeddings_model: str = "nomic-embed-text"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # PostgreSQL (session store)
    postgres_url: str = "postgresql://aquila:aquila@localhost:5432/aquila"

    # Neo4j MCP server (HTTP transport)
    mcp_url: str = "http://localhost:8080/mcp"

    # API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: str = ""  # leave blank to disable auth (dev mode)

    # CORS — comma-separated allowed origins for the frontend
    # Default covers the Vite dev server ports
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Conversation compaction — summarise history when it exceeds this many tokens
    # (estimated at 4 chars per token). The last 4 messages (2 turns) are always
    # kept verbatim; older messages are replaced by an LLM-generated summary.
    max_history_tokens: int = 2000

    # LangSmith (optional — leave blank to disable tracing)
    langsmith_api_key: str = ""
    langsmith_project: str = "aquila-atlas"


settings = Settings()


def get_settings() -> Settings:
    return settings
