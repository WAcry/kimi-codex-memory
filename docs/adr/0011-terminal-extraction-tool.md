# ADR 0011：以单一结果工具交付提取结果

状态：接受。来源：用户要求用 Tool Schema 明确限定结果结构，兼容性
优先；不要求所有模型/网关都支持严格采样或强制调用。授权实施、推送
并发布新的补丁版本。

## 单一结果通道

Phase 1 只提供 submit_memory_extraction，一个没有外部副作用的终止
结果工具。参数仍为 Codex v2 的 rollout_summary、rollout_slug 两个
必填字符串，additionalProperties=false。明确的任务与字段描述解释
Markdown 历史、slug、空结果和只提交一次。

保留提取 prompt 主体，只修改结果交付要求。有效调用完成本次提取，
本地校验、脱敏和存储后结束；不调用 shell，不执行额外读取，不把
工具结果回传给模型再让其回答一句完成，不启动完整 agent。

收集完整流并通过原生完成状态验证后，只解析这个工具的完整参数。
普通 text 与 reasoning 都不能替代它，多个调用、未知工具、缺字段、
类型错误、额外/重复字段、非法 Unicode 或非完整 JSON 均失败。
正常的其他会话继续生成；这次任务沿用原有有界重试与退避，不新增
即时纠错对话、参数探测请求或从正文猜测 JSON 的后备路径。

## 兼容优先的请求策略

默认继承 Kimi 的工具编码与 thinking 设置，使用 auto，只声明一个
结果工具并明确要求调用。模型支持 Tool 不代表它支持 required 或
strict，第三方网关更不能根据模型名字被当成官方接口。

唯一已确认的自动增强边界是直连标准 HTTPS api.openai.com 的
Chat/Responses：为提取工具传 strict=true、tool_choice=required、
parallel_tool_calls=false。不根据别名猜供应商，不对 Kimi/Claude
或第三方网关强制同一参数，不关闭用户 thinking。其他接口按普通
auto 与 schema 描述运行，本地仍执行完全相同的结构验证。

已有 json_mode 配置继续接受，供原有通用 Model 请求使用；提取不再
请求正文 JSON 格式，因此该开关不决定提取结果通道。不增加新的用户
参数、模型白名单、网络能力探测或无限退避/降级组合。

## 与 Codex 和公开用户数据的关系

Codex 参考基线 Phase 1 实际使用 output_schema + strict，而不是
结果 Tool。我们复用的是它的字段结构和记忆内容规则，明确承认跨
供应商的交付通道适配。vendor/codex 原文不修改；执行模板只做上述
最小交付改动。

合并工具、notes 工具入口、reader/hook、引用、文件名、DB schema 和
正式 v1 数据样例不变。新版本替换安装中的旧程序，但不删除旧 Release
或旧用户数据。既有成功来源不强制重新提取；先前失败任务按已有
requester 版本升级规则获得正常重试机会。
