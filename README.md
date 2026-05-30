# Novel Forge v4.5

> 长篇小说 AI 写作引擎 — 可视化多智能体编排，一章一章精工细作

## v4.5 更新日志

### 📖 长篇小说写作引擎

**三阶段流水线**：大纲创作(3节点) → 分批写作(5节点，含润色循环) → 全局审校(5节点)

```
Manager → 创作作家 → 内容审查者 → 润色作家 → 终审者 → Manager(回路)
```

- **一章一生成**：每轮只写一章，保证最高质量
- **退出守卫**：Manager 说完成但章数不够 → 系统强制替换 `[EXIT_LOOP]` 为 `[CONTINUE]`，不写完不许退出
- **动态 MAX_ROUNDS**：自动按 `目标章数 × 3` 计算，500章小说也不会提前截断
- **写/改分离**：Worker 自动识别审查意见是"需修改"还是"通过"，修改模式自动加载被修改章节全文

### 🎛️ 三模式适配

| 模式 | 节点数 | 适用模型 | 特点 |
|------|--------|---------|------|
| **标准 (STD)** | 9节点(3×3) | Claude/GPT-4 | 精简提示词，主流模型 |
| **兼容 (CMP)** | 13节点(3+5+5) | GLM/Llama/Qwen | 极详细提示词，润色循环，宽松退出 |
| **完整 (FULL)** | 13节点(3+5+5) | 高级模型 | 最大token、完整角色库、不截断 |

所有模式 Prompt 均已去硬编码——章数、类型、要求全部从用户任务动态提取。

### 💾 任务检查点 + 续跑

- **自动存盘**：每轮结束自动保存 `state.json` 到 `run_xxx/` 文件夹
- **任务面板**：侧边栏"任务"标签页，显示所有任务进度、状态(运行中/已中断/已完成)
- **一键续跑**：停止后点"继续"，从断点恢复执行，画布自动显示完整管线 + preset 配置
- **原子写入**：`state.json.tmp → os.replace()` 防崩溃损坏
- **每任务独立文件夹**：`run_20260528_任务描述/`，内含所有章节 + memory/ + state.json

### 🧠 全局记忆系统

每个小说独立 `run_xxx/memory/` 目录：

```
run_xxx/memory/
└── novel_memory.md   ← 累积式全局记忆
```

- **`[MEMORY: ...]`**：Manager 每5章更新，记录角色状态、主线进展、伏笔
- **`[SUMMARY: ...]`**：Manager 每10章输出，快速剧情摘要
- Worker 写新章前自动注入全局记忆(最近4000字) + 前文摘要
- 断点续跑不丢失

### 👷 Worker 上下文增强

- **最近3章结尾注入**：保证情节衔接连贯，不只依赖上一章
- **章节列表概览**：Worker 看到已完成章节列表，知道写到哪了
- **修订模式**：Reviewer 说"需修改"时，自动加载被修改章节全文 + 审查意见
- **创作模式**：Manager 说"写第N章"时，注入大纲 + 人物设定 + 前文记忆 + 最近章节

### 🎨 UI 重新设计 — "文人书斋"

- **暖墨色/旧纸色**双主题，默认亮色
- **衬线标题字体**（Noto Serif SC），文学气质
- **朱砂红强调色**（传统印泥色），替代工程蓝
- **节点微交互**：hover 上浮、选中发光、删除按钮渐显
- **任务面板重设计**：进度条、状态标签、续跑/删除按钮，全部 CSS 类化
- **交错入场动画**：列表项依次淡入
- 侧边栏标题竖线装饰、毛玻璃效果

### 🔧 工程优化

- **移除死代码**：`LanguageContext.jsx`、`tools.py`、`locales/zh.js`、空目录(`constants/`、`utils/`、`assets/`)
- **移除重复 import**：`import re as _re3` 重复行
- **MODE_CONFIG 清理**：移除未使用的 `enable_tools`、`tool_max_rounds`
- **阶段名映射修复**：`suffix - 1` 替代 `enumerate` 索引，resume 时阶段名不会错位
- **`_count_chapters()` 统一函数**：4处内联章节计数全部改用正则 `第(\d+)章` 精确提取
- **`_manager_says_done` 扫描窗口**：200→500字符
- **对话记忆持久化**：`conversation_history` 保存到 checkpoint，每轮注入 Manager 而不仅是首轮
- **Resume 节点活动映射修复**：`'info'→'thinking'`, `'working'→'responding'`

### 🗑️ 清理的文件

| 文件 | 原因 |
|------|------|
| `backend/tools.py` | 工具调用方案已移除 |
| `frontend/src/LanguageContext.jsx` | 从未被 App.jsx 引用 |
| `frontend/src/locales/zh.js` | LanguageContext 的附属文件 |
| `frontend/src/constants/` | 空目录 |
| `frontend/src/utils/` | 空目录 |
| `frontend/src/assets/` | Vite 默认模板文件 |
| 根目录 `test_*.py` | 临时测试文件 |

---

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

## 使用指南

### 三种模式

工具栏右侧的模式选择器：

