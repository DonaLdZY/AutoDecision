# AutoDecision 启动说明

AutoDecision 开发模式由多个本地服务组成：

1. `AutoRealize API`：`http://127.0.0.1:18101`
2. `MLEvolve API`：`http://127.0.0.1:18103`
3. `AutoReport API`：`http://127.0.0.1:18104`
4. `Gateway API`：`http://127.0.0.1:18080`
5. `Vue Frontend`：`http://127.0.0.1:5173`

前端只访问 Gateway API，Gateway 再通过 HTTP 调用各个 Core 服务。

## 环境要求

1. Python 3.10+
2. Node.js 18+
3. 已安装 Python 依赖和前端依赖

## Windows 一键启动

从项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1
```

默认会把服务启动到后台，并尽快返回当前 PowerShell prompt。

如果希望启动脚本等待所有服务健康检查通过：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1 -Wait
```

启动后自动打开浏览器：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1 -Open
```

## Windows 常用管理命令

查看服务状态：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-status.ps1
```

查看可用日志：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-logs.ps1
```

查看某个服务最近日志：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-logs.ps1 autorealize-api
```

持续跟踪某个服务日志：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-logs.ps1 gateway-api -Follow
```

重启全部服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-restart.ps1
```

关闭全部服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1
```

如果上次异常退出导致状态文件或端口残留，可以强制启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1 -Force
```

## macOS / Linux 一键启动

首次赋予脚本执行权限：

```bash
chmod +x scripts/dev-up.sh scripts/dev-down.sh
```

启动：

```bash
./scripts/dev-up.sh
```

关闭：

```bash
./scripts/dev-down.sh
```

## 手动启动调试

如果需要观察某个服务的实时终端输出，可以手动开多个终端分别启动。

AutoRealize API：

```bash
cd core/AutoRealize
uvicorn autorealize.service_api:app --host 127.0.0.1 --port 18101
```

MLEvolve API：

```bash
cd core/MLEvolve-Alter
uvicorn service_api:app --host 127.0.0.1 --port 18103
```

AutoReport API：

```bash
cd core/AutoReport
uvicorn service_api:app --host 127.0.0.1 --port 18104
```

Gateway API：

```bash
cd frontend/backend
uvicorn app:app --host 127.0.0.1 --port 18080
```

Frontend UI：

```bash
cd frontend/ui
npm run dev -- --host 127.0.0.1 --port 5173
```

打开前端：

```text
http://127.0.0.1:5173
```

## 常见问题

1. 端口被占用：先运行 `scripts/dev-down.ps1` 或 `scripts/dev-down.sh`，必要时使用 `-Force` / `--force`。
2. 前端报 502：通常是某个 Core API 没启动，用状态脚本或访问 `/health` 检查。
3. 想看原始终端输出：后台启动时输出会写入 `.dev-state/logs/`，用 `dev-logs.ps1` 查看。


