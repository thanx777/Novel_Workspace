# Novel Workspace

> AI 长篇小说写作引擎 — 分层大纲 + 知识图谱 + MWR 循环 + 体裁感知

## 项目简介

Novel Workspace 是一个 AI 驱动的长篇小说写作系统，核心解决 **LLM 写长篇时的三大难题**：记忆断裂（角色/伏笔前后矛盾）、节奏失控（爽点密度不足）、内容截断（输出长度限制导致章节缺失）。

系统采用 **MWR（Manager-Writer-Reviewer）循环架构**，通过三引擎流水线完成从大纲到成书的全流程，并内置知识图谱、体裁规则、反幻觉守卫等保障机制。

## 核心架构

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

## 三引擎生成逻辑

### 1. OutlineEngine（大纲引擎）

**入口**：`generate_all()` → `generate_layer("L1")` → `generate_layer("L2")`

**L1 全书大纲生成**：
1. Manager 决定任务类型（首轮 write，后续 polish）
2. Writer 构建 prompt，注入：体裁声明（最高优先级）→ KG 上下文（L1 不注入）→ 用户需求 → 上一轮反馈 → 体裁指南 → 输出格式约束
3. Reviewer 评估：AI 评分（1-10）+ 硬性校验（分卷信息是否完整、伏笔编号是否合规、人名一致性）
4. MWR 循环直到评分 ≥ 8 且硬性校验全过，或连续5轮无提升
5. 生成后 AI 摄取到 KG（提取角色、伏笔、世界观等实体）

**L2 章节细纲生成**：
1. 从 L1 JSON/md 提取分卷信息（卷号、卷名、卷总章节、核心主题）
2. 按卷分批生成：每卷调用 LLM，注入 L1 全文 + KG 上下文 + 体裁指南
3. 每卷生成后校验实际章数 vs 预期，不足则补齐
4. 每卷生成后立即摄取到 KG（新角色、伏笔状态变化），供下一卷使用

**输出文件**：`outline_L1.md` / `outline_L1.json` / `outline_L2.md` / `outline_L2.json`

### 2. WritingEngine（写作引擎）

**入口**：`run()` → 逐章 `run_mwr_cycle()`

**每章 MWR 循环**：
1. **Manager 决策**：
   - 第1轮 → write（写新章节）
   - 硬性校验未通过（缺标题/字数不足）→ write（重写，最多2次）
   - 硬性校验未通过 + 重写次数用尽 → polish（润色，最多N轮）
   - 硬性校验通过但分数不够 → polish
   - 润色次数用尽仍不达标 → accept_current（接受当前版本）

2. **Writer 写章节**（`_write_chapter`），注入上下文：
   - 体裁声明（最高优先级，含核心设定词、叙事指导）
   - 小说大纲（L1 摘要）
   - 本章细纲（L2/L3）
   - 融合记忆：KG 结构化实体 + 反幻觉上下文 + 人物设定 + 用户笔记
   - 前3章全文（自然衔接，清洗FS编号）
   - 体裁注入（InkOS 规范 + Anti-AI 规范 + 爽点结构 + Strand 节奏）

3. **Writer 润色章节**（`_polish_chapter`），注入上下文：
   - 体裁声明 + 大纲 + 融合记忆 + 体裁注入 + 审查反馈
   - 原文全文作为参考

4. **Reviewer 评估**：AI 评分 + 硬性校验 + 反幻觉校验
   - 内容为空或 LLM 错误时强制 score=0 且 all_required_passed=false
   - 内容不足 100 字时跳过 AI 评审

5. **落盘**：LLM 输出清洗FS编号 → 原子写入章节文件 → 更新反幻觉追踪器 → 写入数据库

**输出文件**：`chapters/第N章.txt`

### 3. ReviewEngine（审校引擎）

**入口**：`run_review()` → 逐章逐维度审校

**6个审校维度**：
| 维度 | 说明 |
|------|------|
| 人物弧光 | 主角/配角性格变化是否合理 |
| 伏笔回收 | 所有伏笔是否都有回收 |
| 跨章一致性 | 时间线、角色状态、场景描述是否矛盾 |
| 风格统一 | 文笔风格、叙事视角是否一致 |
| 爽点与钩子 | 爽点密度和章末钩子是否到位 |
| AI痕迹 | 重复句式、万能形容词、说道滥用 |

**断点续校**：停止时保存 `paused` 状态和 `dimensions_done` 列表，继续时跳过已完成维度。

