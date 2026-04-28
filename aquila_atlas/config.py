from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Git hosting tokens (optional — only needed for private repos or API rate-limit relief)
    github_token: str = ""
    gitlab_token: str = ""  # GitLab Personal Access Token (read_api + read_repository scope)
    gitea_token: str = ""  # Gitea/Forgejo access token

    # LLM provider — openai | ollama | openai_compatible | anthropic | mistral | huggingface
    llm_provider: str = "openai_compatible"
    # LLM model and credentials (shared by all providers)
    llm_base_url: str = "http://localhost:11434/v1"  # only used for openai/ollama/openai_compatible
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
    qdrant_url: str = ""  # set to Qdrant Cloud URL (overrides host/port)
    qdrant_api_key: str = ""  # Qdrant Cloud API key

    # PostgreSQL (session store)
    postgres_url: str = "postgresql://aquila:aquila@localhost:5432/aquila"

    # Valkey/Redis (job store — leave empty to use in-process dict fallback)
    valkey_url: str = "redis://localhost:6379/0"

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

    # ---------------------------------------------------------------------------
    # Identity, Auth & License (Phase 11)
    # ---------------------------------------------------------------------------

    # Auth mode: disabled | key | ldap | both
    # "disabled" (default) preserves all existing behaviour exactly.
    auth_mode: str = "disabled"

    # RS256-signed instance license JWT issued by the vendor.
    # Leave empty in open/dev mode.
    aquila_license_key: str = ""

    # HS256 secret used to sign session access/refresh tokens.
    # MUST be changed for production deployments.
    aquila_jwt_secret: str = "change-me-in-production"

    # Number of days of inactivity after which a seat is considered idle.
    seat_idle_days: int = 30

    # LDAP / Active Directory connection details (only needed when auth_mode=ldap|both)
    ldap_url: str = ""  # e.g. ldap://192.168.1.10:389
    ldap_bind_dn: str = ""  # e.g. cn=svc,dc=acme,dc=com
    ldap_bind_password: str = ""
    ldap_user_base: str = ""  # e.g. ou=users,dc=acme,dc=com
    ldap_user_filter: str = "(mail={username})"  # {username} is substituted at runtime
    ldap_required_group: str = ""  # optional DN; user must be member if set

    # Vendor RSA-2048 public key PEM used to validate license JWTs.
    # Leave empty to fall back to the embedded DEV key (see aquila_atlas/api/auth/license.py).
    # Generate a fresh pair with: python scripts/generate_keypair.py
    aquila_vendor_public_key: str = ""


settings = Settings()


def get_settings() -> Settings:
    return settings
