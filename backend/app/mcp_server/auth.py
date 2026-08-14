from app.db.repositories.user_repo import UserRepository
from app.db.session import AsyncSessionLocal
from app.services.permission_service import is_admin
from uuid import UUID

from app.core.exceptions import UnauthorizedError, AppException
from app.core.security import decode_access_token
from app.db.models import User
from mcp.server.mcpserver import Context

from mcp.server.mcpserver.exceptions import ToolError


def _parse_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise UnauthorizedError("请登录")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedError("无效的登录凭证")
    return token

async def resolve_current_user(ctx: Context) -> User:
    """从 MCP Context 取出 Bearer token 并查到活跃用户。

    与 REST `get_current_user` 行为完全一致；唯一区别是失败时抛
    `ToolError` 而不是 HTTP 401：MCP 协议没有 401 概念，错误信息走
    工具结果通道返回。
    """
    request = getattr(ctx.request_context, "request", None)
    if request is None:
        raise ToolError("当前传输不支持鉴权")
    try:
        token = _parse_bearer_token(request.headers.get("Authorization"))
        subject = decode_access_token(token)
        user_id = UUID(subject)
    except (AppException, ValueError) as e:
        # AppException 含 UnauthorizedError；ValueError 是 sub 非 UUID
        raise ToolError(_user_facing_message(e, default="无效的访问凭证")) from e

    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise ToolError("用户不存在")
    if user.status != "active":
        raise ToolError("用户已禁用")
    return user

def require_admin(user: User) -> None:
    """admin-only 工具入口处调用；非 admin 直接 ToolError。"""
    if not is_admin(user):
        raise ToolError("仅管理员可调用此工具")

def _user_facing_message(e: Exception, *, default: str) -> str:
    """统一把 AppException.message 透出给 Agent；其它异常用兜底文案。"""
    if isinstance(e, AppException):
        return e.message
    return default

