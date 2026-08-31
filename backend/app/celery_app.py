"""
==========================================
  Celery 应用实例 —— 异步任务队列
==========================================

【Celery 是什么？】
Celery 是一个分布式任务队列。你可以把"耗时任务"提交给 Celery，
它在后台异步执行，不会阻塞用户请求。

【工作模式】
1. 应用提交任务：ingest_document_task.delay(document_id, task_id)
2. 任务进入 Redis 消息队列（broker）
3. Celery Worker 从队列拉取任务执行
4. 执行结果存入 Redis（backend）

【启动 Worker】
uv run celery -A app.celery_app worker --loglevel=info --concurrency=1 --pool=solo

--pool=solo：Windows 上 celery worker 需要这个参数才能运行
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "rag_knowledge_base",                           # 应用名称
    broker=settings.celery_broker_url,               # 消息队列（Redis db 1）
    backend=settings.celery_result_backend,          # 结果存储（Redis db 2）
    include=["app.ingestion.tasks"],                # 自动发现任务定义
)

# 配置说明：
# task_acks_late=False：
#   worker 拿到任务就 ack（确认），不是执行完才 ack。
#   文档入库是"最终一致"语义，就算 worker 崩溃，数据库状态也能保证不会丢。
#   用 DB 里的 ingestion_tasks 表跟踪状态，不靠 Celery 重传。
#
# worker_prefetch_multiplier=1：
#   每次只预取一个任务，避免一个 worker 拿太多任务导致分配不均。
#
# task_serializer="json"：
#   任务参数用 JSON 序列化（不用 pickle，更安全更通用）。
celery_app.conf.update(
    task_acks_late=False,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)
