# DESIGN 08：逐项隔离、快照与原生请求桥

## 已确认的原有单点

原 forced-source 补丁捕获全部 TransportError，既漏掉 transcript 分页
及最后 source 重查，也把认证/超时误当成删除。引用集中到整批最后
提交，pool.future.result() 任一异常会停止 phase2，新 hook 到达一律
禁止发布，个别 notes 与 GC 错误也可以让已成功的操作显示为失败。

扫描现移至 scan.py：同一原生 API 的有效行继续处理，分页之后失败
保留之前的结果；on_error 回调标记覆盖不足。缺失来源确认通知完成，
未知/不完整来源不记录成功 watermark。陈旧 Stop/SessionEnd 通知不
应把来源永久当成当前活跃来源；仅近期 Start/TurnStarted 与活动状态
参与当前来源排除。

collect_citations 的局部错误粒度为已完成 assistant step；正常引用
仍在同一来源的小事务中幂等计数。坏时间/未来时间不续期，且不把该
来源的扫描标为完整。异常内容不写日志，Issues 只有分类计数与最多
十个来源 hash 示例。

## 安全的部分进展

ScanResult.complete=false 或有尚未同步的新通知时，selected(...,
preserve=True) 保留之前 selected=1 的来源，即使它们按通常 TTL
已经到期。只把剩余容量用于新来源；若用户刚调低上限，不因坏扫描
移走旧来源。正常完整同步仍执行原版排序/保留策略。

phase2.removes_sources 决定是否需要末端通知门禁。没有移除来源的
合并可发布，新引用下次补记；物理 prune 在成功阶段之后且同步完整
时运行。空提取若会删除旧来源，也先通过同一完整性条件，否则只给
该任务重试，不阻挡其他来源生成。

来源在读取后被删除不会再被检查，因为输入已经是完整内存快照；这
保证模型工作不依赖历史文件持续存在。它不是用户忘记记忆的事务，
也不承诺实时捕获会话变化。读取中发现变更则放弃该次来源，稍后重试。

## 文件与服务清理

extensions 的 UTF-8/大小/读取/链接异常按文件或目录记录；不跟随
链接。该路径有上次成功副本则保留其证据，不能把读取故障变成删除
diff；其他 notes 正常参与。本轮所有文件复制到暂存后模型只访问
暂存，原 note 后来变化留给下一批。

staging/旧 generation 无法删除只报告有限 warning，不让已发布
结果回退成失败。坏实例登记文件被跳过，自有 helper 清理的并发
错误不丢弃已捕获的输入。DB、受管 root、发布指针/manifest、owner
不可信仍属于全局失败，不猜测目录和数据。

queue 通知只确认成功同步或明确缺失的来源，坏来源留待下次。相同
遗留队列不会在一次 --drain 中重复四遍；有新事件才继续。全局失败
保留原退避；旧 worker 版本的退避不拦住刚升级修复的 worker。

## 原生模型实现

上游 be7d5f5fea7800778e4660cd5f36780ba783bddd 中实际依赖的 35 个
源码文件位于 vendor/kimi-requester/human，逐文件 hash 清单位于
files.json。build-model.mjs 将它们与锁定的 SDK 打包到 model.mjs。
包中保留源文件、MIT 许可证及实际打入 bundle 的依赖许可证。

Python Model 解析 Kimi 当前默认配置与凭据，之后通过有界 stdin/stdout
调用 Kimi __plugin_run_node，进程本身只执行低层 requester。依然不
产生宿主 session、不自动加载 MCP、项目工具和 Memory hooks。

传递配置的 capability/always_thinking、reasoning_key、effort/keep、
上下文和输出上限。Chat 的思考字段、Responses encrypted content、
Anthropic signed thinking 和 tool outputs 由上游格式代码回放。
_native_message 只存于单次合并的内存；extraction 最终文本来自
原生 extractText，不包括 think part。无法完成/只有思考/输出超限
仍是错误，不强行生成空摘要或从中猜一个 JSON。

提取的两个字符串仍由本项目最终验证。Chat/Responses 使用 json_object，
Anthropic 使用原生要求的 json_schema。没有模型能力或 schema 支持
保证时也不能忽略输出验证。只有完整 JSON 围栏/BOM 可移除。

模型请求 SDK 重试关闭；认证 401 仍只刷新一次。网络只允许声明的
端点 origin、不跟随重定向；loopback 直接访问，远端继承 HTTP(S)
代理。原生完整应用的其他代理/专用服务配置不在本桥的等价承诺中。
请求、流字节、累计输出及返回管道都有上限/超时，stderr 不作为
用户诊断转发；SDK 的 logLevel 明确关闭，不能因继承用户的 debug
环境变量把请求内容打印到私有返回管道。原始输出与思考不持久化，也不把“推理通道里有 JSON”
当作此次用户报错的既定事实。

## 验证

每个读取阶段注入缺失/损坏/超时语义；在提取与合并期间关闭、归档、
删除来源并断言没有重新访问原会话；同时让一个模型输出错误、一个
成功并验证成功者发布。还覆盖扫描上限/第二页失败、引用时间异常、
坏 notes、发布后清理失败、重试和去重状态、公开 1.0.0 数据样例。

native requester 测试使用真实 Kimi 运行桥与本地 SSE provider，
覆盖三协议 JSON、工具回传、thinking 仅在思考、签名/加密思考、401、
429、输出上限、重定向。六平台还执行 frozen worker 的三协议端到端
提取/合并，同时故意加入一个坏来源和一个已删除通知。
