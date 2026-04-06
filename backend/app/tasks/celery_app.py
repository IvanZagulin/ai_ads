import asyncio

import nest_asyncio
from celery import Celery, Task

from app.config import settings

nest_asyncio.apply()


class AsyncTask(Task):
    """Base class allowing Celery to run async task functions."""
    abstract = True

    def __call__(self, *args, **kwargs):
        result = self.run(*args, **kwargs)
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                return loop.run_until_complete(result)
            return asyncio.run(result)
        return result


celery_app = Celery(
    "ai_ads_manager",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    task_cls=AsyncTask,
    include=["app.tasks.data_collector", "app.tasks.optimization_cycle"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    task_track_started=True,
    task_soft_time_limit=300,
    task_time_limit=600,
)

celery_app.conf.beat_schedule = {
    "collect_wb_data": {
        "task": "app.tasks.data_collector.collect_wb_data_all_accounts",
        "schedule": 43200.0,
    },
    "collect_ozon_data": {
        "task": "app.tasks.data_collector.collect_ozon_data_all_accounts",
        "schedule": 86400.0,
    },
    "optimization_cycle": {
        "task": "app.tasks.optimization_cycle.run_optimization_cycle",
        "schedule": 43200.0,
    },
}
