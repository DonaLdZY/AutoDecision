# 本地工作台 v0.3.0-local

日期：2026-10-14。此版本是本地产品化工作区版本，未创建 Git tag、安装包或线上服务。使用 Vue 浏览器界面与本机 Gateway/Core；没有云试用。

## 使用路径

1. 按仓库 README 安装 Python 3.12 环境、Core 子模块与前端依赖。Windows 在已激活环境中执行 `./scripts/dev-up.ps1 -Open`；Linux/macOS 使用 `./scripts/dev-up.sh --open`。既有启动器继续负责服务进程，不新增桌面壳。
2. 打开“本地运行检查”，配置模型与 Python 环境，确认 Core 在线、输入可读、输出有空间。检查不会请求模型；“测试文本请求”才会发送一条可能收费的短消息，不发送任务数据。
3. 新建任务，选择本机数据目录，填写目标和搜索预算。轻量 / 标准 / 长时间探索预设会根据机器总资源裁剪 CPU/内存；GPU 需要在资源页显式选择。高级参数默认折叠。
4. “检查并开始”创建一次实验。运行中可以“停止并保留进度”，检查点是否完整以后台反馈为准；恢复使用原配置。运行结束查看“方案交付”。
5. 需要修改数据、目标或预算时，选择“新建实验”。复制配置到新身份和新目录，旧记录与旧文件保留。在“实验历史”比较配置并切换查看结果。
6. 导出方案包，或在满足条件时用已有模型试算。报告可以单独补充，无需通过主按钮清空全流程。

关闭浏览器不会停止后台服务；退出运行器、休眠或断电会影响作业。`dev-status`、`dev-logs`、`dev-down` 脚本仍用于状态、日志和退出。不要把关闭页面当成已停止任务。

## 行为变化

| 旧行为 | 本版行为 |
|---|---|
| 主按钮“执行任务”调用删除旧目录的完整重跑 | 调用 `/tasks/start`；已有实验恢复或查看成果；默认流程不调用完整重跑 |
| 启动存在异步重复提交窗口 | store 锁内占用 `running/starting`；重复提交返回 409 |
| 恢复存在异步重复提交窗口 | 锁内占用 `running/resuming`，将原阶段快照传给恢复线程 |
| 配置可在旧运行上覆盖 | 有 execution_config 或 run_dir 时禁止覆盖配置；新实验可编辑 |
| 当前查看页显示成“任务阶段” | 实际阶段由任务 phase / 运行证据推导，查看页独立表示 |
| 所有页展示搜索计数 | 搜索页展示搜索指标，其他阶段显示对应检查重点 |
| 只能下载候选源码 / 文本报告 | 专用成果页读取选定包、导出文件及冻结合同，提供有门槛的试算 |
| UI 侧栏写死 v2.0 | package 版本与根 VERSION 标记为 0.3.0-local |

历史 `/tasks/rerun-full` API 为兼容仍保留，仍是危险操作且要求 confirm；当前 UI 不再使用。高级阶段重跑仍使用原有归档/恢复流程，因此“配置锁定”不等同所有文件永久不可变。新建实验是修改任务条件的推荐路径。

## 就绪检查与模型验证

`GET /api/system/readiness?task_id=...` 检查已配置解释器能运行、Python >=3.10、基础依赖 fastapi/yaml/numpy/pandas/openai/psutil 可导入，三个 Core 的 `/health`（每个 2 秒超时），必需文本角色配置、输出空间和可选任务输入。报告关闭时省略报告服务检查。项目推荐与本次测试环境仍是 Python 3.12；这个检查不是所有库版本和全部候选依赖的验收。

状态为 pass / warn / fail。没有 fail 即 ready；模型仅配置未验证会是 warn，用户可以明确继续。视觉启用但缺配置会 fail；有视觉配置也只标记待验证。向量、视觉、结构化生成、长上下文并未做统一能力验证。

`POST /api/system/probe-model` 只接受 autoRealize、autoMlCode、autoMlFeedback，向 OpenAI 兼容 chat/completions 发送 `Reply OK.`，max_tokens=16、20 秒超时。成功保存模型配置 SHA256 和时间到 `.state/model_checks.json`，24 小时有效；配置改变或过期后回到待验证。失败不回显 Provider 原始响应或密钥。部分 Provider 不接受探测参数，失败不等于模型绝对不可用。

本地目录不代表离线：模型配置页和检查页说明 Provider 主机与数据流。只有 localhost / 127.0.0.1 / ::1 作为本机端点判定；这不是网络拓扑或数据驻留认证。

## 实验身份与配置

TaskModel 增加可选 `experiment_group_id`、`parent_task_id` 和 `execution_config`。旧记录可直接加载，不批量搬迁目录。第一次普通启动冻结任务级 config；旧实验没有冻结记录时不伪造历史。全局 Provider 配置、外部输入文件内容不会被此字段冻结。

`POST /api/tasks/{id}/experiments` 复制当前持久配置，生成新 task id，名字加随机后缀以得到新目录，保留根 group id 和父 id。它只创建草稿，不立即运行。`GET` 同路径返回同组实验。此阶段是兼容 TaskStore 的轻量实验模型，尚非独立数据库中的 Project/Task/Run/Solution 四层实体。

