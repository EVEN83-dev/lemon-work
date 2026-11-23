# 本轮核心改动导读

> 这些文件是 `core-source.zip` 中的核心片段副本，方便评委不下载 zip 也能直接浏览。
> 完整可运行源码见 `core-source.zip`。

---

## company/

### `company_os.html`

公司模式单页应用（约 186KB，无前端框架）：

- 9 工位员工卡、部门分组、汇报连线、图谱缩放/平移。
- 左栏 KPI、底部 RUN LOG / DISPATCH / OUTPUT。
- 员工白盒抽屉：概览 / 技能 / 权限 / 上下文 / 消息 / 产出 / 事件。
- 管理面板：实时计划 / 历史会话 / 公司上下文 / 项目。
- 配置抽屉：9 名员工模型 / API / token 预算。
- 真实策划书上传：md/txt 前端读取，pdf/docx 交桥提取。
- 响应式：3/2/1 列、resize 重绘、顶栏横向滚动、底栏独立滚动。

关键修复：

- 页面加载 `qrc:///qtwebchannel/qwebchannel.js`，不再依赖宿主注入时机。
- 事件到达后 1.2 秒合并补拉 state。
- 员工卡 token 显示从“预算”修正为“已用 / 预算”。
- `tokens`、`API余额`、`cost` 行位对齐，不再串位。

### `hybrid_mode_bridge.py`

`companyApi` 统一动作位：

- 修复 `@pyqtSlot(result=str)` → `@pyqtSlot(str, str, result=str)`，带参调用才真正进入 Python。
- 新增 `uploadBriefFile`：base64 → md/txt/pdf/docx 文本提取 → `upload_brief`。
- 新增 `getProviderBalance`：DeepSeek 余额后台查询 + 60 秒缓存，不阻塞 UI。
- `getAgentWhitebox` 补充 engine / model / engine_inherited。

### `service.py`

公司服务：

- `state()` 无当前轮次时 KPI 归零，不再把全库历史当本轮统计。
- 无当前轮次时 state 只带最近 80 条会话，避免 2200+ 会话把快照撑到 ~580KB。
- `session_list()` / `session_count()` 支持历史会话全量管理。
- `company_context` 落盘配置，并在 `assign()` 时真实注入子代理 DoD。
- `_apply_config` 允许 `company_context`。

### `store.py`

七表 SQLite 账本：

- `stats()` 新增 `tok_total / tok_per_s / tasks_per_min / events_per_min / active_agents`，全部 SQL 聚合。
- `count_sessions()` 供历史会话页显示 N / total。

### `bus.py`

消息总线：

- 会话/消息持久化到 `session_mesh`。
- 同级消息不构成授权，越权写入审计事件。
- 附件路径随信封落库。

---

## media/

### `video_reader.py`

- 字幕优先；无字幕时 faster-whisper 本地转写。
- `_patch_av_compat()` 兼容 PyAV 19 与 faster-whisper 1.2.1。
- 中文 `initial_prompt`，CPU int8，默认 `small` 模型。

### `vision_client.py`

- `pick_vision_model()` 自动选择本地视觉模型。
- `describe_images()` 支持 base64 图片列表。
- 兼容 `OLLAMA_HOST=0.0.0.0` / 无 scheme 的常见写法。

### `pdf_reader.py`

- `action="ocr"`：PyMuPDF 渲染页面 → 本地视觉模型逐页识读。
- 文本型 PDF 直接提取，扫描件走 OCR。

---

## platform/

### `engine_manager.py`

- 多引擎注册与健康检查。
- `vision_chat()` 视觉引擎选择。
- 非视觉引擎收到图片时先本地识图，再注入 prompt。
- 子代理 spawn 与技能白名单。

### `role_system.py`

- 9 工位角色定义、权限矩阵、技能白名单、token 预算、超时。
- 供公司服务、桥接、前端配置抽屉共用。

---

## 验证记录

- 公司页 `real=true`，9 张员工卡来自真实账本。
- 历史会话管理：已载入 1000 条，台账共 2236 条。
- 配置保存：9 名员工模型/预算保存成功。
- 公司上下文保存成功。
- 项目面板：50 个公司轮次，可搜索、筛选、切换。
- 页面重载后 JS 异常 0、console error 0。
- 布局：1400×900 三列、1000×700 两列、860×620 单列。
- docx / pdf 文本提取链路通过。

> 以上验证不包含个人 API Key、余额金额或真实资金数据。
