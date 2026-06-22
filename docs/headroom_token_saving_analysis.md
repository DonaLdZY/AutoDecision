# Headroom Token Saving 机制深度分析与 AutoDecision 迁移设计

> 阅读对象：`D:\Files\项目\headroom-main\headroom-main`  
> 产出目标：解释 Headroom 如何为 Codex、Claude Code、OpenClaw、Hermes 等 agent 系统节省 token，并给出迁移到 AutoDecision、AutoRealize、MLEvolve 的工程方案。  
> 重要结论先说：Headroom 不是一个“更短 prompt 模板”，而是一层本地上下文优化系统。它通过工具输出压缩、可逆检索、cache-hot prefix 保护、live-zone 局部改写、日志/search/diff/JSON 专用压缩器、输出节流和观测指标，把 agent 每轮发给模型的大量低价值上下文变小，同时尽量不破坏模型完成任务所需的关键证据。

## 1. 执行摘要

Headroom 的核心策略可以概括为一句话：

**不要让 LLM 反复看到完整噪声；让它先看到足够完成任务的压缩视图，必要时再按需取回原文。**

它节省 token 主要来自四类收益：

1. **工具输出压缩收益**：Codex、Claude Code 这类 agent 经常把文件读取、grep、ripgrep、测试日志、shell 输出、JSON API 响应反复塞进上下文。Headroom 在这些内容进入模型前按内容类型压缩，尤其对 JSON 数组、日志、搜索结果、大 diff、表格化数据效果明显。
2. **可逆压缩收益**：传统裁剪会丢信息，Headroom 的 CCR（Compress-Cache-Retrieve）把原始内容存到本地 cache，只给模型短视图和 hash marker。模型需要全文时可调用 `headroom_retrieve` 取回，因此可以更激进地压缩。
3. **provider cache 收益**：LLM provider 的 prompt cache 要求 prefix 字节稳定。Headroom 尽量不改 system/developer/frozen prefix，并且在 Rust proxy 侧用 live-zone byte-range surgery 只改最新 user/tool_result 块，避免重新序列化导致 cache miss。
4. **输出 token 收益**：Headroom 不只能压输入，还能在代理请求侧追加简短稳定的“少废话”指令，并在机械性工具续写轮降低 thinking/effort，从而减少模型输出中的礼貌铺垫、重复代码和不必要推理。

对 AutoDecision 最重要的迁移启发不是“直接把 Headroom 接到所有 API 前面”这么简单，而是：

1. **AutoRealize 要有自己的 deterministic context compiler**：把文件认知、字段画像、relations、QDI 问题账本、评估证据包编译成稳定、小而全的 context，而不是每个 LLM 调用都塞完整数据认知报告。
2. **QDI 要 CCR 化**：脚本完整输出、文件完整 preview、完整 sheet profile、本地调查中间产物都存 artifact store；prompt 只放当前问题、当前可见输出、截断标记和 artifact id。
3. **evaluation/description 生成要 section-level live zone**：冻结已完成章节；reviewer 只看当前章节相关 evidence pack 和 defects；失败修复时只把缺陷放动态尾部，不重复整篇 description。
4. **MLEvolve 要压缩运行反馈而不是重复数据预览**：测试日志、异常栈、搜索结果、diff、候选方案历史都应该走 Headroom 风格的结构化压缩；AutoRealize 生成的 `automl_context` 应直接占住数据认知上下文，避免 MLEvolve 再生成一遍 data preview。

## 2. 阅读范围与关键源文件

本报告基于对 Headroom 仓库顶层文档、wiki、Python SDK、Rust core/proxy、TypeScript SDK、插件、benchmark/test 相关文件的阅读和归纳。重点文件包括：

| 类别 | 关键文件 |
|---|---|
| 总览文档 | `README.md`, `llms.txt`, `wiki/ARCHITECTURE.md`, `wiki/compression.md`, `wiki/transforms.md`, `wiki/text-compression.md`, `wiki/ccr.md`, `wiki/LIMITATIONS.md`, `wiki/benchmarks.md` |
| Python pipeline | `headroom/transforms/pipeline.py`, `headroom/transforms/content_router.py`, `headroom/transforms/cache_aligner.py`, `headroom/transforms/read_lifecycle.py` |
| 压缩器 | `headroom/transforms/smart_crusher.py`, `search_compressor.py`, `log_compressor.py` |
| CCR | `headroom/ccr/tool_injection.py`, `headroom/ccr/response_handler.py`, `headroom/cache/compression_store.py` |
| 输出节流 | `headroom/proxy/output_shaper.py`, `verbosity_controller.py` |
| Rust core | `crates/headroom-core/src/transforms/live_zone.rs`, `crates/headroom-core/config/pipeline.toml` |
| Rust proxy cache 稳定 | `crates/headroom-proxy/src/cache_stabilization/tool_def_normalize.rs`, `openai_cache_key.rs` |
| Agent 接入 | `headroom/cli/wrap.py`, `headroom/mcp_registry/codex.py`, `headroom/mcp_registry/claude.py`, `plugins/openclaw/README.md`, `plugins/hermes/README.md` |
| TS SDK | `sdk/typescript/README.md`, `sdk/typescript/src/client.ts` |
| Benchmarks/tests | `benchmarks/*`, `tests/*agent*savings*`, `tests/*search*`, `tests/*log*`, `tests/*smart_crusher*`, `tests/*read_lifecycle*` |

需要特别注意：Headroom 文档中有些架构图和历史说明还提到 RollingWindow / IntelligentContextManager 这类“丢弃旧消息”的阶段，但当前 Python `TransformPipeline` 明确说明这类 message-list mutation 已经从 live pipeline 退役。当前主线更强调 **live-zone/content compression**，而不是任意删历史。

## 3. Headroom 到底是什么

Headroom 不是单一库，而是一组围绕 LLM request/response 的本地上下文优化组件。

### 3.1 产品形态

| 形态 | 作用 |
|---|---|
| Python SDK | 在应用代码里直接调用 `compress(messages)` 或包装 OpenAI/Anthropic client。 |
| TypeScript SDK | 在 Node/Vercel AI SDK/OpenAI SDK/Anthropic SDK/Gemini SDK 中包装请求。 |
| HTTP proxy | OpenAI/Anthropic/Gemini 兼容代理。客户端把 base URL 指向本地 proxy，proxy 压缩请求后转发给 provider。 |
| MCP server | 给 Claude Code/Cursor 等 MCP client 暴露 `headroom_compress`, `headroom_retrieve`, `headroom_stats`。 |
| agent wrap | `headroom wrap claude|codex|cursor|aider|copilot|openclaw...` 自动配置 agent 走本地 proxy/MCP。 |
| plugins | OpenClaw contextEngine、Hermes retrieve tool 等，把压缩和取回接到不同 agent 框架。 |
| Rust core/proxy | 高性能、字节稳定、cache-safe 的 live-zone 压缩与 provider cache 稳定化。 |
| memory/learning | 跨 agent 共享压缩记忆、失败学习、TOIN compression pattern learning。 |

