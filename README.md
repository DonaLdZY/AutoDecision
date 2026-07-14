# AutoDecision

AutoDecision 是一套面向真实数据任务的端到端智能决策系统。用户提供数据目录和自然语言需求后，系统依次完成数据认知与任务定义、算法与代码搜索、方案验证以及交付报告生成。

系统不只面向传统机器学习，也可用于深度学习、时序预测、数学优化、组合决策和强化学习任务。前端统一管理模型配置、任务参数、资源限制、运行状态、搜索树、日志和最终产物。

> **发布状态：尚未完成开源授权。** 上游 MLEvolve 仓库当前没有明确许可证，因此完整 AutoDecision 暂时只能视为源码可见的预发布工程，不能宣称为可自由使用、修改和再分发的开源版本。发布前还必须完成 Git 历史密钥清理。详见 [第三方声明](docs/THIRD_PARTY_NOTICES.md) 和 [发布检查清单](docs/release-checklist.md)。

## 系统工作流

```text
原始数据 + 自然语言需求
          |
          v
AutoRealize
数据认知、精确字段与关系识别、任务书、评估协议、AutoML 上下文
          |
          v
MLEvolve-Alter
多智能体方案生成、代码执行、debug/improve、搜索与最优方案保存
          |
          v
AutoReport
汇总证据、比较候选方案、生成可复用的交付报告
```

五个本地服务共同组成开发环境：

| 服务 | 默认地址 | 作用 |
| --- | --- | --- |
| AutoRealize API | `http://127.0.0.1:18101` | 数据认知与任务定义 |
| MLEvolve API | `http://127.0.0.1:18103` | AutoML、优化与 RL 搜索 |
| AutoReport API | `http://127.0.0.1:18104` | 方案交付报告生成 |
| Gateway API | `http://127.0.0.1:18080` | 任务编排、配置与状态聚合 |
| Vue Frontend | `http://127.0.0.1:5173` | 用户操作界面 |

前端只访问 Gateway，Gateway 再调用三个 Core API。

## 主要功能

### 数据认知与任务实现

- 读取 CSV、Excel、JSON、文档、PDF、图片、压缩包等多种数据。
- 识别目录结构、文件名模式、表格布局、字段语义、表间关系和业务约束。
- 通过 QDI 问题驱动调查执行受限的只读数据探查，补足仅靠预览无法确认的事实。
- 生成精确的 `description.md`、评估协议、输出合同、`sample_submission.csv` 和 `automl_context.md`。
- 使用结构化证据包和本地 artifact 减少长上下文重复传输，同时保留事实追溯能力。

### 算法搜索与验证

- 通过多智能体和搜索树生成、执行、调试并改进候选方案。
- 支持传统机器学习、深度学习、优化、决策和强化学习方案。
- 支持快速首个 draft、后续 stepwise 生成、debug、improve、跨分支融合和全局记忆。
- 保存统一指标、运行输出、代码、模型或求解器 artifact、Top-K 方案和搜索日志。
- 支持任务中止后继续搜索，复用已有 `journal.json` 和工作区产物。

### 报告与交付

- 自动收集 AutoRealize 与 MLEvolve 的关键证据。
- 对比最优方案、Top-K 候选和典型失败方案。
- 生成方法设计、指标解释、适用边界、输入格式和代码复用步骤。
- 报告聚焦“方案为什么有效、如何使用”，而不是介绍系统内部搜索过程。

### 前端任务管理

- 维护全局模型配置库，并为不同 LLM 角色选择模型配置。
- 配置 `thinking mode`、`reasoning_effort`、`max_tokens`、并发和 API 地址。
- 为每个任务独立配置 AutoRealize、AutoML、报告和运行资源。
- 创建、启动、停止、继续以及分阶段重跑任务。
- 查看 AutoRealize 事件、MLEvolve 搜索树、生成中的灰色 draft 节点、节点代码、指标、insight、日志和交付产物。

## 功能亮点

