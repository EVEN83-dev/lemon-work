# Lemon One · 产品与技术总览

> 一个人的 AI 公司操作系统。本文给评委和技术评审看的“实现层说明”，不是营销稿。

---

## 1. 产品结构

Lemon One 由四个能力面组成：

| 能力面 | 解决什么问题 | 关键实现 |
|---|---|---|
| 公司模式 | 一个人如何管理一支 AI 团队 | 9 工位组织、任务 DAG、七表账本、审批门 |
| 标准模式 | 日常 AI 工作台 | 多引擎路由、50+ 技能、文件产物、历史会话 |
| 数字银行沙箱 | 资金类操作如何安全演示 | 本地模拟银行、风控、审计、人工审批 |
| 多模态阅读 | 文档/图片/视频如何进入上下文 | PDF OCR、视觉模型、faster-whisper |

---

## 2. 公司模式：从目标到交付

### 2.1 组织

9 个角色，分为 command / product / platform 三个部门：

```text
owner（人类）
└─ CHIEF / orchestrator
   ├─ PLANNER / planner
   ├─ RESEARCHER / researcher
   ├─ WRITER / writer
   ├─ OPS / ops
   ├─ BUILDER / backend
   ├─ REVIEWER / reviewer
   ├─ TESTER / tester
   └─ AUDITOR / auditor
```

每个角色有：

- `role_type`、`level`、`reports_to`
- `capabilities` 与 `permission_matrix`
- `skill_whitelist`
- `max_token_budget`、`timeout_seconds`
- 独立会话、消息、产物、事件

### 2.2 生命周期

```text
create_run(brief)
  → upload_brief(name, content)
  → artifact(kind=brief)
  → CHIEF decompose
  → task DAG + plan approval
  → owner/manager approve
  → assign(role_id, task)
  → spawn_subagent(engine, whitelist, DoD)
  → completion watcher
  → task_done / artifact / event
  → run complete
```

关键原则：

- 不可逆操作必须审批；
- 同级消息不构成授权；
- 每个任务必须有账本行；
- 引擎失败如实回队/报错，不假装成功。

### 2.3 七表账本

| 表 | 作用 |
|---|---|
| `company_run` | 公司轮次、状态、brief、阶段 |
| `agent` | 9 工位状态、当前任务、token、完成/失败数 |
| `task` | 任务 DAG、依赖、状态、token、耗时、结果 |
| `event` | 全量事件流（任务/消息/审批/工具/仲裁） |
| `approval` | 计划/产物/配置/不可逆操作审批 |
| `artifact` | brief、方案、patch、报告、版本 |
| `session` | 单聊/群聊/审批台会话台账 |

### 2.4 实时推送

```text
CompanyService._notify_state()
  → HybridBridge.companyStateChanged(JSON)
  → window.onCompanyState(state)
  → mapState + renderAllReal
  → 局部重绘（卡片 / 连线 / 日志 / 底栏 / 管理面板）
```

事件流单独走 `companyEventReceived`，前端追加单行日志；每 1.2 秒合并补拉一次 state，避免高频全量重绘。

---

## 3. 前端：公司页

`company_os.html` 是单页应用，不依赖前端框架：

- 左栏：BRIEF / SOURCES / CONSTRAINTS / BUDGET / PRIOR RUNS / SELECTED / FILES / SESSIONS。
- 中间：员工图、汇报连线、缩放/平移、任务/消息/产物联动。
- 底部：RUN LOG / DISPATCH / OUTPUT。
- 抽屉：员工白盒（概览 / 技能 / 权限 / 上下文 / 消息 / 产出 / 事件）。
- 管理面板：实时计划 / 历史会话 / 公司上下文 / 项目。
- 配置抽屉：全局/每员工模型、API、token 预算。

响应式：

- 3 列 → 2 列 → 1 列；
- 顶栏横向滚动；
- 底栏面板独立滚动；
- 矮视口压缩阶段条，不直接隐藏；
- resize 后重绘 hub / 连线 / 阶段时间线，并复位缩放。

---

## 4. 桥接：companyApi

`hybrid_mode/core/hybrid_mode_bridge.py` 提供统一动作位：