### 3.2 它和“LLM 总结压缩”的区别

Headroom 的压缩多数是**非 LLM 压缩**：规则、统计、结构解析、Rust/Python compressor、可选 ML token classifier。它不是再调用一个 LLM 让 LLM 总结工具输出。

这点对 AutoDecision 非常重要。AutoRealize 当前成本问题里，用户已经多次指出“为了压缩再 LLM 总结”会产生额外 API 调用、缓存 miss 和输出 token。Headroom 的设计正好相反：

1. 能规则压缩就规则压缩。
2. 能结构化保留就结构化保留。
3. 需要原始内容时再取回，而不是预先全塞。
4. 压缩过程本身尽量不调用 LLM。

## 4. 总体请求链路

Headroom 在 agent 场景中的典型链路如下：

```text
Codex / Claude Code / OpenClaw / app
  -> 生成 LLM request：system + tools + messages + tool outputs
  -> Headroom proxy / SDK
      -> 计算原始 tokens
      -> 保护 frozen prefix / system / developer / recent code / error outputs
      -> 识别 live-zone 或可压缩 tool result
      -> 按内容类型路由 compressor
      -> 写入 CCR store，插入 marker
      -> 注入 headroom_retrieve tool（如有 marker）
      -> 转发压缩后的 request 给 provider
  -> provider 返回 response
      -> 如果 response 调用 headroom_retrieve
          -> proxy 从本地 store 取回原文或 query 过滤结果
          -> 自动 continuation，再次调用 provider
      -> 最终 response 返回给原 agent
```

这个链路带来的工程价值：

1. 对上层 agent 透明：Codex/Claude Code 可以基本不改任务逻辑。
2. 压缩和取回统一在本地：敏感数据无需先发给远端压缩服务。
3. 可观测：能记录原始 tokens、压缩后 tokens、使用了哪些 transform、耗时、节省率。
4. 可回退：压缩失败时 passthrough，压缩后变大则丢弃压缩结果，尽量不破坏原任务。

## 5. 当前 Python 默认 pipeline 的真实行为

`headroom/transforms/pipeline.py` 当前默认 pipeline 主要是：

1. 可选 tool-result interceptors。
2. `CacheAligner`。
3. `ContentRouter`。

### 5.1 Tool-result interceptors

Tool-result interceptor 默认关闭，只有配置或环境变量打开时才启用。它可以在压缩器前先把某些工具输出换成更短形式。例如 code file read outline：第一次读取某代码文件时返回 outline，第二次读取再给全文。这是 progressive disclosure 思想。

对 AutoDecision 的启发：

1. AutoRealize 读取 Excel/CSV/PDF/JSON 时，不需要所有 LLM 调用看到完整 preview。
2. 第一次给 LLM 看 table card + field stats +少量 preview。
3. 真需要某 sheet/某列/某约束原文时，再通过 QDI 脚本或 artifact retrieve 取。

### 5.2 CacheAligner 当前只是 detector

文档或旧架构图可能说 CacheAligner 会把动态内容从 system prompt 移到后面。但当前 `cache_aligner.py` 明确说明：它是 detector-only，不再修改 messages。它只检测 system prompt 中的 UUID、ISO 时间戳、JWT、hex hash 等动态内容，发 warning，避免破坏 cache-hot zone。

这体现了 Headroom 后期的一个重要反思：

**为了省 token 或提升 cache 命中而修改 system prompt prefix，很容易得不偿失。**

对 AutoRealize/MLEvolve：

1. 固定 system prompt、schema、action contract 要稳定且放最前。
2. 不要把 run_dir、当前时间、随机 ID、上一轮错误、脚本输出这类动态内容混入固定前缀。
3. 如果检测到动态内容进入稳定前缀，应记录 warning，而不是默默重写。

### 5.3 ContentRouter 是真正主力

`ContentRouter` 负责遍历 messages，把可压缩内容按类型交给对应 compressor。它不是粗暴压缩所有文本，而是先做大量保护判断：

| 保护/判断 | 原因 |
|---|---|
| frozen prefix 不动 | 保持 provider prompt cache 字节一致。 |
| system/developer 默认不压 | 这些是稳定指令和 cache-hot 字节。 |
| user 默认不压 | 用户原始意图优先，不应被压缩误解。 |
| cache_control block 不动 | 用户显式设置 cache breakpoint。 |
| recent code 不压 | 当前正在编辑/审查的代码必须精确。 |
| analysis intent 保护代码 | 如果用户在 debug/review/fix，代码体可能是核心证据。 |
| 小内容跳过 | 压缩开销和 marker 开销可能大于收益。 |
| 短错误输出保护 | traceback/error 文本是修复关键证据。 |
| 已压缩 CCR marker 不再压 | 防止 marker 被二次压缩，破坏取回。 |
| 压缩后不够小则放弃 | 避免“压缩反而更大”。 |

这是一种非常工程化的原则：

**不是所有 token 都值得省。要省的是大、旧、重复、结构化、低风险的 token。**

## 6. ContentRouter 的压缩路线

ContentRouter 按内容类型选择策略。典型策略如下：

| 内容类型 | 策略 | 保存什么 | 丢/折叠什么 |
|---|---|---|---|
| JSON array | SmartCrusher | schema、边界样本、异常、变化点、代表行、CCR marker | 重复行、低信息行、可由 schema 推断的重复键值 |
| 搜索结果 | SearchCompressor | 文件多样性、每文件首尾/高分匹配、错误关键行、少量上下文 | 同文件大量重复命中、低相关命中 |
| 构建/测试日志 | LogCompressor | error、fail、warning、stack trace、summary、首尾关键段 | 大量 INFO、重复 warning、成功噪声 |
| diff | DiffCompressor | 有语义变化的 hunk | lockfile、空白-only、巨大低价值上下文 hunk |
| 表格/CSV | Tabular/SmartCrusher 风格 | schema、列、统计、代表行 | 重复行和全量数据 |
| HTML | extractor | 正文内容 | 导航、广告、script/style、模板噪声 |
| 普通文本 | 可选 Kompress ML | 高信息 token、结构 marker | 低信息 prose，代价是额外延迟 |
| code | 默认基本 passthrough | 当前相关代码精确性 | 只有在明确安全时才 AST outline/压缩 |

### 6.1 两级 compression cache

ContentRouter 内部有一个 `CompressionCache`：

