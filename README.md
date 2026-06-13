# Omni-Agent-Hub

> AI 长篇小说写作引擎 — 分层大纲 + 知识图谱 + MWR 循环 + 体裁感知

## 项目简介

Omni-Agent-Hub 是一个 AI 驱动的长篇小说写作系统，核心解决 **LLM 写长篇时的三大难题**：记忆断裂（角色/伏笔前后矛盾）、节奏失控（爽点密度不足）、内容截断（输出长度限制导致章节缺失）。

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

## 关键机制

### 1. MWR 循环（Manager-Writer-Reviewer）

所有引擎共享的迭代骨架，无硬性轮数上限：

```
Manager → 决定任务（首轮 write，后续 polish）
Writer  → 生成/修改内容
Reviewer → 评分 + 检查必填字段 + 反馈问题

退出条件：
  - 评分 ≥ 8 且必填字段全过 → 通过
  - 连续5轮评分无提升 → 卡住，接受当前版本
  - 用户取消 → 停止
```

### 2. 分层大纲

| 层级 | 内容 | 生成方式 |
|------|------|----------|
| L1 | 全书大纲：基础信息 + 分卷（卷号/卷名/卷总章节/核心主题/核心冲突） | MWR 循环，分卷为必填字段 |
| L2 | 章节细纲：逐章的核心目的/出场人物/章节流程/情绪爽点/衔接下章 | 按卷分批生成，每卷后校验章数并补齐 |

**L2 分卷生成流程**：
```
从 L1 提取分卷 → 逐卷调用 LLM → 校验实际章数 vs 预期 → 不足则补齐 → 摄取到 KG → 下一卷
```

### 3. 知识图谱（KG）

JSON 持久化，贯穿大纲→写作→审校全流程：

**11 种节点**：chapter / character / scene / plot_thread / foreshadowing / world_fact / outline_node / genre_rule / strand_tag / coolpoint / hook

**数据流**：
```
L1 生成 → 摄取到 KG（角色、伏笔、世界观）
     ↓
L2 第1卷生成 ← KG 注入
     ↓
L2 第1卷 → 立即摄取到 KG（新角色、伏笔状态变化）
     ↓
L2 第2卷生成 ← KG 注入（包含第1卷新增实体）
     ↓
正文第N章 ← KG 注入（全部上下文：角色+伏笔+场景+世界观+节奏+爽点+钩子）
     ↓
正文第N章 → 摄取到 KG（更新角色状态/伏笔状态/新增场景）
```

**核心能力**：
- 写作时注入完整上下文，防止 LLM 遗忘前文
- 校验角色名/伏笔 ID 是否在 KG 中存在，拦截幻觉
- 多 Agent 流水线摄取（chapter-scanner / entity-extractor / foreshadowing-tracker / character-builder / graph-reviewer）

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
- **FormatValidator** — 章节格式与内容校验

### 6. 全局记忆系统

```
project_dir/memory/
├── novel_memory.md        ← 累积式全局记忆
└── chapter_summaries/     ← 逐章摘要
```

- `[MEMORY: ...]`：每5章更新，记录角色状态、主线进展、伏笔
- `[SUMMARY: ...]`：每10章输出，快速剧情摘要
- 写新章前自动注入全局记忆 + 前文摘要

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

## 前端界面

| 组件 | 功能 |
|------|------|
| ProjectCenter | 项目创建/管理，设定题材/字数/章节数 |
| NovelWorkspace | 小说工作区，章节编辑器 + 侧边栏 |
| ChapterList | 章节列表，逐章生成时实时更新 |
| ChapterEditor | 章节内容编辑器 |
| KnowledgeGraphView | 知识图谱可视化（节点/边/关系） |
| OutlinePanel | 大纲面板，L1/L2 分层展示 |
| LogPanel | 实时日志，SSE 推送 MWR 循环状态 |
| ConfigPanel | 预设配置（模型/温度/模式） |

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
| 测试 | `/api/test/exec` | POST | 执行测试 |

## 项目结构

```
omni-agent-hub/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── v2_api.py                  # V2 API 路由（小说专用）
│   ├── project_db.py              # 项目数据库（SQLite）
│   ├── knowledge_graph.py         # 知识图谱核心（11节点/10边）
│   ├── outline_pipeline.py        # 大纲生成流水线
│   ├── outline_templates.py       # 大纲模板 + 解析 + 校验
│   ├── novel_pipeline.py          # 小说写作流水线
│   ├── memory_pipeline.py         # 多 Agent 记忆摄取流水线
│   ├── memory_manager.py          # 记忆管理器
│   ├── hallucination_guard.py     # 幻觉守卫（旧版）
│   ├── genre_data/                # 体裁数据
│   │   ├── taxonomy.py            # 追读力分类学
│   │   ├── genre_profiles.py      # 14体裁裁决规则
│   │   ├── inkos_data.py          # 33维审计体系
│   │   ├── writing_guides.py      # Anti-AI写作规范
│   │   └── detect.py              # 体裁自动检测
│   ├── engines/                   # 三引擎架构
│   │   ├── common/
│   │   │   ├── base_engine.py     # MWR 循环骨架
│   │   │   ├── llm_client.py      # LLM 客户端（OpenAI/Claude）
│   │   │   ├── kg_adapter.py      # KG 读写适配器
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
│   ├── agents/                    # 60+ 角色 .md
│   │   ├── engineering/           # 工程类
│   │   ├── design/                # 设计类
│   │   ├── product/               # 产品类
│   │   ├── specialized/           # 专业类
│   │   ├── testing/               # 测试类
│   │   └── strategy/              # 策略类
│   └── projects/                  # 项目数据目录
├── frontend/
│   └── src/
│       ├── App.jsx                # 入口组件
│       ├── components/
│       │   ├── ProjectCenter.jsx  # 项目中心
│       │   ├── NovelWorkspace.jsx # 小说工作区
│       │   ├── ChapterList.jsx    # 章节列表
│       │   ├── ChapterEditor.jsx  # 章节编辑器
│       │   ├── KnowledgeGraphView.jsx  # KG 可视化
│       │   ├── OutlinePanel.jsx   # 大纲面板
│       │   ├── LogPanel.jsx       # 实时日志
│       │   └── ConfigPanel.jsx    # 配置面板
│       ├── hooks/
│       │   ├── useProjectV2.js    # V2 项目管理
│       │   ├── useNovelTask.js    # 小说任务
│       │   └── useNovelReader.js  # 章节阅读
│       └── styles/                # 设计系统
└── README.md
```

## 技术栈

- **前端**：React 19 + Vite，CSS 变量双主题，SSE 实时推送
- **后端**：FastAPI + AsyncOpenAI，异步并发，SQLite 持久化
- **AI 集成**：OpenAI 兼容 API / Anthropic Claude 原生 API / thinking_mode
- **知识图谱**：JSON 持久化，11种节点 + 10种边，多 Agent 摄取流水线
- **设计**：Noto Serif SC 衬线字体，"文人书斋"暖色调主题

## 致谢

- [webnovel-writer](https://github.com/EricZhu-42/webnovel-writer) — 追读力分类学、体裁裁决规则
- [InkOS](https://github.com/Narcooo/inkos) — 33维审计体系、疲劳词列表、语言铁律
