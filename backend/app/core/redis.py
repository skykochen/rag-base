"""
==========================================
  Redis 异步客户端 —— 缓存和限流的底层存储
==========================================

【Redis 在这个项目中的角色】
Redis 有三种不同的用途，用不同的 db 索引隔离：
- db 0：应用直接使用（语义缓存 + 滑动窗口限流）—— 就是这里
- db 1：Celery 消息队列（Broker）
- db 2：Celery 任务结果存储（Backend）

【为什么用不同的 db？】
Redis 支持 0-15 共 16 个逻辑数据库。
如果混在一起，key 可能冲突，也方便独立管理（比如清空缓存不影响 Celery 任务）。

【为什么需要连接池？】
每次请求都创建新的 Redis 连接很慢。
连接池维护一组已经建好的连接，请求来了直接复用。
"""

from functools import lru_cache

import redis.asyncio as aioredis

from app.core.config import settings


@lru_cache(maxsize=1)
def get_redis() -> aioredis.Redis:
    """
    返回全局唯一的 Redis 异步客户端实例。

    【为什么用 lru_cache？】
    - 确保整个应用只有一个 Redis 连接池
    - 多次调用 get_redis() 返回同一个实例
    - 避免重复创建连接

    【decode_responses=True】
    - Redis 返回的是字节（bytes），比如 b"OK"
    - 加上这个参数后自动解码成字符串 "OK"
    - 本项目没有二进制数据需求，所以直接解码更方便

    【aioredis 说明】
    - redis-py 库从 4.2 版本开始内置了异步支持
    - import redis.asyncio as aioredis 就是导入异步版本
    - 不冲突：同步代码 import redis，异步代码 import redis.asyncio
    """
    return aioredis.from_url(settings.redis_url, decode_responses=True)