1. skip set：记录“这个内容压不动”，下次直接跳过。
2. result cache：记录“这个内容已经压缩过”，下次复用结果。

这能减少本地 CPU/ML 压缩开销，也保证同一内容在同一进程内压缩输出稳定。

对 AutoRealize：

1. 同一个文件/sheet 的 table card、field stats、LLM file cognition 结果应该有 content hash cache。
2. 同一 QDI 脚本输出如果由相同脚本和相同数据版本得到，可以缓存 artifact id 和可见切片。
3. MLEvolve 的同一测试日志/同一 diff/同一搜索结果也应缓存压缩结果，避免每轮重复压缩。

### 6.2 并行压缩

ContentRouter 对 cache-miss 的压缩候选用 `ThreadPoolExecutor` 并行处理。压缩是本地 CPU/IO 密集，适合并行，尤其 agent 一轮里可能带多个工具输出。

对 AutoDecision：

1. 文件画像已经可以并行，但 LLM file cognition 需要控制并发和 token 日志。
2. 规则生成 table cards/relations/field stats 完全可并行。
3. QDI 的单问题调查不适合并行 LLM，但脚本内可并行读取多个文件。

### 6.3 adaptive compression ratio

Headroom 会根据 context pressure 调整压缩强度。上下文越紧张，目标 ratio 越激进；上下文压力低时更保守。

对 AutoRealize：

1. 如果当前 LLM call 只需一个输出章节，不要给全局超详细 data context。
2. 如果模型 context 很大但 provider cache 未命中很贵，也不代表可以乱塞；未命中 token 仍然计费。
3. 可设置阶段预算：QDI planner、QDI answer、evaluation writer、sample builder、MLEvolve feedback 分别有独立 max context budget。

## 7. SmartCrusher：Headroom 最典型的结构化压缩

SmartCrusher 是 JSON array/tool output 压缩的核心，当前 Python 类是 Rust-backed PyO3 shim。它保留 Python public API，但实际压缩交给 Rust core。

### 7.1 它为什么特别适合 agent 工具输出

很多 agent 工具输出天然是数组：

1. search hits。
2. ripgrep lines。
3. API rows。
4. DB rows。
5. metric time series。
6. 文件列表。
7. 测试用例结果。
8. AutoRealize 的 table/sheet profile 列表。
9. MLEvolve 的搜索节点结果、候选方案评估结果。

数组里常见浪费：

1. 每行重复相同字段名。
2. 大量重复常量字段。
3. 绝大多数行模式相同。
4. LLM 通常只需要 schema、异常、统计、少量代表样本。

SmartCrusher 的解决方式：

1. 小数组直接不压。
2. 对 array-of-dicts 识别 schema 和重复结构。
3. 优先 lossless compaction，例如 `csv-schema` 格式，把重复 key 提出来。
4. 必要时 lossy row dropping，但保留首尾、异常、变化点、代表行。
5. 插入 CCR marker，允许取回被丢行。

### 7.2 保留策略

SmartCrusher 的保留逻辑不是“前 10 行”，而是组合策略：

| 保留对象 | 价值 |
|---|---|
| first fraction | 让模型看到 schema、开头格式、常规样例。 |
| last fraction | 保留近期/尾部状态，agent 日志尾部常有结论。 |
| error/anomaly rows | 错误、失败、异常值通常是任务关键。 |
| change points | 时间序列/指标突变比平稳段更重要。 |
| representative rows | 覆盖数据分布。 |
| constants factored out | 不让常量字段每行重复消耗 token。 |
| CCR sentinel | 告诉模型还有多少行被 offload，如何取回。 |

这和 AutoRealize 的表格画像高度相似：我们也不该把完整表塞给 LLM，而应该给：shape、字段统计、top values、数值统计、时间范围、少量样例、异常 warning、读取方式、关联证据。

## 8. SearchCompressor 与 LogCompressor

### 8.1 SearchCompressor

SearchCompressor 针对 grep/ripgrep 风格结果。它的价值在于：

1. 搜索结果经常有几十/几百条，同一文件重复多次。
2. 模型不需要每个命中，只需要知道哪些文件相关、代表命中在哪里、错误/关键字段在哪。
3. 它能按文件分组，限制每文件命中数量和总命中数量。
4. 能保留首尾、高分、错误关键字、上下文关键词命中。
5. 支持 CCR，把完整搜索结果存起来。

对 MLEvolve：

1. 每轮搜索节点如果把几十个文件全塞进去，会迅速吃满 prompt。
2. 应改成 search card：query、命中文件数量、top files、每文件 1-3 条代表命中、关键 line、遗漏数量、artifact id。
3. 如果后续要某文件更多内容，再读文件或 retrieve。

### 8.2 LogCompressor

LogCompressor 针对 pytest/npm/cargo/make/jest/generic log：

1. 保留 error/fail/warn。
2. 保留 stack trace，但限制数量和长度。
3. 保留 summary lines。
4. 对 warning 去重。
5. 去掉大量 INFO/debug/重复成功输出。
6. 超长日志用 CCR。

对 MLEvolve：

1. 测试通过日志应极短：通过了哪些测试、耗时、warning top-k。
2. 测试失败日志应保留完整 traceback 关键段、失败断言、输入输出差异、相关文件路径。
3. 不要把完整 pytest -vv 或训练日志塞给 feedback LLM。
4. 如果训练日志长，应折叠 epoch 中间段，只保留指标趋势、best/worst、异常。

## 9. ReadLifecycle：文件读取生命周期压缩

`ReadLifecycleManager` 处理 agent 文件读取输出。它的核心观察是：在长 agent 会话中，很多 Read 输出后来已经过期或被新 Read 覆盖。

它把 Read 分成三类：

| 状态 | 含义 | 处理 |
|---|---|---|
| fresh | 文件读取后没有被修改，也没有被更完整重读 | 保留 |
| stale | 文件读取后该文件被 edit/write | 可用 marker 替换，因为旧内容已经事实错误 |
| superseded | 同文件后来被重读，且后读覆盖前读范围 | 可用 marker 替换，因为旧内容冗余 |

并且它尊重 frozen prefix：如果 stale/superseded read 在 provider cached prefix 中，也不轻易替换，避免 cache bust。

对 AutoRealize/MLEvolve：

1. MLEvolve 搜索/读文件/改代码循环也会积累大量旧代码片段。
2. 当前正在编辑的代码、最新读到的代码不能压。
3. 已被修改前的旧 read 可以从 prompt 移除，只留“旧版本已过期，artifact id=...”。
4. 已经被更完整 read 覆盖的 partial read 可以折叠。
5. 这比“压缩代码体”安全得多。

## 10. CCR：Compress-Cache-Retrieve 可逆压缩闭环

