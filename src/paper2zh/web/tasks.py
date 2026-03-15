"""后台任务管理器 — 管理翻译任务的生命周期"""

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from paper2zh.web.models import JobInfo, JobProgress, JobStage


class Job:
    """单个翻译任务"""

    def __init__(self, job_id: str, filename: str):
        self.job_id = job_id
        self.filename = filename
        self.progress = JobProgress(stage=JobStage.PENDING, message="等待处理")
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.result_path: str | None = None
        self.title_slug: str | None = None
        self.error: str | None = None
        self._progress_listeners: list = []
        self._lock = threading.Lock()

    def update_progress(self, stage: str, current: int, total: int, message: str) -> None:
        """更新进度并通知所有监听者"""
        stage_map = {
            "convert": JobStage.CONVERTING,
            "split": JobStage.SPLITTING,
            "translate": JobStage.TRANSLATING,
            "done": JobStage.COMPLETED,
        }
        with self._lock:
            self.progress = JobProgress(
                stage=stage_map.get(stage, JobStage.PENDING),
                current=current,
                total=total,
                message=message,
            )
            # 通知所有等待中的监听者
            for event in self._progress_listeners:
                event.set()

    def add_listener(self) -> threading.Event:
        """添加一个进度监听者，返回 Event 用于等待"""
        event = threading.Event()
        with self._lock:
            self._progress_listeners.append(event)
        return event

    def remove_listener(self, event: threading.Event) -> None:
        """移除监听者"""
        with self._lock:
            if event in self._progress_listeners:
                self._progress_listeners.remove(event)

    def to_info(self) -> JobInfo:
        """转换为 API 返回的信息"""
        return JobInfo(
            job_id=self.job_id,
            filename=self.filename,
            progress=self.progress,
            created_at=self.created_at,
            result_path=self.result_path,
            error=self.error,
        )


class TaskManager:
    """管理所有翻译任务"""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create_job(self, filename: str) -> Job:
        """创建新任务"""
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id=job_id, filename=filename)
        with self._lock:
            self._jobs[job_id] = job
        logger.info(f"创建任务: {job_id} ({filename})")
        return job

    def get_job(self, job_id: str) -> Job | None:
        """获取任务"""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobInfo]:
        """列出所有任务"""
        with self._lock:
            return [job.to_info() for job in reversed(self._jobs.values())]

    def delete_job(self, job_id: str) -> bool:
        """删除任务"""
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                return True
            return False

    def run_translation(self, job: Job, pdf_path: Path, config: dict) -> None:
        """在后台线程中执行翻译"""

        def _run():
            try:
                from paper2zh.pipeline import translate_pdf

                result_path = translate_pdf(
                    pdf_path=pdf_path,
                    output_dir=self.output_dir,
                    backend=config.get("backend", "hybrid-auto-engine"),
                    model=config.get("model", "deepseek-chat"),
                    api_key=config.get("api_key"),
                    base_url=config.get("base_url"),
                    lang=config.get("lang", "en"),
                    on_progress=job.update_progress,
                )
                job.result_path = str(result_path)
                job.title_slug = result_path.parent.name
                job.update_progress("done", 1, 1, f"翻译完成: {result_path.name}")
            except Exception as e:
                logger.error(f"任务失败 [{job.job_id}]: {e}")
                job.error = str(e)
                job.progress = JobProgress(
                    stage=JobStage.FAILED,
                    message=f"失败: {e}",
                )
                # 通知监听者任务失败
                for event in job._progress_listeners:
                    event.set()

        thread = threading.Thread(target=_run, daemon=True, name=f"translate-{job.job_id}")
        thread.start()
