# AutoDecision 服务化与甲方交付建议

## 目标

将 AutoDecision 拆成“前后端完全解耦、Core 统一服务化”的工程结构，方便：

- 本地研发
- Docker 化部署
- 甲方自有前端对接
- 后续替换单个 Core 引擎而不影响整体架构

## 推荐工程边界

### 1. Core 服务层

每个 Core 项目各自暴露独立 FastAPI：

- `AutoRealize API`
- `MLEvolve API`

职责：

- 接收标准任务启动参数
- 返回任务 `job_id`
- 暴露运行状态、停止接口、运行快照接口
- 只负责本引擎内部运行与监控信息暴露

不负责：

- 浏览器界面
- 多任务总编排
- 任务标签页状态管理
- 跨引擎流程串联

### 2. Gateway 编排层

建议单独保留一个 `gateway-api`，统一给前端或甲方系统调用。

职责：

- 任务 CRUD
- 全局配置管理
- 任务运行目录编排
- 先调 `AutoRealize` 再调 `MLEvolve`
- 汇总多服务快照
- 管理重跑、终止、状态恢复

甲方前端建议只对接这一层。

### 3. Frontend 展示层

现有 Vue 前端可以继续作为：

- 内部研发前端
- Demo 前端
- 运维监控前端

但它不应再承担任何 Core 直接调用逻辑。

## 推荐目录结构

```text
AutoDecision/
  core/
    AutoRealize/
    MLEvolve-Alter/
  frontend/
    ui/
    backend/
  deploy/
    docker/
      compose.dev.yml
      compose.prod.yml
      gateway.Dockerfile
      frontend.Dockerfile
  docs/
    architecture.md
    api-contract.md
    deployment.md
```

## API 分层原则

前端或甲方系统只能调用：

- `gateway-api`

`gateway-api` 只能调用：

- `AutoRealize API`
- `MLEvolve API`

禁止：

- 前端直接执行 Core 命令
- 前端直接读 Core 输出目录
- Gateway 直接 import Core 主逻辑并在同进程内执行

## 任务运行目录建议

统一由 Gateway 负责编排：

```text
runs/<task_name>/
  autorealize/
  automl/
    logs/
    workspaces/
```

说明：

- `autorealize/` 存前三步输出
- `automl/` 存 AutoML 引擎运行输出
- 若引擎内部有时间戳子目录，可由对应 FastAPI 返回真实目录给 Gateway

## 甲方交付建议

### 方案 A：甲方只接 Gateway

优点：

- 对接简单
- 甲方无需理解多个 Core 服务差异
- 任务管理逻辑集中

适合：

- 绝大多数项目交付

### 方案 B：甲方直接接多个 Core API

优点：

- 灵活
- 可跳过 AutoDecision 的任务管理 UI

缺点：

- 甲方需要自己做多服务编排
- 目录与状态管理更复杂

适合：

- 甲方平台本身已有成熟工作流编排系统

## 本项目当前状态

当前已经满足：

- `AutoRealize` 通过 FastAPI 暴露
- `MLEvolve-Alter` 通过 FastAPI 暴露
- Vue 前端只调用 `frontend/backend/app.py`
- `frontend/backend/app.py` 只调用各 Core 的 FastAPI

也就是说，已经具备后续 Docker 化与甲方前端接入的基础。

## 后续建议

1. 固化 Core API 契约文档
2. 给 Gateway 增加 JWT / token 鉴权
3. 将任务状态持久化从 JSON 文件切到 SQLite / PostgreSQL
4. 为快照接口增加 WebSocket / SSE 实时推送
5. 为每个服务分别制作 Docker 镜像

