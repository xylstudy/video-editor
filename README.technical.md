> 原版技术说明归档。部分界面、模型名称和执行流程反映早期实现；当前成果、启动方法和能力边界请以 [项目首页](README.md) 及对应专题文档为准。

<p align="center">
  <img src="./assets/banner.svg" alt="CapCut Claw — 爆款Vlog结构迁移引擎" width="100%">
</p>

## 一、项目说明

### 1.1 项目定位

Video Claw 不是一个通用的视频编辑工具，而是一个 **AI 驱动的结构迁移引擎**。其核心假设是：**爆款视频之所以"爆"，其剪辑节奏、镜头结构、转场手法、字幕风格是可被提取、量化和复用的**。

项目通过 AI 多智能体系统分析爆款抖音旅行 Vlog（已分析 11 条爆款），提取其剪辑手法知识库，然后将这套结构迁移到用户自己的照片素材上，自动生成专业级 Vlog 视频。

### 1.2 两条技术路线

| 路线 | 入口 | 驱动方式 | 是否需要 LLM API | 适用场景 |
|------|------|---------|------------------|---------|
| **编辑迁移（轻量）** | `run_editing_transfer.py` | 规则引擎 + librosa 节拍检测 | 否 | 快速出片，一键运行 |
| **多智能体流水线（完整）** | `main.py` | 9 个 AI Agent + LangGraph | 是（DeepSeek / Zhipu） | 需 AI 深度理解视频内容 |

两条路线共享同一套 Remotion 渲染引擎和剪辑手法知识库，输出相同格式的 `scheme.json` + `material_map.json`。

### 1.3 两条路线的本质区别

虽然两条路线目标相同（照片→视频），但它们的思考方式完全不同：

#### 路线一：多智能体流水线（AI 深度理解）

```
工作方式：  看懂了爆款视频 → 看懂了照片内容 → 思考怎么迁移 → 生成方案 → 渲染 → 检查质量
            每一步都是 AI 在"理解"和"决策"

核心逻辑：  "因为我理解了爆款视频为什么好看，
             也看懂了你的照片里有什么，
             所以我决定在这个位置用这张照片配这个转场"
```

- 相当于**一个专业团队**：分析师看爆款、管家看照片、编导出方案、导演喊卡、审片员查质量
- 每个角色都调用 LLM 做理解，方案是从内容理解中推导出来的
- 优点：能处理复杂的创作决策，照片再多也能智能编排
- 缺点：慢（15~30 次 API 调用），贵（每次调用消耗 token），需要配置 API Key

#### 路线二：编辑迁移（规则引擎驱动）

```
工作方式：  提取爆款视频的节拍 → 按节拍分配照片 → 用预定义规则选转场/字幕 → 渲染
            不需要 AI 理解内容，纯粹按数学规则编排

核心逻辑：  "因为爆款视频前 3 秒节奏快，
             所以我也在前 3 秒放 3 张照片用快速切换，
             不管照片里拍的是什么"
```

- 相当于**一套自动化流水线**：检测音乐节拍→按拍子切分→轮选转场→轮选运镜→拼接渲染
- 所有决策基于预定义规则（转场池、运镜轮换、字幕样式表），不需要调用任何 LLM
- 优点：快（秒级出方案），免费（无 API 消耗），稳定（结果可预测）
- 缺点：不"理解"内容，所有照片一视同仁，无法根据照片内容做定制化决策

#### 核心差异总结

| 对比维度 | 多智能体流水线 | 编辑迁移 |
|---------|-------------|---------|
| **驱动方式** | AI 理解驱动 | 规则 + 节拍驱动 |
| **是否理解内容** | 是（GLM-4.6V 看懂每张照片） | 否（照片只是"第 N 张图"） |
| **方案质量天花板** | 高（能做出创意决策） | 中（规则上限固定） |
| **API 消耗** | 15~30 次/轮 | 0 次 |
| **运行时间** | 5~30 分钟（取决于 LLM 响应） | 1~3 分钟 |
| **成本** | 每次运行约 ¥0.5~3 (API 费用) | 0 |
| **适用场景** | 追求高质量、内容理解重要的场景 | 批量出片、快速验证、无 API Key |
| **可预期性** | 低（LLM 每次输出有差异） | 高（规则固定输出一致） |

#### 实际选择建议

```
刚开始接触项目 → 先跑编辑迁移（零成本体验完整流程）
已有 API Key  → 跑多智能体流水线（体验 AI 深度理解）
批量出片      → 编辑迁移（稳定可预期）
精品单条      → 多智能体流水线（质量更高）
```

### 1.4 核心能力

- **爆款分析**：逐镜头分析爆款 Vlog 的画面内容、拍摄技法、结构功能（使用 GLM-4.6V 多模态模型）
- **节奏迁移**：提取爆款视频的结构骨架（5 段式情绪弧线 + 节奏曲线 + 包装风格），迁移到新素材
- **素材管理**：自动分析用户照片的构图、内容、人脸，评估其 Vlog 适用性
- **方案生成**：AI 编导根据素材和爆款结构，生成完整分镜方案（30+ 字段/分镜）
- **视频渲染**：Remotion v4 渲染引擎，支持 30+ 种转场、Ken Burns 运镜、前景分割合成、8 种字幕样式，另有进阶特效示范 Composition（粒子 / 真实运动模糊 / 卡点爆发）
- **质量闭环**：10 维度 AI 审核评分，不达标自动迭代优化（最多 3 轮）
- **统计洞察**：只聚合当前账号的基因分析，统计前 3 秒镜头数 / 节奏 / 镜头类型 / 情绪弧线 / 转场分布；原生深色图表支持逐镜头轨迹钻取（见 3.4）
- **生成可溯源**（2026-08 新增）：逐镜头分析 / 知识提炼 / 方案生成全程落盘 `*_trace.json`，知识与方案携带来源推导信息，评审关联与效果统计可追根溯源（见 3.3）
- **Web 平台**（2026-07 新增）：多用户 Web 应用——FastAPI 后端 + React 前端，基因库 / 知识库 / 统计洞察 / 项目管理 / 任务实时进度 / 作品集一体化（见第三章）

