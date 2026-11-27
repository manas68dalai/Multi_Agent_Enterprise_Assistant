from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "ollama"
    structured_method: str = "auto"

    # --- Ollama ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    ollama_fast_model: str = ""
    ollama_num_ctx: int = 8192
    ollama_reasoning: str = "off"
    ollama_keep_alive: str = "30m"

    # --- Groq ---
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_fast_model: str = ""
    groq_reasoning_effort: str = "low"
    groq_max_retries: int = 6
    groq_timeout: float = 60

    # --- Other cloud providers (optional) ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = ""

    # --- Embeddings (always local Hugging Face) ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # --- Databases ---
    mongo_uri: str
    mongo_db: str = "enterprise"
    qdrant_url: str = "http://localhost:6333"
    qdrant_docs_collection: str = "enterprise_docs"
    qdrant_memory_collection: str = "agent_memory"

    # --- Memory ---
    checkpointer: str = "mongo"
    checkpoint_db: str = "enterprise_checkpoints"
    memory_enabled: bool = True
    memory_top_k: int = 4
    memory_min_score: float = 0.55
    memory_core_limit: int = 5
    memory_dedup_score: float = 0.92
    memory_max_facts_per_turn: int = 3

    # --- API ---
    api_keys: str = ""                        
    admin_users: str = ""                    
    api_max_concurrent_turns: int = 4
    max_upload_mb: int = 10

    # --- Observability ---
    environment: str = "dev"
    log_level: str = "INFO"
    log_format: str = "text"                  
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "enterprise-assistant"
    langsmith_hide_io: bool = False       
    langsmith_endpoint: str = ""             
    langsmith_workspace_id: str = ""           

settings = Settings()