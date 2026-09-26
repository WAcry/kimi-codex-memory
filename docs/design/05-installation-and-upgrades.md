# DESIGN 05：原生分发与升级

## 用户入口

唯一主入口是 Kimi 的原生 Plugin/Marketplace。项目不发布 PyPI 包，也不
安装/升级 Kimi。安装包包含六个平台的独立 Python runtime，平台 shell
launcher 直接选择本机 executable，reader 不经过 Kimi/Node 隐藏入口。
只有后台 OAuth/模型桥继续借用 __plugin_run_node；该入口变化只影响
生成桥接，不会让现成文件的 reader 无法启动。其兼容风险仍需真实宿主
回归。所有后台 Kimi 调用保持局部 NO_AUTO_UPDATE，不修改用户设置。

## 发布

main 上的 CI 在六种平台以当前固定宿主测试、构建、搬移验证，另有最低
支持宿主的 Linux 真实契约测试；全部通过后合并 ZIP。
发布版本以 kimi.plugin.json 为源，并核对 Python/package/Marketplace
版本一致。只有版本尚未发布时才创建 immutable GitHub Release；绝不覆盖
已发布二进制。源码 archive 不等于包含 runtime 的 release ZIP。

Marketplace 指向条目版本对应的完整 ZIP，不用 latest 指向另一个版本。
新目录条目先于发布就绪时，安装可能暂时失败，但不会静默装入旧版本。
版本提示及用户确认由 Kimi 管理。它目前不提供
通用的第三方静默自动更新，因此不假装已有自动升级，也不在会话期间
偷偷覆盖 runtime。更新原生插件不等于更新 Kimi。

## 数据与迁移

数据目录独立于 managed plugin，默认只有 ~/.kimi-codex-memory，也支持
用户显式指定 KIMI_MEMORY_HOME。配置文件只保存用户覆盖；未知选项按正常
配置错误处理，不进行旧名称转换或忽略开发期字段。

1.0.0 是正式兼容起点，SQLite SCHEMA_VERSION=1。版本 0 仅用于初始化
真正空的数据库，创建完整 schema 与版本标记是同一事务。已有版本 1
直接打开、更新 writer_version，不重建表。其他 schema 拒绝写入，reader
仍然独立。没有开发版数据库备份/迁移分支，也不自动采用非空无版本数据库。

current.json（format=1）是唯一发布指针，选择不可变 generation；无需
Windows 符号链接权限。缺失返回无发布状态，格式不明或损坏时不从其他
路径“恢复”摘要。不复制原始历史、不扫描旧产品数据目录。

今后 schema 真正改变时再添加从已正式发布版本出发的显式迁移，迁移前
使用 SQLite backup API 保存包含 WAL 的备份，并覆盖失败恢复与重复运行。
不能降级/清空新数据库来让旧 writer 重新工作。产品版本升级本身不触发
迁移、全量重生成或重复注入。基线数据样例固定在 tests/fixtures/release-v1/，
用于后续版本验证配置、记忆、notes、引用去重和上下文检查状态仍可用。

## 兼容策略

保持独立插件版本及最低支持下限，而不是与 Kimi 一一同号发布。
defaults/host.toml 统一最低版本、当前测试版、源码 commit 和契约名。
除明确低于支持下限外，Kimi product version 用于诊断和实例发现。新版本直接
尝试接口，忽略无关新增字段；缺失必要内容、未知语义或不完整分页才失败。
读取失败不能被解释为“空历史”，不能由此触发删除。
不先调用 --version，不将启动前后版本差异判为错误。正在工作的连接
可以完成批次；自有 helper 随读取结束，下次重新解析安装。无需监视磁盘
安装版本或维护热升级状态机。详细机制见 DESIGN 06。

额度/网络失败保留事件并退避。用户不需要编辑兼容白名单；新版本契约
发生变化时由新版插件适配。reader 不导入 generation 配置/数据库/API。
来源/输出失败有有限次数，外部条件故障只延后不耗尽来源。有效模型/请求器
指纹改变和显式 retry 可恢复失败项，指纹不包含访问 token，不影响成功
来源水位。具体状态边界见 DESIGN 11；升级/维护流程见 DESIGN 12。
