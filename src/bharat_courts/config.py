"""Configuration for bharat-courts."""

from pydantic_settings import BaseSettings


class BharatCourtsConfig(BaseSettings):
    """Configuration loaded from environment variables with BHARAT_COURTS_ prefix."""

    request_delay: float = 1.0  # seconds between requests
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    timeout: int = 30
    max_retries: int = 3
    log_level: str = "INFO"

    model_config = {"env_prefix": "BHARAT_COURTS_", "env_file": ".env", "extra": "ignore"}


config = BharatCourtsConfig()