- **事实优先**：数据字段、文件布局、评估要求和约束尽量从真实数据与权威需求中确认，避免用模糊摘要替代事实。
- **多范式统一工作流**：同一套系统可承接预测、优化、决策与 RL 任务，并由任务合同约束下游实现。
- **过程可观测**：阶段状态、事件流、简略/详细日志、LLM token、缓存命中和资源用量均可落盘。
- **配置驱动**：三个核心项目均以带注释的 YAML 为主要配置入口，前端也通过生成临时 YAML 启动后端任务。
- **可恢复搜索**：达到步数或时间预算后会保存当前最优产物；被停止的任务可以从现有 journal 继续。
- **跨平台资源控制**：按任务设置 CPU、内存和加速卡可见性，并针对 Windows、Linux、macOS 使用不同后端实现。

## 仓库结构

```text
AutoDecision/
|-- core/
|   |-- AutoRealize/       # 独立 Git 子模块：数据认知与任务定义
|   |-- MLEvolve-Alter/    # 独立 Git 子模块：方案搜索与执行
|   `-- AutoReport/        # 独立 Git 子模块：交付报告生成
|-- frontend/
|   |-- backend/           # FastAPI Gateway
|   `-- ui/                # Vue 3 + TypeScript + Vite
|-- scripts/               # 本地服务启动、停止、状态和日志脚本
|-- runs/                  # 默认任务输出目录
|-- requirements.txt       # 四个 Python 服务的聚合依赖
`-- .gitmodules            # Core 子仓库映射
```

Core 项目也可以脱离本仓库独立安装和运行，详见：

- [AutoRealize](core/AutoRealize/README.md)
- [MLEvolve-Alter](core/MLEvolve-Alter/README.md)
- [AutoReport](core/AutoReport/README.md)

## 环境要求

- Git 2.30+
- Python 3.11 或 3.12，建议使用 64 位解释器
- Node.js 20.19+，推荐当前 LTS 版本
- npm 10+
- 足够的磁盘空间用于复制数据、节点工作区、模型和日志
- 可访问所配置的 OpenAI-compatible LLM API

CPU 环境可以运行完整系统。GPU、NPU 或其他加速卡不是系统启动的硬要求，但生成方案需要深度学习时，应提前安装与驱动匹配的 PyTorch 和设备运行时。

## 获取代码

首次克隆时同时拉取三个 Core 子模块：

```bash
git clone --recurse-submodules https://github.com/DonaLdZY/AutoDecision.git
cd AutoDecision
```

如果已经克隆主仓库但 `core` 目录为空或只有 gitlink：

```bash
git submodule update --init --recursive
```

一个不含私有数据的最小输入位于 [`examples/quickstart`](examples/quickstart/README.md)。该示例不会由 CI 调用真实 LLM，手动运行时仍会产生模型 API 费用。

更新主仓库记录的子模块版本：

```bash
git pull
git submodule update --init --recursive
```

## 安装

### 1. 创建 Python 虚拟环境

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Linux/macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

根 `requirements.txt` 会安装 Gateway 和三个 Core 服务的基础依赖。视觉、NLP、时序、音频、地理或化学任务需要额外工具时，再安装：

```bash
python -m pip install -r core/MLEvolve-Alter/requirements_domain.txt
```

如需 GPU 版 PyTorch，请优先按照设备厂商说明安装匹配版本，再安装其余依赖。本项目不会强制绑定某个 CUDA 版本。

### 2. 安装前端依赖

```bash
cd frontend/ui
npm install
cd ../..
```

## 配置

### 前端配置

日常使用建议直接在“全局设置”和“新建任务”界面配置：

1. 在模型配置库中填写模型名、API 地址和 API Key。
2. 将模型配置分配给 AutoRealize、代码生成、反馈评审、Embedding 等角色。
3. 创建任务并选择输入目录、需求文本、搜索预算、并发数和报告选项。
4. 为任务设置 CPU 核心数、总内存上限以及允许看到的加速卡。

全局设置统一持久化到本地 `frontend/config/global_settings.yaml`。Gateway 启动时若文件不存在会自动生成；修改或重新构建 Vue 前端不会清空该文件。文件可能包含明文 API Key，已被 `.gitignore` 排除，浏览器读取设置时只会收到“已配置”标记，不会取回原始 Key。可用 `AUTODECISION_GLOBAL_SETTINGS_PATH` 指定其他保存位置。

Gateway 会把界面配置转换为各 Core 服务可读取的任务临时 YAML。API Key 的优先级为：前端全局设置或任务配置、Core YAML 中的非空值、对应环境变量。不要把真实 Key 提交到 Git。

### Core YAML

三个项目各自只维护一份正式默认配置：

- [`core/AutoRealize/config/config.yaml`](core/AutoRealize/config/config.yaml)
- [`core/MLEvolve-Alter/config/config.yaml`](core/MLEvolve-Alter/config/config.yaml)
- [`core/AutoReport/config/config.yaml`](core/AutoReport/config/config.yaml)

这些文件覆盖模型、思考模式、输出 token、并发、数据读取、QDI、搜索、draft、重试、日志、产物和服务快照。Core 默认读取各自文件，也可以通过命令行或服务请求指定其他位置的 YAML。

### 环境变量

未在配置中提供 Key 时，可使用：

```bash
DEEPSEEK_API_KEY=...
MLEVOLVE_CODE_API_KEY=...
MLEVOLVE_FEEDBACK_API_KEY=...
MLEVOLVE_EMBEDDING_API_KEY=...
```

其中 MLEvolve 的角色专用变量优先于通用 `DEEPSEEK_API_KEY`。

## 一键运行

### Windows

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1 -Wait -Open
```

