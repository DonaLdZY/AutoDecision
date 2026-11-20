# AutoReport 统一交付 · v0.3.5-local

Decision Studio 0.2.5，AutoReport 0.1.1。报告正文、交付说明和机器调用合同统一由 AutoReport 生成。主界面从“算法模型包 → 已有研发成果 → 生成报告与交付包”启动既有报告重跑接口；新任务启用报告阶段后自动走同一链路。

Gateway 先核对选定实现和模型、创建独立交付副本。AutoReport 在原方法分析请求中生成 schema、用途、输入输出、依赖、限制和待核对项，完成正文审查后写 delivery_contract.json / DELIVERY.md。Gateway 验证来源回执、模型身份和报告hash，形成新交付修订；发布表单自动预填。需要人工核对的内容继续保留。

重跑报告不会重新搜索或训练，源工作区、旧修订和旧已发布包保留。报告失败、源码变化或文档身份不一致时不能采用旧文件冒充新结果。最终包携带 REPORT.md、report_provenance.json、真实交付试算记录和原冻结合同。

合同格式 autodecision.delivery.v2；已发布能力包仍为 autodecision.capability v1。旧静态兼容接口保留；主界面以 report_ready 区分报告材料和单纯结构检查。DataFrame建议可登记为包默认转换；首次项目输入绑定仍须发布者明确登记。

本轮硫酸铝历史任务真实 AutoReport 使用3次原有请求完成；前端预填、发布1.0.1和项目真实输入推理通过。冻结模型和搜索日志hash不变；模型质量仍未跑赢已记录的基线，报告与发布完成不代表业务验收。

详细操作见 [Decision Studio README](../frontend/decision-studio/README.md)。完整版本上下文及真实证据见工作区 AutoDecision_doc/项目全量上下文/v1.8.6_20261019。
