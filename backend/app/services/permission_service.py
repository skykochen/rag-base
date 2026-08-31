"""权限计算工具。

设计上故意做成"无状态函数"而不是带 session 的 Service：
- 计算只依赖已加载的 User.roles 集合，不需要再查表
- 调用方（auth_service / api/deps）直接 import 函数即可，避免 Service 套娃
"""

from app.db.models import User

# 通配权限标签：含义"无视权限过滤"，admin 默认持有
WILDCARD_PERMISSION_TAG = "*"
# 内置角色名
ADMIN_ROLE_NAME = "admin"


def compute_user_permission_tags(user: User) -> list[str]:
    """合并用户所有角色的 permission_tags 并去重。

    - 任一角色持有 "*" → 直接返回 ["*"]，下游 SQL 不加权限过滤
    - 多角色叠加用集合去重；顺序对检索逻辑无意义，但稳定排序便于 debug
    """
    merged: set[str] = set()
    for role in user.roles:
        for tag in role.permission_tags:
            if tag == WILDCARD_PERMISSION_TAG:
                return [WILDCARD_PERMISSION_TAG]
            merged.add(tag)
    return sorted(merged)


def is_admin(user: User) -> bool:
    """是否拥有 admin 角色（按角色名识别，不依赖通配标签）。"""
    return any(role.name == ADMIN_ROLE_NAME for role in user.roles)