CCR 是 Headroom 能激进压缩又不太怕丢信息的关键。

### 10.1 工作方式

1. Compressor 决定丢弃或折叠部分内容。
2. 原始内容写入本地 compression store，生成 hash。
3. 压缩文本里插入 marker，例如 `<<ccr:HASH ...>>` 或 `[N items compressed ... hash=...]`。
4. Proxy 检测到 marker 后，把 `headroom_retrieve` tool 注入请求。
5. 如果模型需要更多信息，调用 `headroom_retrieve(hash, query?)`。
6. `CCRResponseHandler` 拦截这个 tool call，从本地 store 取回原文或搜索过滤结果。
7. Proxy 自动继续 provider 调用，最终 response 对原 agent 透明。

### 10.2 它解决的问题

没有 CCR 时，压缩器只能非常保守，因为压错就丢数据。CCR 后可以：

1. 先给 10% 信息。
2. 如果模型不需要全文，节省 90%。
3. 如果模型需要全文，额外花一次 retrieval/continuation 的代价，但正确性不至于直接崩。

### 10.3 CCR 的成本

CCR 不是免费：

1. marker 自身有 token。
2. tool definition 和 system instruction 有 token。
3. 模型调用 retrieve 会增加一轮 latency 和输入输出 token。
4. 如果模型不会正确 retrieve，可能会基于压缩视图误判。
5. store TTL 过期会导致 hash miss。

因此 Headroom 的 Rust `pipeline.toml` 很强调保守阈值：不要为了小收益触发 CCR，因为 retrieval round-trip 本身有成本。

### 10.4 对 AutoRealize 的直接迁移

AutoRealize 不一定需要把 CCR 暴露成 LLM tool。更适合的版本是：

1. 所有大对象写入本地 artifact store：完整文件 preview、完整 sheet profile、完整 PDF 分段、完整 QDI 脚本输出、完整 probe result。
2. Prompt 中只放：短 table card + `artifact_id` + 可见切片 + 截断信息。
3. QDI 如果想看更多，不是自由调用工具菜单，而是生成只读 Python 脚本去重新计算或读取指定 artifact。
4. 对于非 QDI 阶段，writer/reviewer 不应该 retrieve 原始大对象；只能看 evidence pack。

这比给每个 LLM 阶段加一堆 retrieve tool 更符合 AutoRealize 的“减少 API 调用”和“规则优先”目标。

## 11. Provider cache 友好策略

Headroom 不只压 token，还刻意保护 provider prompt cache。

### 11.1 Frozen prefix

Provider cache 的本质是：相同模型、相同工具、相同 system、相同前缀消息能够复用 KV/cache。只要 prefix 某个字节变了，就可能 cache miss。

Headroom 因此把 request 分成：

1. cache-hot prefix：system、developer、tools、历史稳定消息。
2. live zone：当前最新 user message 或最新 tool_result，也就是模型马上要响应的动态内容。

默认不改 prefix，只改 live zone 中的大工具输出。

### 11.2 Rust live-zone byte-range surgery

`crates/headroom-core/src/transforms/live_zone.rs` 明确强调：不能把整个 JSON request 反序列化再序列化，因为 key order、空白、数字格式都可能变化，破坏 provider cache。

Rust live-zone 压缩用 byte-range surgery：

```text
out = body[..block_start] + replacement + body[block_end..]
```

也就是说，除了被压缩的 block，其余字节原样复制。这样才能保证 prefix/suffix 字节真的不变。

对 AutoDecision：

1. 如果我们自己构造 prompt，就应该 deterministic serialization：固定顺序、固定 key order、固定 section order、无随机 timestamp。
2. 如果我们要修改某个动态部分，不要重排稳定 prefix。
3. evidence pack 建议用 canonical JSON：`sort_keys=True`、紧凑 separators、稳定 ID。
4. 动态错误、脚本输出、defects 永远放最后。

### 11.3 Tool/schema 稳定化

Rust proxy 还有 cache stabilization：

1. 工具数组按工具名稳定排序，避免 Python set/dict 随机顺序导致 cache miss。
2. JSON schema keys 递归排序，避免不同 SDK 序列化顺序不同。
3. Anthropic cache_control 在安全时自动放置。
4. OpenAI `prompt_cache_key` 从 structural prefix 派生：model + system + tools，而不是 user/assistant 动态内容。

对 AutoRealize/MLEvolve：

1. 所有工具/action schema 的字段顺序稳定。
2. 所有 prompt block 顺序固定：system/rules/schema -> stable packs -> frozen sections -> dynamic tail。
3. 不要在 schema 中插入变化的 run_dir、任务名、时间戳。
4. QDI available_actions 可以动态变，但应放在后部动态块。
5. LLM usage 统计要区分 cache hit input、cache miss input、output，才能判断 provider-friendly 是否有效。

## 12. 输出 token reduction

`headroom/proxy/output_shaper.py` 说明：Headroom 也优化模型输出，但它不能直接看到“本来会输出什么”，所以只能通过 request shaping 影响输出。

### 12.1 Verbosity steering

它会在 system prompt 尾部追加稳定的简短指令，例如：

1. 不要 preamble/postamble。
2. 不要重述已有代码/文件内容/tool output。
3. 只给结论，除非用户问 why。
4. 使用 path/line 引用，而不是整段复制。

它放在 system prompt 尾部，并且文本稳定、带 sentinel，避免反复追加。

对 AutoDecision：

1. 内部 LLM 调用应明确“只输出 JSON，不要解释，不要重述输入 context”。
2. Writer 阶段可以长一些，但 reviewer、script repair、validator 应非常短。
3. Structured output schema 里不要给模型自由长篇解释空间；defects 要短、可执行。
4. 对 MLEvolve feedback，避免模型把完整日志、完整代码、完整思路重述一遍。

### 12.2 Effort routing

它根据最新消息结构判断：

| turn kind | 处理 |
|---|---|
| 新用户问题 | 保留 full effort/thinking。 |
| 工具成功后的机械续写 | 降低已存在的 effort 或 thinking budget。 |
| 工具错误后的续写 | 保留 full effort，因为需要 debug。 |

安全规则也很关键：

1. 不主动注入 provider 不支持的 effort 字段。
2. 不随意开关 thinking type。
3. 只降低已经存在且模型支持的 effort。

对 AutoDecision：

1. 模型配置里的 `thinking_mode`、`reasoning_effort` 应按阶段使用。
2. QDI script repair、sample validator、artifact sanity check 可以低 effort。
3. 任务定义、评估协议、复杂 QDI answer 可以中高 effort。
4. 不要每个小检查都 xhigh thinking。

## 13. Benchmarks 与真实节省边界

Headroom README 宣称常见 60-95% tokens saved，wiki benchmarks 给了更细的边界。

