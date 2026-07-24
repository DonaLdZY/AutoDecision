# AutoDecision

AutoDecision 是一套面向真实数据任务的端到端智能决策系统。用户提供数据目录和任务需求后，系统依次完成数据认知与任务定义、算法与代码搜索、方案验证，以及交付报告生成。

系统同时支持传统机器学习、深度学习、时序预测、数学优化、组合决策和强化学习任务。Vue 前端统一管理模型配置、任务参数、资源限制、运行状态、搜索树、日志和最终产物。

## 系统流程

```text
原始数据 + 任务需求
        |
        v
AutoRealize
数据认知、字段与关系识别、任务书、评估协议、AutoML 上下文
        |
        v
MLEvolve-Alter
候选方案生成、代码执行、debug/improve、搜索与最优方案保存
        |
        v
AutoReport
证据汇总、候选比较、复用说明与交付报告
```

本地开发环境由以下服务组成：

| 服务            | 默认地址                   | 作用                     |
| --------------- | -------------------------- | ------------------------ |
| AutoRealize API | `http://127.0.0.1:18101` | 数据认知与任务定义       |
| MLEvolve API    | `http://127.0.0.1:18103` | AutoML、优化和 RL 搜索   |
| AutoReport API  | `http://127.0.0.1:18104` | 方案交付报告生成         |
| Gateway API     | `http://127.0.0.1:18080` | 任务编排、配置和状态聚合 |
| Vue Frontend    | `http://127.0.0.1:5173`  | 用户操作界面             |

前端只访问 Gateway，由 Gateway 调用三个 Core 服务。

## 主要功能

### AutoRealize：认知数据并定义任务

- 读取 CSV、Excel、JSON、文本、Office 文档、PDF、图片和压缩包等数据。
- 识别目录结构、文件名模式、表格布局、精确字段、字段语义和表间关系。
- 通过 QDI 执行只读数据探查，验证仅靠预览无法确认的事实。
- 生成 `description.md`、评估合同、输出合同、样例提交和 `automl_context.md`。
- 使用结构化证据包和本地 artifact 控制上下文成本，同时保留完整证据。

### MLEvolve-Alter：搜索并验证方案

- 通过搜索树生成、执行、调试和改进候选代码。
- 支持预测、优化、决策和强化学习路线。
- 支持快速首个 draft、后续 stepwise 生成、debug、improve 和跨分支搜索。
- 保存统一指标、执行输出、代码、模型或求解器 artifact、Top-K 和搜索日志。
- 支持任务停止后从持久化 journal 和工作区继续搜索。

### AutoReport：整理交付证据

- 收集 AutoRealize 与 MLEvolve 的任务事实、方案、指标和产物。
- 对比最佳方案、Top-K 候选和典型失败方案。
- 生成方法流程、评估结果、适用边界、输入格式和代码复用说明。
- 报告聚焦最终方案为何有效、如何使用，不展开系统内部搜索细节。

### 前端与任务管理

- 管理 OpenAI-compatible 模型、API 地址、API Key 和角色分配。
- 配置 LLM 并发、思考模式、输出上限、搜索预算和报告选项。
- 为每个任务配置 CPU、总内存和可见加速卡。
- 创建、启动、停止、继续及分阶段重跑任务。
- 查看 AutoRealize 进度、MLEvolve 搜索树、节点代码、指标、insight、日志和交付物。

## 仓库结构

