# 🍋 Lemon Work · AI 智能工作助手（含数字银行沙箱）

> 桌面级 AI Banking Agent —— 自然语言驱动虚拟银行办理业务、多层次白盒可视化、
> 多模型引擎（DeepSeek / Ollama / 自定义 OpenAI 兼容端点）、任务智能拆解、
> 过程时间线、页面跟随联动演示。为「AI 代人操作银行（安全 + 体验）」而生。

## 📦 参赛材料索引（2026 深圳国际金融科技大赛）

本仓库同时作为**第 03 项「源代码与部署材料」的完整在线版本**，全部材料公开可查：

| 序号 | 材料 | 位置 |
|---|---|---|
| 01 | 技术文档报告（架构图 / 核心算法 / 安全设计） | [参赛材料/01_技术文档报告.pdf](参赛材料/01_技术文档报告.pdf) |
| 02 | 答辩材料 | [参赛材料/02_答辩材料.pdf](参赛材料/02_答辩材料.pdf) |
| 03 | 源代码与部署材料 | [参赛材料/03_源代码与部署材料.zip](参赛材料/03_源代码与部署材料.zip)（6.8MB：全部源码 + 数字银行 + 12 个测试脚本 + README/部署说明/依赖清单） |
| 04 | 安全自评报告（权限分级 + 已知风险清单） | [参赛材料/04_安全自评报告.docx](参赛材料/04_安全自评报告.docx) |
| 05 | 演示视频 | 报名系统已提交（490MB，超出 GitHub 单文件限制） |

> **快速体验**：从 [Releases](../../releases) 下载绿色免安装包（内置 Python 运行时，解压双击即用），无需配置环境。

## ✨ 核心特性

| 能力 | 说明 |
|---|---|
| 🏦 数字银行沙箱 | 内置完整模拟银行（14 账户 / 36 项业务 / 风控·审计·冲正·复利·行情引擎），HTTP API 全开放 |
| 🕵️ 多层次白盒 | 统一过程头（状态灯+动作短语）→ 逐轮小节 → 思考链分节点 → 过程时间线 → 工具聚合条，每层可独立折叠 |
| 🤖 多引擎驱动 | DeepSeek 云端 / Ollama 本地 / 任意 OpenAI 兼容自定义端点（Trae 式表单接入，保存即验活） |
| 🔍 本地模型探测器 | 只显示「探测可达」的本地模型与「验证在线」的自定义模型 |
| 📋 任务智能拆解 | 任务列表不是执行流水账——工具调用流实时聚合成语义子任务，独立状态推进 |
| 🖥️ 页面跟随联动 | Agent 办理业务时，银行操作台自动切页签/滚动/高亮（UI 状态总线），支持 `remote_bank_navigate` 显式演示 |
| 🛡️ 安全分级 | 高危操作（转账/挂失/冲正/申购）权限确认闸 + 风控三规则（单笔限额/夜间大额/高频保护） |
| 📊 规范表达 | 结论强制结构化（表格/列表/加粗），前端 markdown 渲染双保险（marked + lite 兜底），永无源码裸奔 |
| 🧪 四层测试防线 | 契约审计 → 白盒 30 项 → 真实巡航 → 六场景赛题合规（全部脚本化，可 CI） |

## 🚀 快速开始

### 方式一：绿色免安装包（推荐）

从 [Releases](../../releases) 下载 `LemonWork-vX.X-win64-portable.zip`，解压后：

```
双击 启动LemonWork.bat        → 主程序（自带便携 Python，无需安装任何依赖）
双击 启动数字银行.bat          → 银行沙箱服务（:8090，主程序也会自动拉起）
```

### 方式二：源码运行

```bash
git clone https://github.com/<YOU>/lemon-work.git
cd lemon-work
pip install -r requirements.txt
# 准备便携 Python（或直接用系统 Python 3.12+）：
#   _py312/python.exe 即为官方 python 3.12 + PyQt5/PyQtWebEngine
python yh_main.py
```

## 🏦 数字银行沙箱

- 服务：`DigitalBank/server.py`（纯标准库 HTTP，端口 8090）
- 数据：SQLite 本地文件（`data/bank.db`），含日切/利息/社会资金事件等后台生态
- 行情：确定性日线 + 实时 tick 演化（可复现、可审计）
- API 全表：启动后 `GET /` 即银行操作台，`GET /api/menu` 列出全部 36 项业务接口
- Agent 技能族：`shared/skills_builtin/remote_bank_skills.py`（34+ 技能，余额/转账/定时/AA/账单/理财/基金/股票/卡片/订阅/商城/风控/审计/对账/复利/导航…）

> ⚠️ **免责声明**：数字银行为纯本地模拟沙箱，所有账户、资金、行情均为虚构数据，
> 仅用于 AI Agent 能力验证与赛事演示，不涉及任何真实资金与真实金融机构。

## 🧪 测试

```bash
_py312\python.exe scripts\audit_broken_links.py   # ① 契约审计（空连接/假按钮）
_py312\python.exe scripts\gui_whitebox_test.py    # ② 白盒 30 项回归
_py312\python.exe scripts\gui_patrol_test.py      # ③ 真实任务巡航（中断检测）
_py312\python.exe scripts\gui_competition_test.py # ④ 六场景赛题合规
```

## 📐 架构

```
yh_main.py                 启动壳（银行守护看门狗 + Qt 环境准备）
standard_mode/
  main.py                  QtWebEngine 主窗口
  ui/mimo_app.js           前端（TraceRenderer v350+ 白盒渲染器）
  ui/mimo_panel.py         桥接层（trace 事件流 / 任务拆解 / 队列 / 自定义模型）
  core/serve_bridge.py     markdown 渲染 / 卡片桥
shared/
  engine_manager.py        多引擎 Agent 循环（工具调用/复杂度路由/断路器）
  core/task_classifier.py  任务复杂度（轮数预算）
  skills_builtin/          技能族（银行/办公/系统）
DigitalBank/（外部目录）    数字银行沙箱（server.py + bank_core.py + index.html）
```

## 📄 License

MIT © 2026 Lemon Work Contributors
