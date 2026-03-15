"""MinerU PDF→Markdown 转换模块"""

from pathlib import Path

from loguru import logger


def pdf_to_markdown(
    pdf_path: str | Path,
    output_dir: str | Path,
    backend: str = "hybrid-auto-engine",
    lang: str = "en",
) -> tuple[Path, str]:
    """使用 MinerU 将 PDF 转换为 Markdown，并按论文标题重命名输出。

    Args:
        pdf_path: PDF 文件路径
        output_dir: 输出目录
        backend: MinerU 解析后端
        lang: 文档语言

    Returns:
        (重命名后的 Markdown 文件路径, 论文标题 slug)
    """
    pdf_path = Path(pdf_path).resolve()
    output_dir = Path(output_dir).resolve()

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    logger.info(f"开始转换 PDF: {pdf_path.name} (后端: {backend})")

    raw_md_path, raw_image_dir = parse_doc_simple(pdf_path, output_dir, backend=backend, lang=lang)

    # 从 Markdown 中提取论文标题，重命名输出
    from paper2zh.naming import extract_title_from_markdown, rename_output, slugify

    md_content = raw_md_path.read_text(encoding="utf-8")
    title = extract_title_from_markdown(md_content)

    if title:
        title_slug = slugify(title)
        logger.info(f"检测到论文标题: {title} → {title_slug}")
    else:
        title_slug = slugify(pdf_path.stem)
        logger.warning(f"未检测到标题，使用文件名: {title_slug}")

    new_md_path, _ = rename_output(raw_md_path, raw_image_dir, title_slug)

    logger.info(f"PDF 转换完成: {new_md_path}")
    return new_md_path, title_slug


def parse_doc_simple(
    pdf_path: Path,
    output_dir: Path,
    backend: str = "hybrid-auto-engine",
    lang: str = "en",
) -> tuple[Path, Path]:
    """简化版的 MinerU 调用，直接产出 Markdown 文件。

    Returns:
    """
    from mineru.cli.common import prepare_env, read_fn
    from mineru.data.data_reader_writer import FileBasedDataWriter
    from mineru.utils.enum_class import MakeMode

    pdf_bytes = read_fn(str(pdf_path))
    file_name = pdf_path.stem
    parse_method = "auto"

    if backend == "pipeline":
        from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json
        from mineru.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
        from mineru.backend.pipeline.pipeline_middle_json_mkcontent import union_make as pipeline_union_make
        from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2

        pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(pdf_bytes, 0, None)
        infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list = pipeline_doc_analyze(
            [pdf_bytes], [lang], parse_method=parse_method
        )

        local_image_dir, local_md_dir = prepare_env(str(output_dir), file_name, parse_method)
        image_writer = FileBasedDataWriter(local_image_dir)
        md_writer = FileBasedDataWriter(local_md_dir)

        middle_json = result_to_middle_json(
            infer_results[0],
            all_image_lists[0],
            all_pdf_docs[0],
            image_writer,
            lang_list[0],
            ocr_enabled_list[0],
            True,
        )
        pdf_info = middle_json["pdf_info"]
        image_dir = str(Path(local_image_dir).name)
        md_content = pipeline_union_make(pdf_info, MakeMode.MM_MD, image_dir)

    elif backend.startswith("hybrid-"):
        engine = backend[7:]
        from mineru.backend.hybrid.hybrid_analyze import doc_analyze as hybrid_doc_analyze
        from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make as vlm_union_make
        from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2
        from mineru.utils.engine_utils import get_vlm_engine

        if engine == "auto-engine":
            engine = get_vlm_engine(inference_engine="auto", is_async=False)

        pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(pdf_bytes, 0, None)
        parse_method_full = f"hybrid_{parse_method}"
        local_image_dir, local_md_dir = prepare_env(str(output_dir), file_name, parse_method_full)
        image_writer = FileBasedDataWriter(local_image_dir)
        md_writer = FileBasedDataWriter(local_md_dir)

        middle_json, _, _ = hybrid_doc_analyze(
            pdf_bytes,
            image_writer=image_writer,
            backend=engine,
            parse_method=parse_method_full,
            language=lang,
        )
        pdf_info = middle_json["pdf_info"]
        image_dir = str(Path(local_image_dir).name)
        md_content = vlm_union_make(pdf_info, MakeMode.MM_MD, image_dir)

    elif backend.startswith("vlm-"):
        engine = backend[4:]
        from mineru.backend.vlm.vlm_analyze import doc_analyze as vlm_doc_analyze
        from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make as vlm_union_make
        from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2
        from mineru.utils.engine_utils import get_vlm_engine

        if engine == "auto-engine":
            engine = get_vlm_engine(inference_engine="auto", is_async=False)

        pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(pdf_bytes, 0, None)
        local_image_dir, local_md_dir = prepare_env(str(output_dir), file_name, "vlm")
        image_writer = FileBasedDataWriter(local_image_dir)
        md_writer = FileBasedDataWriter(local_md_dir)

        middle_json, _ = vlm_doc_analyze(pdf_bytes, image_writer=image_writer, backend=engine)
        pdf_info = middle_json["pdf_info"]
        image_dir = str(Path(local_image_dir).name)
        md_content = vlm_union_make(pdf_info, MakeMode.MM_MD, image_dir)
    else:
        raise ValueError(f"不支持的后端: {backend}")

    # 写入 Markdown 文件
    md_writer = FileBasedDataWriter(local_md_dir)
    md_writer.write_string(f"{file_name}.md", md_content)

    md_path = Path(local_md_dir) / f"{file_name}.md"
    return md_path, Path(local_image_dir)