### 1.5 知识库来源

项目从 11 个抖音旅行爆款 Vlog 中提取了完整的剪辑手法知识库：

| 分类 | 数量 | 说明 |
|------|------|------|
| 转场效果 | 20 种 | slide / wipe / fade / dissolve / glitch / flip_3d 等 |
| 前景揭示特效 | 7 种 | float_up / scale_burst / glow_fade / parallax 等 |
| 字幕样式 | 8 种 | typewriter / neon_sign / gradient_bar / cinematic 等 |
| 风格预设 | 3 种 | 快速电子 / 电影氛围 / 创意混合 |
| 关键技法 | 8 条 | 前 3 秒抓眼球 / 音乐卡点 / 5 段式情绪弧线 / 转场不重复等 |

---

## 二、代码运行说明

### 2.1 系统依赖

```
- Python >= 3.11（项目基准版本 3.12）
- Node.js 20.19+ 或 22.12+（项目基准版本 22/24）
- FFmpeg (需在 PATH 中)
- Git
- 操作系统: Windows 11（主要开发环境；CI 同时在 Linux 验证）
```

### 2.2 安装步骤

#### Windows 一键安装（推荐）

项目根目录执行：

```powershell
# 默认创建项目本地 .venv；缺少 Python 3.12、FFmpeg 或 Node 时通过 winget 安装，
# 然后安装前端/Remotion 依赖和 Playwright Chromium
.\setup_windows.ps1

# 不使用抖音下载器时可跳过 Chromium（其余依赖仍会安装）
.\setup_windows.ps1 -SkipBrowser

# 偏好 Conda 时可改用 environment.yml
.\setup_windows.ps1 -Mode conda
```

系统已经安装其他 Python 3.11+ 时，也可以显式指定：

```powershell
.\setup_windows.ps1 -Mode venv -PythonExecutable "C:\path\to\python.exe"
```

#### 手动安装

```bash
# 统一安装引擎、Web 后端、测试与下载器 Python 依赖
python -m pip install -c requirements-lock.txt -r requirements-dev.txt

# Node 依赖使用锁文件安装
npm ci --prefix web/frontend
npm ci --prefix viral-structure-engine/remotion

# 抖音下载器需要浏览器（可选）
python -m playwright install chromium

# 启动前体检
python scripts/preflight.py --full
```

Python 基准版本记录在 `.python-version`，Conda 环境定义在 `environment.yml`；
`requirements-dev.txt` 是各 Python 子项目依赖的统一入口，`requirements-lock.txt`
锁定已验证的 Python 3.12 依赖版本。

### 2.3 环境变量配置

在 `viral-structure-engine/` 下创建 `.env` 文件：

```ini
# DeepSeek Chat — 文本推理（方案生成 / 审核 / 规划）
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# Zhipu GLM-4.6V — 多模态视觉分析（视频帧分析 / 照片理解）
ZHIPU_API_KEY=your-key
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4

# Moonshot/Kimi — 备选 LLM
MOONSHOT_API_KEY=sk-your-key

# 阿里云 — 前景分割（segment_aliyun.py）
# 需开通 OSS 和图像分割（SegmentCommonImage）服务
ALIYUN_ACCESS_KEY_ID=your-access-key-id
ALIYUN_ACCESS_KEY_SECRET=your-access-key-secret
ALIYUN_REGION=cn-shanghai
ALIYUN_BUCKET_NAME=video-seg-3270e1a5
ALIYUN_OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
```

### 2.4 运行方式

#### 方式一：编辑迁移（一键出片，无需 LLM）

```bash
cd viral-structure-engine

# 前置步骤：准备素材清单并完成素材入库（只需执行一次）
python run_material_analysis.py --materials-json ../data/materials.json --topic "咖啡探店" --output data/runs/manual/material/inventory.json

# 一键迁移
python run_editing_transfer.py --viral-video ../data/reference.mp4 --materials data/runs/manual/material/inventory.json --topic "咖啡探店"
```

#### 方式二：多智能体流水线（需要 LLM API）

```bash
cd viral-structure-engine

# 端到端执行
python main.py --topic "北京旅行Vlog" \
    --samples "../mmexport1779631125302.mp4" \
    --materials "../data/北京/materials.json"

# 或使用北京照片专属流水线
python run_beijing_pipeline.py
```

#### 方式三：分步调试流水线

```bash
cd viral-structure-engine

# 1. 爆款视频逐镜头分析
python run_video_analysis.py

# 2. 照片素材入库
python run_material_analysis.py --materials-json ../data/materials.json --output data/runs/manual/material/inventory.json

# 3. 分镜方案生成
python run_scheme_generation.py

# 4. 生成并渲染
python run_editing_transfer.py --viral-video ../data/reference.mp4 --materials data/runs/manual/material/inventory.json
```

#### 方式四：前景分割（阿里云 API）

```bash
cd viral-structure-engine

# 需要阿里云 OSS 和图像分割 API 权限
python segment_aliyun.py

# 或使用本地 OpenCV GrabCut（无需 API）
python segment_photos.py
```

#### 方式五：抖音视频下载

```powershell
cd get_video
.\download.ps1
```

#### 方式六：Web 应用（推荐，多用户 + 实时进度）

```bash
# Windows 一键启动（自动定位项目路径与 video-claw/.venv Python，启动前先做环境体检）
start_web.bat

# 只检查环境，不启动服务
start_web.bat --check

# 或手动启动
cd web/backend && python -m uvicorn main:app --host 127.0.0.1 --port 8000
cd web/frontend && npm run dev
```

