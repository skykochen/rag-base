"""
==========================================
  DocumentRepository —— documents 表的数据访问
==========================================

文档表的数据访问。文档是知识库的核心实体，
检索、展示、删除等操作都围绕文档展开。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Document, DocumentStatus
from app.db.repositories.chunk_repo import _permission_where


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(
        self,
        document_id: UUID,
        *,
        permission_tags: list[str] | None = None,
    ) -> Document | None:
        """
        根据 ID 查询文档（可选的权限过滤）。

        参数：
        - document_id: 文档 ID
        - permission_tags: 用户的权限标签列表
          - None: 不限制权限（管理员视角）
          - 非 None: 只返回用户有权限看到的文档
        """
        if permission_tags is None:
            return await self.session.get(Document, document_id)
        perm_where = _permission_where(permission_tags)
        stmt = select(Document).where(Document.id == document_id)
        if perm_where is not None:
            stmt = stmt.where(perm_where)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_hash(self, file_hash: str) -> Document | None:
        """
        根据文件哈希查询文档（幂等校验用）。

        【什么是幂等校验？】
        用户上传文件时，先计算文件的 SHA256 哈希值，
        如果数据库里已有相同哈希的文档，说明是重复上传，
        直接拒绝，不浪费存储和处理资源。
        """
        stmt = select(Document).where(Document.file_hash == file_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, document: Document) -> Document:
        """新增文档记录。"""
        self.session.add(document)
        await self.session.flush()
        return document

    async def update_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        *,
        error_message: str | None = None,
    ) -> None:
        """
        更新文档状态。

        文档状态流转：
        uploading → parsing → indexing → ready（正常流程）
        uploading → parsing → indexing → failed（任意阶段出错）

        参数：
        - status: 新状态
        - error_message: 失败原因（仅在 status 为 failed 时有用）
        """
        doc = await self.session.get(Document, document_id)
        if doc is None:
            return
        doc.status = status
        """
        在任何非失败状态下，都要同步最新的 error_message（包括清空）；
        或者在任何状态下，只要有新的 error_message，就记录下来。
        """
        if error_message is not None or status != DocumentStatus.FAILED:
            doc.error_message = error_message

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        *,
        status: DocumentStatus | None = None,
        permission_tags: list[str] | None = None,
    ) -> tuple[list[Document], int]:
        """
        文档列表分页查询，支持状态筛选和权限过滤。

        参数：
        - status: 按文档状态筛选（如只看 "ready" 的文档）
        - permission_tags: 权限标签过滤
        """
        offset = (page - 1) * page_size
        items_stmt = (
            select(Document)
            .order_by(Document.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        count_stmt = select(func.count()).select_from(Document)

        if status is not None:
            items_stmt = items_stmt.where(Document.status == status)
            count_stmt = count_stmt.where(Document.status == status)

        perm_where: ColumnElement[bool] | None = _permission_where(permission_tags)
        if perm_where is not None:
            items_stmt = items_stmt.where(perm_where)
            count_stmt = count_stmt.where(perm_where)

        items = (await self.session.execute(items_stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(items), int(total)

    async def delete(self, document: Document) -> None:
        """
        删除文档。

        ORM 级联删除：
        - Document 被删除时，其关联的 chunks 会自动删除
        - 因为 Document.chunks 配置了 cascade="all, delete-orphan"
        """
        await self.session.delete(document)

    async def count(
        self,
        *,
        permission_tags: list[str] | None = None,
    ) -> int:
        """统计文档总数（MCP 统计用）。"""
        stmt = select(func.count()).select_from(Document)
        perm_where = _permission_where(permission_tags)
        if perm_where is not None:
            stmt = stmt.where(perm_where)
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_last_indexed_at(
        self,
        *,
        permission_tags: list[str] | None = None,
    ) -> datetime | None:
        """查询最近一次入库的文档时间。"""
        stmt = select(func.max(Document.updated_at)).where(
            Document.status == DocumentStatus.READY
        )
        perm_where = _permission_where(permission_tags)
        if perm_where is not None:
            stmt = stmt.where(perm_where)
        return (await self.session.execute(stmt)).scalar_one_or_none()