| 按钮 | 模式 | 节点 | 提示词 | 适用场景 |
|------|------|------|--------|---------|
| STD | 标准 | 9节点 | 精简 50% | Claude/GPT-4 等强模型 |
| CMP | 兼容 | 13节点(润色循环) | 极详细 | GLM/Llama/Qwen 等弱模型 |
| FULL | 完整 | 13节点(润色循环) | 详细 | 高级模型，最大 token |

### 任务面板

侧边栏"任务"标签页：
- 显示所有已中断/已完成的写作任务
- 进度条显示 `已完成/总章数`
- 点击"继续"从断点恢复，画布自动还原完整管线
- 点击"删除"清理整个 run 文件夹

### 节点类型

| 节点 | 颜色 | 说明 |
|------|------|------|
| **Manager** | 朱砂红 | 指挥调度、查看进度、维护全局记忆 |
| **Worker** | 玉绿 | 创作内容、产出文件 |
| **Reviewer** | 古金 | 审查内容、给出"通过/需修改/不通过" |

### 连线结构 (兼容/完整模式)

```
阶段1 大纲:  m_1 → w_1 → r_1 → m_1(回路)
阶段2 写作:  m_2 → w_2a(创作) → r_2a(审查) → w_2b(润色) → r_2b(终审) → m_2(回路)
阶段3 审校:  m_3 → w_3a(修订) → r_3a(初审) → w_3b(精修) → r_3b(终审) → m_3(回路)
```

## 执行流程

```
用户输入任务："写一个100章的玄幻小说"
    │
    ▼
阶段1: 大纲创作
    Manager → Worker(outline.md + characters.md) → Reviewer → Manager
    │
    ▼
阶段2: 分批写作 (循环100轮)
    Manager(报进度)→ 创作作家(写第N章) → 内容审查者 → 润色作家 → 终审者 → Manager
    │                                                    │
    │                                          [EXIT_LOOP] 未达100章→ [CONTINUE]
    │
    ▼
阶段3: 全局审校
    Manager(找问题)→ 修订编辑 → 初审编辑 → 精修编辑 → 终审编辑 → Manager
    │
    ▼
完成 → 100章全部生成 + 审校通过
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/presets` | GET/POST/PUT/DELETE | 预设模型管理 |
| `/api/run-task` | POST | 执行图谱任务（SSE 流式） |
| `/api/stop-task` | POST | 停止当前任务 |
| `/api/tasks` | GET | 列出所有任务 |
| `/api/tasks/{folder}` | GET/DELETE | 查看/删除任务 |
| `/api/tasks/{folder}/resume` | POST | 续跑任务（SSE 流式） |
| `/api/skills` | GET | Skill 列表 |
| `/api/projects` | GET/POST | 项目保存/加载 |
| `/api/workspace/files` | GET | 列出文件 |
| `/api/test-connection` | POST | 测试 API 连接 |
| `/api/test/terminal/ws` | WebSocket | 终端实时交互 |

## 项目结构

```
omni-agent-hub/
├── backend/
│   ├── main.py              # FastAPI + 图谱执行引擎 + 长篇小说管线
│   ├── test_runner.py       # Agent 测试执行引擎
│   ├── agent_loader.py      # Agent 角色加载器
│   ├── skill_loader.py      # Skill 加载器
│   ├── config.json           # 预设模型配置
│   ├── requirements.txt
│   ├── agents/               # Agent 角色定义
│   ├── skills/               # Skill 定义
│   ├── workspace/            # 文件输出 + run_xxx/ 任务文件夹
│   └── projects/             # 项目保存
├── frontend/
│   ├── src/
│   │   ├── App.jsx           # 主应用 + 13/9节点管线定义
│   │   ├── App.css            # 核心样式
│   │   ├── constants.js       # 常量配置
│   │   ├── translations.js    # 中/英翻译
│   │   ├── styles/            # 设计系统
│   │   │   ├── variables.css  # CSS 变量 + 主题
│   │   │   ├── typography.css # 排版
│   │   │   └── animations.css # 动画
│   │   ├── hooks/
│   │   │   ├── useTask.js     # 任务执行
│   │   │   ├── useCanvas.js   # 画布交互
│   │   │   ├── usePreset.js   # 预设管理
│   │   │   ├── useSkill.js    # Skill 管理
│   │   │   └── useProject.js  # 项目管理
│   │   └── components/
│   │       ├── Canvas.jsx     # 连线 + 节点画布
│   │       ├── ConfigPanel.jsx
│   │       ├── Sidebar.jsx    # 预设/对话/任务面板
│   │       ├── Toolbar.jsx
│   │       ├── Modals.jsx
│   │       ├── TerminalPanel.jsx
│   │       └── TestResultCard.jsx
│   ├── package.json
│   └── vite.config.js
└── README.md
```

## 技术栈

- **前端**：React 19 + Vite 8，SVG 连线，CSS 变量驱动双主题，SSE + WebSocket
- **后端**：FastAPI + AsyncOpenAI，BFS拓扑排序，异步并发，checkpoint序列化
- **AI 集成**：OpenAI 兼容 API / Anthropic Claude 原生 API
- **设计**：Noto Serif SC 衬线字体，"文人书斋"暖色调主题