```text
AutoDecision/
|-- core/
|   |-- AutoRealize/       # Git 子模块：数据认知与任务定义
|   |-- MLEvolve-Alter/    # Git 子模块：方案搜索与执行
|   `-- AutoReport/        # Git 子模块：交付报告生成
|-- frontend/
|   |-- backend/           # FastAPI Gateway
|   `-- ui/                # Vue 3 + TypeScript + Vite
|-- scripts/               # 开发环境启动、停止、状态和日志脚本
|-- runs/                  # 默认任务输出目录
|-- environment.yml        # Conda 环境定义
|-- requirements.txt       # 全部 Python 服务的聚合依赖
`-- .gitmodules            # Core 子模块映射
```

三个 Core 项目也可以脱离主仓库独立安装：

- [AutoRealize](core/AutoRealize/README.md)
- [MLEvolve-Alter](core/MLEvolve-Alter/README.md)
- [AutoReport](core/AutoReport/README.md)

## 环境要求

- Git 2.30+
- Conda、Miniconda 或 Miniforge
- Python 3.11 或 3.12，推荐 Python 3.12
- Node.js 20.19+ 和 npm 10+
- 可访问所配置的 OpenAI-compatible LLM API
- 足够的磁盘空间保存输入副本、节点工作区、模型和日志

CPU 环境可以运行完整系统。GPU、NPU 或其他加速卡不是启动必需项；如果生成方案需要深度学习，请安装与本机驱动和硬件匹配的 PyTorch 或设备运行时。

## 获取代码

首次克隆时一并拉取三个 Core 子模块：

```bash
git clone --recurse-submodules https://github.com/DonaLdZY/AutoDecision.git
cd AutoDecision
```

已经克隆主仓库时，使用以下命令补全或更新子模块：

```bash
git submodule update --init --recursive
```

## Conda 环境安装

以下命令在 Windows、Linux 和 macOS 上相同。项目根目录的 `environment.yml` 会创建名为 `automl` 的 Python 3.12 环境：

```bash
conda env create -f environment.yml
conda activate automl
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果环境已经存在，更新依赖即可：

```bash
conda activate automl
conda env update -n automl -f environment.yml --prune
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

根 `requirements.txt` 会安装 Gateway、AutoRealize、MLEvolve 和 AutoReport 的基础依赖。需要额外的视觉、NLP、音频、地理或化学算法库时，再安装 MLEvolve 的领域依赖：

```bash
python -m pip install -r core/MLEvolve-Alter/requirements_domain.txt
```

如需 GPU 版 PyTorch，请先根据 PyTorch 或设备厂商官网选择与驱动匹配的安装命令，再安装其余依赖。本项目不固定 CUDA、ROCm、XPU、MPS 或 Ascend 版本。

确认当前命令使用的是 Conda 环境：

```bash
python -c "import sys; print(sys.executable); print(sys.version)"
```

## 安装前端依赖

```bash
cd frontend/ui
npm install
cd ../..
```

## 配置

### 全局前端配置

日常使用建议在前端的“全局设置”和“新建任务”页面完成配置：

1. 填写模型名、API 地址和 API Key。
2. 为 AutoRealize、代码生成、反馈评审、Embedding 和报告选择模型。
3. 设置任务输入目录、需求、搜索预算、并发和报告选项。
4. 设置任务可用的 CPU 核心数、总内存和加速卡。

全局设置默认保存在 `frontend/config/global_settings.yaml`。文件不存在时由 Gateway 自动创建，并已通过 `.gitignore` 排除。可通过 `AUTODECISION_GLOBAL_SETTINGS_PATH` 指向其他位置。

前端配置中的 API Key 优先于 Core 默认 YAML 和环境变量。不要把包含真实密钥的临时配置、日志或全局设置提交到 Git。

### Core YAML

三个 Core 项目的正式默认配置分别是：

- `core/AutoRealize/config/config.yaml`
- `core/MLEvolve-Alter/config/config.yaml`
- `core/AutoReport/config/config.yaml`

配置文件均带中英文注释。前端启动任务时会根据全局设置和任务设置生成临时 YAML；独立运行 Core 项目时也可以直接修改默认文件，或指定其他 YAML 路径。

Linux / macOS 可在当前终端设置：

```bash
export DEEPSEEK_API_KEY="..."
export MLEVOLVE_CODE_API_KEY="..."
export MLEVOLVE_FEEDBACK_API_KEY="..."
export MLEVOLVE_EMBEDDING_API_KEY="..."
```

Windows PowerShell：

```powershell
$env:DEEPSEEK_API_KEY = "..."
$env:MLEVOLVE_CODE_API_KEY = "..."
$env:MLEVOLVE_FEEDBACK_API_KEY = "..."
$env:MLEVOLVE_EMBEDDING_API_KEY = "..."
```

## 一键启动

启动前先激活 Conda 环境：

```bash
conda activate automl
```

### Windows PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1 -Wait -Open
```

