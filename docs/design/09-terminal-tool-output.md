# DESIGN 09：终止式结果 Tool 与跨协议验证

## 实现

extraction_output.py 是结果函数的唯一 Python 定义：名称、tool
description、JSON Schema 和参数验证器。worker.extract_one 仅提供
该工具并指定 output_tool，不再设置 json_mode=True，也不读取回答
正文。两字段语义、空结果检查、字节上限和 owner/source-version
存储条件不变。Model 输入预算现在也计入工具定义。

output_tool 是内部请求契约，不是开放给用户的工具管理开关。
requester.py 验证恰好声明一个匹配工具、没有冲突的 response_format，
再为官方 OpenAI origin 选择 strict/required 增强，其他情况用 auto。
bridge/model.ts 使用原生 requester 的 convertTool/extraParams
扩展点把参数放到正确层级；vendor/kimi-requester 保持原字节/hash。

| 协议 | 默认工具描述/调用结果 | 默认选择 |
| --- | --- | --- |
| Chat | tools[].function.parameters / tool_calls[].function.arguments | auto |
| Responses | tools[].parameters / function_call.arguments | auto，store=false |
| Anthropic | tools[].input_schema / tool_use.input（原生统一成 arguments） | {type:auto} |

官方 OpenAI 增强在最终 HTTP 请求中验证：Chat 的 strict 在 function
内，Responses 在工具项上；parallel_tool_calls=false，required
确保有工具调用。只在标准 https/443 api.openai.com origin 启用，
api.openai.com.evil.test、网关 URL 路径中的域名和模型名称均不能触发。
Anthropic 和 Kimi 保持原生 auto，避免 forced choice 与 thinking
的已知限制；strict 支持不明不是不能使用结果工具的理由。

原生工具调用参数仍需正常 JSON 解码。这不同于在自由文本中找括号、
去围栏或从推理中提取答案。允许与有效 tool call 同时出现的普通
说明，但不会存储它；如果只有正文 JSON，失败而不回退。

## 不变的故障边界

流截断、缺少最终完成事件、超时、纯推理、拒绝等先被原生请求完成
检查拒绝。只有完整成功响应进入结果校验。即使 arguments 看起来
已经完整，也不能绕过 truncated/incomplete/missing finish。

结构错误仅失败该来源，保留上次摘要；走现有最多三次任务尝试、
退避、配额与局部隔离。没有新增立即追问或第二轮无意义确认。
JSON/参数正文和 reasoning 不进入持久诊断；错误仅记录受控分类。

## 官方依据（实现时核对）

- OpenAI function calling：https://developers.openai.com/api/docs/guides/function-calling
  tool_choice 与 strict 独立；严格 schema 要求必填字段与
  additionalProperties=false；并行关闭可限制为至多一次。
- Kimi tool choice：https://platform.kimi.ai/docs/guide/use-tool-choice
  缺省为 auto，指定函数与 thinking 存在兼容限制。
- Claude tools：https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools
  部分 thinking 模式/模型不接受 any/tool，auto 可用。
- Codex 5c5308fc 的 memories/write/src/phase1.rs:310–317 与
  phase1_output.rs:73–80：严格输出 schema 的双字符串契约。

这些不是运行时查询或能力注册表。测试采用本地服务，不声称对所有
真实供应商或用户网关做过验证。接口将来变化时通过插件补丁适配。

## 测试

test_tool_submission 覆盖工具名、调用数量、字段类型、重复键、非法
常量、Unicode、正文/推理隔离、一次请求即完成，以及同批故障隔离。
test_native_submission 通过真实 Kimi 底层 requester 连接本地 SSE
服务验证三协议实际 wire，保留 thinking，关闭输出 JSON 要求；工具
参数被切成多个 delta，完整流后再验证。还模拟 missing finish、
截断、未知工具、多调用、正文 JSON、无效参数，确保不误写。

官方 strict 路径用已单测的 origin 策略与本地传输替身验证最终请求
字段，不访问官方付费模型；普通网关即使使用 GPT 类模型名也仍 auto。
frozen worker 的三协议端到端同样检查首个请求只提供结果 Tool、没有
response_format/output_config，并保持一次提取＋现有合并调用数。
