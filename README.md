<div align="center">

# Novel Workspace

**AI-Powered Long-Form Novel Writing Engine**

*Hierarchical Outlines · Knowledge Graph · MWR Loop · Genre-Aware*

[![CI](https://github.com/thanx777/Novel_Workspace/actions/workflows/ci.yml/badge.svg)](https://github.com/thanx777/Novel_Workspace/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

Novel Workspace 是一个 AI 驱动的长篇小说写作系统，核心解决 **LLM 写长篇时的三大难题**：

| 痛点 | 解决方案 |
|:----:|:--------:|
| 记忆断裂 — 角色/伏笔前后矛盾 | 知识图谱贯穿全流程，写作时注入完整上下文 |
| 节奏失控 — 爽点密度不足 | 体裁感知系统，融合追读力分类学 + 33维审计 + Anti-AI 规范 |
| 内容截断 — 输出长度限制导致章节缺失 | MWR 循环 + 硬性校验，确保每章达标 |

系统采用 **MWR（Manager-Writer-Reviewer）循环架构**，通过三引擎流水线完成从大纲到成书的全流程。

---

## Architecture

```
用户创建项目 → 设定题材/字数/章节数
       │
       ▼
┌─────────────────────────────────────────────────────┐
│                 三引擎流水线                           │
│                                                       │
│  1. OutlineEngine（大纲引擎）                          │
│     L1 全书大纲 → L2 章节细纲                          │
│     ├─ L1: MWR 循环，必须输出分卷信息                   │
│     └─ L2: 按卷分批生成，每卷生成后校验章数+补齐         │
│                                                       │
│  2. WritingEngine（写作引擎）                          │
│     逐章 MWR 循环，每章：写 → 审 → 润色 → 再审         │
│     ├─ KG 上下文注入（角色/伏笔/场景/世界观）            │
│     ├─ 体裁规则注入（爽点密度/节奏/禁忌）                │
│     └─ 反幻觉校验（人名/伏笔ID一致性）                  │
│                                                       │
│  3. ReviewEngine（审校引擎）                           │
│     按维度 MWR 循环全书审校                             │
│     人物弧光 / 伏笔回收 / 跨章一致性 / 风格统一 /        │
│     爽点与钩子 / AI痕迹检测                             │
└─────────────────────────────────────────────────────┘
       │
       ▼
  全部章节 + 审校通过 → 成书
```

## Key Features

### MWR Loop (Manager-Writer-Reviewer)

所有引擎共享的迭代骨架，轮数上限可配置：

```
Manager → 决定任务（首轮 write，后续 polish）
Writer  → 生成/修改内容
Reviewer → 评分 + 检查必填字段 + 反馈问题

评分机制（增量评分）：
  R1 首次评审 → 锚定 base_score（LLM 完整评审）
  R2+ 增量评审 → 只判断问题修复/新增，不打总分
  评分 = base_score + 修复×1.0 - 新增×0.25 + 重写奖励

退出条件：
  ✓ 评分 ≥ 7 且必填字段全过 → 通过
  ✓ 连续3轮评分无提升 → 卡住，接受当前版本
  ✓ 达到 max_rounds 上限 → 强制停止
  ✓ 连续3轮 LLM 错误/空内容 → 强制停止
  ✓ 用户取消 → 停止
```

#### 润色后处理流水线

每次写作/润色后自动执行，程序化优先于 LLM 修正：

| 层级 | 功能 | 说明 |
|:----:|:----:|:-----|
| 1 | 省略号配额 | 保留前5个，多余替换为标点（，。——！） |
| 2 | 对话标签多样化 | "说道"超过3次随机替换为"沉声道/冷声道/低声道"等 |
| 3 | AI短语黑名单 | "心中一震/不禁感叹/沉默了片刻"等替换为自然表达 |
| 4 | 句长波动注入 | 连续短句≥3个时合并，打破AI节奏模板 |

### Knowledge Graph

SQLite 持久化（自动从旧 JSON 迁移），贯穿大纲→写作→审校全流程：

- **11 种节点**：chapter / character / scene / plot_thread / foreshadowing / world_fact / outline_node / genre_rule / strand_tag / coolpoint / hook
- **增量 upsert**：`INSERT OR REPLACE` 避免全量重建
- **Per-project 锁**：支持多项目并发

```
L1 生成 → 摄取到 KG → L2 按卷生成（每卷注入 KG + 摄取回 KG）
→ 正文逐章写作（注入全部 KG 上下文 + 摄取回 KG）
→ 全书审校（注入 KG 上下文）
```

### Genre-Aware System

融合三大体系，注入 Writer/Reviewer prompt：

| 体系 | 来源 | 内容 |
|:----:|:----:|:-----|
| 追读力分类学 | [webnovel-writer](https://github.com/EricZhu-42/webnovel-writer) | 5种钩子 / 8种爽点 / Hard Invariants / 14种体裁裁决规则 |
| 33维审计体系 | [InkOS](https://github.com/Narcooo/inkos) | 5种体裁配置 / 疲劳词列表 / 33维审计维度 |
| Anti-AI 写作规范 | 自研 | 对抗 LLM 8大倾向 / 爽点三段式 / Strand 三线节奏 |

### Anti-Hallucination Guard

四个子模块与 KG 互补：

- **CharacterTracker** — 角色状态追踪（位置/状态/关系变化）
- **PlotThreadTracker** — 情节线索追踪（伏笔埋设/回收状态）
- **ConsistencyChecker** — 跨章节一致性交叉验证
- **FormatValidator** — 章节格式与内容校验（支持项目级字数配置）

### Authentication & Security

| 机制 | 说明 |
|:----:|:-----|
| JWT + API Key | 双模式认证，`AUTH_DISABLED=true` 可关闭（本地开发） |
| API Key 加密 | Fernet 对称加密存储，密钥从环境变量或 `.secret_key` 文件读取 |
| 速率限制 | slowapi 中间件，LLM 端点 10次/分钟，普通端点 60次/分钟 |
| 路径遍历防护 | `_validate_project_name()` + `ProjectNameError`，拒绝 `../` 等路径攻击 |
| CORS | 环境变量 `CORS_ORIGINS` 控制，默认 `*` |
| Schema 迁移 | 版本化迁移链（v0→v1→v2），自动升级旧项目数据库 |

---

## Quick Start

### 方式一：直接下载 exe（推荐，零配置）

1. 前往 [Releases](https://github.com/thanx777/Novel_Workspace/releases) 下载最新的 `NovelWorkspace.exe`
2. 双击运行 → 弹出原生窗口 → 首次启动引导配置 API Key → 开始写作

> **系统要求**：Windows 10 1809+ / Windows 11（自带 WebView2）
>
> **杀毒软件**：首次运行可能被 Windows Defender 误报，点击"仍要运行"即可
>
> **数据存储**：`%LOCALAPPDATA%\NovelWorkspace\`

### 方式二：从源码运行

#### Prerequisites

- Python 3.8+
- Node.js 18+

#### Launch

```bash
# 一键启动（推荐）
restart-all.bat          # 后端 :8000 + 前端 :5176

# 或手动启动
cd backend
pip install -r requirements.txt
python main.py           # → http://127.0.0.1:8000

cd frontend
npm install
npm run dev              # → http://localhost:5176
```

> 本地开发默认 `AUTH_DISABLED=true`，无需登录即可使用。

### 打包 exe

```bash
cd frontend && npm run build && cd ..
pip install pyinstaller pywebview
pyinstaller NovelWorkspace.spec
# 产出：dist/NovelWorkspace.exe
```

### API Key 配置

1. 在前端项目配置中填入 API Key（自动加密存储）
2. 或设置环境变量 `NOVEL_WORKSPACE_SECRET`（Fernet 密钥，用于 API Key 加解密）

---

## Configuration

### 环境变量

| 变量 | 默认值 | 说明 |
|:-----|:------:|:-----|
| `AUTH_DISABLED` | `false` | 设为 `true` 跳过认证（本地开发） |
| `AUTH_SECRET` | — | JWT 签名密钥，未设置时回退到 `NOVEL_WORKSPACE_SECRET`，再回退到硬编码默认值 |
| `AUTH_TOKEN_EXPIRE_HOURS` | `24` | JWT Token 过期时间（小时） |
| `ADMIN_PASSWORD` | — | 管理员初始密码，未设置时使用默认密码 `admin123` |
| `CORS_ORIGINS` | `*` | 允许的跨域来源，多个用逗号分隔，如 `http://localhost:5176,http://localhost:3000` |
| `NOVEL_WORKSPACE_SECRET` | — | Fernet 对称加密密钥，用于 API Key 加解密 |

### config.json 配置文件

将 `backend/config.example.json` 复制为 `backend/config.json`，按需修改：

```json
{
  "presets": [
    {
      "name": "My-LLM",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-4o",
      "api_key": "sk-xxx",
      "api_format": "openai",
      "thinking_mode": null
    }
  ],
  "workspace_dir": "",
  "projects_dir": "",
  "default_preset": "My-LLM",
  "auth": {
    "disabled": false,
    "token_expire_hours": 24,
    "admin_password_env": "ADMIN_PASSWORD"
  }
}
```

#### Preset 字段说明

| 字段 | 必填 | 说明 |
|:-----|:----:|:-----|
| `name` | Yes | 预设名称，唯一标识 |
| `base_url` | Yes | LLM API 地址（OpenAI 兼容格式） |
| `model` | Yes | 模型名称，如 `gpt-4o`、`deepseek-chat`、`claude-3-5-sonnet-20241022` |
| `api_key` | Yes | API 密钥 |
| `api_format` | No | API 格式：`openai`（默认）或 `claude` |
| `thinking_mode` | No | 思考模式：`"enabled"` / `"disabled"` / `null`（仅 DeepSeek 等支持思考模式的模型） |

#### 支持的 LLM 提供商

| 提供商 | base_url 示例 | api_format | thinking_mode |
|:-------|:-------------|:----------:|:------------:|
| OpenAI | `https://api.openai.com/v1` | `openai` | — |
| DeepSeek | `https://api.deepseek.com/v1` | `openai` | `enabled` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `openai` | — |
| Anthropic Claude | `https://api.anthropic.com` | `claude` | — |
| 其他 OpenAI 兼容 | 按服务商文档 | `openai` | — |

### 项目级配置

每个项目可在前端「项目配置」面板中调整以下参数：

| 参数 | 默认值 | 说明 |
|:-----|:------:|:-----|
| `word_count_min` | 3000 | 每章最少字数 |
| `word_count_max` | 5000 | 每章最多字数 |
| `max_rounds_writing` | 10 | 写作 MWR 循环最大轮次 |
| `max_rounds_outline` | 8 | 大纲 MWR 循环最大轮次 |
| `max_polish_rounds` | 3 | 每章最大润色轮次 |
| `total_chapters` | — | 总章节数（创建时设定） |
| `genre` | — | 体裁（创建时设定，影响体裁规则注入） |

---

## Tech Stack

| Layer | Technologies |
|:-----:|:-------------|
| **Frontend** | React 19 · Vite 8 · Vitest · CSS Variables 双主题 · SSE · react-markdown |
| **Backend** | FastAPI · AsyncOpenAI · SQLite · slowapi · Fernet |
| **AI** | OpenAI Compatible API · Anthropic Claude · thinking_mode |
| **Knowledge Graph** | SQLite + JSON 自动迁移 · 11种节点 · 11种边 · per-project 锁 |
| **Testing** | pytest (backend 67+ cases) · Vitest + Testing Library (frontend 17+ cases) |
| **CI/CD** | GitHub Actions · ruff · eslint · prettier |
| **Design** | Noto Serif SC 衬线字体 · "文人书斋"暖色调主题 |

---

## Project Structure

```
novel-workspace/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── launcher.py                # PyInstaller 启动器（pywebview 原生窗口）
│   ├── paths.py                   # 统一数据根目录管理
│   ├── project_db.py              # 项目数据库 + 用户认证
│   ├── knowledge_graph.py         # 知识图谱核心（增量 upsert）
│   ├── api/                       # API 路由层（模块化）
│   │   ├── auth.py                # JWT + API Key 认证
│   │   ├── auth_models.py         # 认证数据模型
│   │   ├── shared.py              # 共享限流器 + 路径辅助
│   │   ├── v2_router.py           # V2 路由聚合
│   │   ├── v1_router.py           # V1 路由（deprecated）
│   │   ├── projects.py            # 项目 CRUD
│   │   ├── generate.py            # 大纲/写作/审校生成（SSE）
│   │   ├── chapters.py            # 章节读写 + AI 修改
│   │   ├── chat.py                # AI 助理对话
│   │   ├── graph.py               # KG 查询
│   │   ├── outlines.py            # 大纲读写
│   │   ├── presets.py             # 预设管理
│   │   ├── skills.py              # 技能 CRUD
│   │   ├── workspace.py           # 文件操作
│   │   ├── agent_catalog.py       # 角色目录 + 提示词优化
│   │   ├── assistant.py           # AI 助手
│   │   ├── config_api.py          # 工作区配置
│   │   └── skill_loader.py        # 技能数据访问层
│   ├── engines/                   # 三引擎架构
│   │   ├── common/
│   │   │   ├── base_engine.py     # MWR 循环骨架
│   │   │   ├── llm_client.py      # LLM 客户端 + LLMError 异常类层级
│   │   │   ├── kg_adapter.py      # KG 读写适配器（per-project 锁）
│   │   │   ├── genre_adapter.py   # 体裁规则适配器
│   │   │   ├── hallucination_guard.py  # 反幻觉守卫
│   │   │   ├── prompts.py         # 系统提示词 + 引擎配置
│   │   │   └── state.py           # 引擎状态管理
│   │   ├── outline/engine.py      # 大纲引擎（L1→L2）
│   │   ├── writing/engine.py      # 写作引擎（逐章MWR）
│   │   └── review/engine.py       # 审校引擎（按维度MWR）
│   ├── genre_data/                # 体裁数据
│   ├── conftest.py                # pytest 共享 fixtures
│   ├── pyproject.toml             # pytest + ruff 配置
│   ├── requirements.txt           # 运行时依赖
│   └── requirements-dev.txt       # 开发/测试依赖
├── frontend/
│   └── src/
│       ├── App.jsx                # 入口组件 + Provider
│       ├── context/
│       │   ├── AppContext.jsx      # 全局状态（语言/主题/通知）+ t() 插值
│       │   ├── PresetContext.jsx   # 预设 Context
│       │   └── ProjectContext.jsx  # 项目 Context
│       ├── components/
│       │   ├── Workbench/          # 工作台组件集
│       │   ├── common/
│       │   │   └── AccessibleButton.jsx  # 可访问按钮组件
│       │   ├── ErrorBoundary.jsx
│       │   ├── KnowledgeGraphView.jsx
│       │   ├── LogPanel.jsx
│       │   ├── OutlinePanel.jsx
│       │   └── Sidebar.jsx
│       ├── hooks/
│       │   ├── useProjectV2.js    # 聚合 hook（64 行）
│       │   ├── useProjectCrud.js  # 项目 CRUD
│       │   ├── useEngineStream.js # SSE 引擎流
│       │   ├── useStageReview.js  # 阶段审核
│       │   ├── useProjectFiles.js # 文件读写
│       │   ├── useProjectLogs.js  # 日志 + 预设 + 迁移
│       │   ├── useEngineState.js  # 引擎状态查询
│       │   └── usePreset.js       # 预设管理
│       ├── utils/
│       │   ├── format.js          # 时间格式化
│       │   └── sse.js             # SSE 纯函数（formatSSEEvent + readSSEStream）
│       ├── styles/
│       │   └── components.css     # 设计系统 CSS
│       ├── translations.js        # i18n（中/英，支持 {{param}} 插值）
│       └── test/setup.js          # Vitest setup
├── .github/workflows/ci.yml       # GitHub Actions CI
└── restart-all.bat                 # 一键启动脚本
```

---

## API Reference

### V2 API（小说专用）

| 端点 | 方法 | 说明 |
|:-----|:----:|:-----|
| `/api/v2/projects` | POST | 创建项目 |
| `/api/v2/projects` | GET | 项目列表 |
| `/api/v2/projects/{name}` | GET/DELETE | 查看/删除项目 |
| `/api/v2/projects/{name}/outline/generate/stream` | POST | 启动大纲生成（SSE） |
| `/api/v2/projects/{name}/writing/start/stream` | POST | 启动写作（SSE） |
| `/api/v2/projects/{name}/review/start/stream` | POST | 启动审校（SSE） |
| `/api/v2/projects/{name}/stop` | POST | 停止当前任务 |
| `/api/v2/projects/{name}/outline` | GET | 获取大纲（L1/L2） |
| `/api/v2/projects/{name}/chapters` | GET | 章节列表 |
| `/api/v2/projects/{name}/chapters/{num}` | GET | 单章内容 |
| `/api/v2/projects/{name}/kg` | GET | 知识图谱数据 |
| `/api/v2/projects/{name}/kg/search` | GET | KG 实体搜索 |
| `/api/v2/projects/{name}/logs` | GET | 历史日志 |
| `/api/v2/projects/{name}/assistant/chat` | POST | AI 助理对话 |
| `/api/login` | POST | 登录获取 JWT |

### V1 API（通用任务，deprecated）

| 类别 | 端点 | 方法 | 说明 |
|:----:|:-----|:----:|:-----|
| 任务 | `/api/run-task` | POST | 启动任务(SSE) |
| | `/api/stop-task` | POST | 停止任务 |
| 预设 | `/api/presets` | GET/POST/PUT/DELETE | CRUD |
| 文件 | `/api/workspace/files/{path}` | GET/POST/DELETE | 文件操作 |
| 角色 | `/api/agent-catalog` | GET | 角色目录 |
| 技能 | `/api/skills` | GET/POST/PUT/DELETE | CRUD |
| 测试 | `/api/test/exec` | POST | 执行测试 |

---

## LLM Error Handling

统一使用 `LLMError` 异常类层级：

| 异常类 | 场景 | 可重试 |
|:------:|:-----|:------:|
| `LLMConfigError` | API Key / Base URL 未配置 | No |
| `LLMRateLimitError` | 429 速率限制 | Yes |
| `LLMTimeoutError` | 请求超时 | Yes |
| `LLMAuthError` | 401/403 认证失败 | No |
| `LLMNotFoundError` | 404 模型不存在 | No |
| `LLMServerError` | 5xx 服务端错误 | Yes |
| `LLMEmptyResponseError` | 模型返回空内容 | No |

- **call_strict()**：失败时抛出 `LLMError` 子类（推荐）
- MWR 循环：连续 3 轮 LLM 错误/空内容自动停止

---

## Acknowledgements

- [webnovel-writer](https://github.com/EricZhu-42/webnovel-writer) — 追读力分类学、体裁裁决规则
- [InkOS](https://github.com/Narcooo/inkos) — 33维审计体系、疲劳词列表、语言铁律

---

<div align="center">

**Novel Workspace** — 让 AI 写出真正的长篇小说

</div>
