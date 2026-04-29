# astrbot_plugin_paper

面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的多来源论文插件，支持 ArXiv 与 Hugging Face 的检索、获取、定时推送与去重，并提供 LLM 摘要处理与 PDF 增强能力。

## 功能特性

- **多来源检索** - 同时支持 ArXiv 与 Hugging Face 论文来源
- **快速搜索** - `/arxiv search` 与 `/huggingface search` 返回轻量搜索结果
- **单篇精确获取** - `/arxiv get <arxiv_id>` 获取指定论文完整内容
- **最新论文获取** - 支持按配置拉取 ArXiv 最新论文与 Hugging Face 每日论文
- **定时推送与去重** - 支持分来源定时推送，自动跳过已发送论文
- **会话管理** - 支持通过命令将当前会话添加/移除推送目标
- **发送模式** - 支持逐条发送与合并转发
- **PDF 增强** - 支持附带 PDF、首页截图、大小限制控制
- **摘要处理** - 支持原文摘要、LLM 中文处理、摘要图片渲染
- **LLM 论文总结** - 可基于论文内容生成中文总结，并支持自定义 Prompt

## 指令列表

| 指令 | 说明 |
|------|------|
| `/arxiv help` | 显示 ArXiv 指令帮助 |
| `/arxiv search <关键词> [数量]` | 搜索 ArXiv 论文（仅显示基本信息，不下载 PDF） |
| `/arxiv get <arxiv_id>` | 通过 arXiv ID 获取单篇论文完整内容（含 PDF 截图/LLM 总结） |
| `/arxiv latest` | 获取已配置分类下的最新 ArXiv 论文 |
| `/arxiv categories` | 列出所有支持的 ArXiv 学科分类 |
| `/arxiv status` | 查看 ArXiv 配置与状态 |
| `/arxiv add_session` | 将当前会话加入定时推送目标 |
| `/arxiv remove_session` | 将当前会话移出定时推送目标 |
| `/huggingface help` | 显示 Hugging Face 指令帮助 |
| `/huggingface search <关键词> [数量]` | 搜索 Hugging Face 论文（仅显示基本信息，不下载 PDF） |
| `/huggingface latest` | 获取 Hugging Face 每日论文 |
| `/huggingface status` | 查看 Hugging Face 配置与状态 |

> 合并转发模式依赖平台能力（如 QQ）。若当前平台不支持，请关闭 `use_forward`。

## 使用示例

```text
# ArXiv 快速搜索
/arxiv search diffusion model
/arxiv search attention transformer 5

# 按 ID 获取单篇论文完整内容
/arxiv get 2501.12345

# 拉取最新论文
/arxiv latest
/huggingface latest
```

## 配置说明

可在 AstrBot WebUI 的插件管理面板中修改全部配置项。

### arxiv_config

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `categories` | list | `['cs.AI']` | ArXiv 学科分类代码列表 |
| `tags` | list | `[]` | 关键词标签（模糊匹配） |
| `max_results` | int | `1` | 每次推送/搜索的最大论文数量 |
| `timeout_seconds` | int | `30` | HTTP 请求超时（秒） |

### huggingface_config

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `max_results` | int | `1` | 每次推送/搜索的最大论文数量 |
| `timeout_seconds` | int | `30` | HTTP 请求超时（秒） |

### network_config

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `proxy` | string | `""` | 全局代理地址（留空表示不使用） |

### send_config

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `push_time` | string | `"09:00"` | ArXiv 每日推送时间（HH:MM） |
| `huggingface_push_time` | string | `"10:00"` | Hugging Face 每日推送时间（HH:MM） |
| `push_timezone` | string | `"Asia/Shanghai"` | 推送时区 |
| `target_sessions` | list | `[]` | 自动推送目标 UMO 会话列表 |
| `use_forward` | bool | `false` | 是否使用合并转发发送 |
| `bot_name` | string | `"ArXiv Bot"` | 统一机器人昵称（来源专属昵称未设置时回退使用） |
| `arxiv_bot_name` | string | `"ArXiv Bot"` | ArXiv 来源显示昵称 |
| `huggingface_bot_name` | string | `"Hugging Face Bot"` | Hugging Face 来源显示昵称 |
| `send_abstract` | bool | `true` | 是否发送摘要 |
| `abstract_as_image` | bool | `false` | 是否将摘要渲染为图片 |
| `attach_pdf` | bool | `true` | 是否附带 PDF 文件 |
| `screenshot_pdf` | bool | `true` | 是否截图 PDF 首页 |
| `screenshot_dpi` | int | `150` | PDF 首页截图 DPI |
| `max_pdf_size_mb` | int | `20` | PDF 最大体积限制（MB） |
| `history_retention_days` | int | `30` | 已发送记录保留天数 |

### llm_config

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `abstract_mode` | string | `"original"` | 摘要处理方式：`original` / `llm_chinese` |
| `llm_summarize` | bool | `false` | 是否启用 LLM 论文总结 |
| `llm_provider_id` | string | `""` | LLM 提供商 ID（留空时使用当前对话默认提供商） |
| `llm_summary_prompt` | text | `""` | 自定义总结 Prompt（需包含 `{content}`） |

## 依赖

- `aiohttp`：异步 HTTP 请求
- `feedparser`：ArXiv Atom XML 解析
- `pymupdf`：PDF 文本提取与截图（软依赖）
- `Pillow`：摘要图片渲染（软依赖）

## 许可证

[GPL-3.0](LICENSE)
