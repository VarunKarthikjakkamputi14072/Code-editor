from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Kafka
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_query_topic: str = "query-ingestion"
    kafka_ingest_topic: str = "doc-ingestion"
    kafka_result_topic: str = "query-results"
    kafka_group_id: str = "rag-workers"
    kafka_max_poll_records: int = 10

    # PostgreSQL
    postgres_dsn: str = "postgresql://kuberag:kuberag@postgres:5432/kuberag"

    # Redis
    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = 3600

    # Ollama
    ollama_base_url: str = "http://ollama:11434"
    embed_model: str = "nomic-embed-text"
    gen_model: str = "llama3"
    generation_timeout: int = 120

    # RAG
    chunk_size: int = 512
    chunk_overlap: int = 64


settings = Settings()