新建普通任务继承最近运行的参数偏好，但清空原数据/目标，并生成新名字；“新建实验”才会继承同一任务的数据与目标。原始输入仍是目录引用；如需严格复现，应自行固定或快照输入数据。恢复任务允许通过系统设置修复模型连接，但使用原任务配置。

## 方案导出

`GET /api/tasks/{id}/solution` 解析实际 workspace/best_solution/solution_manifest.json，读取选定 node_id、入口、评价协议、模型路径和实现 hash。它不把搜索最佳节点自动当成最终选定模型，不导入生成代码。

`GET /api/tasks/{id}/solution/bundle` 生成临时 ZIP，完成响应后清理。限制 20000 个文件、4 GiB，检查临时盘余量；文件逐块复制和哈希，不整包读入内存。前端下载目前使用 Blob，特别大的包仍建议从本地目录交付。

包括方案目录的实现、wrapper、serialization module、artifact、配方/依赖/验证记录等实际存在文件；排除 runtime、input、__pycache__、.git、.env、config.yaml、global_settings.yaml、secrets.json 与 pyc。不是全盘敏感信息扫描，生成代码/说明中自行写入的内容仍由用户核对。

冻结合同只从当前 workspace/input 的白名单文件取，包括 description、requirements/protocol 文档及 realize_report 下 main_task_protocol、data_access_protocol、automl_context、evaluation_contract_report、task_definition_report；不使用可能已变更的任务根合同，不复制训练原始数据。

包内 model_path.txt 和清单 artifact_path 改为相对路径，原文件不修改。另生成 package_inventory.json（来源、任务配置、原文件哈希）与 LOCAL_USAGE.md。这不保证旧实现内部的硬编码绝对路径已消除。

运行中、模型文件缺失/越界、实现 hash 不符或文件复制期间变化会阻止导出。结构检查通过不等于依赖安装成功、模型泛化有效、独立验收通过或业务达标。

## 已有方案试算

`POST /api/tasks/{id}/solution/trial` 只对模型齐全、已停止且带 implementation_path 和 implementation_file_sha256 的包开放；入口限定 predict / solve / rollout，不调用 train / train_policy。

输入选 JSON 对象/数组（1 MiB）或本任务输入目录内 CSV（16 MiB、无越界链接）。CSV 在试算解释器中解析成 pandas DataFrame；需要文件路径、GPU、其他格式或复杂时间窗的方案仍应使用导出包及专用适配器。

复制方案到临时目录，复核复制的实现 hash，用配置的 Python 独立进程执行 `solution_trial_runner.py`，一次只允许一个网页试算。默认 30 秒，可设 1—120 秒，超时尝试终止进程树；复制准备不计入执行超时。结果可为 JSON 兼容对象、DataFrame、ndarray 等，严格 JSON 输出，预览上限 1 MiB。

进程环境去掉名称含 API_KEY/APIKEY/TOKEN/SECRET 的变量，设置常见 GPU 隐藏与单线程环境变量。这是轻量调用约束，**不是网络/文件系统沙箱，也不是跨平台硬 CPU/内存限额**；代码显式指定设备、写入绝对路径或自行启动子进程时仍需运行环境隔离。不要把候选生成代码视为绝对安全。失败只返回分类提示，不把任意 stdout/stderr 回传到网页。

成功记录 `.state/trials/{task_id}/{trial_id}.json`：选定节点、入口、包文件 hash、实现 hash、输入 hash、时间、结果和验证范围。`GET /solution/trials` 返回最近20条摘要，`GET /solution/trials/{trial_id}` 返回单条结果，刷新后可重新查看和下载；不改写旧模型、journal 或指标。文件的“未修改”保证针对打包/调度器本身；生成代码仍受前述执行权限限制。本轮只用合成函数验证调用、超时与来源记录，没有运行历史实例的真实预测。

## 资源与默认值

新默认：CPU 4 核、内存 8 GiB、GPU 不可见；搜索 2 并行、分析 API 8 并发、搜索时间 10800 秒；视觉默认关闭。已有显式配置保留。可选视觉/embedding 角色为空时不再悄悄映射到第一项聊天模型。

预设轻量/标准/长时间探索分别给定 CPU 上限 2/4/总核数减 1，内存上限 4/8/总内存 75%，本地 worker 1/2/4，分析 API 并发 4/8/16，搜索时间 30/180/360 分钟。最终 CPU 留至少一个核（单核机例外）、内存不超过总量 75%（最低 1 GiB）、worker 不超过所选核数。预设是启发式配置，不是完成时间或费用保证；所有预设关闭 GPU，需要另行选择。

## 验证与尚未覆盖的产品能力

新增后端隔离测试与 Python Playwright 浏览器测试；测试结果及源码 SHA256 存放于工作区外层的项目上下文 v1.2.0 版本包。测试不发真实付费模型请求，不重新训练历史数据。

此版本完成安全主流程、初步就绪检查、轻量实验谱系、成果导出与有限格式试算。尚未实现统一费用硬预算、所有模型能力认证、跨平台发行安装器/自动升级、完整磁盘配额、输入数据版本管理、任务特定自动表单适配、业务指标自动跨实验比较，以及持久化人工确认/等待状态机。严格命题仍须以具体合同与验证证据为准。
