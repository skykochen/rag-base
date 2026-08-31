from uuid import UUID

from app.celery_app import celery_app
from app.ingestion.pipeline import run_ingest_sync, run_reindex_sync



@celery_app.task(name="ingest_document", bind=True)
def ingest_document_task(self, document_id: str, task_id: str) -> None:
    run_ingest_sync(document_id, task_id)


@celery_app.task(name="reindex_document", bind=True)
def reindex_document_task(self, document_id: str, task_id: str) -> None:
    """增量重建任务。"""
    run_reindex_sync(UUID(document_id), UUID(task_id))