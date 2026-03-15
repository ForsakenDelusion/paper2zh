"""论文标题提取 + 路径友好化命名"""

import re
import shutil
from pathlib import Path

from loguru import logger


def slugify(title: str, max_length: int = 80) -> str:
    """将论文标题转换为路径友好的文件名。

    规则:
    - 转小写
    - 空格/特殊字符 → 短横线
    - 连续短横线合并
    - 去除首尾短横线
    - 截断到 max_length

    Examples:
        "Attention Is All You Need" → "attention-is-all-you-need"
        "GPT-4: Technical Report" → "gpt-4-technical-report"
        "A Survey of LLMs (2024)" → "a-survey-of-llms-2024"
    """
    s = title.lower()
    # 保留字母、数字、短横线、空格，其他全部替换
    s = re.sub(r"[^\w\s-]", " ", s)
    # 空格和下划线 → 短横线
    s = re.sub(r"[\s_]+", "-", s)
    # 连续短横线合并
    s = re.sub(r"-{2,}", "-", s)
    # 去首尾
    s = s.strip("-")
    # 截断
    if len(s) > max_length:
        # 尽量在单词边界截断
        s = s[:max_length].rsplit("-", 1)[0]
    return s


def extract_title_from_markdown(md_content: str) -> str | None:
    """从 MinerU 产出的 Markdown 中提取论文标题。

    策略: 取第一个 # 标题（一级标题），这通常就是论文标题。
    如果没有一级标题，取第一个任意级别标题。
    """
    for line in md_content.splitlines():
        line = line.strip()
        if not line:
            continue
        # 一级标题优先
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip()

    # fallback: 任意级别标题
    for line in md_content.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^#{1,6}\s+(.+)$", line)
        if m:
            return m.group(1).strip()

    return None


def rename_output(
    md_path: Path,
    image_dir: Path,
    title_slug: str,
) -> tuple[Path, Path]:
    """将 MinerU 产出的 md 文件和图片重命名为论文标题。

    MinerU 默认产出:
        output/<pdf_stem>/<method>/<pdf_stem>.md
        output/<pdf_stem>/<method>/images/img_0.jpg

    重命名为:
        output/<title_slug>/<title_slug>.md
        output/<title_slug>/images/<title_slug>_img_0.jpg

    每张图片文件名加上论文标题前缀，同时更新 md 中的引用路径。

    Returns:
        (新的 md 路径, 新的图片目录路径)
    """
    old_md_dir = md_path.parent
    output_root = old_md_dir.parent.parent  # 上两级: output/

    new_dir = output_root / title_slug
    new_md_name = f"{title_slug}.md"

    # 如果目标目录已存在且不同于旧目录，先清理
    if new_dir.exists() and new_dir.resolve() != old_md_dir.resolve():
        shutil.rmtree(new_dir)

    new_dir.mkdir(parents=True, exist_ok=True)

    # 移动并重命名图片文件
    old_image_dir_name = image_dir.name  # 通常是 "images"
    new_image_dir = new_dir / "images"
    rename_map: dict[str, str] = {}  # old_filename -> new_filename

    if image_dir.exists():
        new_image_dir.mkdir(parents=True, exist_ok=True)
        for img_file in sorted(image_dir.iterdir()):
            if not img_file.is_file():
                continue
            # img_0.jpg → attention-is-all-you-need_img_0.jpg
            new_img_name = f"{title_slug}_{img_file.name}"
            shutil.copy2(img_file, new_image_dir / new_img_name)
            rename_map[img_file.name] = new_img_name

        logger.info(f"图片重命名: {len(rename_map)} 个文件添加前缀 '{title_slug}_'")

    # 读取 md，逐个替换图片引用
    md_content = md_path.read_text(encoding="utf-8")
    for old_name, new_name in rename_map.items():
        # ![...](images/img_0.jpg) → ![...](images/attention-is-all-you-need_img_0.jpg)
        md_content = md_content.replace(
            f"]({old_image_dir_name}/{old_name}",
            f"](images/{new_name}",
        )
        # <img src="images/img_0.jpg"> → <img src="images/attention-is-all-you-need_img_0.jpg">
        md_content = md_content.replace(
            f'src="{old_image_dir_name}/{old_name}',
            f'src="images/{new_name}',
        )

    new_md_path = new_dir / new_md_name
    new_md_path.write_text(md_content, encoding="utf-8")
    logger.info(f"Markdown: {md_path.name} → {new_md_name}")

    # 清理旧目录（如果不同于新目录）
    if old_md_dir.resolve() != new_dir.resolve():
        try:
            shutil.rmtree(old_md_dir.parent)  # 删除 output/<pdf_stem>/
        except OSError:
            pass

    return new_md_path, new_image_dir