## 关键机制

### 1. MWR 循环（Manager-Writer-Reviewer）

所有引擎共享的迭代骨架，轮数上限可配置：

```
Manager → 决定任务（首轮 write，后续 polish）
Writer  → 生成/修改内容
Reviewer → 评分 + 检查必填字段 + 反馈问题

退出条件：
  - 评分 ≥ 8 且必填字段全过 → 通过
  - 连续3轮评分无提升 → 卡住，接受当前版本
  - 达到 max_rounds 上限 → 强制停止
  - 连续3轮 LLM 错误/空内容 → 强制停止
  - 用户取消 → 停止
```

**项目级配置**：`max_rounds_writing`（默认10）和 `max_rounds_outline`（默认8）可在前端项目配置中调整。

### 2. 分层大纲

| 层级 | 内容 | 生成方式 |
|------|------|----------|
| L1 | 全书大纲：基础信息 + 分卷 | MWR 循环，分卷为必填字段 |
| L2 | 章节细纲：逐章核心目的/出场人物/流程/爽点/衔接 | 按卷分批生成，每卷后校验章数并补齐 |

### 3. 知识图谱（KG）

SQLite 持久化（自动从旧 JSON 迁移），贯穿大纲→写作→审校全流程：

**11 种节点**：chapter / character / scene / plot_thread / foreshadowing / world_fact / outline_node / genre_rule / strand_tag / coolpoint / hook

**数据流**：
```
L1 生成 → 摄取到 KG → L2 按卷生成（每卷注入 KG + 摄取回 KG）
→ 正文逐章写作（注入全部 KG 上下文 + 摄取回 KG）
→ 全书审校（注入 KG 上下文）
```

**核心能力**：
- 写作时注入完整上下文，防止 LLM 遗忘前文
- 校验角色名/伏笔 ID 是否在 KG 中存在，拦截幻觉
- 多 Agent 流水线摄取（chapter-scanner / entity-extractor / foreshadowing-tracker / character-builder / graph-reviewer）
- Per-project 锁，支持多项目并发

### 4. 体裁感知

融合三大体系，注入 Writer/Reviewer prompt：

| 体系 | 来源 | 内容 |
|------|------|------|
| 追读力分类学 | webnovel-writer | 5种钩子 / 8种爽点 / Hard Invariants / 14种体裁裁决规则 |
| 33维审计体系 | InkOS | 5种体裁配置 / 疲劳词列表 / 33维审计维度 |
| Anti-AI 写作规范 | 自研 | 对抗 LLM 8大倾向 / 爽点三段式 / Strand 三线节奏 |

### 5. 反幻觉守卫

四个子模块与 KG 互补：
- **CharacterTracker** — 角色状态追踪（位置/状态/关系变化）
- **PlotThreadTracker** — 情节线索追踪（伏笔埋设/回收状态）
- **ConsistencyChecker** — 跨章节一致性交叉验证
- **FormatValidator** — 章节格式与内容校验（实例化，支持项目级字数配置）

### 6. 全局记忆系统

```
project_dir/memory/
├── novel_memory.md        ← 累积式全局记忆
└── chapter_summaries/     ← 逐章摘要
```

### 7. LLM 错误处理

统一使用 `LLMError` 异常类层级：

| 异常类 | 场景 | 可重试 |
|--------|------|--------|
| `LLMConfigError` | API Key / Base URL 未配置 | 否 |
| `LLMRateLimitError` | 429 速率限制 | 是 |
| `LLMTimeoutError` | 请求超时 | 是 |
| `LLMAuthError` | 401/403 认证失败 | 否 |
| `LLMNotFoundError` | 404 模型不存在 | 否 |
| `LLMServerError` | 5xx 服务端错误 | 是 |
| `LLMEmptyResponseError` | 模型返回空内容 | 否 |

- **call_strict()**：失败时抛出 `LLMError` 子类（推荐新代码使用）
- **call()**：失败时返回 `[LLM_ERROR: ...]` 字符串（向后兼容，已标记 deprecated）
- MWR 循环：连续 3 轮 LLM 错误/空内容自动停止

## 安全机制

| 机制 | 说明 |
|------|------|
| API Key 加密 | Fernet 对称加密存储，密钥从 `NOVEL_WORKSPACE_SECRET` 环境变量或 `.secret_key` 文件读取 |
| 速率限制 | slowapi 中间件，LLM 端点 10次/分钟，普通端点 60次/分钟 |
| 路径遍历防护 | `_validate_project_name()` + `ProjectNameError`，拒绝 `../` 等路径攻击 |
| Schema 迁移 | 版本化迁移链（v0→v1→v2），自动升级旧项目数据库 |

