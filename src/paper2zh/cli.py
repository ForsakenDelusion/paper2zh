"""CLI 入口 — 一条命令完成 PDF → 翻译 Markdown 全流程"""

import os
from pathlib import Path

import click
from loguru import logger


def _load_env():
    """从 .env 文件加载环境变量（如果存在）"""
    env_file = Path.cwd() / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


# 模块加载时即读取 .env，确保 click 的 envvar 能拿到值
_load_env()


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """paper2zh — 英文学术 PDF 一键翻译为中文 Markdown"""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="输出目录，默认为 PDF 所在目录下的 output/",
)
@click.option(
    "-b",
    "--backend",
    default="hybrid-auto-engine",
    help="MinerU 解析后端 (hybrid-auto-engine / pipeline / vlm-auto-engine)",
)
@click.option("-m", "--model", default="deepseek-chat", help="翻译用的 LLM 模型名称 (默认: deepseek-chat)")
@click.option("--api-key", envvar="OPENAI_API_KEY", help="LLM API Key (或设置 OPENAI_API_KEY 环境变量)")
@click.option(
    "--base-url",
    envvar="OPENAI_BASE_URL",
    default=None,
    help="LLM API Base URL (默认读取 OPENAI_BASE_URL 环境变量)",
)
@click.option("--lang", default="en", help="PDF 文档语言 (默认: en)")
@click.option("--skip-convert", is_flag=True, help="跳过 MinerU 转换，直接翻译已有的 Markdown")
@click.option(
    "--md-path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="配合 --skip-convert 使用，指定已有的 Markdown 文件路径",
)
def translate(
    pdf_path: Path,
    output_dir: Path | None,
    backend: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    lang: str,
    skip_convert: bool,
    md_path: Path | None,
):
    """翻译英文学术 PDF 为中文 Markdown

    用法: paper2zh translate paper.pdf
    """
    if not api_key:
        raise click.ClickException("未提供 API Key。请通过 --api-key 参数或 OPENAI_API_KEY 环境变量设置。")

    if output_dir is None:
        output_dir = pdf_path.parent / "output"

    from paper2zh.pipeline import translate_pdf

    try:
        result = translate_pdf(
            pdf_path=pdf_path,
            output_dir=output_dir,
            backend=backend,
            model=model,
            api_key=api_key,
            base_url=base_url,
            lang=lang,
            skip_convert=skip_convert,
            md_path=md_path,
        )
        logger.info(f"✅ 翻译完成: {result}")
    except ValueError as e:
        raise click.ClickException(str(e))


@cli.command()
@click.option("-h", "--host", default="127.0.0.1", help="监听地址 (默认: 127.0.0.1)")
@click.option("-p", "--port", default=8000, type=int, help="监听端口 (默认: 8000)")
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="输出目录 (默认: 当前目录下的 output/)",
)
def web(host: str, port: int, output_dir: Path | None):
    """启动 WebUI 服务"""
    import uvicorn

    if output_dir is None:
        output_dir = Path.cwd() / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 将输出目录传递给 web app
    os.environ["PAPER2ZH_OUTPUT_DIR"] = str(output_dir.resolve())

    logger.info(f"启动 WebUI: http://{host}:{port}")
    logger.info(f"输出目录: {output_dir.resolve()}")

    uvicorn.run(
        "paper2zh.web.app:app",
        host=host,
        port=port,
        reload=False,
    )


# 保持向后兼容：直接 paper2zh paper.pdf 仍然可用
@click.command()
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", "output_dir", type=click.Path(path_type=Path), default=None)
@click.option("-b", "--backend", default="hybrid-auto-engine")
@click.option("-m", "--model", default="deepseek-chat")
@click.option("--api-key", envvar="OPENAI_API_KEY")
@click.option("--base-url", envvar="OPENAI_BASE_URL", default=None)
@click.option("--lang", default="en")
@click.option("--skip-convert", is_flag=True)
@click.option("--md-path", type=click.Path(exists=True, path_type=Path), default=None)
def main(
    pdf_path: Path,
    output_dir: Path | None,
    backend: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    lang: str,
    skip_convert: bool,
    md_path: Path | None,
):
    """paper2zh — 英文学术 PDF 一键翻译为中文 Markdown

    用法: paper2zh paper.pdf
    """
    if not api_key:
        raise click.ClickException("未提供 API Key。请通过 --api-key 参数或 OPENAI_API_KEY 环境变量设置。")

    if output_dir is None:
        output_dir = pdf_path.parent / "output"

    from paper2zh.pipeline import translate_pdf

    try:
        result = translate_pdf(
            pdf_path=pdf_path,
            output_dir=output_dir,
            backend=backend,
            model=model,
            api_key=api_key,
            base_url=base_url,
            lang=lang,
            skip_convert=skip_convert,
            md_path=md_path,
        )
        logger.info(f"✅ 翻译完成: {result}")
    except ValueError as e:
        raise click.ClickException(str(e))


if __name__ == "__main__":
    _load_env()
    main()
