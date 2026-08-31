"""
==========================================
  健康检查接口 —— 验证各服务是否正常
==========================================

【这些接口有什么用？】
- 部署后验证后端是否能正常响应
- 监控系统定期检查各组件连通性
- 排查问题时快速定位是哪个组件出了问题

【三个检查点】
GET /health       → 应用本身是否在运行
GET /health/db    → 数据库是否能连上
GET /health/cos   → 对象存储是否能连上
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings
from app.core.logging import get_logger
from app.storage.cos_client import get_cos_client

logger = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# 用 Literal 而非 str，让 OpenAPI 文档精确列出三个可能值
HealthStatusValue = Literal["ok", "error", "not_configured"]


class HealthStatus(BaseModel):
    status: HealthStatusValue
    detail: str | None = None  # 失败时的详细原因


@router.get("", response_model=HealthStatus, operation_id="healthApp")
async def health() -> HealthStatus:
    """
    最基本的健康检查：应用是否在运行。

    只要这个接口能返回，就说明 FastAPI 应用启动了。
    不需要数据库连接，不会因为数据库挂了而报错。
    """
    return HealthStatus(status="ok")


@router.get("/db", response_model=HealthStatus, operation_id="healthDb")
async def health_db(session: DbSession) -> HealthStatus:
    """
    数据库健康检查：跑一句 SELECT 1 验证连通性。

    text("SELECT 1") 是 SQLAlchemy 的原生 SQL 执行方式。
    如果能查到结果，说明数据库连接正常。
    """
    try:
        result = await session.execute(text("SELECT 1"))
        result.scalar_one()
        return HealthStatus(status="ok")
    except Exception as exc:
        logger.exception("db health check failed")
        return HealthStatus(status="error", detail=str(exc))


@router.get("/cos", response_model=HealthStatus, operation_id="healthCos")
async def health_cos() -> HealthStatus:
    """
    COS 对象存储健康检查。

    未配置 COS 时不报 500，而是返回 not_configured，
    让监控系统知道"这不是故障，只是没配"。
    """
    if not settings.cos_configured:
        return HealthStatus(status="not_configured", detail="COS 凭据未在 .env 中配置")

    try:
        ok = await get_cos_client().ping()
    except Exception as exc:
        logger.exception("cos health check failed")
        return HealthStatus(status="error", detail=str(exc))

    return HealthStatus(status="ok") if ok else HealthStatus(status="error", detail="head_bucket 失败")
