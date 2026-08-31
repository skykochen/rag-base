"""
==========================================
  FastAPI 依赖注入 —— 共享的"基础设施"
==========================================

【什么是依赖注入？】
想象你写一个路由函数，需要一个数据库连接和一个当前用户。
没有依赖注入时：
    @router.get("/items")
    async def get_items(request: Request):
        token = request.headers.get("Authorization")
        user = parse_token(token)
        session = create_session()
        ...

每个路由都重复写这些"准备工作"。

有依赖注入时：
    @router.get("/items")
    async def get_items(user: CurrentUser, session: DbSession):
        ...

FastAPI 自动帮你完成准备工作，你只需要声明「我需要什么」。

【本文件提供的依赖】
- DbSession：数据库连接 session（每个请求独立）
- CurrentUser：当前登录用户（解析 JWT token）
- CurrentAdmin：当前登录的管理员用户（如果是普通用户会 403）
- RateLimited：限流检查（写接口用）
"""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import PermissionDeniedError, UnauthorizedError
from app.core.rate_limiter import get_rate_limiter
from app.core.security import decode_access_token
from app.db.models import User, UserStatus
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_session
from app.services.permission_service import is_admin


def _parse_bearer_token(authorization: str | None) -> str:
    """
    从 Authorization header 中提取 Bearer token。

    请求头格式：Authorization: Bearer <token>

    参数：
    - authorization: HTTP 请求头 Authorization 的值

    返回：
    - token 字符串

    异常：
    - 请求头缺失 → 401
    - 格式不是 Bearer → 401
    """
    if not authorization:
        raise UnauthorizedError("请先登录")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedError("无效的访问凭证")
    return token


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User:
    """
    解析 JWT token，查库拿到当前登录用户。

    【为什么每次请求都查一次数据库？】
    有人可能会说"把用户信息直接放在 token 里不就不用查库了？"
    但那样的话：
    - 用户被禁用后，token 没到期之前仍然有效
    - 用户的角色变了，但 token 里还是旧角色
    所以我们只在 token 里放 user_id，每次请求重新查库，
    保证状态永远是最新的。
    """
    token = _parse_bearer_token(authorization)
    subject = decode_access_token(token)

    try:
        from uuid import UUID
        user_id = UUID(subject)  # token 里的 sub 是 user_id 字符串
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError("无效的访问凭证") from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("用户不存在或已被删除")
    if user.status != UserStatus.ACTIVE:
        raise UnauthorizedError("账号已被禁用")
    return user


async def get_current_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    仅管理员可通过的依赖。

    在 CurrentUser 基础上判断用户是否有管理员权限。
    普通用户访问会收到 403 Forbidden。
    """
    if not is_admin(user):
        raise PermissionDeniedError("仅管理员可访问")
    return user


async def enforce_rate_limit(
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    """
    滑动窗口限流依赖。

    按 user_id 维度限流，每分钟最多 RATE_LIMIT_PER_MINUTE 次。
    只用在写接口（chat、upload 等），读接口不限流（因为前端会 3s 轮询）。
    """
    if not settings.rate_limit_enabled:
        return
    await get_rate_limiter().check(f"user:{user.id}")


# ──────────── 类型别名 ────────────
# 这些是写好的"依赖组合"，路由直接引用即可：
#   async def create_chat(user: CurrentUser, session: DbSession): ...
#
# Annotated 是 Python 3.9+ 的类型注解语法，
# FastAPI 会自动识别 Depends() 并执行依赖注入。
DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
RateLimited = Annotated[None, Depends(enforce_rate_limit)]
