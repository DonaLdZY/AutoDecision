# AutoDecision 前端

AutoDecision 的浏览器界面，使用 Vue 3、TypeScript 和 Vite 构建。界面只访问 AutoDecision Gateway，由 Gateway 编排 AutoRealize、MLEvolve-Alter 和 AutoReport。

## 环境要求

- Node.js `>=20.19 <23`
- npm 10+
- 已启动的 Gateway，默认地址为 `http://127.0.0.1:18080`

## 本地开发

```bash
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

也可以从 AutoDecision 根目录运行统一启动脚本；详见根目录 [README](../../README.md)。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VITE_AUTODECISION_API_BASE` | `http://127.0.0.1:18080/api` | Gateway API 根地址 |
| `VITE_AUTODECISION_API_TOKEN` | 空 | Gateway 启用 `AUTODECISION_API_TOKEN` 后使用的 Bearer token |

`VITE_*` 变量会被打包进浏览器资源，不能用来保存模型 API Key 或其他长期服务器密钥。

模型和 API Key 等全局设置由 Gateway 持久化到 `frontend/config/global_settings.yaml`。该文件缺失时会在 Gateway 启动时自动创建，并已被 Git 忽略；重新构建或更新 Vue 前端不会要求重新输入 API Key。浏览器只接收 Key 是否已配置的标记，不接收已保存的明文值。

## 测试与构建

```bash
npm run test
npm run build
```

`npm run build` 会先执行 `vue-tsc` 类型检查，再生成生产资源到 `dist/`。该目录属于构建产物，不应提交到 Git。

## 目录

```text
src/
|-- components/     # 任务、配置、搜索树和资源控件
|-- composables/    # API 状态与任务工作流逻辑
|-- utils/          # 纯函数和资源配置转换
|-- api.ts          # Gateway HTTP 客户端
|-- types.ts        # 前后端契约类型
`-- App.vue         # 应用组合入口
```

修改前后端契约时，应同步更新 `src/types.ts`、Gateway Pydantic 模型和相关测试。
