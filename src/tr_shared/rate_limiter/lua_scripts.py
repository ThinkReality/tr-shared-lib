"""Atomic Lua scripts for Redis-based rate limiting.

Extracted and consolidated from:
- tr-api-gateway/app/core/rate_limiter.py (lines 37-75)
- tr-lead-management/app/core/rate_limiter.py (lines 81-88)

Both scripts return ``{count, is_over}`` for uniform result parsing.
"""

# Sliding window — ZSET-based (more precise, slightly more memory)
# Used by: gateway, media-service
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_size = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

-- Remove entries outside the sliding window
redis.call('zremrangebyscore', key, 0, now - window_size)

-- Add current request with timestamp as both score and member
redis.call('zadd', key, now, now .. ':' .. math.random(1000000))

-- Count requests in window
local count = redis.call('zcard', key)

-- Set expiration to window_size seconds from now (cleanup)
redis.call('expire', key, math.ceil(window_size))

-- Return count and whether blocked
return {count, count > limit and 1 or 0}
"""

# Fixed window — INCR + conditional EXPIRE (fastest, least memory)
# Used by: lead-management, HR, admin-panel, crm-backend
FIXED_WINDOW_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

-- Increment counter
local count = redis.call('incr', key)

-- Set expiration only on first request in the window
if count == 1 then
    redis.call('expire', key, ttl)
end

-- Get remaining TTL for reset_at calculation
local remaining_ttl = redis.call('ttl', key)

-- Return count, whether blocked, and TTL
return {count, count > limit and 1 or 0, remaining_ttl}
"""