## 快速开始

### 环境

- Python 3.8+
- Node.js 18+

### 启动

```bash
# 后端
cd backend
pip install -r requirements.txt
python main.py          # → http://127.0.0.1:8000

# 前端（新终端）
cd frontend
npm install
npm run dev             # → http://localhost:5173
```

### API Key 配置

1. 在前端项目配置中填入 API Key（自动加密存储）
2. 或设置环境变量 `NOVEL_WORKSPACE_SECRET`（Fernet 密钥，用于 API Key 加解密）

## 前端界面

| 组件 | 功能 |
|------|------|
| ProjectSidebar | 项目创建/管理，设定题材/字数/章节数/MWR轮次 |
| Workbench | 工作台，预设下拉选择 + 引擎控制 + 章节编辑 |
| ChapterEditor | 章节内容编辑器（阅读/编辑/AI修改模式） |
| ChapterTree | 分卷章节树形展示 |
| KnowledgeGraphView | 知识图谱可视化（ForceGraph） |
| OutlinePanel | 大纲面板，L1/L2 分层展示，Markdown 渲染 |
| LogPanel | 实时日志，SSE 推送 MWR 循环状态 |
| Sidebar | 预设管理 + 对话面板 + 任务面板 |

## API 端点

### V2 API（小说专用）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v2/projects` | POST | 创建项目 |
| `/api/v2/projects` | GET | 项目列表 |
| `/api/v2/projects/{id}` | GET/DELETE | 查看/删除项目 |
| `/api/v2/projects/{id}/generate` | POST | 启动大纲生成（SSE） |
| `/api/v2/projects/{id}/write-chapter` | POST | 写单章（SSE） |
| `/api/v2/projects/{id}/review` | POST | 启动全局审校（SSE） |
| `/api/v2/projects/{id}/stop` | POST | 停止当前任务 |
| `/api/v2/projects/{id}/outline` | GET | 获取大纲（L1/L2） |
| `/api/v2/projects/{id}/chapters` | GET | 章节列表 |
| `/api/v2/projects/{id}/chapters/{num}` | GET | 单章内容 |
| `/api/v2/projects/{id}/kg` | GET | 知识图谱数据 |
| `/api/v2/projects/{id}/kg/search` | GET | KG 实体搜索 |
| `/api/v2/projects/{id}/logs` | GET | 历史日志 |
| `/api/v2/projects/{id}/assistant/chat` | POST | AI 助理对话 |
| `/api/v2/projects/{id}/ai-add-character` | POST | AI 添加角色 |
| `/api/v2/projects/{id}/assistant/suggest-next` | POST | AI 建议下一步 |
| `/api/v2/projects/{id}/assistant/analyze-consistency` | POST | AI 一致性分析 |

### V1 API（通用任务）

| 类别 | 端点 | 方法 | 说明 |
|------|------|------|------|
| 任务 | `/api/run-task` | POST | 启动任务(SSE) |
| | `/api/tasks/{folder}/resume` | POST | 恢复任务(SSE) |
| | `/api/stop-task` | POST | 停止任务 |
| | `/api/tasks` | GET | 任务列表 |
| 预设 | `/api/presets` | GET/POST/PUT/DELETE | CRUD |
| 文件 | `/api/workspace/files/{path}` | GET/POST/DELETE | 文件操作 |
| 角色 | `/api/agent-catalog` | GET | 角色目录 |
| 技能 | `/api/skills` | GET/POST/PUT/DELETE | CRUD |
| 优化 | `/api/optimize-prompt` | POST | 提示词优化 |
| 测试 | `/api/test/exec` | POST | 执行测试 |

## 项目结构