常用管理命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-status.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\dev-logs.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\dev-restart.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1
```

### Linux / macOS

```bash
./scripts/dev-up.sh --open
```

常用管理命令：

```bash
./scripts/dev-status.sh
./scripts/dev-logs.sh gateway-api --follow
./scripts/dev-restart.sh
./scripts/dev-down.sh
```

脚本优先使用全局设置中的 `python.executable`，否则使用当前 Conda 环境的 Python。需要临时指定解释器时：

```bash
./scripts/dev-up.sh --python "$(which python)"
```

启动成功后访问 `http://127.0.0.1:5173`。

## 手动启动服务

需要分别调试服务时，在五个已激活 `automl` 环境的终端中运行：

```bash
# AutoRealize
cd core/AutoRealize
python -m uvicorn autorealize.service_api:app --host 127.0.0.1 --port 18101

# MLEvolve
cd core/MLEvolve-Alter
python -m uvicorn service_api:app --host 127.0.0.1 --port 18103

# AutoReport
cd core/AutoReport
python -m uvicorn service_api:app --host 127.0.0.1 --port 18104

# Gateway
cd frontend/backend
python -m uvicorn app:app --host 127.0.0.1 --port 18080

# Vue
cd frontend/ui
npm run dev -- --host 127.0.0.1 --port 5173
```

各 FastAPI 服务启动后可访问 `/docs` 查看 OpenAPI 文档，使用 `/health` 检查 Core 服务，使用 `/api/health` 检查 Gateway。

## 任务输出

一次完整任务通常写入：

```text
runs/<task-name>/
|-- input/                  # 输入数据副本
|-- autorealize/
|   |-- description.md
|   |-- sample_submission.csv
|   `-- realize_report/
|       `-- automl_context.md
|-- automl/
|   |-- dependency_installations.jsonl          # 该任务跨 run 的自动补库明细
|   |-- dependency_installations_summary.json   # requirements 候选汇总
|   |-- logs/               # journal、状态、token 和运行日志
|   `-- workspaces/         # 最优方案、Top-K 和节点产物
`-- report/
    |-- report.md
    `-- report.json
```

实际目录可能按运行时间再增加一层。前端会根据服务快照定位当前有效运行目录。

AutoML 配置中的“缺少依赖时安装到任务隔离目录并重跑当前脚本”默认开启。该机制只响应精确的 `ModuleNotFoundError`：AI 可以声明一个合法的 PyPI distribution，系统将其安装到 `runs/<task>/automl/python_packages`，并只通过该任务的 `PYTHONPATH` 加载，不修改基础 Conda 或系统 Python 环境。同一包每次任务只尝试一次，避免安装死循环。任务级补库日志位于上述 `automl/dependency_installations.*`，其中 `requirements_candidates` 可用于补充项目 requirements。严格部署仍可把 `exec.dependency_install_policy` 改为 `allowlist`。

## 每任务资源限制

- **CPU**：限制整个 MLEvolve 任务进程树共享的逻辑核心，不是每个并行节点各获得一份核心。
- **内存**：限制任务主进程及全部子进程共享的总预算；`0` 表示不限制。
- **加速卡**：控制任务可见的 CUDA、ROCm、XPU、Ascend 或其他设备；可见性隔离不等于设备独占或显存配额。

Windows 使用 CPU affinity 和 Job Object；Linux 优先使用 CPU affinity 与 cgroup v2；macOS 使用线程预算和进程资源限制。实际限制后端、设备、峰值与诊断写入 MLEvolve 的 `resource_usage.json`。

## 测试

```bash
conda activate automl
python -m pip install -r requirements-dev.txt

python -m pytest frontend/backend/tests -q
python -m pytest core/AutoRealize/tests -q
python -m pytest core/MLEvolve-Alter/tests -q
python -m pytest core/AutoReport/tests -q
```

前端测试与构建：

```bash
cd frontend/ui
npm run test
npm run build
```

默认单元测试不应调用真实 LLM。端到端测试会产生 API 费用，并可能运行较长时间。
