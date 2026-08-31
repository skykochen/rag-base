"""
==========================================
  IngestionTaskRepository —— 入库任务的数据访问
==========================================

ingestion_tasks 表记录每次文档入库操作的状态和进度。
Celery Worker 在处理过程中会更新这里的记录。
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestionTask, IngestionTaskStatus, IngestionTaskType


class IngestionTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, document_id: UUID, task_type: IngestionTaskType) -> IngestionTask:
        """创建入库任务记录（状态为 pending）。"""
        task = IngestionTask(
            document_id=document_id,
            task_type=task_type,
            status=IngestionTaskStatus.PENDING,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def get_by_id(self, task_id: UUID) -> IngestionTask | None:
        """查询任务。"""
        return await self.session.get(IngestionTask, task_id)

    async def get_latest_by_document(self, document_id: UUID) -> IngestionTask | None:
        """获取文档的最新入库任务。"""
        stmt = (
            select(IngestionTask)
            .where(IngestionTask.document_id == document_id)
            .order_by(IngestionTask.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def mark_running(self, task_id: UUID) -> None:
        """标记任务为运行中。"""
        task = await self.session.get(IngestionTask, task_id)
        if task is None:
            return
        task.status = IngestionTaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)

    async def mark_success(self, task_id: UUID) -> None:
        """标记任务为成功。"""
        task = await self.session.get(IngestionTask, task_id)
        if task is None:
            return
        task.status = IngestionTaskStatus.SUCCESS
        task.finished_at = datetime.now(timezone.utc)
        task.error_message = None

    async def mark_failed(self, task_id: UUID, error_message: str) -> None:
        """标记任务为失败，记录错误信息。"""
        task = await self.session.get(IngestionTask, task_id)
        if task is None:
            return
        task.status = IngestionTaskStatus.FAILED
        task.finished_at = datetime.now(timezone.utc)
        task.error_message = error_message[:500]  # 截断过长的错误信息

    async def set_progress_total(self, task_id: UUID, total: int) -> None:
        """设置任务的总进度。"""
        task = await self.session.get(IngestionTask, task_id)
        if task is None:
            return
        task.progress_total = total

    async def increment_progress(self, task_id: UUID, delta: int) -> None:
        """增加已完成进度。"""
        task = await self.session.get(IngestionTask, task_id)
        if task is None:
            return
        task.progress_done += delta
