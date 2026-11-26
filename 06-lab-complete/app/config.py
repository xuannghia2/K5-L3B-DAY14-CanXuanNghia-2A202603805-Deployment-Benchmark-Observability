"""12-Factor configuration; secrets come from the runtime."""
import os
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "10")))
    daily_budget_usd: float = field(default_factory=lambda: float(os.getenv("DAILY_BUDGET_USD", "1")))
    monthly_budget_usd: float = field(default_factory=lambda: float(os.getenv("MONTHLY_BUDGET_USD", "10")))
    price_input_per_1k: float = field(default_factory=lambda: float(os.getenv("PRICE_INPUT_PER_1K", "0.00015")))
    price_output_per_1k: float = field(default_factory=lambda: float(os.getenv("PRICE_OUTPUT_PER_1K", "0.0006")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

settings = Settings()