- 前端界面：http://localhost:5173 ｜ 后端 API 文档：http://127.0.0.1:8000/docs
- 注册账号后可执行 `python web/backend/seed_demo.py <用户名>` 写入示例基因/项目/成片，页面开箱即有内容
- 用户级 API Key 在「设置」页配置，任务运行时优先于引擎 `.env`

详见第三章「Web 应用平台」。

### 2.5 输出产物

```
data/runs/{run_id}/
├── run_info.json                   # 运行配置
├── pipeline_summary.json           # 最终摘要
├── 01_analyst/                     # 爆款分析结果
│   ├── video_info.json
│   ├── scenes.json
│   ├── shot_analyses.json
│   ├── structure_analysis.json
│   ├── analysis_trace.json         # 逐镜头推理轨迹（溯源）
│   └── frames/                     # 关键帧图片
├── 02_material/                    # 素材分析结果
│   └── inventory.json
├── 03_planner/                     # 方案生成
│   ├── skeleton.json
│   ├── scheme_v0.json / v1.json
│   └── planning_trace.json         # 方案决策轨迹（溯源）
├── 04_renderer/                    # 渲染决策
│   └── render_decisions.json
├── 05_assembler/                   # 视频合成
│   └── rendered_video.mp4
├── 06_reviewer/                    # 审核评估
│   └── review_result.json
└── logs/
    └── agent_logs.jsonl
```

---

## 三、Web 应用平台（2026-07 新增）

引擎最初只有命令行脚本：没有用户概念、过程不可见、分析产物跑完就扔。Web 平台把这台"发动机"装进了能开的车里——**FastAPI 后端 + React 前端**，覆盖完整产品闭环：

```
工作台 → 基因库（拆解爆款）→ 知识库（沉淀经验）→ 统计洞察（聚合跨视频规律）→ 项目（迁移生成）→ 作品集（展示成果）
```

### 3.1 功能页面展示

**工作台** — 项目 / 基因 / 知识 / 成片统计 + 最近任务，一眼掌握全局：

<p align="center">
  <img src="./assets/web/dashboard.png" alt="工作台" width="720">
</p>

**基因库** — 上传爆款视频，引擎后台自动拆解其结构基因（Hook 策略 / 段落结构 / 节奏曲线 / 包装风格）：

<p align="center">
  <img src="./assets/web/genes.png" alt="基因库" width="720">
</p>

**基因报告** — 分析结果可视化：基因概览标签、前 3 秒 Hook 策略、逐镜头标注、节奏曲线图，可一键提炼知识入库或直接用它创建项目：

<p align="center">
  <img src="./assets/web/gene-detail.png" alt="基因报告" width="720">
</p>

**知识库** — “我的知识”和“系统技法”分层展示：新账号的个人知识从 0 开始，52+ 条内置剪辑技法单独放在系统技法中；支持类型筛选、搜索、逐条播放演示视频。多智能体生成时会组合系统能力与当前用户个人知识，且不会读取其他用户的条目：

<p align="center">
  <img src="./assets/web/knowledge.png" alt="知识库" width="720">
</p>

**项目详情** — 上传参考视频与照片素材，选择执行步骤（完整生成 / 仅素材分析 / 仅视频分析）；创建项目时可直接选用基因库中已分析的爆款作参考：

<p align="center">
  <img src="./assets/web/project-detail.png" alt="项目详情" width="720">
</p>

**任务详情** — 步骤时间线（素材分析 → 视频分析 → 生成分镜 → 用户确认 → 渲染输出）+ 可编辑分镜确认台 + WebSocket 实时日志 + 成片预览下载。确认台支持更换素材、修改时长/字幕/转场、上下排序和删除分镜：

<p align="center">
  <img src="./assets/web/task-detail.png" alt="任务详情" width="720">
</p>

**作品集** — 所有项目生成的成片集中画廊，随时播放和下载：

<p align="center">
  <img src="./assets/web/works.png" alt="作品集" width="720">
</p>

**设置** — 每用户独立配置智谱 / DeepSeek / Moonshot / 阿里云 API Key，任务运行时优先于引擎 `.env`：

<p align="center">
  <img src="./assets/web/settings.png" alt="设置" width="720">
</p>

### 3.2 三层架构

```
┌─────────────────────────────────────────────────────────┐
│  前端 React（web/frontend，Vite + Tailwind，端口 5173）  │
│  12 个页面，深色主题设计系统                              │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP /api + WebSocket（Vite 代理）
┌──────────────────────▼──────────────────────────────────┐
│  后端 FastAPI（web/backend，端口 8000）                   │
│  JWT 认证 → 项目/素材 → 任务队列 → 进度广播               │
│  genes / knowledge / insights / works / stats 五个产品模块│
└──────────────────────┬──────────────────────────────────┘
                       │ 子进程调用脚本 + 进程内 import
┌──────────────────────▼──────────────────────────────────┐
│  引擎 viral-structure-engine/                            │
│  analyze_video.py / run_material_analysis.py /           │
│  run_editing_transfer.py / run_pipeline_e2e.py /         │
│  knowledge/ 知识子系统（knowledge.json 为单一事实源）     │
└─────────────────────────────────────────────────────────┘
```

### 3.3 关键设计

