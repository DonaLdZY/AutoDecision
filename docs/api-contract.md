# Core API 契约约束

## 总原则

- Core 只通过 HTTP API 暴露能力
- 前端不得直接调用 Core 命令行
- 前端不得直接读取 Core 输出目录作为主要数据源
- Gateway 是唯一对外编排入口

## 每个 Core 服务至少应支持

### Health

- `GET /health`

### Job Lifecycle

- `POST /jobs/start`
- `GET /jobs/{job_id}`
- `POST /jobs/stop`

### Snapshot

- `POST /snapshot`

## 推荐统一响应字段

### `/jobs/start`

```json
{
  "job_id": "...",
  "status": "started",
  "log_dir": "...",
  "workspace_dir": "..."
}
```

### `/jobs/{job_id}`

```json
{
  "job_id": "...",
  "task_id": "...",
  "status": "running|completed|failed|stopped",
  "started_at": 0,
  "updated_at": 0,
  "exit_code": 0,
  "last_error": "...",
  "stdout_tail": "...",
  "stderr_tail": "..."
}
```

### `/snapshot`

推荐至少包含：

```json
{
  "engine": "ml_master|mlevolve|autorealize",
  "log_dir": "...",
  "workspace_dir": "...",
  "events": [],
  "nodes": [],
  "best_node_id": "..."
}
```

## Gateway 的职责

- 把不同 Core 的快照适配成统一前端可消费结构
- 保留原始引擎信息 `engine`
- 不篡改 Core 主要逻辑
- 只可增加探针、日志采集、状态桥接与路径推断

## 修改 Core 的允许范围

允许：

- 增加 FastAPI 包装层
- 增加日志输出
- 增加快照解析辅助函数
- 增加环境变量驱动的可选行为
- 增加中间状态暴露

不允许：

- 改变算法主流程语义
- 改变搜索策略核心行为
- 改变默认命令行使用方式
- 修改任务求解主逻辑结果
