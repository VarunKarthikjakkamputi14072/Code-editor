from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "KubeRAG Gateway"
    debug: bool = False

    # Kafka
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_query_topic: str = "query-ingestion"
    kafka_ingest_topic: str = "doc-ingestion"
    kafka_result_topic: str = "query-results"

    # Redis
    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = 3600

    # Auth
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60


settings = Settings()
