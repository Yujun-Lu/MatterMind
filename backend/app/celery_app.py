from __future__ import annotations

from celery import Celery

from .config import REDIS_URL

celery_app = Celery(
    "mattergen",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=86400,
)