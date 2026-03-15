"""LLM 翻译模块 — 支持 OpenAI 兼容 API"""

from typing import Callable

from loguru import logger
from openai import OpenAI

from paper2zh.splitter import Block, BlockType

# 默认翻译 prompt
TRANSLATE_SYSTEM_PROMPT = """\
你是一位专业的学术论文翻译者。请将以下英文学术文本翻译为中文。

要求：
1. 保持学术论文的专业性和准确性
2. 专业术语首次出现时，用"中文翻译（English Term）"的格式
3. 保留所有 Markdown 格式标记（如 **粗体**、*斜体*、列表等）
4. 保留所有内联 LaTeX 公式 $...$ 不做修改
5. 保留所有引用标记 [1]、[2] 等不做修改
6. 保留所有 URL 链接不做修改
7. 翻译要自然流畅，符合中文学术写作习惯
8. 不要添加任何解释或额外内容，只输出翻译结果
"""

TRANSLATE_HEADING_PROMPT = """\
你是一位专业的学术论文翻译者。请将以下英文学术标题翻译为中文。

要求：
1. 只翻译标题文本内容，保留 Markdown 标题前缀（如 ##）
2. 专业术语可保留英文原文
3. 不要添加任何解释，只输出翻译后的标题行
"""


def create_client(
    api_key: str,
    base_url: str | None = None,
    model: str = "gpt-4o-mini",
) -> dict:
    """创建 LLM 客户端配置。

    Args:
        api_key: API 密钥
        base_url: API 基础 URL（用于兼容其他 API，如 DeepSeek、本地模型等）
        model: 模型名称

    Returns:
        客户端配置字典
    """
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    return {
        "client": OpenAI(**client_kwargs),
        "model": model,
    }


def translate_text(
    text: str,
    client_config: dict,
    system_prompt: str = TRANSLATE_SYSTEM_PROMPT,
) -> str:
    """使用 LLM 翻译单段文本。

    Args:
        text: 要翻译的英文文本
        client_config: create_client 返回的配置
        system_prompt: 系统提示词

    Returns:
        翻译后的中文文本
    """
    client: OpenAI = client_config["client"]
    model: str = client_config["model"]

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        temperature=0.3,  # 低温度保证翻译一致性
    )

    return response.choices[0].message.content.strip()


def translate_blocks(
    blocks: list[Block],
    client_config: dict,
    on_progress: Callable[[int, int, str], None] | None = None,
    context_prompt: str = "",
) -> list[Block]:
    """翻译块列表中所有需要翻译的块。

    只翻译 TEXT 和 HEADING 类型的块，其他类型保留原样。

    Args:
        blocks: 分块后的 Markdown 块列表
        client_config: LLM 客户端配置
        on_progress: 进度回调 (current_idx, total, block_type_value)
        context_prompt: 论文上下文信息（来自 tagger），注入到 system prompt 末尾

    Returns:
        翻译后的块列表（原地修改并返回）
    """
    translatable = [b for b in blocks if b.type in (BlockType.TEXT, BlockType.HEADING)]
    total = len(translatable)

    # 构建带上下文的 prompt
    if context_prompt:
        text_prompt = TRANSLATE_SYSTEM_PROMPT + "\n\n以下是本论文的背景信息，请据此提高翻译准确性：\n" + context_prompt
        heading_prompt = TRANSLATE_HEADING_PROMPT + "\n\n以下是本论文的背景信息：\n" + context_prompt
    else:
        text_prompt = TRANSLATE_SYSTEM_PROMPT
        heading_prompt = TRANSLATE_HEADING_PROMPT

    logger.info(f"共 {len(blocks)} 个块，其中 {total} 个需要翻译")

    for idx, block in enumerate(translatable, 1):
        if block.type == BlockType.HEADING:
            prompt = heading_prompt
        else:
            prompt = text_prompt

        logger.info(f"翻译进度: [{idx}/{total}] ({block.type.value})")
        if on_progress:
            on_progress(idx, total, block.type.value)

        try:
            block.translated = translate_text(block.content, client_config, system_prompt=prompt)
        except Exception as e:
            logger.error(f"翻译失败 [{idx}/{total}]: {e}")
            # 翻译失败时保留原文
            block.translated = block.content

    return blocks
