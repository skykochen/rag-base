"""
==========================================
  UserRepository —— users 表的数据访问
==========================================

负责 User 模型的增删改查。

【ORM 操作说明】
- select(User)：构建查询语句（相当于 SQL: SELECT * FROM users）
- .where(User.username == "admin")：添加 WHERE 条件
- .options(selectinload(User.roles))：预加载关联对象
  - roles 是 User 的一个属性，但存的是 Role 对象（多对多关系）
  - 不加 selectinload，访问 user.roles 时会发额外的 SQL 查询（N+1 问题）
  - 加了后，一次查询就把 roles 也查出来了
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Role, User


class UserRepository:
    """
    用户表的数据访问对象。

    每个方法接收必要的参数，执行数据库操作，返回 Python 对象。
    不负责事务提交（commit 由调用方在 service 层控制）。
    """

    def __init__(self, session: AsyncSession) -> None:
        # 从外部传入 session，而不是自己创建
        # 这样多个 repository 可以共享同一个事务
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        """
        根据主键 ID 查询用户。

        session.get() 是最高效的查询方式（直接按主键查）。
        roles 字段配置了 lazy="selectin"，会在查询时自动预加载关联的角色数据。
        """
        return await self.session.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        """
        根据用户名查询用户（登录时用）。

        selectinload(User.roles) 的作用：
        - User 和 Role 是多对多关系，存在 user_roles 关联表
        - 不加这个选项，访问 user.roles 时会触发额外的 SQL 查询
        - 加了后，一次查询就把用户和角色数据都查出来
        """
        stmt = (
            select(User)
            .where(User.username == username)
            .options(selectinload(User.roles))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_all(self) -> int:
        """
        统计用户总数。

        给 seed.py 用的：检查数据库中是否已有用户，
        决定是否执行种子数据初始化。
        """
        return int(
            (await self.session.execute(select(func.count(User.id)))).scalar_one()
        )

    async def list_paginated(self, page: int, page_size: int) -> tuple[list[User], int]:
        """
        分页查询用户列表。

        参数：
        - page: 第几页（从 1 开始）
        - page_size: 每页多少条

        返回：
        - (用户列表, 总用户数)

        offset 计算：第 1 页偏移 0，第 2 页偏移 page_size，依此类推
        """
        page = max(page, 1)
        page_size = max(min(page_size, 100), 1)  # 限制 page_size 最大 100
        offset = (page - 1) * page_size

        items_stmt = (
            select(User)
            .order_by(User.created_at.asc(), User.id.asc())
            .offset(offset)
            .limit(page_size)
            .options(selectinload(User.roles))
        )
        count_stmt = select(func.count(User.id))

        items = (await self.session.execute(items_stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(items), int(total)

    async def add(self, user: User) -> User:
        """新增用户。"""
        self.session.add(user)
        await self.session.flush()  # flush 把 SQL 发给数据库，但还没 commit
        return user

    async def delete(self, user: User) -> None:
        """删除用户。"""
        await self.session.delete(user)
        await self.session.flush()

    async def set_roles(self, user: User, roles: list[Role]) -> None:
        """整体替换用户的角色集合。"""
        user.roles = roles
        await self.session.flush()
