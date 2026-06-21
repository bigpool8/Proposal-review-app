from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "proposal_review",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.review_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,
    worker_pool="solo",  # Windows prefork 비호환 우회
)
