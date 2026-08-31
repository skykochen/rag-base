"""
==========================================
  认证路由 —— 登录和获取用户信息
==========================================

两个接口：
- POST /auth/login     → 登录（用户名 + 密码 → JWT token）
- GET  /auth/me        → 获取当前用户信息（验证 token 是否有效）

【前端是怎么用的？】
登录页输入账号密码 → POST /auth/login → 拿到 token 存到 localStorage
后续每个请求都在 Authorization header 带上 token
每次刷新页面 → GET /auth/me → 验证 token 有效，拿到用户信息
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.auth import LoginRequest, LoginResponse, MeResponse, UserRead
from app.core.exceptions import UnauthorizedError
from app.services.auth_service import AuthService
from app.services.permission_service import compute_user_permission_tags, is_admin

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse, operation_id="login")
async def login(payload: LoginRequest, session: DbSession) -> LoginResponse:
    """
    用户登录。

    流程：
    1. 接收用户名和密码
    2. 调用 AuthService 验证凭据
    3. 验证通过 → 签 JWT token，返回用户信息和权限
    4. 验证失败 → 返回 401（不区分"用户名不存在"还是"密码错误"）

    【为什么不区分用户名和密码的错误？】
    防止攻击者通过错误信息枚举有效的用户名。
    统一的「用户名或密码错误」让攻击者无从判断。
    """
    service = AuthService(session)
    user = await service.authenticate(payload.username, payload.password)
    if user is None:
        raise UnauthorizedError("用户名或密码错误")

    token = AuthService.issue_token(user)
    return LoginResponse(
        access_token=token,
        user=UserRead.model_validate(user),
        permission_tags=compute_user_permission_tags(user),
        is_admin=is_admin(user),
    )


@router.get("/me", response_model=MeResponse, operation_id="getCurrentUser")
async def me(user: CurrentUser) -> MeResponse:
    """
    获取当前登录用户的信息。

    前端在每次刷新页面或切换路由时调用这个接口，
    以保证用户状态（角色、权限等）是最新的。
    """
    return MeResponse(
        user=UserRead.model_validate(user),
        permission_tags=compute_user_permission_tags(user),
        is_admin=is_admin(user),
    )
