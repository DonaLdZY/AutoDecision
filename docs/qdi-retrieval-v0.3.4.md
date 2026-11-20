# QDI 取回与操作额度：v0.3.4-local

本版把“调查动作次数”和“已有证据取回次数”拆开：

- `request_script`、`request_checks`、`refine_current_question` 消耗调查动作槽；脚本/检查还消耗脚本额度。无效的检查请求也会扣一次脚本动作额度，避免反复失败绕过上限。
- `request_context`、`search_document`、`read_document_chunks`、`read_qdi_artifact_excerpt` 不消耗调查动作槽，也不消耗脚本额度；它们分别消耗有限的 context、documents、artifact 取回额度。
- 取回仍然需要一次结构化模型决策，仍有 Provider 请求和输入/输出 token 成本；“不占调查槽”不等于免费。
- 调查槽只剩一个时，不能再请求新脚本或改写问题，但可以使用仍有余额的取回动作，然后回答或放弃。

动态提示词现在显式提供：

- `investigation_action_budget`：调查槽已用、剩余和上限；
- `decision_budget`：当前问题的模型决策序号、剩余决策和上限；
- `script_budget`：每题/全局脚本余额、repair 上限和结果硬上限；
- `retrieval_budget`：context、documents、artifact 三类取回余额；
- `record.budget_usage`：问题完成后的实际使用统计。

同时，完整脚本结果、工作记忆、问答、动作历史和字段 profile 保存为本地 artifact；提示词只使用有界、可回读的视图。需要完整内容时，模型可用已暴露的 artifact 引用和 `json_path`/`offset` 分段回读。64 MiB 结构化脚本结果上限超出时明确失败，不把残缺 JSON 当成功。

验证状态：

- AutoRealize 全量：**480 passed、20 skipped**；
- 本地 QDI 合成链路：脚本 → artifact 尾部取回 → context 取回 → profile 取回 → 文档检索/读取 → 最终回答，7 次模型决策、2 个调查槽、1 次脚本、1 次 context、2 次文档、2 次 artifact 取回，**通过**；
- 本版没有付费 Provider A/B，不宣称缓存命中率或线上业务质量已改善。

完整设计、配置默认值、兼容性和审计文件见：[项目全量上下文 v1.3.3](../../AutoDecision_doc/项目全量上下文/v1.3.3_20261015/AutoDecision_QDI取回完整性与预算上下文_v1.3.3.md)。
