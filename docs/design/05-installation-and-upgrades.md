# DESIGN 05：原生分发与升级

## 用户入口

唯一主入口是 Kimi 的原生 Plugin/Marketplace。项目不发布 PyPI 包，也不
安装/升级 Kimi。安装包包含六个平台的独立 Python runtime；小型 launcher
在 Kimi 自带的 Node 运行时中选择本机产物。

当前使用 Kimi 的 __plugin_run_node 入口，standalone 和 npm 两种安装都
提供它，但它不是承诺永远不变的公共接口；必须做真实宿主回归。它失效时
无需迁移记忆数据，但需要更新插件 launcher。业务 API 失败与该入口失效
是不同故障，不能声称任意宿主破坏性变更都不会影响 hook 运行。
在调用该入口之前，平台 shell 包装先设置子进程的 NO_AUTO_UPDATE；Kimi
main 在解析子命令之前处理 native staged swap，不能在 launch.mjs 内才
设置它。包装不修改用户 shell/配置，不安装其他运行时。

## 发布

main 上的 CI 在六种平台测试、构建、搬移验证，全部通过后合并 ZIP。
发布版本以 kimi.plugin.json 为源，并核对 Python/package/Marketplace
版本一致。只有版本尚未发布时才创建 immutable GitHub Release；绝不覆盖
已发布二进制。源码 archive 不等于包含 runtime 的 release ZIP。

Marketplace 指向完整 ZIP；版本提示及用户确认由 Kimi 管理。它目前不提供
通用的第三方静默自动更新，因此不假装已有自动升级，也不在会话期间
偷偷覆盖 runtime。更新原生插件不等于更新 Kimi。

## 数据与迁移

数据目录独立于 managed plugin。配置文件只保存用户覆盖；新版默认值可以
生效，旧版 inject_every_prompt、refresh_on_change、allowed_versions 等
字段被忽略，不恢复被用户否定的行为。

SQLite 使用 user_version，与产品/Kimi版本分开。v1→v2 先通过 SQLite
backup API 保存包含 WAL 的快照，再迁移；重复启动不重复备份。更高的
未知 schema 暂停 writer，不尝试降级，也不妨碍离线 reader。旧程序回滚
不能把旧数据库覆盖回去并丢掉新的 notes/引用；至少仍可读取已发布文件。

新布局以 current.json 选择不可变 generation，避免 Windows 符号链接
权限要求。支持从此前开发版 current 符号链接读取已有数据，既不创建旧
协议分支，也不复制完整历史。

## 兼容策略

Kimi product version 仅用于诊断和实例发现。新 patch/minor 版本直接
尝试接口，忽略无关新增字段；缺失必要内容、未知语义或不完整分页才失败。
读取失败不能被解释为“空历史”，不能由此触发删除。
不先调用 --version，不将启动前后版本差异判为错误。正在工作的连接
可以完成批次；自有 helper 随读取结束，下次重新解析安装。无需监视磁盘
安装版本或维护热升级状态机。详细机制见 DESIGN 06。

额度/网络失败保留事件并退避。用户不需要编辑兼容白名单；新版本契约
发生变化时由新版插件适配。reader 不导入 generation 配置/数据库/API。
