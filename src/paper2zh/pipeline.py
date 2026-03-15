"""翻译流水线 — CLI 和 Web 共用的核心流程"""

from pathlib import Path
from typing import Callable

from loguru import logger

from paper2zh.splitter import BlockType, merge_blocks, split_markdown


# 进度回调签名: (stage, current, total, message)
ProgressCallback = Callable[[str, int, int, str], None]


def _noop_progress(stage: str, current: int, total: int, message: str) -> None:
    """默认空回调，仅日志输出"""
    pass


def translate_pdf(
    pdf_path: Path,
    output_dir: Path,
    *,
    backend: str = "hybrid-auto-engine",
    model: str = "deepseek-chat",
    api_key: str | None = None,
    base_url: str | None = None,
    lang: str = "en",
    skip_convert: bool = False,
    md_path: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """执行完整的 PDF → 中文 Markdown 翻译流程。

    Args:
        pdf_path: PDF 文件路径
        output_dir: 输出目录
        backend: MinerU 解析后端
        model: LLM 模型名称
        api_key: LLM API Key
        base_url: LLM API Base URL
        lang: PDF 文档语言
        skip_convert: 跳过 MinerU 转换
        md_path: 已有 Markdown 文件路径 (配合 skip_convert)
        on_progress: 进度回调函数 (stage, current, total, message)

    Returns:
        翻译后的 Markdown 文件路径

    Raises:
        ValueError: 参数校验失败
        FileNotFoundError: 文件不存在
    """
    progress = on_progress or _noop_progress

    if not api_key:
        raise ValueError("未提供 API Key。请通过参数或环境变量设置。")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: PDF → Markdown
    progress("convert", 0, 1, "开始 PDF 转换")

    if skip_convert:
        if md_path is None:
            raise ValueError("使用 skip_convert 时必须提供 md_path")
        logger.info(f"跳过转换，使用已有 Markdown: {md_path}")
        md_content = md_path.read_text(encoding="utf-8")

        from paper2zh.naming import extract_title_from_markdown, slugify

        title = extract_title_from_markdown(md_content)
        title_slug = slugify(title) if title else slugify(pdf_path.stem)
    else:
        logger.info("Step 1/3: MinerU 转换 PDF → Markdown")
        from paper2zh.converter import pdf_to_markdown

        result_md_path, title_slug = pdf_to_markdown(pdf_path, output_dir, backend=backend, lang=lang)
        md_content = result_md_path.read_text(encoding="utf-8")
        logger.info(f"Markdown 已生成: {result_md_path}")

    progress("convert", 1, 1, f"PDF 转换完成 → {title_slug}")

    # Step 2: 智能分块
    progress("split", 0, 1, "开始智能分块")
    logger.info("Step 2/3: 智能分块 Markdown")

    blocks = split_markdown(md_content)

    text_count = sum(1 for b in blocks if b.type in (BlockType.TEXT, BlockType.HEADING))
    skip_count = len(blocks) - text_count
    logger.info(f"分块完成: {text_count} 个文本块待翻译, {skip_count} 个块保留原样")
    progress("split", 1, 1, f"分块完成: {text_count} 个待翻译, {skip_count} 个保留")

    from paper2zh.translator import create_client, translate_blocks

    client_config = create_client(api_key=api_key, base_url=base_url, model=model)

    # Step 2.5: 论文标签提取
    progress("tagging", 0, 1, "开始提取论文标签")
    logger.info("Step 2.5/4: 提取论文标签")

    from paper2zh.tagger import build_context_prompt, tag_paper

    tags = tag_paper(blocks, client_config)
    context_prompt = build_context_prompt(tags)
    if context_prompt:
        logger.info(f"标签上下文: {context_prompt[:100]}...")
    else:
        logger.info("未提取到标签，使用默认 prompt")
    progress("tagging", 1, 1, f"标签提取完成: {tags.domain or '未知领域'}")

    # Step 3: LLM 翻译
    progress("translate", 0, text_count, "开始 LLM 翻译")
    logger.info("Step 3/4: LLM 翻译")

    def _translation_progress(idx: int, total: int, block_type: str) -> None:
        progress("translate", idx, total, f"翻译进度: [{idx}/{total}] ({block_type})")

    translate_blocks(blocks, client_config, on_progress=_translation_progress, context_prompt=context_prompt)

    # 输出
    output_md = merge_blocks(blocks)
    output_file = output_dir / title_slug / f"{title_slug}_zh.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(output_md, encoding="utf-8")

    progress("done", 1, 1, f"翻译完成: {output_file}")
    logger.info(f"✅ 翻译完成: {output_file}")

    return output_file
