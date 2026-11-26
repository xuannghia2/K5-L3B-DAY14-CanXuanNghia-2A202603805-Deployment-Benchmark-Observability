"""UTC daily/monthly budgets persisted across restarts in Redis."""
from datetime import datetime, timezone
from fastapi import HTTPException
from .config import settings
from .redis_client import r

def budget_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"agent:cost:day:{now:%Y-%m-%d}", f"agent:cost:month:{now:%Y-%m}"

def check_budget() -> None:
    day, month = r.mget(budget_keys())
    if (float(day or 0) >= settings.daily_budget_usd
            or float(month or 0) >= settings.monthly_budget_usd):
        raise HTTPException(402, "LLM budget exhausted")

def record_cost(input_tokens: int, output_tokens: int) -> float:
    cost = (input_tokens * settings.price_input_per_1k
            + output_tokens * settings.price_output_per_1k) / 1000
    day, month = budget_keys()
    with r.pipeline(transaction=True) as pipe:
        pipe.incrbyfloat(day, cost).expire(day, 172800)
        pipe.incrbyfloat(month, cost).expire(month, 2764800)
        pipe.execute()
    return cost