### 13.1 高收益场景

| 场景 | 典型收益原因 |
|---|---|
| JSON array 100-500 items | 重复 schema/key，SmartCrusher 能大幅压缩。 |
| build/test logs | 大量重复成功输出，LogCompressor 保留错误/summary。 |
| SRE incident debugging | 日志/metrics 工具输出巨大且重复。 |
| code search 100 results | 重复路径/匹配，SearchCompressor 可分组限额。 |
| 多工具长 agent session | 历史工具输出累积膨胀。 |

### 13.2 低收益场景

| 场景 | 原因 |
|---|---|
| 短 conversational turn | 没有大工具输出，压缩 overhead 不值得。 |
| 当前相关代码 | 默认保护，不压。 |
| 已经很紧凑的 grep 输出 | 有时压缩收益为 0。 |
| plain text 文档 | 可压但可能增加延迟，且语义风险更高。 |
| RAG plain text user messages | 默认不压 user message，保护用户意图。 |

### 13.3 真实生产 median 不一定夸张

`wiki/benchmarks.md` 提到 production telemetry 中 median compression 可能只有约 4.8%，因为大量请求本身很短。重工具会话可见 40-80%。这点非常关键：

**Headroom 的 85%+ 节省不是所有请求的平均真理，而是大工具输出/长 agent 会话中的目标上限。**

对 AutoDecision 的判断：

1. 配送任务 AutoRealize 这种大文件认知 + QDI + description 生成，是高收益场景。
2. MLEvolve 搜索/测试反馈循环也是高收益场景。
3. 普通短配置页问答不需要复杂压缩。

## 14. Agent 接入：Codex、Claude Code、OpenClaw、Hermes

### 14.1 wrap 模式

`headroom wrap claude|codex|cursor|aider|copilot|openclaw...` 的理念是：

1. 自动启动本地 proxy。
2. 修改 agent 的 provider base URL 或 MCP 配置。
3. 注入 retrieve tool。
4. 让 agent 原有工作流不感知压缩层。

Codex/Claude Code 场景中，价值来自代理所有 LLM 请求：

1. 文件读取输出压缩。
2. shell/test log 压缩。
3. 搜索结果压缩。
4. provider cache 稳定。
5. 输出 verbosity/effort shaping。

### 14.2 OpenClaw plugin

OpenClaw 插件把 Headroom 注册成 contextEngine，还可以把 provider gateway routing 指向 Headroom proxy。README 还明确对比了 `lossless-claw`：

| 项 | lossless-claw | Headroom |
|---|---|---|
| 压缩方法 | LLM summarization/DAG | 内容感知零 LLM 压缩 |
| 压缩成本 | 需要 LLM token | 本地压缩，零 LLM token |
| 取回 | grep/expand | `headroom_retrieve` |

这正好对应 AutoRealize 的核心诉求：少调用 LLM，把 deterministic compression 放前面。

### 14.3 Hermes plugin

Hermes 插件重点解决“marker 不可逆”的问题。没有 retrieve tool 时，模型看到 `<<ccr:abc123>>` 可能会误当文件路径去 cat，或者重新跑命令。插件直接提供 retrieve 能力，闭合 CCR。

对 AutoRealize：

如果我们在 prompt 里放 `artifact_id` 或 `ccr_id`，必须告诉当前阶段它能不能用、怎么用。否则 LLM 可能幻觉 artifact 内容。对于非 QDI 阶段，最好直接规定“不允许根据 artifact_id 猜测原文”。

## 15. Headroom 的安全边界和失败模式

### 15.1 fail open

Headroom 多数 compressor 遵循：失败就返回原文。

1. JSON parse 失败 -> passthrough。
2. AST parse 失败 -> 原文。
3. 压缩后更大 -> 原文。
4. optional dependency 缺失 -> passthrough + warning。
5. pipeline 连续失败 -> circuit breaker，一段时间内 passthrough。

这对 agent 系统很重要：压缩层不能成为任务失败的主因。

### 15.2 不压当前关键代码

代码压缩是危险项。Headroom 默认保护 recent code 和 analysis intent 下的所有代码。因为用户让 agent 看代码，通常就是要改/审/解释这段代码，压缩函数体会害死任务。

对 MLEvolve：

1. 当前节点正在修改的文件不能压缩。
2. 最新失败 traceback 指向的文件片段不能压缩。
3. 旧搜索结果、旧读文件、旧 diff 可以折叠。

### 15.3 不要盲目 CCR

CCR marker + retrieval tool 有成本。小内容、重要错误、短日志、关键代码不应压缩成 marker。

对 AutoRealize：

1. 不要把 description.md 草稿压成 artifact marker 给 reviewer。
2. evaluation reviewer 必须看到明确公式/缺陷，不应让它自己 retrieve。
3. QDI 可用 artifact/script 重新计算，但 writer/reviewer 应尽量只看裁剪好的 evidence pack。

## 16. 对 AutoRealize 的迁移设计

### 16.1 建立 AutoRealize Context Compiler

AutoRealize 应该内置一个类似 Headroom ContentRouter 的 context compiler，但对象不是任意 agent messages，而是 AutoRealize 已有的结构化认知。

建议生成以下稳定包：

| pack | 来源 | 进入哪些 LLM 调用 |
|---|---|---|
| `task_authority_pack` | 用户输入、已有 description.md、官方文档、冲突裁决 | 任务定义、评估、输出章节 |
| `table_cards` | CSV/Excel/JSON 表格化画像、字段统计、LLM file cognition 短认知 | QDI、sample builder、automl_context |
| `relation_cards` | 规则推断字段关系：one_to_many/many_to_many/shared_attribute 等 | QDI、任务定义、输出/约束 |
| `constraint_memory` | 说明文档和 QDI 发现的硬约束、防泄漏、非法解 | 评估协议、约束章节、automl_context |
| `qdi_question_records` | QDI 问题账本短记录 | QDI answer、tips、任务边界 |
| `evaluation_evidence_pack` | 权威评估要求、目标方向、约束、输出要求、QDI 评估结论 | 评估章节 writer/reviewer |
| `output_evidence_pack` | sample_submission、输出文件要求、字段来源、官方格式 | 输出章节、sample builder/validator |
| `data_access_minipack` | 非默认 CSV、多 sheet Excel、JSON 表格化、特殊 header 的读取方式 | sample builder、QDI script prompts |

关键原则：

1. 这些 pack 由已有认知和规则裁剪，不新增 LLM 总结调用。
2. 所有 pack canonical JSON 序列化，字段顺序稳定。
3. 不同阶段只取相关 pack。
4. 动态错误/defects/script output 放最后。
5. 每个 pack 有 token 估计和 hash，写入 token log。

