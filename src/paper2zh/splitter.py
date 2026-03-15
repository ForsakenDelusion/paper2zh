"""Markdown 智能分块器 — 区分可翻译文本和需保留原样的内容"""

import re
from dataclasses import dataclass
from enum import Enum


class BlockType(Enum):
    """Markdown 块类型"""

    TEXT = "text"  # 正文段落，需要翻译
    HEADING = "heading"  # 标题行，需要翻译（保留 # 前缀）
    LATEX_BLOCK = "latex_block"  # $$...$$ 块级公式，保留
    LATEX_INLINE = "latex_inline"  # 已嵌入 TEXT 中，不单独出现
    TABLE = "table"  # HTML 表格，保留
    IMAGE = "image"  # 图片引用 ![](...)，保留
    CODE_BLOCK = "code_block"  # 代码块 ```...```，保留
    EMPTY = "empty"  # 空行，保留
    REFERENCE = "reference"  # 参考文献引用行，保留


@dataclass
class Block:
    """一个 Markdown 内容块"""

    type: BlockType
    content: str
    translated: str | None = None

    @property
    def output(self) -> str:
        """返回最终输出内容：翻译后的或原始内容"""
        if self.translated is not None:
            return self.translated
        return self.content


# 匹配模式
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_LATEX_BLOCK_START_RE = re.compile(r"^\$\$")
_IMAGE_RE = re.compile(r"^!\[.*?\]\(.*?\)$")
_TABLE_START_RE = re.compile(r"^\s*<table", re.IGNORECASE)
_TABLE_END_RE = re.compile(r"</table>\s*$", re.IGNORECASE)
_CODE_BLOCK_RE = re.compile(r"^```")
_EMPTY_RE = re.compile(r"^\s*$")
# 参考文献模式: [1] Author... 或 1. Author... 在文末
_REFERENCE_RE = re.compile(r"^\s*\[?\d+\]?\s*[A-Z]")


def split_markdown(content: str) -> list[Block]:
    """将 Markdown 内容分割为块列表。

    策略:
    - $$...$$ 块级 LaTeX 公式 → LATEX_BLOCK (保留)
    - <table>...</table> HTML 表格 → TABLE (保留)
    - ```...``` 代码块 → CODE_BLOCK (保留)
    - ![alt](url) 图片 → IMAGE (保留)
    - # 标题 → HEADING (翻译，保留前缀)
    - 空行 → EMPTY (保留)
    - 其他文本 → TEXT (翻译)

    内联 LaTeX ($...$) 保留在 TEXT 块中，由 LLM 翻译时通过 prompt 指示保留。
    """
    lines = content.split("\n")
    blocks: list[Block] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # 空行
        if _EMPTY_RE.match(line):
            blocks.append(Block(type=BlockType.EMPTY, content=line))
            i += 1
            continue

        # 块级 LaTeX: $$...$$
        if _LATEX_BLOCK_START_RE.match(line.strip()):
            latex_lines = [line]
            # 如果 $$ 在同一行闭合（如 $$E=mc^2$$）
            stripped = line.strip()
            if stripped.endswith("$$") and len(stripped) > 2 and stripped != "$$":
                blocks.append(Block(type=BlockType.LATEX_BLOCK, content=line))
                i += 1
                continue
            # 多行 LaTeX 块
            i += 1
            while i < n:
                latex_lines.append(lines[i])
                if _LATEX_BLOCK_START_RE.match(lines[i].strip()) and lines[i].strip().endswith("$$"):
                    break
                i += 1
            blocks.append(Block(type=BlockType.LATEX_BLOCK, content="\n".join(latex_lines)))
            i += 1
            continue

        # HTML 表格
        if _TABLE_START_RE.match(line):
            table_lines = [line]
            if _TABLE_END_RE.search(line):
                blocks.append(Block(type=BlockType.TABLE, content=line))
                i += 1
                continue
            i += 1
            while i < n:
                table_lines.append(lines[i])
                if _TABLE_END_RE.search(lines[i]):
                    break
                i += 1
            blocks.append(Block(type=BlockType.TABLE, content="\n".join(table_lines)))
            i += 1
            continue

        # 代码块
        if _CODE_BLOCK_RE.match(line.strip()):
            code_lines = [line]
            i += 1
            while i < n:
                code_lines.append(lines[i])
                if _CODE_BLOCK_RE.match(lines[i].strip()):
                    break
                i += 1
            blocks.append(Block(type=BlockType.CODE_BLOCK, content="\n".join(code_lines)))
            i += 1
            continue

        # 图片
        if _IMAGE_RE.match(line.strip()):
            blocks.append(Block(type=BlockType.IMAGE, content=line))
            i += 1
            continue

        # 标题
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            blocks.append(Block(type=BlockType.HEADING, content=line))
            i += 1
            continue

        # 普通文本 — 合并连续非空行为一个段落
        text_lines = [line]
        i += 1
        while i < n:
            next_line = lines[i]
            # 遇到空行、特殊标记就停止合并
            if (
                _EMPTY_RE.match(next_line)
                or _LATEX_BLOCK_START_RE.match(next_line.strip())
                or _TABLE_START_RE.match(next_line)
                or _CODE_BLOCK_RE.match(next_line.strip())
                or _IMAGE_RE.match(next_line.strip())
                or _HEADING_RE.match(next_line)
            ):
                break
            text_lines.append(next_line)
            i += 1

        blocks.append(Block(type=BlockType.TEXT, content="\n".join(text_lines)))

    return blocks


def merge_blocks(blocks: list[Block]) -> str:
    """将块列表重组为 Markdown 字符串。"""
    return "\n".join(block.output for block in blocks)
