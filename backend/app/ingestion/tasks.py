"""
==========================================
  Celery 任务定义 —— 异步执行文档入库
==========================================

【为什么需要 Celery？】
文档入库可能要处理几十 MB 的文件，耗时几分钟。
如果在 HTTP 请求里同步等待，用户会一直转圈。
所以：
1. 用户上传文件 → API 立即返回"已收到"
2. API 把任务提交给 Celery
3. Celery Worker 在后台慢慢处理
4. 前端轮询文档状态看到进度

【同步包装异步】
Celery worker 是同步进程，但入库逻辑是异步的（asyncio）。
所以每个任务函数内部用 asyncio.run() 启动事件循环。
"""

from uuid import UUID

from app.celery_app import celery_app
from app.ingestion.pipeline import run_ingest_sync, run_reindex_sync


@celery_app.task(name="ingest_document", bind=True)
def ingest_document_task(self, document_id: str, task_id: str) -> None:
    """首次入库任务。"""
    run_ingest_sync(UUID(document_id), UUID(task_id))


@celery_app.task(name="reindex_document", bind=True)
def reindex_document_task(self, document_id: str, task_id: str) -> None:
    """增量重建任务。"""
    run_reindex_sync(UUID(document_id), UUID(task_id))
