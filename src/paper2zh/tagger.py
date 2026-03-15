"""论文标签提取模块 — 用最少文本为翻译提供领域上下文"""

import random
import re
from dataclasses import dataclass

from loguru import logger

from paper2zh.splitter import Block, BlockType

# 采样配置
MAX_SAMPLE_CHARS = 1500  # 采样文本总字符上限（摘要 + 段落）
SAMPLE_PARAGRAPH_COUNT = 3  # 随机采样段落数

TAGGING_PROMPT = """\
你是一位学术论文分析专家。根据以下论文片段，提取论文的核心信息。

请严格按以下格式输出（每行一项，不要多余内容）：

领域: <论文所属学科领域，如 计算机科学/软件工程、机器学习/强化学习>
关键术语: <5-10个核心英文术语，逗号分隔>
术语翻译: <上述术语的推荐中文翻译，格式为 English→中文，逗号分隔>
"""


@dataclass
class PaperTags:
    """论文标签"""

    domain: str  # 领域，如 "计算机科学/软件工程"
    keywords: list[str]  # 关键英文术语
    translations: dict[str, str]  # 术语翻译映射 English→中文
    raw_response: str  # LLM 原始响应


def extract_sample_text(blocks: list[Block]) -> str:
    """从 blocks 中提取最少量文本用于打标签。

    策略：
    1. 找到摘要（Abstract）段落
    2. 从剩余 TEXT 块中随机采样几段
    3. 总字符数控制在 MAX_SAMPLE_CHARS 以内
    """
    text_blocks = [b for b in blocks if b.type == BlockType.TEXT]
    heading_blocks = [b for b in blocks if b.type == BlockType.HEADING]

    # --- 1. 提取摘要 ---
    abstract_text = ""
    abstract_idx = -1  # 摘要标题在 blocks 中的位置

    for i, block in enumerate(blocks):
        if block.type == BlockType.HEADING and re.search(r"abstract", block.content, re.IGNORECASE):
            abstract_idx = i
            break

    if abstract_idx >= 0:
        # 收集摘要标题后的连续 TEXT 块
        for b in blocks[abstract_idx + 1 :]:
            if b.type == BlockType.HEADING:
                break
            if b.type == BlockType.TEXT:
                abstract_text += b.content + "\n"
    else:
        # 没找到 Abstract 标题，取第一个较长的 TEXT 块作为摘要
        for b in text_blocks:
            if len(b.content) > 200:
                abstract_text = b.content
                break

    abstract_text = abstract_text.strip()

    # --- 2. 随机采样段落 ---
    # 排除摘要区域的 TEXT 块
    remaining = []
    past_abstract = abstract_idx < 0  # 没找到摘要则全部可选
    for i, b in enumerate(blocks):
        if not past_abstract:
            if i > abstract_idx and b.type == BlockType.HEADING:
                past_abstract = True
            continue
        if b.type == BlockType.TEXT and len(b.content) > 80:
            remaining.append(b)

    sample_count = min(SAMPLE_PARAGRAPH_COUNT, len(remaining))
    if remaining and sample_count > 0:
        # 均匀采样：首段 + 中段 + 尾段
        indices = []
        if len(remaining) <= sample_count:
            indices = list(range(len(remaining)))
        else:
            step = len(remaining) / sample_count
            indices = [int(step * i) for i in range(sample_count)]
        sampled = [remaining[i] for i in indices]
    else:
        sampled = []

    # --- 3. 组装采样文本，控制总长度 ---
    parts = []
    if abstract_text:
        parts.append(f"[摘要]\n{abstract_text[:800]}")

    budget = MAX_SAMPLE_CHARS - sum(len(p) for p in parts)
    for b in sampled:
        snippet = b.content[:400]
        if len(snippet) > budget:
            break
        parts.append(f"[段落]\n{snippet}")
        budget -= len(snippet)

    return "\n\n".join(parts)


def parse_tags(response: str) -> PaperTags:
    """解析 LLM 返回的标签文本。"""
    domain = ""
    keywords: list[str] = []
    translations: dict[str, str] = {}

    for line in response.strip().splitlines():
        line = line.strip()
        if line.startswith("领域:") or line.startswith("领域："):
            domain = line.split(":", 1)[-1].split("：", 1)[-1].strip()
        elif line.startswith("关键术语:") or line.startswith("关键术语："):
            raw = line.split(":", 1)[-1].split("：", 1)[-1].strip()
            keywords = [k.strip() for k in raw.split(",") if k.strip()]
        elif line.startswith("术语翻译:") or line.startswith("术语翻译："):
            raw = line.split(":", 1)[-1].split("：", 1)[-1].strip()
            for pair in raw.split(","):
                pair = pair.strip()
                if "→" in pair:
                    en, zh = pair.split("→", 1)
                    translations[en.strip()] = zh.strip()
                elif "->" in pair:
                    en, zh = pair.split("->", 1)
                    translations[en.strip()] = zh.strip()

    return PaperTags(
        domain=domain,
        keywords=keywords,
        translations=translations,
        raw_response=response,
    )


def tag_paper(blocks: list[Block], client_config: dict) -> PaperTags:
    """对论文进行标签提取。

    Args:
        blocks: split_markdown 产出的块列表
        client_config: create_client 返回的 LLM 配置

    Returns:
        PaperTags 包含领域、关键术语和术语翻译
    """
    from openai import OpenAI

    sample = extract_sample_text(blocks)
    if not sample:
        logger.warning("无法提取采样文本，跳过标签提取")
        return PaperTags(domain="", keywords=[], translations={}, raw_response="")

    logger.info(f"标签提取: 采样 {len(sample)} 字符")
    logger.debug(f"采样文本:\n{sample[:300]}...")

    client: OpenAI = client_config["client"]
    model: str = client_config["model"]

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": TAGGING_PROMPT},
            {"role": "user", "content": sample},
        ],
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()
    logger.info(f"标签提取结果:\n{raw}")

    tags = parse_tags(raw)
    logger.info(f"领域: {tags.domain} | 术语: {len(tags.keywords)} 个 | 翻译: {len(tags.translations)} 对")

    return tags


def build_context_prompt(tags: PaperTags) -> str:
    """将标签转化为注入翻译 prompt 的上下文段落。"""
    if not tags.domain and not tags.keywords:
        return ""

    parts = []
    if tags.domain:
        parts.append(f"本文属于「{tags.domain}」领域。")
    if tags.translations:
        term_list = "、".join(f"{en}（{zh}）" for en, zh in tags.translations.items())
        parts.append(f"核心术语参考翻译：{term_list}。")
    elif tags.keywords:
        parts.append(f"核心术语：{'、'.join(tags.keywords)}。")

    return "\n".join(parts)
