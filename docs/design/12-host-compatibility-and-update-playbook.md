# DESIGN 12：宿主兼容边界与维护手册

## 唯一基线

src/kimi_memory/defaults/host.toml 定义 minimum_version、tested_version、
source_commit、contract。当前2.1.0是最低兼容版，2.1.1是六平台验证和
OAuth/requester原文的统一官方release来源。upstream.toml两个区段
必须与其一致，由源码hash测试保证；不把版本字符串当完整Schema指纹。

## 分层而不预建虚构的多版本框架

| 边界 | 当前实现与故障策略 |
| --- | --- |
| hook reader | shell直接调用自带runtime；无Kimi Node/REST/模型依赖。事件变更用原生请求/多hook回归发现 |
| history | KimiClient 负责当前HTTP契约和 Source/Transcript 归一化；已有分页完整性/角色/来源检查，未知重要语义只失败该项，不原始日志回退 |
| config | model_config 把宿主有效默认/别名与本地凭据引用转为 Connection；不声称接管宿主所有高级参数 |
| OAuth | 固定 FileTokenStorage/OAuthManager/身份头源码，使用已安装宿主运行桥接；失败不拖垮reader |
| requester | 固定原生Chat/Responses/Anthropic流式编解码；输出thinking/tool/final分离。不是完整Kimi agent，不创建会话 |

无需仅为三个字段命名再包一层 HostAdapter interface；现有模块本身就是
薄适配边界。将来遇到真实旧/新结构差异再扩展有限归一化分支，不猜测
未知字段、不维护每个产品小版本一套源码。

## 支持表

| 能力 | 支持范围 |
| --- | --- |
| Kimi订阅 | 原生file OAuth的命名、续期、401恢复及身份请求头；没有另建keyring/登录系统 |
| 第三方服务 | 配置为支持的协议、常规endpoint/API key或环境变量凭据；OpenAI-compatible不代表任意厂商扩展全部支持 |
| 请求协议 | Chat Completions、Responses、Anthropic Messages；Gemini明确拒绝，不默默切provider |
| 默认选择 | 宿主有效default alias/provider及本地credential引用，显式Memory覆盖优先 |
| 上下文 | 用户设置窗口/输入/输出上限，已知窗口不越界；未知回退256000 |
| Thinking | 当前映射的enabled/effort/keep、native capability/effort/reasoning-key元数据；实际供应商能力由原生trait处理 |
| 未覆盖高级行为 | 不完整继承所有profile临时参数、工具/MCP、multimodal重新理解、任意云IAM/SSO。需要扩展时必须新增显式实现与测试 |

供应商能力不能因模型名称猜测，未知协议拒绝。已支持协议中的未知可选
配置目前不全量转发；对此不宣称完全镜像当前安装的Kimi模型栈。

## 维护流程

1. 每周/手动 Host upstream compatibility workflow 调GitHub最新稳定
   release，生成source diff报告，并在隔离目录安装该host执行实际
   API/续聊/多hook/认证/请求协议测试。没有写权限、没有Release步骤。
2. 维护agent阅读报告。API新增无关字段不需要发版；关键失败或必须继承
   的模型行为变化才更新边界代码。源diff超过GitHub返回上限时报告不完整，
   不能以列表中没有某文件推断没有变化。
3. 改源码基线时统一核验OAuth/requester、commit与license hash；重建
   bundle并检查可复现性。不是自动复制最新文件后就发版。
4. 发版前六平台运行pinned host，额外minimum host执行真实契约测试，
   frozen ZIP验证直启reader与模型桥。成功后才允许发布独立插件版本。
5. 小型兼容修复用patch/minor；不合理维护巨大旧行为时在major提高
   minimum。现有数据继续兼容或给迁移方案；绝不替用户升级Kimi。

## 更新体验

Kimi插件管理器负责用户确认更新，不承诺第三方插件自动升级。新版Kimi
默认尝试，version低于支持下限或实际契约失败可在doctor/worker-status
看到支持说明与兼容提示；不把运行故障警告注入模型上下文。reader照常可用。
ADR 0015 单独允许经过验证的新版本通知作为 hook 卡片显示；这不是故障
日志，不会触发自动更新，具体传输和去重边界见 DESIGN 13。
既有helper完成批次后自然结束，下次用当前安装；不用版本号相等检查、
热重启/二进制安装接管或周期性全量重提取。
