"""
==========================================
  数据库连接管理 —— Engine / Session 工厂
==========================================

【核心概念】
- Engine（引擎）：数据库连接池，负责管理底层连接
  - 应用启动时创建一次，全局复用
  - 本身是线程安全的，所有请求共享

- Session（会话）：与数据库的一次"对话"
  - 每次请求创建新的 Session
  - 用完关闭，归还连接到连接池

- async_sessionmaker：Session 的工厂
  - 不是 Session 本身，而是"生产 Session 的机器"
  - 每次调用它都会得到一个全新的 Session

【事务边界在哪？】
重要原则：repository 负责增删改查，service 决定什么时候提交（commit）。
这个文件只提供 Session，不控制事务边界。
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# 创建全局唯一的异步引擎（连接池）
# echo=False 表示不打印 SQL 语句，生产环境关掉
# pool_pre_ping=True 表示每次从连接池取连接时先 ping 一下，
# 如果连接已断开（比如数据库重启过），自动换一条新连接
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

# Session 工厂：每次调用 AsyncSessionLocal() 返回一个新 Session
# expire_on_commit=False：commit 后对象不会过期（仍然可以访问属性）
# autoflush=False：查询前不自动 flush，需要我们手动 flush
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """
    FastAPI 依赖注入函数：为每个请求创建一个 Session，请求结束自动关闭。

    用法：
        @router.get("/items")
        async def get_items(session: DbSession):
            ...

    yield 模式的原理：
    1. 进入时：创建 Session，yield 给路由函数用
    2. 退出时（函数 return 后）：自动关闭 Session，归还连接到连接池
    """
    async with AsyncSessionLocal() as session:
        yield session