常用管理命令：

```powershell
# 查看状态
powershell -ExecutionPolicy Bypass -File .\scripts\dev-status.ps1

# 查看日志列表或持续跟踪某个服务
powershell -ExecutionPolicy Bypass -File .\scripts\dev-logs.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\dev-logs.ps1 gateway-api -Follow

# 重启或停止
powershell -ExecutionPolicy Bypass -File .\scripts\dev-restart.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1
```

如果异常退出后遗留状态文件或端口占用，可在确认旧进程不再需要后使用 `dev-up.ps1 -Force`。

### Linux/macOS

```bash
chmod +x scripts/dev-up.sh scripts/dev-down.sh
./scripts/dev-up.sh
```

停止服务：

```bash
./scripts/dev-down.sh
```

启动后访问 `http://127.0.0.1:5173`。

## 手动启动

调试时可以在五个终端分别运行：

```bash
# Terminal 1
cd core/AutoRealize
python -m uvicorn autorealize.service_api:app --host 127.0.0.1 --port 18101

# Terminal 2
cd core/MLEvolve-Alter
python -m uvicorn service_api:app --host 127.0.0.1 --port 18103

# Terminal 3
cd core/AutoReport
python -m uvicorn service_api:app --host 127.0.0.1 --port 18104

# Terminal 4
cd frontend/backend
python -m uvicorn app:app --host 127.0.0.1 --port 18080

# Terminal 5
cd frontend/ui
npm run dev -- --host 127.0.0.1 --port 5173
```

## 任务输出

一次完整任务通常写入：

```text
runs/<task-name>/
|-- input/                  # 用户输入数据
|-- autorealize/
|   |-- description.md
|   |-- sample_submission.csv
|   `-- realize_report/
|-- automl/
|   |-- logs/               # journal、状态、token 与运行日志
|   `-- workspaces/         # best_solution、top_solution 与节点产物
`-- report/
    |-- report.md
    `-- report.json
```

实际日志和工作区下可能再按运行时间建立一层目录。前端会从服务快照中解析当前有效目录。

## 每任务资源限制

- **CPU**：限制 MLEvolve 任务整个进程树共享的逻辑核心，而不是给每个并行节点各分配一份核心。
- **内存**：限制任务主进程与全部子进程共享的总预算；`0` 表示不限制。
- **加速卡**：通过 CUDA、ROCm、Intel XPU 或 Ascend 的可见性环境变量控制任务可见设备；这是可见性隔离，不是设备独占或显存配额。