```text
getState / getAgentWhitebox / getConfig / setConfig
uploadBrief / uploadBriefFile
assignTask / approve / reject / complete
message / inbox / listMessages / listSessions
listRuns / switchRun / listStageTimeline
listApprovals / listArtifacts / listTasks
stopRun / pauseRun / resumeRun / stopAgent
getProviderBalance
```

关键修复：

1. 页面加载 `qrc:///qtwebchannel/qwebchannel.js`，不再依赖宿主注入时机。
2. `companyApi` 使用 `@pyqtSlot(str, str, result=str)`，带参调用才能进入 Python。
3. 文件上传在桥内提取 md/txt/pdf/docx 文本，再交给 `CompanyService.upload_brief`。
4. API 余额查询在后台线程执行，缓存 60 秒，不阻塞 UI，不把 Key 传到前端。

---

## 5. 多引擎

`shared/engine_manager.py` 负责：

- 引擎注册与健康检查：DeepSeek / Ollama / MIMO / MIEMIE / 自定义 OpenAI 兼容端点。
- 子代理 spawn：`spawn_subagent(engine_name, skill_whitelist, dod)`。
- 视觉预处理：非视觉引擎收到图片时，先用本地视觉模型生成描述，再注入 prompt。
- 任务路由：按复杂度/成本/可用性选择引擎。

每员工模型覆盖：

```python
cfg = svc.get_config()
ov = cfg["per_agent"].get(role_id, {})
engine_name = ov.get("engine") or cfg["model_global"]
```

---

## 6. 安全与审计

- 角色权限矩阵：`can_peer_message / can_command / can_approve / can_handoff`。
- 同级消息只作 request，不构成授权。
- 高风险工具触发确认；资金类操作进入 owner 审批。
- 所有拒绝写入 `event(type=audit_denied / rule_denied)`。
- 数字银行为本地沙箱，不接真实资金。
- 配置保存、公司上下文保存、文件变更均留事件。

---

## 7. 多模态

| 能力 | 实现 |
|---|---|
| PDF 文本 | PyMuPDF 提取 |
| 扫描件 OCR | PyMuPDF 渲染页面 → 本地视觉模型逐页识读 |
| 图片识图 | `vision_client.describe_images()` |
| 视频字幕 | 优先读取字幕文件 |
| 视频语音 | 无字幕时 faster-whisper 本地转写（CPU int8，中文 initial_prompt） |
| 工具接入 | 技能白名单 + `skill_packs` + `skill_domain_router` |

---

## 8. 已验证结果

以下为本轮实机验证记录（不包含个人余额/Key）：

- 公司页 `real=true`，9 张员工卡来自真实账本。
- 历史会话管理：已载入 1000 条，台账共 2236 条。
- 配置保存：9 名员工模型/预算保存成功。
- 公司上下文保存成功。
- 项目面板：50 个公司轮次，可搜索、筛选、切换。
- 页面重载后 JS 异常 0、console error 0。
- 布局：1400×900 三列、1000×700 两列、860×620 单列，底栏/顶栏滚动正常。
- docx / pdf 文本提取链路通过。

---

## 9. 诚实边界

- 当前是 Windows 桌面客户端，未做公网 SaaS。
- 实时计划当前为最近 40 条任务快照；全量 `listTasks` 接口已存在，可继续切换。
- 部分旧会话的消息正文可能已被消息库清理，界面如实提示。
- 成本为估算值，实际以 API 账单为准。
- 默认本地小模型，能力靠编排、权限与工程纪律，不靠模型参数规模。

---

## 10. 为什么它是“AI 原生”的

不是因为用了大模型，而是因为：

1. **组织结构是 AI 的一等公民**：角色、权限、预算、技能都是可执行的系统对象。
2. **过程是可见的**：每个任务、消息、工具调用、审批都进入账本。
3. **人保留最终控制权**：不可逆操作必须人工审批。
4. **失败可解释**：失败任务、拒绝原因、越权记录都落到事件流。
5. **一个人可运营**：计划、会话、上下文、项目都有管理入口，不依赖团队。