- **任务级引擎契约**：后端以子进程方式调用引擎脚本，并显式传入任务独立的输入、草案和输出路径，避免并发任务共享中间文件。
- **实时进度**：任务队列（asyncio 单 worker）执行中把日志写入 WebSocket 广播；基因提取走独立后台任务，解析子进程输出的 `__GENE_EVENT__` 事件，前端 3 秒轮询 + 进度可视化，支持取消。
- **知识单一事实源**：知识库不复制到 Web 数据库，每次请求直接读/写引擎的 `knowledge.json`，CLI 与 Web 看到的是同一份知识；用户提炼的知识自动签发 `k_u{user_id}_{uuid8}` 全局唯一 ID，且仅本人可见可删（用户隔离）。
- **基因复用**：创建项目时指定 `gene_id`，后端自动把基因视频复制为项目参考素材，分析过一次的视频可无限次复用。
- **渲染前确认**：完整任务先生成 `scheme.json` 并暂停到等待确认状态；用户保存草案后才进入纯渲染阶段，渲染阶段不调用模型 API。
- **多用户**：bcrypt 密码哈希 + JWT（7 天有效期），项目 / 素材 / 任务 / 基因 / API Key 全部按用户隔离。
- **生成可溯源**：逐镜头分析（`analysis_trace.json`）、知识提炼（`knowledge_extract_trace.json`）、方案生成（`planning_trace.json`）会把推理轨迹落盘——含每镜 frame_paths / prompt 版本 / 模型 / 原始返回；知识条目携带 `derivation`（来源基因、prompt 版本、模型、时间），方案携带 `knowledge_refs`（注入参考的手法 id），供审核关联、效果统计与故障排查。
- **统计洞察**：Insights 只扫描当前用户 `genes/`，不混入全局历史产物；接口输出已脱敏，前端使用原生 React 深色图表（详见 3.4）。

### 3.4 统计洞察（2026-08 新增）

知识库沉淀的是**单条**爆款的拆解结论，而洞察把"这些爆款**共同**的剪辑规律"聚合出来——例如"爆款前 3 秒平均几个镜头""高频转场是什么""5 段情绪弧线各段主导哪种情绪"。跨视频规律才是"结构迁移"最该复用的知识。

**五个统计维度**（每条带 `sample_size` 与 `confidence`，样本不足如实标注、不编造结论）：

| 维度 | 统计什么 |
|------|---------|
| `hook` | 前 3 秒镜头数 + 主要 hook 方法 |
| `rhythm` | 镜头时长中位数/范围，后 1/3 段是否较前段加速 |
| `shot_types` | 镜头类型整体分布 + 前 3 镜集中度 |
| `emotion_arc` | 5 段式情绪弧线每段主导情绪 + 整体基调 |
| `transitions` | 高频转场及占比 |

- **原生交互式页面**：统计指标、分布条形图、逐视频镜头时间线、情绪流和镜头详情全部由 React 渲染，与主站深色主题一致，无 iframe 和双滚动条。
- **严格用户隔离**：`GET /api/insights` 只扫描当前用户 `storage/users/{user_id}/genes`，新账号从 0 个样本开始。
- **兼容并去重**：统一识别 Web 的 `report.json`、CLI 的 `analysis_result.json` 与旧 `runs/*/analyst/` 结构；相同内容的报告副本只统计一次。
- **样本语义**：0 个样本显示引导空态，1 个样本只展示单视频特征，2 个以上才展示跨视频聚合结论和置信度。
- **接口脱敏**：前端响应不包含分析报告、视频或关键帧的本机绝对路径。
- **离线报告保留**：`run_insight_mining.py` 仍可生成自包含 HTML，`/api/insights/report` 作为兼容接口保留，但 Web 主页面不再依赖它。

---

## 四、视频展示与成果

> 项目生成的视频效果概览。完整视频文件存放在 `videos/` 目录（Git LFS）。

### 4.1 编辑迁移路线输出

由 `run_editing_transfer.py` 一键生成，纯规则引擎驱动，无需 LLM API。

**编辑迁移最终输出**（50MB）— 39 张北京照片，librosa 节拍检测 + 预定义转场/运镜/字幕规则，Remotion 渲染。

### 4.2 多智能体流水线输出

由 `main.py` / `run_beijing_pipeline.py` 执行，AI Agent 协作完成爆款分析→素材理解→方案生成→渲染→审核全流程。

**多智能体流水线输出**（28MB）— AI 编导根据爆款结构生成的北京旅行 Vlog，含多段情绪弧线和风格化包装。

### 4.3 前景分割 + 字幕合成

阿里云 SegmentCommonImage API 前景分割 + Remotion 字幕系统叠加。

**前景分割 + 字幕合成展示**（25MB）— 照片主体抠出叠加在背景上，配合多种字幕样式的综合效果。

### 4.4 剪辑技法综合展示

30+ 种转场效果、Ken Burns 运镜、多字幕样式的技术集锦。

**剪辑技法综合展示**（20MB）— 集中展示 Remotion 渲染引擎支持的转场、运镜、字幕、前景合成等核心能力。

### 4.5 完整视频清单

| 分类 | 文件 | 大小 | 来源路线 |
|------|------|------|---------|
| **编辑迁移** | `final_video.mp4` | 50MB | 规则引擎，无需 LLM |
| **流水线输出** | `北京旅行Vlog _ 漫步京城.mp4` | 28MB | 多智能体流水线 |
| | `北京旅行Vlog.mp4` | 70MB | 多智能体流水线 |
| | `北京｜一场治愈的旅行.mp4` | 27MB | 多智能体流水线 |
| | `北京·漫游记.mp4` | 22MB | 多智能体流水线 |
| | `北京，下次见.mp4` | 24MB | 多智能体流水线 |
| | `北京，我来了.mp4` | 23MB | 多智能体流水线 |
| | `beijing_vlog.mp4` | 131MB | 流水线高清输出 |
| **前景分割** | `foreground_split_subtitles.mp4` | 25MB | 阿里云 API 分割 + 字幕 |
| | `foreground_split_aliyun.mp4` | 25MB | 阿里云 API 前景分割 |
| | `foreground_split.mp4` | 25MB | OpenCV GrabCut 本地分割 |
| **技法展示** | `vlog_techniques_showcase.mp4` | 20MB | 转场/运镜/字幕集锦 |
| **FFmpeg 回退** | `北京记忆_fallback.mp4` | 15MB | Remotion 不可用时的降级渲染 |
| | `北京｜39张照片_fallback.mp4` | 14MB | FFmpeg 拼接版 |
| **特效展示** | `effects_showcase.mp4` | 1.7MB | 转场特效集锦 |
| **Ken Burns** | `kb_test.mp4` / `kb_verify.mp4` | 0.6~3.2MB | 运镜参数测试 |