```
novel-workspace/
├── backend/
│   ├── main.py                    # FastAPI 入口 + 速率限制
│   ├── project_db.py              # 项目数据库（SQLite + schema 迁移 + API Key 加密）
│   ├── knowledge_graph.py         # 知识图谱核心（SQLite 后端 + JSON 迁移）
│   ├── api/                       # API 路由层
│   │   ├── v2_router.py           # V2 路由聚合
│   │   ├── projects.py            # 项目 CRUD
│   │   ├── generate.py            # 大纲/写作/审校生成
│   │   ├── chapters.py            # 章节读写 + AI 修改
│   │   ├── chat.py                # AI 助理对话
│   │   ├── graph.py               # KG 查询
│   │   ├── outlines.py            # 大纲读写
│   │   ├── logs.py                # 日志查询
│   │   └── ...
│   ├── engines/                   # 三引擎架构
│   │   ├── common/
│   │   │   ├── base_engine.py     # MWR 循环骨架
│   │   │   ├── llm_client.py      # LLM 客户端 + LLMError 异常类层级
│   │   │   ├── kg_adapter.py      # KG 读写适配器（per-project 锁）
│   │   │   ├── genre_adapter.py   # 体裁规则适配器
│   │   │   ├── hallucination_guard.py  # 反幻觉适配器
│   │   │   ├── prompts.py         # 系统提示词 + 引擎配置
│   │   │   └── state.py           # 引擎状态管理
│   │   ├── outline/
│   │   │   └── engine.py          # 大纲引擎（L1→L2）
│   │   ├── writing/
│   │   │   └── engine.py          # 写作引擎（逐章MWR）
│   │   └── review/
│   │       └── engine.py          # 审校引擎（按维度MWR）
│   ├── genre_data/                # 体裁数据
│   ├── scripts/
│   │   └── export_openapi.py      # OpenAPI 规范导出
│   ├── test_all.py                # 全流程测试（27 用例）
│   ├── test_llm_client.py         # LLM 客户端测试（24 用例）
│   ├── test_kg_adapter.py         # KG 适配器测试（27 用例）
│   ├── test_hallucination_guard.py # 反幻觉测试（27 用例）
│   ├── test_outline_engine.py     # 大纲引擎测试（16 用例）
│   ├── test_review_engine.py      # 审校引擎测试（14 用例）
│   ├── test_api_v2.py             # V2 API 测试（14 用例）
│   ├── requirements.txt           # 运行时依赖
│   └── requirements-dev.txt       # 开发/测试依赖
├── frontend/
│   └── src/
│       ├── App.jsx                # 入口组件 + ErrorBoundary
│       ├── context/
│       │   └── AppContext.jsx     # 全局状态（语言/主题/通知）
│       ├── components/
│       │   ├── Workbench/         # 工作台组件集
│       │   │   ├── index.jsx      # 主工作台
│       │   │   ├── ChapterEditor.jsx
│       │   │   ├── ChapterTree.jsx
│       │   │   ├── Modals.jsx
│       │   │   ├── OutlineEditor.jsx
│       │   │   ├── ProjectSidebar.jsx
│       │   │   ├── SidebarTabs.jsx
│       │   │   ├── Toolbar.jsx
│       │   │   └── AssistantPanel.jsx
│       │   ├── ErrorBoundary.jsx  # React 错误边界
│       │   ├── KnowledgeGraphView.jsx
│       │   ├── LogPanel.jsx
│       │   ├── Modals.jsx         # 全局模态框
│       │   ├── OutlinePanel.jsx   # Markdown 渲染（react-markdown）
│       │   └── Sidebar.jsx        # 预设/对话/任务面板
│       ├── hooks/
│       │   ├── usePreset.js       # 预设管理（async/await）
│       │   └── useProjectV2.js    # V2 项目管理
│       ├── utils/
│       │   └── format.js          # 时间格式化工具
│       ├── translations.js        # i18n 翻译（中/英）
│       └── styles/                # 设计系统
└── README.md
```

## 技术栈

- **前端**：React 19 + Vite 8，CSS 变量双主题，SSE 实时推送，react-markdown
- **后端**：FastAPI + AsyncOpenAI，异步并发，SQLite 持久化，slowapi 速率限制
- **安全**：Fernet API Key 加密，路径遍历防护，schema 版本化迁移
- **AI 集成**：OpenAI 兼容 API / Anthropic Claude 原生 API / thinking_mode
- **知识图谱**：SQLite 持久化 + JSON 自动迁移，11种节点 + 10种边，per-project 锁
- **测试**：自定义轻量框架，149 用例（7 个测试文件）
- **设计**：Noto Serif SC 衬线字体，"文人书斋"暖色调主题

## 致谢

- [webnovel-writer](https://github.com/EricZhu-42/webnovel-writer) — 追读力分类学、体裁裁决规则
- [InkOS](https://github.com/Narcooo/inkos) — 33维审计体系、疲劳词列表、语言铁律
