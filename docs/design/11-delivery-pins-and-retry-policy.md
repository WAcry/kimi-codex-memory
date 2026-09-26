# DESIGN 11：投递、快照和失败恢复

## P1-1：处理材料不是发布产物

Codex 的 workspace.reset_memory_workspace_baseline 先删除 diff，
再调用 git-utils 的 reset，删除旧 .git 并创建新的基线。我们的
prepare 每次从供应文件重建 Git，所以 publish 可以更简单：校验
最终摘要后删除 DIFF_FILE 与整个 .git，只发布实际记忆/扩展文件及
manifest。不把任何 reflog 或不可达 Git 对象带入当前 generation。

之前版本的当前快照会被 clean_current_publication 局部清理，不动
摘要和 manifest，无需调用模型。历史 generation 仍受保留规则管理，
notes 与数据库也不因此消失。此修复不是彻底擦除所有本地数据。

## P1-2：投递状态与正常门禁的实际关系

Kimi agentExternalHooksService.ts:335–386 先汇总各 UserPromptSubmit
结果，有任何 block 就不追加其他成功注入。loopService.runPromptGate
等待上述处理，接受之后才进入 turnStarted；TurnStarted 通过
agentExternalHooksService.ts:222–232 输出 turn_id/origin_kind/prompt。
turnEvents.turnPromptText 会去掉 bundled Skill 前缀，读取文本部分。

prepared receipt 写入快照、摘要 hash、少量 prompt hash 与 pin 时间，
不写用户原文。用户 TurnStarted 必须与 prompt hash 匹配才变成
committed。单独 SessionStart、Stop、其他后台 turn 或不匹配确认都
不算接纳；其他 hook 阻断后下一次输入仍重发。普通已确认上下文则只
续期 pin，不再次渲染 prompt。

该信号来自已验证的宿主实现，不是宿主正式承诺的持久化 ack。hook
事件丢失、超时、同文并发或崩溃仍可能造成重发，极端情况下也没有
严格投递保证。明确选择 best-effort/偏向重试，不建立跨进程消息总线。
原生 2.1.0/2.1.1 的双 hook 首次拦截场景有端到端回归。

## P1-4/P2-5：内容与 pin 同一个快照

RenderedMemory 同时返回 text、generation、summary_hash，只读取一次
current.json。短 snapshot.lock 从选择、文件读取延续至 pin 写入；
发布指针切换和 GC 选择也拿同一锁。GC 在锁内把无 pin 的目录移到
专用 _staging/gc-<uuid>，在锁外递归删除，失败留待下次清理。

锁最多短暂等待；争用时跳过本轮，保留下一输入的重试机会。不能持有
它调用模型、OAuth、API、Git 或进行目录递归删除。新增 last_seen
保留原 time，旧 receipt 未写这个值则暂用 time，避免丢弃正式用户状态。

普通输入和 SessionStart 都可续期 pin，不改已接受的内容。默认30天
无活动后可回收；恢复时缺失快照，则下一 UserPromptSubmit 提供当前
快照并附一句旧路径失效说明，重新走 prepared/committed。无需永久
保留所有版本，也不能谎称仅刷新时间可以救回已删除目录。

## P1-3：先区分外部条件与来源失败

- 外部调用预算、认证/配置、HTTP拒绝/限流/服务异常、网络、桥进程
  暂时失败：释放 lease、写 retry_after，但 attempts_left 不递减。
  每日预算至少等到下个 UTC 日界，正常请求次数预算仍然生效。
- 来源/输出结构、上下文超限、超大响应等：有限尝试，耗尽后可见于
  failed_extractions/retry --list，不清空既有摘要。
- 身份指纹在扫描/领取前计算：插件请求器版本 + 有效模型/协议/窗口/
  thinking/相关配置。访问 token/认证 header 不加入指纹，其他值只
  以摘要形式存储。配置未就绪不反复重置。fingerprint 改变只重置
  非成功且失败的任务，不重提取已经完成的同版本历史。
- retry --source 或 retry 重置失败项，不调用模型、不越过正常来源
  资格、不修改成功项或正在运行的任务；--list 是显式诊断入口。

不添加独立 auth watcher 或 blocked 状态表，外部问题恢复后由后续
正常唤醒再试。不是无间隔/无限模型循环；SDK重试依旧关闭、每批/每日
请求预算仍生效。原先版本消耗光的失败任务在本次版本/模型指纹变化时
获得一次预算，后续同指纹不会不断重置。

## 验证

测试覆盖当前 diff/.git 不含删除内容、旧处理材料无模型清理、两个
线程精确控制渲染/GC交错、40天后续期/已删除快照重建、双hook阻断与
正常续聊去重、外部故障超过3次仍可恢复、坏输出耗尽后改模型恢复、
旧发布数据保留与显式retry不触碰成功来源。发布包还在伪造的故障
Kimi/Node 位于 PATH 首位时验证完整离线读取。
