# Decision Studio 默认启动与开发入口

更新日期：2026-10-20。对应上下文 v1.8.11，产品工作区 `0.3.6-local`，Studio `0.2.6`。

## 默认入口

`frontend/decision-studio` 是当前产品前端及后续开发重点，`frontend/ui` 是兼容旧研究界面与共享组件来源。默认启动端口为 `5178`，默认加载真实工作台；纯模拟界面需要显式 `?demo=1`。

| 入口 | 默认行为 |
| --- | --- |
| 根目录 `启动AutoDecision.cmd` / `start.ps1` | 三个 Core + Gateway + 构建后的新版前端；打开浏览器 |
| `bash start.sh --open` | 同上；`--open` 控制浏览器 |
| `python scripts/studio.py up` | 同上，不自动打开浏览器 |
| `scripts/dev-up.ps1` / `bash scripts/dev-up.sh` | 三个 Core + Gateway + 新版 Vite 热更新 |
| `scripts/dev-restart-frontend.ps1` | 只重启新版前端，使用热更新 |
| `frontend/decision-studio/start-studio.ps1` | 兼容完整启动入口；不带 `-WithCore` 也启动 Core |
| `frontend/decision-studio/start-demo.ps1` | 兼容前端独立入口；默认仍为真实产品模式 |
| `停止AutoDecision.cmd` / `停止决策工作台.cmd` | 退出完整服务组；活动研发/推理会阻断后端退出 |
| `stop-demo.ps1` / `down --frontend-only` | 只停止新版前端 |

`--no-core` / `-NoCore` 只选择 Gateway+前端；`--frontend-only` / `-FrontendOnly` 只选择前端；`--legacy-ui` / `-LegacyUI` 才选择旧 `5173`。`frontend`、`frontend-ui`、`ui`、`studio` 服务别名均指向新版。

## 服务管理实现

PowerShell/Bash 都委托 `scripts/studio.py`。管理器只用标准库、项目已有 `psutil` 和读取配置所需的 PyYAML；没有新引入包或更改前端 lockfile。解释器优先级：CLI → 环境变量 → 全局配置 → bootstrap Python。

统一记录为 `.dev-state/studio-processes.json`，包括仓库身份、服务、PID、进程创建时间、工作目录、日志、前端模式、配置 hash 和代理目标。单实例启动/停止/重启通过 OS 文件锁串行化，状态用临时文件原子替换。

每个实际新启动服务写入独立时间戳 stdout/stderr 日志，启动后等待健康检查。记录在每个进程启动后及时保存；若后面的服务失败，先前已经启动的健康服务仍保留且可由统一停止命令管理，不丢记录或强杀复用服务。

服务端进程必须同时匹配本仓工作目录及 uvicorn 模块；前端必须匹配本目录 Vite 脚本。端口有其他所有者时拒绝操作。停止时通过监听进程身份，或已记录 PID+创建时间+命令+目录核验，避免复用 PID 误伤。

正常 `up` 复用已核验健康后端，不把“健康”宣称为“加载最新代码”。需加载后端修改时使用 `restart --only gateway` 或对应 Core。前端模式、Vite 配置 hash 或代理目标变化时可以只重启已核验前端。

普通启动会做生产构建；开发启动使用 `vite --strictPort`，不自动退到其他端口。Python 服务不启用自动 reload，避免研发任务被热更新打断。兼容 `--force` / `-Force` 不再授权按端口杀无关进程。

## 停止与任务状态

后端停止前读取 Gateway `/api/tasks` 和 `/api/studio/state`，检测运行中的研发和推理。有令牌时使用 `AUTODECISION_API_TOKEN`；不能获取状态时明确拒绝停止。Gateway 不在线时保守检查当前状态目录中的任务与 Studio 推理记录。

先完成所有目标进程身份及任务状态检查，再停止第一个进程。前端独立停止不检查或操作后台任务。该检查不提供多用户事务级锁：不要同时执行新的研发/对话/试算与服务退出。Core 服务暂无通用的全局作业清单，本管理器无法发现其他状态目录/独立 Core 直接发起的作业；此类作业应由原调用者管理。

原 `.dev-state/pids.json`、`.demo-state`、`.runtime-state` 仅作旧记录保留，不再作为新版生命周期权威。属于本仓的在线旧服务可以通过身份核验后复用；管理器未生成的日志应查看旧启动器位置。没有进行数据、模型或任务清理。

## 检查与验证

```bash
python -m pytest scripts/tests/test_studio_launcher.py frontend/backend/tests/test_security.py -q
python scripts/studio.py status
python scripts/studio.py logs --name frontend --lines 20
npm --prefix frontend/decision-studio run build
```

该轮单测共 25 项通过，覆盖默认路由、旧界面显式选择、Node 版本契约、进程身份、同端口无关应用拒绝、活动研发/推理阻断、停止前整体校验、前端独立停止、原子状态文件与仓库边界、重启前依赖检查。PowerShell 包装器语法及 Git Bash 的 shell 语法检查通过。

Windows 实际运行验证：根目录完整启动、重复启动复用、预览切到热更新、只重启新版前端、只停止前端、只重启 Gateway、完整停止及干净开发启动均通过。最后保留全部五个服务运行，Studio 为开发热更新，Gateway 加载 `0.2.6`，`5173` 未监听。具体运行证据与浏览器结果归档在开发工作区上下文 v1.8.11；没有付费模型调用、训练或算法包发布。

Linux/macOS 本轮仅完成 Bash 语法与 Git Bash 参数转发检查，没有在 Linux/macOS 完整启动 Core。不要把跨平台共享实现写成所有平台均已实机验收。