---

## 五、项目团队

| 成员 | 角色 | 职责 |
|------|------|------|
| **杨瑞环** | 核心开发 | 项目架构设计、AI 流水线开发、渲染引擎集成、文档编写 |
| 陈榕阳 | 测试与反馈 | 参与项目讨论、功能测试与问题反馈 |
| 张涵 | 资料整理 | 参与资料收集、文档校对 |

---

## 六、整体 AI 架构

### 6.1 总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户输入层                                     │
│   爆款参考视频(.mp4)      用户照片素材(.jpg)        目标主题描述     │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                      AI 决策层（多 Agent 协作）                       │
│                                                                     │
│  ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌─────────────┐  │
│  │Analyst   │   │MaterialManager│   │Planner   │   │Creative     │  │
│  │视频分析师 │──▶│素材管家      │──▶│编导策划师 │──▶│创意补全师   │  │
│  │GLM-4.6V  │   │GLM-4.6V     │   │DeepSeek  │   │DeepSeek     │  │
│  └──────────┘   └──────────────┘   └──────────┘   └─────────────┘  │
│        │               │               │               │            │
│        ▼               ▼               ▼               ▼            │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │              ViralEngineState（共享黑板）                    │     │
│  │  source_structures │ material_inventory │ scheme │ gaps     │     │
│  └────────────────────────────────────────────────────────────┘     │
│        ▲               ▲               ▲               ▲            │
│        │               │               │               │            │
│  ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌─────────────┐  │
│  │Renderer  │   │Assembler     │   │Reviewer  │   │Supervisor   │  │
│  │渲染策略师 │◀──│视频合成师    │◀──│质量审核师 │◀──│项目经理    │  │
│  │DeepSeek  │   │Remotion CLI │   │DeepSeek  │   │DeepSeek     │  │
│  └──────────┘   └──────────────┘   └──────────┘   └─────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                        渲染层                                        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Remotion v4 渲染引擎                                          │    │
│  │  30+ 转场 │ Ken Burns 运镜 │ 前景合成 │ 8 种字幕 │ BGM 音轨   │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                           │                                          │
│                           ▼                                          │
│                    final_video.mp4                                   │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 多 Agent 协作模型

系统采用 **Supervisor-Worker 架构**，所有 Agent 通过 `ViralEngineState` 共享黑板通信，由 LangGraph 状态机构编调度：

#### Agent 角色定义

| Agent | 角色 | 驱动模型 | 职责 |
|-------|------|---------|------|
| **Supervisor** | 项目经理 | DeepSeek Chat | 读取黑板状态，决定下一步叫谁 |
| **Analyst** | 视频分析师 | GLM-4.6V + OpenCV + Whisper | 逐镜头分析爆款 Vlog，提取结构并生成 StructureGene（结构基因） |
| **MaterialManager** | 素材管家 | GLM-4.6V + OpenCV | 照片内容理解、质量评估、人脸检测 |
| **Planner** | 编导策划师 | DeepSeek Chat | 消费 Gene + 素材 + 按需 Skill，做结构迁移生成分镜方案 |
| **Creative** | 创意补全师 | DeepSeek Chat | 制定素材缺口填充策略 |
| **Renderer** | 渲染策略师 | DeepSeek Chat + esbuild | 分析方案、生成动态 React 组件 |
| **Assembler** | 视频合成师 | Remotion CLI / FFmpeg | 渲染最终视频 |
| **Reviewer** | 质量审核师 | DeepSeek Chat | 双维度评分（Fidelity 结构保真 + Quality 剪辑质量），判断是否迭代 |

#### 调度流程

```
Supervisor 循环调度（LangGraph 条件边）：

init → [Analyst → MaterialManager → Planner → Renderer → Creative → Assembler → Reviewer]
         ↑                                                                         │
         └────────────────── 不通过且 iteration < 3 ──────────────────────────────┘

终止条件：审核通过 OR iteration >= 3 OR hook_score < 4
```

Supervisor 的决策采用 **硬编码阶段路由 + LLM 兜底** 混合策略：对于明确的阶段转换（如 `phase=materials → planner`），直接路由不走 LLM；仅在模糊边界调用 LLM 做判断。

### 6.3 LLM 调用链

| 阶段 | 调用次数 | 模型 | 用途 |
|------|---------|------|------|
| Supervisor | 6~10 次 | DeepSeek Chat | 状态判断与路由决策 |
| Analyst | 2+N 次 | GLM-4.6V | N 次逐镜头分析 + 1 次全局结构分析 |
| MaterialManager | 素材数+1 次 | GLM-4.6V | 每个素材一次图文理解 |
| Planner | 2~3 次 | DeepSeek Chat | 骨架提取 + 方案生成 + 迭代 |
| Creative | 1~2 次 | DeepSeek Chat | 补全策略制定 |
| Reviewer | 1~3 次 | DeepSeek Chat | 多维度质量评分 |
| **总计** | **15~30 次/轮** | — | 取决于镜头数和迭代数 |

### 6.4 数据模型体系

