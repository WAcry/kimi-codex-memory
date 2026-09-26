# DESIGN 13：原生新版本提醒的实现边界

## 宿主路径

Kimi 2.1.0/2.1.1的UserPromptSubmit聚合通过后，context.append存入
role=user、origin=hook_result，同时dispatch HookResult。TUI的
handleHookResult直接格式化卡片；print/stream-json也直接输出该
事件，序列化为assistant展示条目。这个展示角色不代表模型曾生成
那段文本，也不改变模型实际收到的user消息角色。

没有使用PluginUpdateNotifier（它限制官方来源）、未注册MCP或
新插件命令，也不让模型调用NotifyUser。网络结果不得驱动任意
shell/工具；更新安装仍由用户调用原生插件管理器。

## 文件与进程

- updates.toml：可选，只有enabled=true/false，默认true；无效则关闭。
- updates/cache.json：format=1、attempted_at、state，成功后另存
  checked_at与latest版本；不保存远端内容。
- updates/launch.json：60秒进程启动合并窗口，不代表已完成网络检查。
- updates/notice.json：最近notified_version/time，或唯一pending
  version、hashed session key、prompt hash集合和准备时间。

update_notices.py不导入网络、生成配置、数据库或模型。hooks在相关
观察事件尝试schedule_check；单独的runtime check-updates才导入
release_check.py与JsonHttp。stdin/stdout/stderr断开，进程自行退出。
worker暂停/长时间整理/生成关闭不会阻止这个独立的小型检查。

check-updates先在专用check.lock下写attempted_at，再请求一次固定
https://api.github.com/repos/WAcry/kimi-codex-memory/releases/latest。
5秒HTTP超时、128KiB响应上限，不跟随重定向、不重试，无认证，只使用
固定Accept/User-Agent。支持正常系统代理，不传递模型custom headers。
失败记录unavailable并等24小时，无旧信息通知；崩溃留checking记录也
不会造成不断发请求。没有独立时钟服务，只有用户活动才启动下一次。

候选release必须draft=false、prerelease=false，tag严格为vX.Y.Z，
版本各段有长度上限，published_at为带时区日期，html_url是精确仓库
release地址，assets含已上传且精确对应tag的kimi-codex-memory.zip。
不跟着不可信URL取代码，也不为通知下载ZIP或校验文件。通知中的链接
在本地用固定仓库与已验证版本构造。未来不同tag格式先静默不提醒，
不影响核心Memory工作。

## 显示和状态

每次UserPromptSubmit先执行原来的memory reader；再单独尝试读取
updates状态，只有新缓存、新版本和未提示版本才添加短通知。两者在
一个hook message里（通知放前面）；已有记忆不重新渲染，有通知时
可只输出通知。render命令和Memory Prompt模板不带更新内容。

通知有独立锁和状态，不修改memory receipt。准备后等待同session、
同用户prompt hash的TurnStarted确认，才提升notified_version。先
前block、失败或无关turn不确认。最多一个pending，跨session保留5
分钟，避免并发重复；SessionEnd/PostCompact释放自身pending；丢失
ack可重发，但已确认版本不因新会话/压缩重发。未得到输入机会就不
强行弹窗；这不是每个新版本发布瞬间的推送服务。

在当前安装版本不低于缓存版本时完全静默。通知版本已确认以后仍每天
检查是否出现更高版本。同一data home全局去重，不是每个会话都显示。
关闭updates只关闭新的检查/提醒；已经进入对话的内容不会被撤回。

## 容错与隐私

通知异常包裹在独立边界，不得使已有memory输出丢失、退出码变成block
或生成任务失败。读路径不导入release_check/http；缓存旧、字段不明、
异常类型、锁忙和无法写入投递状态都只跳过这次提醒。

只对GitHub发送公开GET，无会话数据、当前项目、访问token或安装唯一
ID；GitHub/代理仍可看到正常网络连接的地址。hash用于临时关联，不
是隐私匿名化承诺；不持久化prompt原文。远端release notes永远不
进入模型context、记忆生成输入或通知状态。

## 验证

单元测试覆盖稳定/同版/旧版/预发布/坏tag、安装资产缺失、大小上限、
限流/离线、24h节流、进程合并、缓存失效、无凭据请求、独立配置、
读路径网络模块不可导入、通知异常不影响memory、跨会话去重与重试。
原生测试用三种协议截获真实请求及print显示事件，确保无需assistant
生成文字且不会增加模型调用；另测双hook拦截后再次显示、正常续聊
与新会话不重复。冻结包测试直接调用通知、确认、关闭和check-updates
禁用分支，且在Kimi/Node不可用时继续离线渲染。