### 16.2 表格画像对标 SmartCrusher

AutoRealize 的 CSV/Excel/JSON 表格解析应本地确定性生成：

```json
{
  "table_id": "成本/承运商1 承运商成本.xlsx::sheet1",
  "source_file": "成本/承运商1 承运商成本.xlsx",
  "sheet_name": "sheet1",
  "role": "承运商成本与计费规则",
  "shape": {"rows": 123, "columns": 8, "profiled_rows": 50000, "sampled": false},
  "reading_note": "多 sheet Excel，需 pandas.read_excel(path, sheet_name='sheet1')",
  "file_cognition": "LLM 单文件认知短文，200-300 字以内",
  "fields": [
    {
      "name": "订单号",
      "meaning": "订单唯一标识或订单分组键",
      "role": "id/key",
      "logical_type": "text",
      "row_count": 2104,
      "non_null_count": 2104,
      "null_ratio": 0,
      "unique_count": 2104,
      "top_values": []
    }
  ],
  "warnings": ["统计基于前 50000 行抽样"]
}
```

字段统计保留，但不要附带 raw preview/source_metadata/完整 probe_results。

### 16.3 Excel 多 sheet 处理

结合用户已明确的设计，Excel 应该：

1. 每个 sheet 至少读 header、shape、少量样例、字段统计。
2. sheet 数少于阈值时，每个 sheet 都做统计。
3. sheet 名明显有模式且表头高度相似时，可以聚合为 sheet group，但必须保留代表 sheet 和共享字段。
4. 每个 sheet 等价为一张 table card。
5. LLM file cognition 要能看到每个 sheet 的切片/字段统计，特别是开头说明文字 sheet，不能只看第一个 sheet。
6. 多 sheet Excel 的读取提示只在需要时写，例如 `pd.read_excel(path, sheet_name='...')`。

这比 Headroom 的通用 JSON compressor 更领域化，但思想一致：先给 schema/统计/代表样本，不给全量。

### 16.4 QDI 的 Headroom 化

QDI 当前优化方向可直接吸收 Headroom 思想：

1. 全局 compact context 类似 compressed tool output。
2. 当前问题是 live zone。
3. 当前脚本输出是 current visible output。
4. 历史脚本完整输出进入 artifact store，不再进 prompt。
5. 如果要旧结果，LLM 必须生成新脚本重新计算或读取 artifact。
6. 问题账本只保存短结构化记录，类似 compressed conversation state。

建议 QDI 每轮 prompt：

```text
固定前缀：QDI 角色、动作 schema、只读脚本规则、输出 JSON schema
稳定中段：table_cards, relation_cards, filename_sample_groups, authoritative_memory, constraint_memory
冻结账本：question_records，只含 question_id/status/short_answer/unresolved_reason
动态尾部：current_question, available_actions, remaining counts, current_script/error/current_visible_output
```

不要输入：

1. 完整 source_metadata。
2. raw preview 大段。
3. 完整 detailed_report。
4. 历史脚本完整输出。
5. 历史失败完整 traceback 超长段。
6. 和当前问题无关的 sample slices。

### 16.5 QDI 中的 CCR-like artifact store

建议实现轻量本地 artifact store：

| artifact 类型 | 内容 | prompt 中显示 |
|---|---|---|
| `file_profile_full` | 完整字段画像/preview/probe | table card + artifact id |
| `script_output_full` | QDI 脚本完整 stdout/stderr | 截断可见输出 + chars count + artifact id |
| `pdf_pages` | PDF 分页文本 | 页码范围 + 摘要式索引 + artifact id |
| `excel_sheet_preview` | sheet 前 N 行、header scan、merged cell 信息 | sheet card + artifact id |
| `submission_probe` | sample_submission probe | 列、shape、head + artifact id |

注意：这里说的“prompt 中显示”不是 LLM 总结，而是程序确定性裁剪出的可见文本和结构化信息。

### 16.6 evaluation_contract_reviewer 精简

Headroom 的核心提醒：不要让 reviewer 看全量历史。evaluation reviewer 应只看：

1. 固定评估合同 schema。
2. 冻结任务定义中和评估有关的部分。
3. `evaluation_evidence_pack`。
4. 上一版 evaluation contract。
5. 程序发现的 defects。
6. 上一轮 reviewer defects（动态尾部）。

不要看：

1. 完整 description.md。
2. 完整 data cognition。
3. 完整 QDI 报告。
4. 完整 agent_context_route。
5. 所有文件字段统计。

如果 review 失败，下一轮 writer 必须看到失败理由。第三轮按用户最新要求：**直接采用第三轮 LLM 生成的合同，不再让程序 fallback 成人类不可读的“未明确”占位。**

### 16.7 description 分章节生成

Headroom 的 live-zone 思想可以映射到 description：

1. 每次只生成一个章节或一组强相关章节。
2. 已通过的章节冻结，不反复重写全文。
3. 当前章节相关 evidence pack 是 live zone。
4. reviewer defects 放动态尾部。
5. 普通章节不做 LLM review，靠 prompt 约束。
6. 评估协议和 sample_submission 做强校验和有限修复。

这样能减少 token，也减少“全文重写导致前文变差”。

## 17. 对 MLEvolve 的迁移设计

### 17.1 不再重复 data preview

有 AutoRealize `automl_context` 时，MLEvolve 应直接把它作为稳定任务上下文，而不是重新生成 data preview。

建议：

1. `description.md`：给模型一直看的简洁任务说明。
2. `automl_context.md/json`：给模型的数据认知补充，包含表/sheet/字段/读取方式/relations/约束检查/评估公式。
3. MLEvolve prompt 中固定引用这两个上下文，避免每个节点重复塞完整数据预览。
4. 如果节点需要某表具体内容，由代码读取数据，不由 LLM 看全量 preview。

### 17.2 搜索结果压缩

MLEvolve 搜索节点输出应变成：

```json
{
  "query": "evaluation score",
  "files_affected": 12,
  "matches_total": 184,
  "matches_visible": 24,
  "by_file": [
    {"file": "src/eval.py", "matches": [{"line": 42, "text": "score = ..."}]}
  ],
  "omitted_matches": 160,
  "artifact_id": "search_..."
}
```

原则：保留文件多样性、关键错误/评分/提交相关命中；不要展开每个命中。

### 17.3 测试日志压缩

反馈 LLM 应看到：

1. 运行命令。
2. exit code。
3. 失败测试名称。
4. traceback 关键段。
5. assertion diff。
6. stdout/stderr tail。
7. summary。
8. artifact id。

不应看到：

1. 完整训练日志。
2. 全部 passed tests。
3. 大量重复 warning。
4. 长 epoch 每轮指标。

### 17.4 diff 压缩

候选节点之间传 diff 时：