```
ViralEngineState（共享黑板，所有 Agent 共享）
├── sample_videos: string[]          # 输入：爆款视频路径
├── user_materials: dict[]           # 输入：用户素材
├── target_topic: string             # 输入：目标主题
├── source_structures: VideoStructure[]  # Analyst 输出（每结构含 .gene）
├── source_genes: StructureGene[]        # Analyst 输出（Reference Gene，Planner 核心输入）
├── material_inventory: MaterialInventory  # MaterialManager 输出
├── scheme: VideoScheme              # Planner 输出
├── knowledge_refs: string[]         # 注入的知识/手法 id
├── skill_refs: string[]             # 本次按需加载的 Editing Skill reference 名
├── generated_materials: list        # Creative 输出
├── rendered_video_path: string      # Assembler 输出
├── review_result: dict              # Reviewer 输出（含 fidelity/quality/feedback_type）
├── current_task: dict               # Supervisor 输出（路由）
├── phase: string                    # 流程控制
└── iteration: int / is_complete: bool / errors / logs

VideoStructure（原片结构分析结果）
├── shots / script_blocks / rhythm_curve / packaging / bgm / vlog_meta
└── gene: StructureGene               # 结构功能基因（迁移核心约束）

StructureGene（结构基因 — 表达功能，不复制内容）
├── shot_genes: ShotGene[]
│   ├── function（hook/establishing/climax/closing/...）
│   ├── semantic_role / rhythm_role / emotion_role / relation_to_previous
│   ├── visual_requirement（功能性画面要求，而非物体）
│   ├── duration_ratio / importance（critical/high/medium/low）
│   └── hard_constraints / soft_preferences
├── structure_type / rhythm_pattern / climax_position_ratio / emotion_arc
└── hard_constraints / soft_preferences / migration_notes

VideoScheme（视频方案 → 渲染引擎消费）
├── storyboard: StoryboardFrame[]    # 35 个分镜
│   ├── shot_type / duration / purpose
│   ├── material_id / fg_source_id (前景) / bg_source_id (背景)
│   ├── subtitle_text / subtitle_config (8 种样式参数)
│   ├── transition_in (30+ 种转场)
│   ├── composite_mode (overlay / reveal / pip)
│   ├── render_component (auto / ken_burns / text_card / custom:*)
│   ├── structure_function / gene_shot_index   # 溯源：本镜承担的 Gene 功能 + 对应下标
│   ├── skill_refs                             # 溯源：本镜用到的 Skill reference
│   └── adaptation                              # 溯源：{preserved, reason, original_function}
├── gene_refs / skill_refs_used / adaptation_log  # 方案级溯源
├── packaging / bgm / audio_config
└── canvas_width=1080 / canvas_height=1920
```

### 6.5 渲染架构

Remotion 渲染引擎的组件架构：

```
VideoSchemeComposition
├── AudioLayer (BGM：淡入 15 帧 + 淡出 15 帧 + 循环)
├── Sequence[] × N (每个分镜一个)
│   └── DualTransitionLayer
│       ├── incoming: FrameLayer → DynamicFrame
│       │   ├── AutoFrame (智能推断)
│       │   │   ├── 有 text_card → TextCard
│       │   │   ├── 有视频素材 → NativeVideoLayer
│       │   │   ├── 有图片素材 → KenBurns (5 运镜 × 3 速度)
│       │   │   ├── 有前后景分离 → ForegroundLayer
│       │   │   └── 无素材 → TextCard(描述)
│       │   └── 叠加层：Subtitles + TextOverlay + FilmGrain
│       └── outgoing: 前一分镜（重叠期间显示）
└── 全局 fade-out（最后 0.5 秒）
```

Remotion 渲染时需要一个本地 HTTP 服务器提供素材（Chrome 禁止 `file://`），使用 `http.server` 在随机端口启动。

### 6.6 Reference-guided 结构迁移（Gene × Skill）

本次架构升级把系统从「复制爆款内容」升级为「迁移爆款结构」：核心原则是
**Gene 决定「迁移什么」，Skill 决定「怎么迁移好」**。

#### 6.6.1 核心概念与边界

| | Reference Gene（结构基因） | Editing Skill（剪辑技能） |
|---|---|---|
| 作用域 | 当前参考视频**专属** | 跨任务**长期复用** |
| 决定什么 | 迁移**什么结构**（镜头功能 / 节奏 / 情绪骨架） | **怎么剪好**（具体手法 / 替代策略） |
| 约束性质 | 硬约束为主（`hard_constraints` / `importance=critical`） | 软策略为主 |
| 可否被覆盖 | 仅用户显式要求可覆盖 | 可被 Gene 硬约束覆盖 |

**决策优先级（贯穿系统，Planner 与 Reviewer 均遵守）**：

```
用户显式要求  >  Reference Gene 硬约束  >  Editing Skill 策略  >  模型自由发挥
```

Gene 表达的是「结构功能」而非原始内容：例如不记录「航拍 A 地标」，而是记录
`function=establishing`（场景建立）、`visual_requirement=宽景/地标/环境交代`、
`rhythm_role=breather`、`relation_to_previous=continue`。迁移时按功能找替代素材，
实现 **Structure Transfer（结构迁移），不是 Content Copy（内容复制）**。

#### 6.6.2 数据流

```
参考视频 → Analyst（GLM-4.6V 逐镜头 + 全局结构分析）
        → build_gene()（纯函数，把分析映射为 StructureGene）
        → VideoStructure.gene（挂在原片结构上，一并持久化）
        → Planner（消费 Gene + 素材清单 + 用户意图 + 按需 Skill）
        → VideoScheme（统一中间表示，逐镜带溯源字段）
        → Reviewer（双维度评估：Fidelity + Quality）
        → 回 Planner 迭代（≤3 轮）
        → Renderer / Assembler
```

#### 6.6.3 渐进式披露（按需加载 Skill）

Skill 不是一次性全量注入，而是按规划阶段 / 镜头功能**确定性路由 + LLM 语义兜底**：

- 目录结构：`skills/video-editing/SKILL.md`（定位 / 使用时机 / 路由规则 / 优先级）
  + `references/*.md`（7 个文件承载真实知识：适用条件 / 不适用条件 / 推荐策略 / 例子）。