平台实现：

- Windows 使用 CPU affinity 和 Job Object 总内存限制。
- Linux 使用 CPU affinity，并优先使用可写的 cgroup v2 `memory.max`；无权限时退化为节点 `RLIMIT_AS` 与子进程保护。
- macOS 使用 worker/线程预算近似控制 CPU，使用 `RLIMIT_AS` 与子进程保护限制内存。
- Apple MPS 可以检测，但没有标准的按进程设备隐藏机制。

资源配置、实际 CPU 编号、限制后端、峰值和诊断会写入 MLEvolve 日志目录的 `resource_usage.json`。

## 服务接口

常用健康检查与任务接口：

| 服务 | 健康检查 | 主要接口 |
| --- | --- | --- |
| Gateway | `GET /api/health` | `/api/tasks`、`/api/settings/global` 等前端接口 |
| AutoRealize | `GET /health` | `POST /jobs/start`、`GET /jobs/{id}`、`POST /jobs/stop`、`POST /snapshot` |
| MLEvolve | `GET /health` | `GET /resources/inventory`、任务接口、`POST /snapshot` |
| AutoReport | `GET /health` | `GET /usage`、`GET /config/schema`、任务接口、`POST /snapshot` |

服务启动后可访问各 FastAPI 服务的 `/docs` 查看当前 OpenAPI 文档。

## 测试与校验

先安装开发依赖：

```bash
python -m pip install -r requirements-dev.txt
```

```bash
# Gateway
python -m pytest frontend/backend/tests -q

# AutoRealize
python -m pytest core/AutoRealize/tests -q

# MLEvolve
python -m pytest core/MLEvolve-Alter/tests -q

# AutoReport
python -m pytest core/AutoReport/tests -q

# 仓库安全、配置、链接、测试与构建的一体化检查
powershell -ExecutionPolicy Bypass -File .\scripts\release-check.ps1

# 前端单元测试、类型检查与生产构建
cd frontend/ui
npm run test
npm run build
```

涉及真实 LLM 的端到端任务会产生 API 费用，不应作为默认单元测试运行。

发布与维护文档：

- [架构](docs/architecture.md)
- [API 契约](docs/api-contract.md)
- [部署边界](docs/deployment.md)
- [平台与任务支持矩阵](docs/support-matrix.md)
- [API 费用和数据隐私](docs/cost-and-privacy.md)
- [发布检查清单](docs/release-checklist.md)

## 常见问题

### `core` 目录没有项目代码

运行 `git submodule update --init --recursive`。三个 Core 项目是独立仓库，不是普通目录副本。

### 前端出现 502 或任务服务不可用

先检查 `scripts/dev-status.ps1` 或逐个访问服务 `/health`。后台日志位于 `.dev-state/logs/`。

### 配置了 API Key 但后端仍提示缺失

确认 `frontend/config/global_settings.yaml` 中对应模型保存了 Key、模型角色选择正确，并检查临时任务配置中对应字段是否为空。手动运行 Core 项目时，再检查角色专用环境变量和 `DEEPSEEK_API_KEY`。

### 找不到 GPU 或生成代码无法使用 GPU

前端检测到设备不等于当前 Python 环境可用。请检查驱动、PyTorch 构建、设备运行时和任务的加速卡可见性配置。

### 搜索达到时限后为什么结束

步数用尽或时间预算耗尽都属于正常完成条件。MLEvolve 会保存当时已有的最佳方案、Top-K、journal 和状态，之后仍可继续任务或生成报告。

## 安全说明

- 不要提交真实 API Key、运行期临时配置、输入数据、模型权重或 `.dev-state`。
- 对外发布前应使用 secret scanner 检查 Git 历史，而不只检查当前文件。
- 自动生成代码会读取数据并执行第三方库，生产使用前仍需人工审查方案、依赖、指标与安全边界。
