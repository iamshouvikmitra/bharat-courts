"""Configuration for bharat-courts."""

from pydantic_settings import BaseSettings


class BharatCourtsConfig(BaseSettings):
    """Configuration loaded from environment variables with BHARAT_COURTS_ prefix."""

    request_delay: float = 1.0  # seconds between requests
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    # Wide District Courts party-name searches genuinely take 30-60s on the
    # portal; 30 was too tight and made the SDK hit ReadTimeout + retry
    # against an endpoint that was actually about to respond.
    timeout: int = 60
    max_retries: int = 3
    log_level: str = "INFO"

    model_config = {"env_prefix": "BHARAT_COURTS_", "env_file": ".env", "extra": "ignore"}


config = BharatCourtsConfig()
