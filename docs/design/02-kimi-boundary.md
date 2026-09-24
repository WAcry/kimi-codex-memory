# DESIGN 02：Kimi 接入契约

## 当前兼容基线

源码基线为 Kimi `a1e4c13d411f75bd327e2c33077daff42ee63582`，产品版本 `2.1.0`。
原生二进制集成测试另外核对其报告的产品版本；产品版本相同并不证明构建 commit
完全相同。实际接口和响应仍需验证。

产品版本只用于诊断，不用白名单阻止新版本。新增无关字段可以保留／忽略；
未知消息类型、来源、完成状态或缺失必需分页信息则不能被当成正常空数据。

## 使用的只读 API

连接过程读取 `/api/v1/meta` 和 `/openapi.json`。业务读取使用 session 列表、
单 session 元数据、主 agent 的 transcript 页面。不调用 `/messages` 或
`/snapshot`，以避免为历史读取恢复运行整套旧会话。

分页从最新页向旧页前进，按原生顺序恢复完整历史。全局 entities 在分页期间
必须一致，最后再核对来源更新时间和 busy 状态。达到 page/session/byte 上限
表示不完整，不是“成功得到前 N 条”。

第一版使用主 agent 视图；子 agent 返回主会话的内容作为其他-agent 证据，
不递归抓取所有子 agent 的私有日志。附件按元数据与占位信息处理。

## 实例发现中已经验证的陷阱

原生实例目录的 `server_id` 和 `/meta.server_id` 是**分别生成**的 ULID。
它们不能直接比较。原生真实二进制测试最初发现这一点，已有回归测试。

实例目录在 listen 之前写入，因此候选端口暂时可能仍属于较早实例。连接时
核对注册进程仍存活、注册项未变化、产品版本相符，且 meta 的启动时间不早于
当前注册。之后记录 API 的实际身份。不要把能响应 HTTP 的任意端口当成目标。

辅助实例仅绑定 loopback，使用现有 home token；拒绝 HTTP 重定向，避免把凭据
带往其他目的地。token 每次请求重新读取，401 允许一次重新读取后的重试。
不改变 token 权限、不主动 rotation、不打印启动横幅里的 token。

借用实例不赋予关闭权限。自有实例通过实际 Popen 句柄管理；读取批次完成即
关闭，不保持整个模型生成期间的服务器。不同端口并不隔离 home 内索引、认证
和实例发现的共享行为，不能声称辅助服务没有任何副作用。
自有 Kimi 子进程显式设置 KIMI_CODE_NO_AUTO_UPDATE=1；不修改用户自己的环境
或升级设置。独立安装从 PATH 解析；Windows npm shim 转成 node + 实际入口，
避免将用户参数拼接进 cmd.exe。

## hooks 与注入

当前 SessionStart hook 的 stdout 不进入模型。实现通过 SessionStart 重置
本地注入状态，在 UserPromptSubmit 注入完整规则与摘要。插件 system prompt
保存稳定规则，并指明读取功能不依赖后台健康状态。

SessionStart/PostCompact 只触发重新注入标记；PostCompact 的输出也不会直接
进入下一模型步骤。一次 turn 内自动压缩后，稳定系统规则要求 agent 在需要
历史时读取本地摘要；下一次用户输入再自动补回。不声称与 Codex 的上下文优先级
和生命周期逐事件完全一致。

hook 通知仅保存 event、session ID 和时间。UserPromptSubmit 的大正文、普通
assistant 输出、图片字节都不写第二份。hook 内部设置 INTERNAL 标记跳过
我们自己的辅助环境，避免递归唤醒。

## 引用与来源身份

输出格式保留 `<oai-mem-citation>`、`citation_entries` 和 `rollout_ids`。
IDs 接受 Kimi 的原始 session 标识，不要求 UUID。程序仅解析最后一个完整的
非代码围栏引用块，且只解析 completed step 的 assistant 文本。

原生 cold transcript 的 stepId 是显示序号，不是日志中的完成事件 UUID。
第一版使用原 triggerPromptId、完成时间、step ordinal、回答内容 hash 组合
幂等键，排除包含它的 session ID，防止 fork 拷贝旧历史时增加使用次数。

这是明确的宿主适配：不是与 Codex 内部完成事件 ID 的逐字节等价。极端的
缺失原始身份或显示序号重排，需要进一步契约增强。没有可靠完成时间时暂停
相关扫描，不能以扫描时间为旧来源续期。
