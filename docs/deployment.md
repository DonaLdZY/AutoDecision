# 部署说明

## 本地开发

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1 -Force
```

关闭:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1
```

macOS / Linux:

```bash
bash ./scripts/dev-up.sh
```

关闭:

```bash
bash ./scripts/dev-down.sh
```

## Docker 化建议

推荐拆成 4 个服务：

- `autorealize-api`
- `mlevolve-api`
- `gateway-api`
- `frontend-ui`

其中：

- 甲方正式对接建议只暴露 `gateway-api`
- `frontend-ui` 可作为内部演示与运维界面
- 两个 Core API 可放在内网网络中，不直接暴露公网

## 数据卷建议

建议挂载：

- 项目代码目录
- `runs/` 输出目录
- 模型缓存目录
- Python / pip / huggingface 缓存目录

## 生产环境建议

1. `gateway-api` 前增加 Nginx / Traefik
2. 通过环境变量注入 API key
3. 对 `/api/tasks/start`、`/api/tasks/stop` 增加鉴权
4. 将任务状态持久化从 JSON 文件迁移到数据库
5. 给 Core 服务设置资源限制与超时保护

## 注意事项

- MLEvolve 当前适配未改变其原始求解功能
- 仅增加了服务包装、日志桥接、快照提取和运行目录可预测支持
- 若要继续容器化，优先保持“服务包装层”和“核心求解逻辑”分离

