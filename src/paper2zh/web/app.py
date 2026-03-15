"""FastAPI 应用 — paper2zh WebUI 后端"""

import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from paper2zh.web.models import JobStage
from paper2zh.web.tasks import TaskManager

# 输出目录
_output_dir = Path(os.environ.get("PAPER2ZH_OUTPUT_DIR", Path.cwd() / "output"))
_output_dir.mkdir(parents=True, exist_ok=True)

# 上传临时目录
_upload_dir = _output_dir / ".uploads"
_upload_dir.mkdir(parents=True, exist_ok=True)

# 任务管理器
task_manager = TaskManager(output_dir=_output_dir)

# FastAPI app
app = FastAPI(title="paper2zh", description="英文学术 PDF 一键翻译为中文 Markdown")

# 静态文件
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回 WebUI 首页"""
    index_file = _static_dir / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>paper2zh WebUI</h1><p>static/index.html not found</p>")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.post("/api/translate")
async def start_translation(
    file: UploadFile = File(...),
    backend: str = Form("hybrid-auto-engine"),
    model: str = Form("deepseek-chat"),
    api_key: str = Form(""),
    base_url: str = Form(""),
    lang: str = Form("en"),
):
    """上传 PDF 并启动翻译任务"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="请上传 PDF 文件")

    # 优先使用表单提交的 api_key，其次读环境变量
    effective_api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not effective_api_key:
        raise HTTPException(status_code=400, detail="未提供 API Key")

    effective_base_url = base_url or os.environ.get("OPENAI_BASE_URL") or None

    # 保存上传文件
    pdf_path = _upload_dir / f"{os.urandom(8).hex()}_{file.filename}"
    with open(pdf_path, "wb") as f:
        content = await file.read()
        f.write(content)

    logger.info(f"接收到 PDF: {file.filename} ({len(content)} bytes)")

    # 创建任务
    job = task_manager.create_job(filename=file.filename)

    # 启动后台翻译
    config = {
        "backend": backend,
        "model": model,
        "api_key": effective_api_key,
        "base_url": effective_base_url,
        "lang": lang,
    }
    task_manager.run_translation(job, pdf_path, config)

    return {"job_id": job.job_id, "message": "翻译任务已启动"}


@app.get("/api/jobs")
async def list_jobs():
    """获取所有任务列表"""
    jobs = task_manager.list_jobs()
    return {"jobs": [j.model_dump() for j in jobs]}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """获取单个任务详情"""
    job = task_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.to_info().model_dump()


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """删除任务（历史论文同时删除文件）"""
    job = task_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 如果是历史论文，删除对应的输出目录
    if job.result_path:
        paper_dir = Path(job.result_path).parent
        if paper_dir.is_dir():
            shutil.rmtree(paper_dir, ignore_errors=True)
            logger.info(f"删除输出目录: {paper_dir}")
    if not task_manager.delete_job(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"message": "已删除"}


@app.get("/api/jobs/{job_id}/progress")
async def job_progress_sse(job_id: str):
    """SSE 流式推送任务进度"""
    job = task_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    def event_stream():
        listener = job.add_listener()
        try:
            # 先发送当前状态
            data = json.dumps(job.progress.model_dump(), ensure_ascii=False)
            yield f"data: {data}\n\n"

            # 持续监听直到完成或失败
            while job.progress.stage not in (JobStage.COMPLETED, JobStage.FAILED):
                # 等待进度更新（最多 30 秒超时，防止连接挂起）
                listener.wait(timeout=30)
                listener.clear()

                data = json.dumps(job.progress.model_dump(), ensure_ascii=False)
                yield f"data: {data}\n\n"

            # 发送最终状态
            data = json.dumps(job.progress.model_dump(), ensure_ascii=False)
            yield f"data: {data}\n\n"
        finally:
            job.remove_listener(listener)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/jobs/{job_id}/result")
async def download_result(job_id: str):
    """下载翻译结果（zip 包含 md + images）"""
    job = task_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not job.result_path:
        raise HTTPException(status_code=400, detail="翻译尚未完成")

    result_file = Path(job.result_path)
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")

    paper_dir = result_file.parent
    zip_name = paper_dir.name + ".zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 添加翻译后的 md
        zf.write(result_file, result_file.name)
        # 添加英文原文 md（如果存在）
        original_md = paper_dir / (paper_dir.name + ".md")
        if original_md.exists():
            zf.write(original_md, original_md.name)
        # 添加 images 目录
        images_dir = paper_dir / "images"
        if images_dir.is_dir():
            for img in images_dir.iterdir():
                if img.is_file():
                    zf.write(img, f"images/{img.name}")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@app.get("/api/jobs/{job_id}/preview")
async def preview_result(job_id: str):
    """获取翻译结果的 Markdown 原文用于预览"""
    job = task_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not job.result_path:
        raise HTTPException(status_code=400, detail="翻译尚未完成")

    result_file = Path(job.result_path)
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")

    md_content = result_file.read_text(encoding="utf-8")

    # 如果有图片目录，提供图片 base path
    image_base = ""
    if job.title_slug:
        image_base = f"/api/images/{job.job_id}"

    return {"markdown": md_content, "image_base": image_base}


@app.get("/api/images/{job_id}/{filename:path}")
async def serve_image(job_id: str, filename: str):
    """提供任务产出的图片"""
    job = task_manager.get_job(job_id)
    if not job or not job.result_path:
        raise HTTPException(status_code=404, detail="资源不存在")

    result_dir = Path(job.result_path).parent
    image_path = result_dir / filename
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")

    # 安全检查: 确保路径在结果目录内
    try:
        image_path.resolve().relative_to(result_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="禁止访问")

    suffix = image_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(path=str(image_path), media_type=media_type)


@app.get("/api/config")
async def get_default_config():
    """获取默认配置（从环境变量读取）"""
    return {
        "has_api_key": bool(os.environ.get("OPENAI_API_KEY")),
        "base_url": os.environ.get("OPENAI_BASE_URL", ""),
        "backends": [
            {"value": "hybrid-auto-engine", "label": "Hybrid (推荐, 需 GPU)", "default": True},
            {"value": "pipeline", "label": "Pipeline (纯 CPU)"},
            {"value": "vlm-auto-engine", "label": "VLM (纯视觉模型, 需 GPU)"},
        ],
    }
