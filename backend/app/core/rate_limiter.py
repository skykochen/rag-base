"""
==========================================
  滑动窗口限流 —— 防止接口被频繁调用
==========================================

【什么是滑动窗口？】
想象一个 60 秒的窗口，随着时间推移不断向右滑动：

    假设限制是每分钟 5 次：

    时间轴：0s---10s---20s---30s---40s---50s---60s---70s---80s
    请求号：①②③④⑤

    在 50s 时：窗口[0s~60s]内有 5 个请求 → 达到上限，拒绝
    在 70s 时：窗口[10s~70s]内只有 4 个请求 → 允许（因为①已经离开了窗口）

【为什么不用固定窗口？】
固定窗口是每分钟重置计数器，比如 10:00:00~10:01:00 最多 60 次。
问题：用户在 10:00:59 发了 60 次，又在 10:01:00 发了 60 次，
实际上 2 秒内发了 120 次。滑动窗口能避免这种边界突刺。

【实现原理】
用 Redis 的 Sorted Set（有序集合）：
- member：每个请求生成一个唯一 ID（UUID4）
- score：请求到达时的时间戳
- 每次检查前先清理过期的 member（score < now - 60s）
- 统计剩下的 member 数量就是当前窗口内的请求数

【为什么不用现成的限流库？】
- slowapi / fastapi-limiter 功能完整
- 但本项目只用了「单用户每分钟 N 次」最简单的限流
- 自己实现能精确控制逻辑，也方便学习
"""

import time
from functools import lru_cache
from uuid import uuid4

from app.core.config import settings
from app.core.exceptions import RateLimitedError
from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)

# 窗口大小固定 60 秒
# 配合 settings.rate_limit_per_minute 实现「每分钟 N 次」
_WINDOW_SECONDS = 60


class RateLimiter:
    """
    滑动窗口限流器。

    以用户（或其他身份标识）为维度独立限流。
    每个用户有自己的 key（如 rag:rate_limit:user_123），互不影响。
    """

    def __init__(self) -> None:
        self._redis = get_redis()

    async def check(self, identity: str) -> None:
        """
        检查指定身份是否超过限流阈值。

        参数：
        - identity: 身份标识，例如 user_id 或 IP 地址

        行为：
        - 未超过阈值：静默返回（什么都不做）
        - 超过阈值：抛出 RateLimitedError

        【Redis pipeline 的作用】
        正常情况下，一条命令一次网络往返。
        这里需要执行 4 条命令（清理老数据 → 查询数量 → 添加新记录 → 设置过期），
        用 pipeline 打包成一次网络往返，大幅减少延迟。

        关键：pipeline 中的命令是顺序执行的，而且用事务模式（transaction=True），
        确保并发情况下数据一致。
        """
        now = time.time()
        key = f"rag:rate_limit:{identity}"  # Redis key，如 rag:rate_limit:user_abc

        async with self._redis.pipeline(transaction=True) as pipe:
            # 第1步：删除窗口之外的老记录
            # 删除 score 在 [0, now-60] 范围内的所有 member
            await pipe.zremrangebyscore(key, 0, now - _WINDOW_SECONDS)

            # 第2步：统计当前窗口内有多少条记录
            await pipe.zcard(key)

            # 第3步：把本次请求的时间戳加入集合
            # member 用 uuid4 保证唯一，这样同一毫秒的多次请求不会互相覆盖
            await pipe.zadd(key, {str(uuid4()): now})

            # 第4步：设置 key 的过期时间
            # 如果这个用户之后不再请求，60 秒后 key 自动删除，不占用内存
            await pipe.expire(key, _WINDOW_SECONDS)

            # 执行 pipeline，返回每条命令的结果
            _, count, *_ = await pipe.execute()

        limit = settings.rate_limit_per_minute
        # 注意：zcard 返回的是 zadd 之前的计数
        # 所以 count >= limit 就意味着本次请求会超过限制
        if int(count) >= limit:
            logger.warning(
                "rate limit exceeded: identity=%s count=%s limit=%s",
                identity,
                count,
                limit,
            )
            raise RateLimitedError(
                f"请求过于频繁，每分钟最多 {limit} 次，请稍后再试"
            )


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    """全局唯一的 RateLimiter 实例"""
    return RateLimiter()