1. 当前要 review 的核心源码 diff 保留。
2. lockfile、格式化、空白-only、生成文件 diff 折叠。
3. 大文件 diff 只保留 hunk header、函数名、核心改动、测试相关片段。
4. 对新增大文件，给 outline + 关键函数签名，不要全量粘贴。

### 17.5 代码 read lifecycle

MLEvolve 应记录：

1. 每个文件 read 的版本 hash。
2. 文件被 edit/write 后，旧 read 标记 stale。
3. 后续完整 read 覆盖旧 partial read 后，旧 partial 标记 superseded。
4. Prompt 只保留 fresh/current 代码片段。
5. stale/superseded 代码从 prompt 中移除或 marker 化。

### 17.6 节点级 provider cache

MLEvolve 的搜索/草稿/反馈/修复节点应固定 prompt 布局：

```text
system: 固定 agent 角色和规则
schema: 固定输出格式
stable task context: description.md + automl_context hash/compact version
stable code policy: 固定工程规则
node memory: 小而稳定的候选历史结构
current dynamic tail: 当前错误、当前 diff、当前搜索结果、当前问题
```

不要在前缀里放：

1. 当前时间。
2. run_dir。
3. 随机 node id。
4. 当前错误日志。
5. 最新搜索结果。

## 18. 是否应该直接接入 Headroom 代码

### 18.1 可以直接用 proxy 的场景

如果 AutoDecision 的 LLM provider 是 OpenAI/Anthropic/Gemini/OpenAI-compatible，并且请求格式能被 Headroom proxy 正确识别，可以考虑试验：

1. 把 AutoRealize/MLEvolve 的 provider base URL 指向 Headroom proxy。
2. 开启 stats，观察真实 tokens before/after。
3. 先只对 MLEvolve 运行反馈/search/log 类请求启用。
4. 不要一开始就让任务定义/评估协议这类高精度结构化输出走激进压缩。

优点：快。

风险：

1. 我们的 structured output、tool calling、DeepSeek/OpenAI-compatible 细节可能和 Headroom handler 不完全兼容。
2. CCR tool injection 可能改变工具列表，影响结构化输出。
3. 对 description/evaluation writer 这种非工具输出场景收益有限。
4. 如果压缩 system/user prompt 可能影响任务质量，所以必须保守配置。

### 18.2 更推荐先迁移思想

对 AutoDecision 更稳的路线是先做内部 Headroom-like 机制：

1. deterministic evidence pack compiler。
2. artifact store / CCR marker。
3. search/log/diff/test-output compressor。
4. token ledger。
5. prompt cache-friendly layout。
6. section-level writer/reviewer。

这些不依赖外部 proxy，不会引入额外 provider 兼容风险。

### 18.3 可复用代码的边界

Headroom 是 Apache 2.0，技术上可借鉴或 vendor。但注意：

1. Rust core/PyO3 build 集成复杂。
2. Headroom 通用 compressor 面向 agent messages，不直接理解 AutoRealize 的 task protocol。
3. 我们的数据表画像/字段语义/评估协议需要领域规则，不适合直接用通用 compressor 替代。
4. 最值得复用的是 SearchCompressor/LogCompressor/DiffCompressor 思想，甚至可以先实现简化 Python 版。

## 19. AutoDecision 分阶段落地路线图

### Phase 0：观测先行

目标：知道 token 花在哪里。

任务：

1. AutoRealize 和 MLEvolve 所有 LLM call 记录 input/output/cache_hit/cache_miss tokens。
2. 记录每个 prompt part 的 token：system、schema、stable_pack、files、relations、question_records、script_output、defects。
3. 记录每次调用的 run stage、model、max_tokens、finish_reason。
4. 记录 context hash，判断稳定块是否真的稳定。

验收：能回答“QDI 为什么 1M input”、“evaluation reviewer 哪个 part 最大”、“MLEvolve 搜索节点为什么没出”。

### Phase 1：Context compiler

目标：让 LLM 不再看到完整大报告。

任务：

1. QDI files 改为 table cards。
2. relations 改为字段级 relation cards。
3. filename groups 只保留模板/数量/代表文件/共享结构。
4. authoritative_memory 和 constraint_memory 独立承载重要事实。
5. field stats 保留标准字段，但去掉 raw metadata。

验收：QDI planner 单次输入降到 2-5 万 tokens 左右，answer/judge 控制在 3-8 万 tokens 级别，而不是近百万。

### Phase 2：Artifact store / CCR-like retrieval

目标：完整信息不丢，但不默认进入 prompt。

任务：

1. 存完整 file profile、script output、preview、probe result。
2. Prompt 放 artifact id、可见切片、截断标记。
3. QDI 脚本可重新读取数据或 artifact。
4. 历史脚本输出不进入后续 prompt。

验收：超长脚本输出只给 current_visible_output；后续 prompt 不携带历史完整输出。

### Phase 3：QDI 单问题闭环

目标：用 BFS 问题队列替代全局批量调查。

任务：

1. 初始 planner 只生成问题队列。
2. 每题 answer/request_script/give_up/add_followup/mark_duplicate/refine。
3. 每题有限脚本次数，最多 3 层 BFS。
4. 问题账本始终可见但短。
5. 脚本修复只看当前问题、脚本、错误、相关读取提示。

验收：不保存旧脚本完整输出到后续 prompt；重复问题可 mark_duplicate。

### Phase 4：Description/evaluation 分章节生成

目标：避免整篇 description 反复重写和 reviewer 大上下文。

任务：

1. 任务概述+任务定义一次生成。
2. 评估协议 writer + reviewer，失败理由返回，最多修 3 轮，第三轮强制采用。
3. 输出/提交格式生成 sample spec。
4. sample builder/validator 有限修复，不阻断后续章节。
5. 普通章节只 prompt 约束，不额外 review。

验收：不再出现评估协议全是“未明确”的程序 fallback；review 失败理由进入下一轮 writer。

### Phase 5：MLEvolve feedback compression

目标：搜索/日志/diff/测试反馈不再爆上下文。

任务：

1. 测试日志压缩器。
2. 搜索结果压缩器。
3. diff 压缩器。
4. code read lifecycle。
5. node prompt cache-friendly layout。

验收：失败反馈 prompt 中 traceback 保真但日志总量显著下降；搜索结果不展开全部命中。

## 20. AutoRealize/MLEvolve 的具体 prompt/cache 规则

建议统一以下 prompt 结构：

```text
[固定 system]
- agent role
- 不可违反的输出格式
- 权威优先级
- 不要重述上下文

[固定 schema]
- JSON schema/action schema
- 字段说明

[稳定 facts]
- task_authority_pack
- compact table/relation cards
- frozen previous sections
- question_records

[当前任务]
- current section/question/node
- available actions
- budgets/remaining attempts

[动态尾部]
- script output/error
- reviewer defects
- validation failure
- current diff/log/search result
```

