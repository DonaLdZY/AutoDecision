# Decision Studio

Decision Studio 是 AutoDecision 的 Web 工作台。它通过 Gateway API 管理本地数据项目、决策对话、研发任务、算法模型包、调用记录和系统设置。

## 本地运行

推荐从仓库根目录启动完整服务：

```powershell
./start.ps1 -Dev
```

```bash
./start.sh --dev
```

启动后打开 `http://127.0.0.1:5178/`。完整安装、Python 环境、服务停止、日志和故障排查见仓库根目录 [README](../../README.md)。

只运行前端开发服务器时：

```bash
npm ci
npm run dev
```

前端开发服务器监听 `127.0.0.1:5178`，`/api` 请求通过 Vite 代理转发到 Gateway。默认目标为 `http://127.0.0.1:18080`，可通过 `AUTODECISION_GATEWAY_TARGET` 调整。

构建生产静态资源：

```bash
npm run build
```

## 代码结构

| 路径 | 职责 |
| --- | --- |
| `src/main.ts` | 应用入口和显式演示模式分流 |
| `src/live/StudioApp.vue` | 工作台布局、导航和页面组合 |
| `src/live/Chat.vue` | 决策对话、模型包复用和研发入口 |
| `src/live/ResearchForm.vue` | 研发任务草稿、数据目录和任务约束 |
| `src/live/Projects.vue` | 数据项目及其输入范围 |
| `src/live/Packages.vue` | 算法模型包目录、交付和发布 |
| `src/live/Tasks.vue` | 研发任务列表和阶段状态 |
| `src/live/TaskDetail.vue` | 任务证据、操作和运行详情 |
| `src/live/InvokeForm.vue` | 输入准备、字段适配和模型包调用 |
| `src/live/Settings.vue` | 模型配置和角色分配 |
| `src/live/store.ts` | API 客户端、共享状态和前端类型 |
| `src/live/live.css` | 工作台布局和交互样式 |
| `src/style.css` | 应用基础样式 |
| `../backend/decision_studio.py` | 项目、会话、模型包和调用 API |
| `../backend/app.py` | 任务编排、配置、资源和状态 API |

`src/App.vue` 提供显式的本地演示模式，只有在 URL 查询参数中指定 `demo=1` 时加载。真实工作台默认连接 Gateway；Gateway 不可用时会显示连接错误，不会伪造任务或预测结果。

## 页面职责

工作台围绕一个本地数据项目组织业务流程：

1. 在项目页登记数据目录并查看历史任务。
2. 在对话页提出预测、优化或分析需求。
3. 对已有模型包核对修订、输入合同和字段适配后执行。
4. 对未覆盖的需求创建研发草稿，选择项目内数据目录并确认约束。
5. 在任务页启动、恢复、停止和查看 AutoRealize、AlgoEvolve、AutoReport 各阶段。
6. 在模型包页核对交付材料、试算输入和发布修订。
7. 在调用页查看输入快照、执行结果和来源记录。

对话转研发的初始指令可以由模型结合当前会话、项目认知、数据范围和已有模型包进行润色，但返回内容始终是可编辑草稿，保存前由用户确认。项目认知缓存和历史 QDI 证据由 Gateway 与 AutoRealize 管理，前端只展示其状态和来源。

## API 约定

开发时优先通过 `src/live/store.ts` 中的类型化方法访问接口，不在页面组件内重复拼接请求 URL。所有浏览器请求使用相对 `/api` 路径，以便复用 Vite 开发代理和生产部署代理。

常用接口分组：

- `/api/studio/*`：项目、会话、模型包、调用和工作台状态
- `/api/tasks/*`：研发任务创建、启动、恢复、停止、阶段详情和报告交付
- `/api/settings/*`：模型配置、角色分配和服务测试
- `/api/projects/*`：数据项目、输入目录和文件范围

接口请求可能受到 Gateway API token 保护。认证失败、后台服务离线、任务状态冲突和输入合同不匹配必须在界面中展示明确错误；不要在前端把错误响应转换为成功状态。

## 前端约定

- 使用 Vue 3、TypeScript 和 Vite。
- 页面状态优先通过 `store.ts` 和组合式状态共享，避免在多个页面复制同一份服务器状态。
- 后端返回的任务、项目、模型包和调用 ID 作为稳定标识，不使用数组下标做引用。
- 异步请求需要处理加载、成功、失败、取消和组件卸载后的过期响应。
- 用户正在编辑的字段不能被晚到的润色或刷新响应覆盖。
- 只在用户明确确认后执行研发、推理、停止、重跑和发布等有副作用操作。
- 输入字段、单位、时间窗口和来源摘要应在执行前可见；不能把隐式转换藏在按钮行为中。
- 新的工作台页面和交互放在 `src/live/`；共享类型和接口变更同步检查 Gateway 与测试。

## 验证

```bash
npm run build
npm run format:check
```

仓库根目录的后端和启动器测试：

```bash
python -m pytest frontend/backend/tests scripts/tests -q
```

需要浏览器验证时，先启动 Gateway 和工作台，再运行 `e2e/` 下对应脚本。真实模型质量、研发效果和业务验收需要使用明确的数据与独立验证协议，不能用演示模式结果代替。
