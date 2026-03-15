# paper2zh

英文学术 PDF 一键翻译为中文 Markdown。

基于 [MinerU](https://github.com/opendatalab/MinerU) 解析 PDF 结构，通过 LLM 翻译正文，自动保留公式、表格、图片。翻译前会自动提取论文领域标签和术语表，让 LLM 带着上下文翻译，显著提升专业术语的准确性。

## 工作流程

```
英文 PDF
  │  MinerU 解析
  ▼
Markdown（LaTeX 公式 / HTML 表格 / 图片引用）
  │  智能分块
  ▼
识别可翻译文本 vs 需保留的公式/表格/图片
  │  标签提取（读摘要 + 采样段落 → 领域标签 + 术语翻译表）
  ▼
LLM 翻译（注入领域上下文，仅翻译正文和标题）
  │  重组
  ▼
中文 Markdown
```

## 安装

### 环境要求

- Python 3.10 ~ 3.13
- macOS 14+ / Linux / Windows
- 推荐 16GB 以上内存

### 安装步骤

```bash
git clone https://github.com/yourname/paper2zh.git
cd paper2zh

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 安装
pip install -e .
```

> MinerU 模型文件较大，首次安装需要一些时间。

### 模型下载

MinerU 首次运行时会自动下载模型。国内环境无法访问 HuggingFace 时：

```bash
export MINERU_MODEL_SOURCE=modelscope
```

## 配置

复制 `.env.example` 为 `.env`，填入你的 API Key：

```bash
cp .env.example .env
```

```env
OPENAI_API_KEY=your-api-key-here
OPENAI_BASE_URL=https://api.deepseek.com
```

支持任何 OpenAI 兼容的 API（DeepSeek、OpenAI、本地模型等），改 `OPENAI_BASE_URL` 即可。

## 使用

### CLI 模式

```bash
# 基本用法
paper2zh translate paper.pdf

# 指定输出目录
paper2zh translate paper.pdf -o ./my_output

# 指定模型
paper2zh translate paper.pdf -m gpt-4o-mini --base-url https://api.openai.com/v1 --api-key sk-xxx

# 跳过 PDF 转换，直接翻译已有 Markdown
paper2zh translate paper.pdf --skip-convert --md-path ./existing.md
```

也支持简写（向后兼容）：

```bash
paper2zh paper.pdf
```

### WebUI 模式

```bash
paper2zh web
```

浏览器打开 `http://127.0.0.1:8000`，支持：

- 拖拽上传 PDF
- 配置翻译参数（模型、后端、API Key 等）
- 实时进度条（转换 → 分块 → 标签提取 → 翻译）
- Markdown + LaTeX 公式预览
- 翻译历史管理

```bash
# 自定义监听地址和端口
paper2zh web -h 0.0.0.0 -p 9000

# 指定输出目录
paper2zh web -o ./my_output
```

### MinerU 解析后端

| 后端 | GPU | 显存 | 精度 | 适合场景 |
|------|-----|------|------|---------|
| `hybrid-auto-engine` | 需要 | ≥10GB | 90+ | 默认，最佳质量 |
| `pipeline` | 不需要 | — | 82+ | 没有 GPU 时 |
| `vlm-auto-engine` | 需要 | ≥8GB | 90+ | 纯视觉语言模型 |

```bash
# 纯 CPU 模式
paper2zh translate paper.pdf -b pipeline
```

## 标签提取

翻译前，paper2zh 会自动从论文中提取少量文本（摘要 + 随机采样段落），通过一次 LLM 调用识别：

- 论文所属领域（如「计算机科学/软件工程」）
- 核心英文术语及推荐中文翻译

这些信息会注入到后续每个翻译块的 system prompt 中，让 LLM 在翻译时拥有领域上下文，避免术语翻译不一致的问题。

## 翻译策略

| 内容类型 | 处理方式 |
|---------|---------|
| 正文段落 | 翻译为中文 |
| 标题 `# ## ###` | 翻译为中文，保留 Markdown 格式 |
| 行内公式 `$E=mc^2$` | 保留原样 |
| 块级公式 `$$...$$` | 保留原样 |
| HTML 表格 `<table>` | 保留原样 |
| 图片 `![](...)` | 保留原样 |
| 代码块 `` ```...``` `` | 保留原样 |
| 引用标记 `[1]` | 保留原样 |

## 输出结构

```
output/
└── attention-is-all-you-need/
    ├── attention-is-all-you-need.md              # 英文 Markdown（MinerU 产出）
    ├── attention-is-all-you-need_zh.md           # 中文翻译
    └── images/
        ├── attention-is-all-you-need_img_0.jpg
        └── ...
```

## 完整参数

```
paper2zh translate [OPTIONS] PDF_PATH

Options:
  -o, --output PATH      输出目录（默认: PDF 所在目录下的 output/）
  -b, --backend TEXT      MinerU 解析后端（默认: hybrid-auto-engine）
  -m, --model TEXT        LLM 模型名称（默认: deepseek-chat）
  --api-key TEXT          LLM API Key（或设置 OPENAI_API_KEY 环境变量）
  --base-url TEXT         LLM API Base URL（或设置 OPENAI_BASE_URL 环境变量）
  --lang TEXT             PDF 文档语言（默认: en）
  --skip-convert          跳过 MinerU 转换，直接翻译已有 Markdown
  --md-path PATH          配合 --skip-convert 使用，指定 Markdown 文件路径

paper2zh web [OPTIONS]

Options:
  -h, --host TEXT         监听地址（默认: 127.0.0.1）
  -p, --port INTEGER      监听端口（默认: 8000）
  -o, --output PATH       输出目录（默认: 当前目录下的 output/）
```

## 项目结构

```
paper2zh/
├── .env.example              # 环境变量模板
├── pyproject.toml             # 项目配置
└── src/paper2zh/
    ├── cli.py                 # CLI 入口（translate + web 子命令）
    ├── pipeline.py            # 翻译流水线（串联各模块）
    ├── converter.py           # MinerU PDF → Markdown
    ├── splitter.py            # Markdown 智能分块
    ├── tagger.py              # 论文标签提取（领域 + 术语表）
    ├── translator.py          # LLM 翻译（支持上下文注入）
    ├── naming.py              # 标题提取 + 文件命名
    └── web/
        ├── app.py             # FastAPI 后端
        ├── models.py          # 数据模型
        ├── tasks.py           # 后台任务管理
        └── static/index.html  # WebUI 前端
```

## License

MIT