- `skills/router.py::SkillRouter`：
  - `route_for_stage(stage)` —— 规划 Opening Hook 只加载 `hook.md`；
  - `route_for_shot(function)` —— 镜头功能 → reference；
  - `route_for_gene(gene)` —— 汇总整条 Gene 需要的 reference（恒含 `structure-adaptation`；
    存在 `establishing` 时强制 `material-matching`）；
  - `route_by_llm(context, llm)` —— 仅确定性规则覆盖不到时的语义兜底。
- 未引入 RAG / 向量库 / 复杂检索。

#### 6.6.4 Planner 如何融合 Gene / 素材 / Skill

Planner 的 prompt 结构（`prompts/planner_prompts.py`）：

1. `gene_json` 作为**核心约束**单独成段（硬约束 / critical 镜头功能优先保持）；
2. `skill_context` 按需注入（只注入本次加载的 reference，带 `===== Skill 参考：xxx.md =====` 标题）；
3. 素材清单 + 音频特征 + 系统能力手册；
4. 决策优先级块 + Structure Transfer 指引。

产出 `VideoScheme`，每个分镜带溯源字段：

- `structure_function`（本镜承担的 Gene 功能）、`gene_shot_index`（对应 Gene 镜头下标）；
- `skill_refs`（本镜用到的 Skill reference 名）、`adaptation`（`{preserved, reason, original_function}`）；
- 顶层 `gene_refs` / `skill_refs_used` / `adaptation_log`（整方案级溯源）。

#### 6.6.5 Reviewer 双维度评估

Reviewer 同时评价两组指标（`prompts/reviewer_prompts.py`）：

- **A 组 Gene / Structure Fidelity**（迁移得「像不像」Reference）：Hook 结构、镜头/时长关系、
  节奏曲线、情绪弧线、高潮/Ending 位置、核心镜头功能是否保持；
- **B 组 Adaptation / Editing Quality**（在当前素材上「剪得好不好」）：素材匹配、转场、节奏自然度、
  情绪连贯、字幕包装、素材覆盖。

输出 `feedback_type ∈ {fidelity, quality, mixed}`：fidelity 问题回 Planner 恢复 Gene 结构，
quality 问题在不破坏 Gene 的前提下优化剪辑。

---

## 七、工具协议

### 7.1 Agent 协议（BaseAgent）

每个 Agent 继承自 `BaseAgent`，使用统一的 **thought → action → observation → done** 决策循环：

```
Agent 内部循环（最多 15 步）:
  1. LLM 接收：当前状态摘要 + 可用工具清单 + 历史步骤
  2. LLM 输出：{thought, action, action_input, is_final}
  3. 如果 action="done" → 结束循环，返回 AgentResult
  4. 否则执行工具函数 → 将 observation 追加到历史
  5. 回到步骤 1
```

所有 Agent 通过共享 `ViralEngineState` 黑板间接通信，**不直接调用**。

### 7.2 LLM 统一接口协议（LLMTools）

系统通过 `LLMTools` 类统一封装三家 LLM 的 API，提供 3 种调用模式：

| 方法 | 用途 | 传输方式 | 支持模型 |
|------|------|---------|---------|
| `chat()` | 纯文本推理 | HTTP POST, JSON body | DeepSeek Chat |
| `chat_with_images()` | 图片理解 | base64 嵌入 | GLM-4.6V / Qwen-VL |
| `chat_with_video()` | 视频+音频理解 | base64 嵌入 | Qwen3-OMNI-Flash |

**协议细节：**
- 接口：`{base_url}/chat/completions`（OpenAI 兼容格式）
- 认证：`Authorization: Bearer {api_key}`
- 重试：最多 10 次，429 限流等待递增（5s→30s），网络错误等待 3s
- 超时：180 秒（`LLM_TIMEOUT`）
- JSON 输出：通过 `response_format: {"type": "json_object"}` 强制模型输出 JSON
- 无 API Key 时：返回 mock JSON，流水线直接结束

### 7.3 工具函数协议

每个工具模块暴露独立的函数接口：

```
VideoTools (FFmpeg 封装)
  get_video_info(path) → {width, height, fps, duration}
  detect_scene_changes(path, threshold=0.3) → [{start, end, duration}]
  extract_audio(path) → wav_path
  apply_ken_burns(img, motion_type, speed, duration) → mp4_path
  concat_clips(paths, transitions) → mp4_path

AudioTools (音频分析)
  transcribe(audio_path) → 文字（Whisper）
  detect_beats(audio_path) → {bpm, beat_times}（librosa）
  analyze_audio_segments(audio_path) → [{time, energy}, ...]

FaceTools (人脸检测)
  has_face(image_path) → bool
  get_main_face_region(image_path) → {x, y, w, h}

FFmpegRenderer（回退渲染）
  render(scheme, inventory, audio_path) → mp4_path
  # 内部：Ken Burns zoompan + overlay + drawtext 字幕 + xfade 转场
```

### 7.4 LangGraph 图协议

图结构定义在 `graph/builder.py` 中，遵循以下规则：

1. **入口固定**：`graph.set_entry_point("supervisor")`
2. **Supervisor 出边**：条件路由，读取 `current_task.expert` 映射到对应节点
   - `analyst` → `analyst_node`
   - `material_manager` → `material_node`
   - `planner` → `planner_node`
   - `renderer` → `renderer_node`
   - `creative` → `creative_node`
   - `assembler` → `assembler_node`
   - `reviewer` → `reviewer_node`
   - `__end__` → `END`
3. **专家出边**：统一条件边，`is_complete=True → END`，否则回到 `supervisor`
4. **清理规则**：每个专家节点返回时必须设置 `current_task: {}`，防止 Supervisor 重复路由

### 7.5 Remotion 渲染协议

Python 端与 Remotion 端通过 JSON 文件约定接口：

