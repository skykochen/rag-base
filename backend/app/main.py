"""FastAPI 应用入口。"""
from contextlib import asynccontextmanager

from app.db.seed import seed_default_admin
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.error_handlers import register_error_handlers
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.observability import configure_observability
from app.api.routes import chat, documents, evaluations, health, auth, users, roles
from collections.abc import AsyncIterator
from app.mcp_server import knowledge_mcp

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期钩子：启动时做种子初始化，启动期间维护 MCP session manager。

    `mcp.session_manager.run()` 是 FastMCP streamable HTTP 必须的后台任务组，
    没有它工具调用会因 ASGI scope 缺失抛 RuntimeError；与 lifespan 绑定保证
    应用退出时干净收尾。
    """
    logger = get_logger(__name__)
    if not settings.jwt_secret:
        logger.error("JWT_SECRET 未配置，请检查 .env 文件")
    try:
        await seed_default_admin()
    except Exception:
        logger.exception("数据库种子初始化失败")

    async with knowledge_mcp.session_manager.run():
        yield

def create_app() -> FastAPI:
    configure_logging()
    configure_observability()
    logger = get_logger(__name__)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(health.router, prefix="/api")
    # 新增
    app.include_router(documents.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")

    app.include_router(evaluations.router, prefix="/api")

    app.include_router(auth.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(roles.router, prefix="/api")
    # MCP Server 同进程挂载到 /mcp：外部 Agent 用 Streamable HTTP transport 调用，
    # 鉴权复用 Authorization: Bearer JWT
    app.mount("/mcp", knowledge_mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    ), name="mcp")

    logger.info("app initialized: %s", settings.app_name)
    return app


app = create_app()