稳定性要求：

1. 固定 block 字节不随任务运行变化。
2. 稳定 facts 尽量按固定 key order 序列化。
3. 当前任务和动态尾部放最后。
4. 大对象只进 artifact，不进 stable facts。
5. 每个 block 单独统计 token。

## 21. 对当前 AutoRealize 痛点的直接回答

### 21.1 为什么 QDI 会接近 1M input

典型原因不是 QDI planner/answer 自身 prompt 长，而是 stable context 里混入了：

1. 完整 files metadata。
2. raw preview。
3. 完整 excel_sheet_profiles。
4. 完整 probe_results。
5. 完整 detailed_report。
6. 历史脚本输出。
7. 说明文档原文和文件认知重复。
8. 关系/文件组展开太细。

Headroom 的对应解决方案是：tool output/card 化 + artifact marker + live-zone only。

### 21.2 evaluation_contract_reviewer 为什么也会大

如果 reviewer 看完整 description draft、完整 data cognition、完整 agent_context_route，就等于每次检查都重新读全世界。应改成只看 evaluation_evidence_pack、冻结任务定义、上一版 contract、defects。

### 21.3 “不允许瞎扯淡”为什么会导致未明确

根因不是“不允许瞎扯淡”本身，而是 repair/review 流程没有把缺陷理由有效返回 writer，或者 fallback 用程序占位覆盖了人类可读合同。正确策略：

1. 证据不足时允许 LLM 基于任务目标提出明确可执行评估协议，但必须标注依据和假设。
2. reviewer 发现不明确，必须把具体 defects 返回 writer。
3. 最多修 3 轮。
4. 第 3 轮不再程序 fallback 成“未明确”，直接采用 LLM 最后一版，并在报告里记录 review 未完全通过。

这和 Headroom 的 fail-open 思路一致：不要让优化层产生更糟糕的人类不可用输出。

## 22. 风险与注意事项

### 22.1 压缩不是总结

用户已经明确反感“摘要”一词被滥用。工程上必须区分：

| 类型 | 是否 LLM call | 示例 |
|---|---|---|
| 规则裁剪 | 否 | top_values 前 6 个、shape、字段统计、截断 stdout |
| 结构化压缩 | 否 | search/log/diff compressor、table card |
| LLM file cognition | 是 | 单文件认知短文、字段含义说明 |
| LLM answer | 是 | QDI 对当前问题的回答 |

Prompt 和报告中要明确数据来源，不能把规则裁剪叫成 LLM 总结。

### 22.2 不要压掉权威事实

说明文档中的硬约束、官方评估、输出要求、用户明确要求不能只放在 `file_cognition`。必须进入 `authoritative_memory` 或 `constraint_memory`。

### 22.3 不要让 artifact marker 变成幻觉源

如果 LLM 看到 `artifact_id` 但不能读取，就必须明确：不可根据 artifact id 猜测内容。

### 22.4 不要为 cache 命中牺牲正确性

当前错误、当前脚本输出、当前失败日志即使导致 cache miss，也必须放在动态尾部。cache 优化是性能手段，不是任务事实优先级。

### 22.5 输出 max_tokens 不是根治方案

把 max_tokens 从 16k 调到 65k 可以减少截断，但不能解决输入膨胀。Headroom 的核心是输入裁剪和可逆取回；输出长度只能作为兜底。

## 23. 建议的验收指标

### AutoRealize

| 指标 | 目标 |
|---|---|
| QDI planner input | 普通任务 2-5 万 tokens，复杂多文件任务不超过 10 万 |
| QDI answer/judge input | 3-8 万 tokens，除非当前脚本输出极长 |
| QDI repair input | 5 千-2 万 tokens |
| evaluation reviewer input | 不携带完整 data cognition/draft，目标 1-3 万 tokens |
| description 生成 | 不再全篇多轮重写；章节冻结 |
| 评估协议 | 不允许最终全“未明确”；第三轮 LLM 合同可强制采用 |
| cache miss ratio | 稳定前缀大部分命中；动态尾部占未命中主体 |
| artifact usage | 历史脚本完整输出不进后续 prompt |

### MLEvolve

| 指标 | 目标 |
|---|---|
| 数据预览 | 有 AutoRealize context 时不重复生成 |
| 测试日志压缩 | 失败保真，成功日志折叠，token 降 70%+ |
| 搜索结果压缩 | 大量命中时 token 降 50-90% |
| diff 压缩 | 生成文件/lockfile/空白-only 不进入 feedback prompt |
| code read lifecycle | stale/superseded read 不持续占 prompt |
| token log | 与 AutoRealize 一样记录 per-call/per-part/cache split |

## 24. 最推荐的落地顺序

如果只选最有收益的 5 件事，建议按这个顺序：

1. **per-part token ledger**：先知道钱烧在哪。
2. **QDI table cards + relation cards**：立刻砍掉 files metadata/raw preview 膨胀。
3. **artifact store + current_visible_output**：防止脚本输出和文件画像重复进入 prompt。
4. **evaluation reviewer evidence-only + defects repair**：解决评估协议“未明确”和大输入问题。
5. **MLEvolve log/search/diff compression**：减少搜索/反馈循环成本。

## 25. 结论

Headroom 的成功不来自单一算法，而来自一组非常一致的工程原则：

1. **规则/结构优先，LLM 最后**。
2. **压缩工具输出，而不是压缩用户意图**。
3. **保护最新代码、错误和权威事实**。
4. **大对象本地保存，prompt 只给可见切片和取回线索**。
5. **固定前缀稳定，动态尾部后置**。
6. **压缩失败就 passthrough，不让优化层破坏任务**。
7. **所有阶段可观测，知道每个 prompt part 花了多少 token**。

迁移到 AutoDecision 时，我们不应该把 Headroom 当作“神奇外置省钱代理”一键接上就完事。更稳、更贴合业务的做法是把它的思想内化到 AutoRealize 和 MLEvolve：

- AutoRealize 负责把数据认知变成稳定、短、小而全的任务协议和 `automl_context`。
- QDI 只围绕当前问题使用可见证据和只读脚本，不再背全量历史。
- Description/evaluation 生成按章节和 evidence pack 工作，不再全文反复修。
- MLEvolve 消费 AutoRealize context，压缩搜索、日志、diff 和旧代码读取。
- 全系统记录 token ledger 和 cache split，用数据证明优化是否真的省钱。

这套方向比单纯调大 `max_tokens` 或压缩 prompt 文案更根本，也更接近 Headroom 对 Codex/Claude Code 节省 token 的真正原因。