```typescript
// Remotion 接收的 input_props 结构
interface RenderInput {
  scheme: {
    storyboard: StoryboardFrame[];  // 每个分镜定义
    bgm: { audio_path: string; loop: boolean };
    packaging: { subtitle_style: string };
    audio_config: { volume: number };
  };
  material_map: Record<string, string>;  // 素材 ID → HTTP URL
}

interface StoryboardFrame {
  index: number;
  duration: number;
  shot_type: string;
  material_id: string;
  subtitle_text: string;
  subtitle_config?: { fontSize, color, textAlign, ... };
  transition_in: string;
  composite_mode: "none" | "fg_overlay" | "fg_reveal" | "pip";
  fg_source_id?: string;
  bg_source_id?: string;
  render_component: string;
  layers?: Record<string, any>[];
}
```

### 7.6 数据持久化协议（OutputManager）

每次运行在 `data/runs/{run_id}/` 下创建目录，按阶段归档：

```
路径规则：data/runs/{timestamp}_{topic}/
命名规则：{stage}/{filename}
日志格式：logs/agent_logs.jsonl（JSON Lines，每行一条）
```

---

## 八、安全边际

### 8.1 API Key 安全

- **环境变量加载**：所有 API Key 通过 `.env` 文件加载，使用 `python-dotenv`
- **不硬编码密钥**：代码中不包含生产密钥；`segment_aliyun.py` 从 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` 读取
- **无 Key 降级**：`LLMTools` 在检测不到 API Key 时返回 mock JSON，流水线安全退出而非崩溃
- **密钥分类**：DeepSeek（文本推理）、Zhipu（视觉理解）、Moonshot（备选）、阿里云（前景分割）四个密钥独立配置

### 8.2 调用安全与容错

| 保护机制 | 实现位置 | 说明 |
|---------|---------|------|
| LLM 自动重试 | `LLMTools._post()` | 最多 10 次重试，429 限流等待，网络错误 3s 间隔 |
| JSON 解析容错 | `LLMTools.parse_json()` | 5 级降级：标准解析 → 修复尾逗号 → 提取 JSON 块 → 诊断输出 |
| Response Format 降级 | `LLMTools._post()` | 400 错误时自动去掉 `response_format` 参数重试 |
| 单点异常隔离 | 每个 Agent 节点 | `try/except` 包裹，失败记录到 `errors[]` 列表，流程继续 |
| 渲染双保险 | `assembler_node` | Remotion 失败 → FFmpeg 智能渲染 → FFmpeg 基础拼接，三级降级 |
| 超时保护 | `LLM_TIMEOUT=180s` | LLM 调用超时 180 秒，Remotion 渲染超时 1800 秒 |
| 音频分析降级 | `analyst_node` | 音频分析失败仅打日志，不影响主流程 |

### 8.3 流程安全

```
终止条件（防止无限循环）：
  is_complete = passed_review OR iteration >= max_iter(3) OR hook_score < 4

Supervisor 兜底：
  - 硬编码路由覆盖 90% 场景，减少 LLM 幻觉导致的错误路由
  - 专家节点必须清空 current_task，防止路由死循环

审核安全阈值：
  - hook_score < 4：开场吸引力太低，立即终止不继续浪费 API 调用
  - max_iterations = 3：最多迭代 3 轮，防止无限循环
```

### 8.4 文件系统安全

- **Windows 兼容**：`_safe_filename()` 清理 Windows 非法字符 `\/:*?"<>|`
- **FFmpeg Win 适配**：`FFmpegRenderer` 将字体复制到工作目录使用相对路径，避免 Windows 冒号破坏 filter 解析
- **临时文件清理**：Remotion 渲染后清理 `props_file`、`media_root` 临时目录、FFmpeg 片段文件
- **磁盘空间**：临时帧图片、分段视频存储在 `data/temp/`，由 `OutputManager` 管理

### 8.5 多线程与资源安全

- **端口冲突**：Remotion 素材 HTTP 服务器使用 `socket` 自动寻找空闲端口
- **文件锁**：FFmpeg 回退渲染使用 `id(scheme)` 生成唯一输出文件名，防止并发文件锁冲突
- **并行控制**：阿里云分割 API 的 `MAX_WORKERS=4`，限制并发连接数
- **子进程超时**：FFmpeg 子进程 120 秒超时，Remotion 渲染 1800 秒超时

### 8.6 数据边界

```
输入边界：
  - 爆款视频：本地 .mp4 文件
  - 用户素材：本地 .jpg/.png 图片或 .mp4 视频（路径由用户指定）
  - 配置：.env 文件（不在版本控制中）
  - 不涉及：网络爬取（除 get_video 独立模块外）、用户隐私数据

输出边界：
  - 渲染视频：data/output/ 或 data/runs/{run_id}/
  - 中间产物：data/runs/{run_id}/{stage}/
  - 不涉及：云端存储（除阿里云 OSS 分割 API 外）、数据上报

API 调用边界：
  - 所有 LLM 调用通过本地 HTTP 客户端
  - 不上传完整视频到第三方（仅上传关键帧 base64 到 GLM-4.6V）
  - 阿里云分割 API 仅处理单张图片的前景/背景分离
```

### 8.7 已知限制与风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM 幻觉导致方案不合理 | 生成不可渲染的分镜方案 | Reviewer 10 维度审核 + 3 轮迭代 |
| GLM-4.6V 视觉理解偏差 | 爆款分析不准确 | 多帧抽取 + 多维度验证 |
| Remotion 渲染失败 | 无法输出视频 | 自动回退 FFmpeg 渲染 |
| 长视频（>5 分钟）内存溢出 | 渲染进程 OOM | Remotion 分片渲染（待实现） |
| 中文路径问题 | OpenCV 无法读取文件 | FaceTools 已修复中文路径编码 |
| 阿里云 API 密钥泄露 | 资产损失风险 | `.env` + `.gitignore` 双重保护 |

---

*文档版本: v1.2 | 最后更新: 2026-09-06*
