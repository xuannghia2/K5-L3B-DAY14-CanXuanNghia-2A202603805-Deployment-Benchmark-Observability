"""Atomic sliding window shared by all workers."""
import hashlib
import uuid
from fastapi import HTTPException
from .config import settings
from .redis_client import r

WINDOW_LUA = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return math.max(1, math.ceil(tonumber(oldest[2]) + 60 - now))
end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('EXPIRE', KEYS[1], 61)
return 0
"""

def check_rate_limit(key: str) -> None:
    if settings.rate_limit_per_minute < 1:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
    digest = hashlib.sha256(key.encode()).hexdigest()
    retry = r.eval(WINDOW_LUA, 1, f"agent:rate:{digest}",
                   settings.rate_limit_per_minute, uuid.uuid4().hex)
    if retry:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(retry)})

