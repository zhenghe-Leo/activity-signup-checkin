# 03 架构设计（Architecture）

| 项目 | 内容 |
|---|---|
| 名称 | 活动报名与签到系统 |
| 版本 | v0.8（P2.1 Docker 完成后按代码回写差异） |
| 更新日期 | 2026-10-11 |
| 依据 | [01-spec.md](01-spec.md) v1.2 |

---

## 0. 设计要点

1. **单进程、单端口、单文件数据库**：浏览器 → FastAPI（同时托管前端静态文件）→ SQLite 文件。部署者只需执行一条启动命令。
2. **不超卖靠「锁内检查」**：所有写操作都放在 `BEGIN IMMEDIATE` 写锁事务里，「检查名额」与「写入记录」在同一把锁内完成；唯一约束兜底防重复报名（DEC-02）。
3. **按时间变化的状态一律实时计算，不落库**：活动阶段、候补失效、签到窗口、统计数字都在读取时按当前时间计算；当前时间来自可注入的时钟，测试可以固定时间。
4. **AI 只给建议，不直接改数据**：AI 生成的内容只填进可编辑表单，发布前必须过校验器；自然语言筛选的结果只被解析成白名单条件，再由系统查库。AI 失败时自动降级，接口照常返回 200（DEC-03）。
5. **常需调整的业务规则集中在 `policies`**：递补顺序、退回候补的人选、签到窗口等可替换的规则都写成独立函数，改一处即可。

---

## 1. 系统上下文

```mermaid
flowchart LR
  ST["学生<br/>（浏览器）"]
  OR["组织者<br/>（浏览器）"]
  RV["部署者<br/>（本地终端）"]
  subgraph SYS["校园活动报名与签到系统（本地单进程）"]
    FE["Vue 3 前端<br/>（静态文件）"]
    BE["FastAPI 后端<br/>（/api）"]
    DB[("SQLite<br/>data/app.db")]
    FE -- "HTTP JSON" --> BE
    BE --> DB
  end
  DS["DeepSeek API<br/>（外部，可选）"]
  ST --> FE
  OR --> FE
  RV -- "python scripts/start.py" --> SYS
  BE -. "HTTPS，可选；无密钥时自动降级" .-> DS
```

| 外部方 | 交互 | 说明 |
|---|---|---|
| 学生 | 浏览器访问 | 浏览与筛选活动、报名、取消、签到、查看我的报名 |
| 组织者 | 浏览器访问 | 管理活动、用 AI 生成内容、发布后调整、生成签到口令、查看名单与统计 |
| 部署者 | 本地终端 | 一键启动、重置演示数据、运行测试与 AI 评测 |
| DeepSeek | HTTPS（可选） | 只用于 A1 内容生成和 A2 自然语言筛选；不可用时系统完全可用 |

---

## 2. 技术栈与依赖


| 层 | 选型 | 许可证 | 说明 |
|---|---|---|---|
| 后端框架 | FastAPI + Uvicorn | MIT / BSD-3 | Pydantic v2 负责入参校验，并自动生成 OpenAPI 文档 |
| 配置 | pydantic-settings | MIT | 从环境变量和 `.env` 读取配置 |
| 数据访问 | Python 标准库 `sqlite3`（不用 ORM） | PSF | SQL 和事务边界都显式写出（DEC-01、DEC-02） |
| 数据库 | SQLite 3（WAL 模式） | Public Domain | 嵌入式数据库，不需要安装服务 |
| HTTP 客户端 | httpx | BSD-3 | 调用 DeepSeek；FastAPI 的测试客户端也依赖它 |
| 测试 | pytest | MIT | 规则测试、并发测试、AI 测试（使用假客户端） |
| 前端 | Vue 3（JavaScript）+ Vite + Vue Router | MIT | 不引入 TypeScript，减少构建配置 |
| UI 组件 | Element Plus | MIT | 提供表格、表单、对话框、消息提示 |
| AI | DeepSeek（OpenAI 兼容的 Chat Completions 接口） | 商业 API | 使用 JSON 输出模式 |

运行环境要求：Python ≥ 3.11、Node ≥ 20。

后端依赖版本锁定在 `src/backend/requirements.txt`（M1：fastapi 0.143.0、uvicorn 0.54.0、pydantic 2.14.0、pydantic-settings 2.15.0、httpx 0.28.1、pytest 9.1.1、tzdata 2026.5）。`tzdata` 为 Windows 提供 IANA 时区数据，否则 `ZoneInfo("Asia/Shanghai")` 无法加载。M1 在 Python 3.11.9 + SQLite 3.45.1（Windows 11）上验证。

---

## 3. 模块设计

### 3.1 模块图

```mermaid
flowchart TB
  subgraph FE["前端 src/frontend（Vue 3）"]
    V1["学生端页面<br/>活动列表 / 详情 / 我的报名"]
    V2["组织者端页面<br/>汇总 / 活动表单 / 活动管理"]
    IDS["身份切换"]
    AC["api 客户端<br/>附加 X-User-Id，错误码转中文"]
    V1 --> AC
    V2 --> AC
    IDS --> AC
  end
  subgraph BE["后端 src/backend/app（FastAPI）"]
    R["api 路由层<br/>入参出参校验、身份与角色"]
    subgraph SV["services 业务层"]
      S1["activity_service"]
      S2["registration_service"]
      S3["checkin_service"]
      S4["change_service"]
      S5["query_service"]
    end
    CV["content_validator"]
    PO["policies<br/>可替换的规则函数"]
    subgraph AIM["ai 模块"]
      A0["client<br/>DeepSeek 调用与失败分类"]
      A1["generator<br/>A1 内容生成"]
      A2["nl_filter<br/>A2 自然语言筛选"]
    end
    RP["repo<br/>参数化 SQL"]
    DBM["db<br/>连接、读事务、写事务"]
    CK["clock<br/>当前时间"]
  end
  AC -- "HTTP JSON" --> R
  R --> SV
  R --> AIM
  A1 --> CV
  S1 --> CV
  A2 --> S5
  A1 --> A0
  A2 --> A0
  SV --> PO
  SV --> CK
  SV --> RP
  AIM --> RP
  RP --> DBM
  DBM --> SQ[("SQLite")]
  A0 -. HTTPS .-> DS["DeepSeek"]
```

### 3.2 模块职责

| 模块 | 职责 | 不负责 |
|---|---|---|
| api 路由层 | 定义接口；Pydantic 入参出参；按 `X-User-Id` 解析身份并校验角色；把业务异常转成统一错误结构 | 任何业务判断 |
| activity_service | 活动的创建、编辑、发布、取消（含联动取消报名）；生成签到口令 | 发布后变更 |
| registration_service | 报名、进入候补、取消、递补；维护通知状态 | 签到 |
| checkin_service | 签到资格判断、重复签到拦截 | 生成口令 |
| change_service | 发布后变更的影响计算、预览指纹、确认执行 | — |
| query_service | 学生列表与筛选、详情、组织者名单、统计、操作记录查询 | 写操作 |
| content_validator | BR-22：事实一致、长度、敏感词校验，输出逐条问题；在发布、发布后编辑简介或注意事项、A1 预检时调用 | 改写内容 |
| policies | 可替换的规则：候补队首选择、退回候补人选、签到窗口、活动阶段计算 | 读写数据库 |
| ai.client | 调用 DeepSeek；处理超时；把失败分为 4 类（`AiFailure`）。测试用的假客户端在 `tests/fakes.py`，测试中通过 `create_app(…, ai_client)` 注入 | 业务含义 |
| ai.generator | A1 提示词、输出结构校验、模板降级（模板在 ai.templates）、写 AI 调用日志 | 保存或发布 |
| ai.nl_filter | A2 提示词、白名单解析、规则解析器降级、生成「使用字段」、写 AI 调用日志 | 执行查询（交给 query_service） |
| repo | 每张表的参数化 SQL 函数 | 事务边界（由服务层决定） |
| db | 建连接、设置 PRAGMA；提供读事务 `read_tx` 和写事务 `write_tx` | — |
| clock | 提供当前时间；测试中替换为固定时钟 | — |
| seed | 生成种子数据，时间相对 reset 时刻计算 | — |
| 前端 api 客户端 | 附加 `X-User-Id`；后端错误的 message 已是中文，直接展示；网络异常、非 JSON 错误补充中文提示；VALIDATION_ERROR 附字段名 | 加载状态（由各页面的按钮 loading 管理） |

### 3.3 目录结构

```
src/backend/
├── requirements.txt
└── app/
    ├── main.py            # 应用入口：create_app(settings, clock, ai_client, frontend_dist) 工厂、挂载路由、全局异常处理；存在 dist/index.html 时在所有 /api 路由之后把前端挂在「/」
    ├── config.py          # 配置项（§10.3）；预置标签库常量 TAG_LIBRARY
    ├── db.py              # 连接、PRAGMA、read_tx / write_tx；建表、删表
    ├── schema.sql         # 建表、约束、索引（§4）
    ├── clock.py           # SystemClock / FixedClock；数据库时间格式 to_db / from_db（§4.6）
    ├── errors.py          # 业务异常 AppError 与错误码表（§5.6）
    ├── deps.py            # 依赖注入：当前用户、角色校验、时钟、连接
    ├── schemas.py         # Pydantic 请求与响应模型
    ├── api/               # public.py / student.py / organizer.py / ai.py
    ├── services/          # activity.py / registration.py / checkin.py / query.py / policies.py / content_validator.py / change.py
    ├── ai/                # client.py / generator.py / nl_filter.py / templates.py
    ├── repo/              # users.py / activities.py / registrations.py / logs.py / ai_logs.py
    └── seed.py            # 种子数据（01-spec §7.1）；init_database（已存在则跳过）/ reset_database；demo_activities=False 时只导入账号（测试用）
tests/                     # conftest.py：每个测试独立的临时数据库 + 固定时钟 + 假 AI 客户端；helpers.py：造数、不变量检查（§7.4）；fakes.py：假 AI 客户端
└── ai_eval/               # cases_filter.json（16 条）/ cases_generate.json（8 条）/ run_eval.py / results/<mode>.json
pytest.ini                 # testpaths = tests，pythonpath = src/backend
src/frontend/
├── package.json           # 依赖版本锁定为精确值：vue 3.5.43、vue-router 5.4.0、element-plus 2.14.7、vite 8.3.4、@vitejs/plugin-vue 6.0.10
├── package-lock.json
├── vite.config.js         # 开发时把 /api 代理到 8000 端口；构建输出 dist/
├── index.html
└── src/
    ├── main.js            # 注册 Element Plus（中文语言包）与路由
    ├── App.vue            # 外壳：身份切换（下拉框，直接写在外壳中）、按角色导航、AI 配置状态、学生未读通知角标
    ├── api/client.js
    ├── store/session.js   # 当前身份、用户列表、/api/meta、未读通知数（简单的 reactive 对象，不引入 Pinia）
    ├── router.js          # hash 路由（#/activities 等），刷新任意页面都不需要后端回退规则
    ├── labels.js          # 阶段、报名状态、通知、操作日志动作的中文文案；时间格式化
    ├── views/student/     # ActivityList（手动筛选 + 一句话筛选）/ ActivityDetail（报名、取消、签到）/ MyRegistrations
    ├── views/organizer/   # Dashboard（汇总表）/ ActivityForm（新建与编辑、AI 生成、内容校验问题）/ ActivityManage（统计、口令、名单、操作记录、发布与取消）
    └── components/        # StatusTag / AiSourceTag / ChangePreviewDialog（发布后变更：修改 → 预览影响 → 确认）
```

---

## 4. 数据模型

### 4.1 ER 图

```mermaid
erDiagram
  USERS ||--o{ ACTIVITIES : "创建"
  USERS ||--o{ REGISTRATIONS : "报名"
  ACTIVITIES ||--o{ REGISTRATIONS : "拥有"
  ACTIVITIES ||--o{ OPERATION_LOGS : "被记录"
  AI_CALL_LOGS |o--o| ACTIVITIES : "内容生成来源"
  USERS {
    INTEGER id PK
    TEXT name
    TEXT role "student 或 organizer"
    TEXT grade "可空"
  }
  ACTIVITIES {
    INTEGER id PK
    TEXT title
    TEXT location
    TEXT start_at "UTC"
    TEXT end_at "UTC"
    TEXT deadline_at "UTC"
    INTEGER capacity "至少为 1"
    TEXT tags "JSON 数组"
    TEXT summary
    TEXT notes "JSON 数组"
    TEXT status "DRAFT PUBLISHED CANCELLED"
    TEXT checkin_code "6 位，可空"
    INTEGER created_by FK
    INTEGER ai_call_id FK "可空"
  }
  REGISTRATIONS {
    INTEGER id PK
    INTEGER activity_id FK "与 student_id 联合唯一"
    INTEGER student_id FK
    TEXT status "REGISTERED WAITLISTED CANCELLED"
    TEXT registered_at "最近一次成为已报名的时间"
    INTEGER wait_seq "候补序号，越小越靠前"
    TEXT cancel_reason "BY_STUDENT 或 BY_ACTIVITY"
    TEXT checked_in_at "可空"
    TEXT notify_status "NONE UNREAD READ"
    TEXT notify_message
  }
  OPERATION_LOGS {
    INTEGER id PK
    TEXT occurred_at
    INTEGER actor_id "系统操作时为空"
    TEXT actor_role "student organizer system"
    TEXT action
    INTEGER activity_id FK
    INTEGER target_student_id
    TEXT detail "JSON"
  }
  AI_CALL_LOGS {
    INTEGER id PK
    TEXT occurred_at
    TEXT feature "GENERATE 或 NL_FILTER"
    TEXT mode "MODEL 或 FALLBACK"
    TEXT fallback_reason "可空"
    INTEGER latency_ms
    TEXT input_summary
    TEXT output "模型原始输出或降级输出"
  }
```

### 4.2 表结构与约束

**users**（种子数据预置，不提供注册）

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | PRIMARY KEY | |
| name | TEXT | NOT NULL | |
| role | TEXT | NOT NULL，CHECK IN ('student','organizer') | |
| grade | TEXT | 可空 | 年级，目前只用于展示 |

**activities**

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | PRIMARY KEY | |
| title | TEXT | NOT NULL | 长度上限由应用层按配置校验 |
| location | TEXT | NOT NULL | |
| start_at / end_at / deadline_at | TEXT | NOT NULL | UTC 时间（§4.6） |
| capacity | INTEGER | NOT NULL，CHECK (capacity >= 1) | 上限 1000 由应用层按配置校验 |
| tags | TEXT | NOT NULL DEFAULT '[]'，CHECK (json_valid(tags)) | 取值必须在标签库内，由应用层校验 |
| summary | TEXT | NOT NULL DEFAULT '' | |
| notes | TEXT | NOT NULL DEFAULT '[]'，CHECK (json_valid(notes)) | 注意事项数组 |
| status | TEXT | NOT NULL DEFAULT 'DRAFT'，CHECK IN ('DRAFT','PUBLISHED','CANCELLED') | |
| checkin_code | TEXT | 可空，CHECK (checkin_code IS NULL OR length(checkin_code) = 6) | |
| created_by | INTEGER | NOT NULL，FK → users(id) | |
| ai_call_id | INTEGER | 可空，FK → ai_call_logs(id) | 内容来自哪次 AI 生成，用于 AC-21 对照 |
| created_at / updated_at | TEXT | NOT NULL | |
| published_at / cancelled_at | TEXT | 可空 | |
| — | — | CHECK (deadline_at <= start_at AND start_at < end_at) | 时间顺序在数据库层兜底（BR-21） |
| — | — | CHECK (status = 'DRAFT' OR published_at IS NOT NULL) | |
| — | — | CHECK (status <> 'CANCELLED' OR cancelled_at IS NOT NULL) | |

> 草稿创建时就必须填好标题、时间、地点、名额、截止时间，因为 AI 生成依赖这些字段（DEC-03、BR-24）。草稿阶段只有简介、标签、注意事项可以为空。

**registrations**

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | PRIMARY KEY | |
| activity_id | INTEGER | NOT NULL，FK → activities(id) | |
| student_id | INTEGER | NOT NULL，FK → users(id) | |
| status | TEXT | NOT NULL，CHECK IN ('REGISTERED','WAITLISTED','CANCELLED') | |
| registered_at | TEXT | 可空 | 最近一次成为已报名的时间，BR-13 按它决定谁先退回候补 |
| wait_seq | INTEGER | 可空 | 候补序号：入队时取当前最大值 + 1；退回候补的 k 人取当前最小值 − k … 最小值 − 1（候补为空时以 1 为基准），因此可能为 0 或负数 |
| waitlisted_at | TEXT | 可空 | 进入候补的时间，仅用于展示 |
| cancel_reason | TEXT | 可空，CHECK IN ('BY_STUDENT','BY_ACTIVITY') | |
| cancelled_at | TEXT | 可空 | |
| checked_in_at | TEXT | 可空 | 有值即为已签到 |
| notify_status | TEXT | NOT NULL DEFAULT 'NONE'，CHECK IN ('NONE','UNREAD','READ') | BR-29 |
| notify_message | TEXT | 可空 | 最近一条通知的内容 |
| created_at / updated_at | TEXT | NOT NULL | |
| — | — | **UNIQUE (activity_id, student_id)** | R1：一人一活动只有一条记录；再报名时复用这条记录（D4） |
| — | — | CHECK ((status = 'WAITLISTED') = (wait_seq IS NOT NULL)) | 只有候补中的记录才有候补序号 |
| — | — | CHECK (status <> 'REGISTERED' OR registered_at IS NOT NULL) | |
| — | — | CHECK (status <> 'CANCELLED' OR cancel_reason IS NOT NULL) | |
| — | — | CHECK (checked_in_at IS NULL OR status = 'REGISTERED') | 只有已报名才能签到；已签到的记录不能取消，也不能退回候补 |

> 「已报名人数 ≤ 名额」涉及多行数据，单表 CHECK 表达不了，由写锁事务保证（§7、DEC-02）。

**operation_logs**（BR-30，只追加不修改）

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | PRIMARY KEY | |
| occurred_at | TEXT | NOT NULL | |
| actor_id | INTEGER | 可空 | 系统操作（递补、退回候补、联动取消）时为空 |
| actor_role | TEXT | NOT NULL，CHECK IN ('student','organizer','system') | |
| action | TEXT | NOT NULL | CREATE / UPDATE / PUBLISH / CANCEL_ACTIVITY / CODE_RESET / REGISTER / WAITLIST / CANCEL / PROMOTE / DEMOTE / CHECKIN / CHANGE_CONFIRM |
| activity_id | INTEGER | 可空，FK → activities(id) | |
| target_student_id | INTEGER | 可空 | |
| detail | TEXT | NOT NULL DEFAULT '{}' | JSON，例如候补位次、变更前后的值 |

**ai_call_logs**（BR-30）

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | PRIMARY KEY | |
| occurred_at | TEXT | NOT NULL | |
| actor_id | INTEGER | 可空 | |
| feature | TEXT | NOT NULL，CHECK IN ('GENERATE','NL_FILTER') | |
| mode | TEXT | NOT NULL，CHECK IN ('MODEL','FALLBACK') | |
| fallback_reason | TEXT | 可空，CHECK IN ('NO_KEY','TIMEOUT','CALL_FAILED','INVALID_OUTPUT') | |
| model | TEXT | 可空 | |
| latency_ms | INTEGER | NOT NULL | |
| input_summary | TEXT | NOT NULL | 截断到 500 字；**不含密钥和请求头** |
| output | TEXT | NOT NULL | 模型原始输出或降级输出（截断到 4000 字） |

### 4.3 索引

| 索引 | 定义 | 类型 | 用途 |
|---|---|---|---|
| uq_reg_activity_student | registrations(activity_id, student_id) | UNIQUE | R1 唯一报名；按「活动 + 学生」查找记录 |
| uq_reg_wait_seq | registrations(activity_id, wait_seq) WHERE status = 'WAITLISTED' | UNIQUE 部分索引 | 候补序号不重复（AC-07）；快速取队首 |
| idx_reg_activity_status | registrations(activity_id, status) | 普通 | 统计已报名人数、组织者名单 |
| idx_reg_student | registrations(student_id) | 普通 | 我的报名 |
| idx_act_status_start | activities(status, start_at) | 普通 | 学生列表、日期筛选 |
| idx_log_activity | operation_logs(activity_id, occurred_at) | 普通 | 活动的操作记录、递补人次统计 |
| idx_ai_log_time | ai_call_logs(occurred_at) | 普通 | 排查、评测 |

连接级设置：`PRAGMA foreign_keys = ON`；初始化时设置 `PRAGMA journal_mode = WAL`（持久生效）；busy_timeout 取配置值（默认 5000 ms）。

### 4.4 报名记录状态机

```mermaid
stateDiagram-v2
  [*] --> REGISTERED: 报名，有余量
  [*] --> WAITLISTED: 报名，已满
  WAITLISTED --> REGISTERED: 递补（候补序号最小者优先）
  REGISTERED --> WAITLISTED: 缩减名额，退回候补队首
  REGISTERED --> CANCELLED: 学生取消（未签到）或活动取消
  WAITLISTED --> CANCELLED: 学生取消或活动取消
  CANCELLED --> REGISTERED: 再报名，有余量（复用原记录）
  CANCELLED --> WAITLISTED: 再报名，已满（排在队尾）
  REGISTERED --> REGISTERED: 签到（写入签到时间）
```

活动状态只有存储状态 `DRAFT → PUBLISHED → CANCELLED`。所处阶段（报名中、已截止、进行中、已结束）按 §4.5 实时计算；各状态下允许哪些操作，以 01-spec §6.9 的矩阵为准。

### 4.5 派生数据（不落库，读取时计算）

| 数据 | 计算方式 | 所在模块 |
|---|---|---|
| 活动阶段 `phase` | 草稿、已取消直接取存储状态（`DRAFT`、`CANCELLED`）；已发布按 now 与 deadline_at、start_at、end_at 比较：`OPEN` 报名中 / `CLOSED` 已截止 / `ONGOING` 进行中 / `ENDED` 已结束（01-spec §3.2） | policies |
| 签到窗口 | [start_at − 签到窗口提前量, end_at] | policies |
| 剩余名额 | capacity − 已报名记录数 | query_service |
| 候补位次 | 同一活动中，候补序号 ≤ 本人序号的候补记录数 | query_service |
| 展示状态 `display_status` | `REGISTERED`；已报名且已签到为 `CHECKED_IN`；`WAITLISTED`；候补中且 now ≥ start_at 为 `WAITLIST_EXPIRED`（「候补失效，活动已开始」，位次为空）；`CANCELLED` | query_service |
| 统计数字 | 按 BR-28 计算；递补人次 = 该活动 action = PROMOTE 的日志条数 | query_service |

### 4.6 时间存储约定
- 数据库统一存 UTC，格式固定为 `YYYY-MM-DDTHH:MM:SSZ`。格式定长，所以字符串比较等同于时间比较，CHECK 约束和日期筛选可以直接用。
- 接口收发带时区偏移的 ISO 8601 时间，例如 `2026-10-20T14:00:00+08:00`。
- 「今天」「本周」等日期边界按配置的时区计算（默认 `Asia/Shanghai`，见 §10.3）。

---

## 5. 关键接口

### 5.1 通用约定

| 项 | 约定 |
|---|---|
| 基础路径 | `/api`，JSON，UTF-8 |
| 身份 | 请求头 `X-User-Id: <用户 ID>`；缺失、不是整数或用户不存在 → 401；角色不符 → 403。`/api/health`、`/api/users`、`/api/meta` 不需要身份 |
| 成功响应 | 200 / 201，返回资源 JSON |
| 错误响应 | `{"code": "错误码", "message": "中文提示", "details": { … 可选 }}` |
| HTTP 状态 | 400 业务输入不合法；401 未识别身份；403 无权限；404 不存在；409 状态冲突；422 请求结构不合法；503 系统繁忙；500 未预期错误 |
| AI 接口 | 模型失败时**不返回错误**，返回 200 + 降级结果，并在 `source` 中标明模式和原因 |

公共数据对象：
- **ActivityBrief**：`id, title, location, start_at, end_at, tags, capacity, registered_count, remaining, phase`
- **ActivityDetail**：在 ActivityBrief 基础上加 `deadline_at, summary, notes, waitlist_count, my_registration`（未报名过为 null）
- **RegistrationView**（学生的 my_registration 与组织者名单共用）：`status, display_status, cancel_reason, waitlist_position, registered_at, checked_in_at, notify_status, notify_message`
- **Stats**：`registered, waitlisted, checked_in, cancelled, checkin_rate（0–1）, promoted_count`
- **ActivitySummary**（组织者汇总表一行）：ActivityBrief + `status, stats`
- **OrganizerActivity**：ActivitySummary + `deadline_at, summary, notes, checkin_code, ai_call_id, created_at, published_at, cancelled_at`
- **AiSource**：`mode (MODEL | FALLBACK), reason (NO_KEY | TIMEOUT | CALL_FAILED | INVALID_OUTPUT | null), reason_text（原因的中文，如「未配置 API 密钥」）, model（降级时为 null）`

### 5.2 公共接口

| 方法与路径 | 输入 | 输出 | 错误码 |
|---|---|---|---|
| GET `/api/health` | — | `{status: "ok"}` | — |
| GET `/api/users` | — | `[{id, name, role}]`，供身份切换使用 | — |
| GET `/api/meta` | — | `{tag_library, checkin_open_before_minutes, limits, ai_enabled}`；`ai_enabled` 只是布尔值，不暴露密钥 | — |

### 5.3 学生端接口（角色：student）

| 方法与路径 | 输入 | 输出 | 错误码 | AC |
|---|---|---|---|---|
| GET `/api/activities` | query：`keyword`（标题或简介包含）`, tags`（逗号分隔，命中任一即可）`, date_from, date_to`（`YYYY-MM-DD`，按配置时区的自然日对开始时间筛选）`, has_seats`；条件之间为「且」 | `ActivityBrief[]`，只包含已发布且未取消的活动，按开始时间排序 | VALIDATION_ERROR（含 date_from 晚于 date_to） | AC-27 |
| GET `/api/activities/{id}` | — | `ActivityDetail`；草稿返回 404；已取消的活动可以看到详情，并标明已取消 | ACTIVITY_NOT_FOUND | AC-19、27 |
| POST `/api/activities/{id}/registration` | — | 201 `{status, waitlist_position}` | ACTIVITY_NOT_FOUND、ACTIVITY_CANCELLED、ACTIVITY_STARTED、REG_DEADLINE_PASSED、ALREADY_REGISTERED、ALREADY_WAITLISTED、SYSTEM_BUSY | AC-01、02、05~09 |
| DELETE `/api/activities/{id}/registration` | — | `{status: "CANCELLED", promoted_count}` | NOT_REGISTERED、ACTIVITY_CANCELLED、ACTIVITY_STARTED、CANCEL_AFTER_CHECKIN、SYSTEM_BUSY | AC-03、04、08、09 |
| POST `/api/activities/{id}/checkin` | `{code}`（1–20 字符；格式不对按口令错误处理） | `{checked_in_at}` | ACTIVITY_CANCELLED、CHECKIN_NOT_OPEN、CHECKIN_CLOSED、CHECKIN_NOT_REGISTERED、CHECKIN_WAITLISTED、ALREADY_CHECKED_IN、CHECKIN_CODE_INVALID | AC-10~12 |
| GET `/api/me/registrations` | — | `[{activity: ActivityBrief, registration: RegistrationView}]`，包含已取消的活动和记录；只读，不改变通知状态 | — | AC-03、13 |
| POST `/api/me/notifications/read` | — | `{updated}`：把本人所有 UNREAD 置为 READ；页面加载「我的报名」后调用 | — | AC-03 |
| POST `/api/ai/nl-filter` | `{query}`（1–200 字） | `{conditions: {keyword, tags, date_from, date_to, location, has_seats}（未生效的为 null / [] / false）, used_fields, items: ActivityBrief[], source: AiSource, message}`；message 为「找到 N 个符合条件的活动」「没有符合条件的活动」或「未识别出筛选条件，请换个说法」 | VALIDATION_ERROR | AC-24、25 |

### 5.4 组织者端接口（角色：organizer，前缀 `/api/organizer`）

| 方法与路径 | 输入 | 输出 | 错误码 | AC |
|---|---|---|---|---|
| GET `/activities` | — | `ActivitySummary[]`：全部活动（含草稿、已取消）+ 每个活动的统计，即汇总表 | — | AC-28 |
| POST `/activities` | `{title, location, start_at, end_at, deadline_at, capacity, tags?, summary?, notes?, ai_call_id?}`；时间必须带时区偏移；未知字段 → 422 | 201 `OrganizerActivity`（DRAFT） | FIELD_INVALID（details.field 指出字段） | AC-19 |
| GET `/activities/{id}` | — | `OrganizerActivity`（含签到口令） | ACTIVITY_NOT_FOUND | — |
| PUT `/activities/{id}` | 只提交要改的字段。草稿：全部字段；已发布：只能改 `title, summary, tags, notes`，提交与原值相同的名额等字段不算修改 | `OrganizerActivity` | FIELD_INVALID、CONTENT_INVALID（发布后编辑简介或注意事项时）、ACTIVITY_NOT_EDITABLE（已结束、已取消）、USE_CHANGE_FLOW（details.fields 列出字段） | AC-19、22 |
| POST `/activities/{id}/publish` | — | 活动（PUBLISHED） | FIELD_INVALID、CONTENT_INVALID、ACTIVITY_NOT_EDITABLE | AC-19、21、22 |
| POST `/activities/{id}/cancel` | — | `{cancelled_registrations}` | ACTIVITY_NOT_EDITABLE（不是已发布）、CHANGE_LOCKED | AC-13、18 |
| POST `/activities/{id}/checkin-code` | — | `{code}`：新口令，旧口令立即失效 | ACTIVITY_NOT_EDITABLE | AC-10、12 |
| GET `/activities/{id}/registrations` | — | `[{student_id, student_name, …RegistrationView}]`，按已报名、候补、已取消排序 | ACTIVITY_NOT_FOUND | AC-03、10 |
| GET `/activities/{id}/stats` | — | `{registered, waitlisted, checked_in, cancelled, checkin_rate, promoted_count}` | — | AC-28 |
| GET `/activities/{id}/logs` | — | `[{id, occurred_at, actor_id, actor_name（系统操作为「系统」）, actor_role, action, target_student_id, target_student_name, detail}]`，按时间倒序 | ACTIVITY_NOT_FOUND | AC-30 |
| POST `/activities/{id}/changes/preview` | `{capacity?, deadline_at?, start_at?, end_at?, location?}`；与当前值相同的字段不算调整 | `{changes: {字段: {from, to}}, demoted[], promoted[], notified[], waitlist_after[], preview_token}`，名单项为 `{student_id, student_name}`；demoted 按「成为已报名最晚」在前 | FIELD_INVALID（含「没有需要调整的字段」「活动开始时间必须晚于当前时间」）、CHANGE_LOCKED、ACTIVITY_NOT_EDITABLE（不是已发布）、ACTIVITY_NOT_FOUND | AC-14、15、17 |
| POST `/activities/{id}/changes/confirm` | 与预览相同的字段 + `preview_token` | 与预览相同的影响字段 + `activity`（OrganizerActivity） | PREVIEW_STALE、CHANGE_LOCKED、FIELD_INVALID、ACTIVITY_NOT_EDITABLE、SYSTEM_BUSY | AC-14~18 |
| POST `/ai/generate` | `{title, description（≤ 500 字）, location, start_at, end_at, capacity}` | `{summary, tags, notes, issues[], source: AiSource, ai_call_id}`；`issues` 是校验器的预检结果，结构同 CONTENT_INVALID 的 details；不保存任何活动 | VALIDATION_ERROR | AC-20、23 |

### 5.5 业务检查顺序（保证同一情形总是返回同一个错误码）
- **报名**：活动存在且对学生可见 → 未取消 → 未开始 → 未截止 → 本人记录不是已报名或候补中 → 判断名额。
- **取消**：活动未取消 → 未开始 → 本人有已报名或候补中的记录 → 尚未签到。
- **签到**：活动未取消 → 在签到窗口内 → 本人记录为已报名（否则区分「未报名」和「候补中」）→ 尚未签到 → 口令正确。
- **发布后变更 / 取消活动**：活动已发布 → 签到窗口尚未开放 → 字段合法 →（确认时）预览指纹一致。
- **发布**：是草稿 → 保存时的字段校验 → 标签 1–5 个 → 截止时间晚于当前 → 内容校验（BR-22）。
- **编辑**：活动存在 → 未结束、未取消 → 已发布时不能改名额、时间、地点、截止时间 → 字段校验。

### 5.6 错误码表

| 错误码 | HTTP | 中文提示（前端展示） | AC |
|---|---|---|---|
| VALIDATION_ERROR | 422 | 请求参数不合法（details 中给出具体字段） | AC-31 |
| UNAUTHENTICATED | 401 | 请先选择身份 | — |
| FORBIDDEN | 403 | 无权限 | AC-31 |
| NOT_FOUND | 404 | 资源不存在（框架层：路由不存在） | — |
| METHOD_NOT_ALLOWED | 405 | 请求方法不被允许（框架层） | — |
| ACTIVITY_NOT_FOUND | 404 | 活动不存在 | AC-19 |
| FIELD_INVALID | 400 | 按具体字段给出，例如「报名截止时间不能晚于活动开始时间」 | AC-19 |
| CONTENT_INVALID | 400 | 内容校验未通过：<各条原因，以「；」分隔>（details 为 `[{field, rule, text, message}]`，rule 取 DATE_MISMATCH / TIME_MISMATCH / COUNT_MISMATCH / TOO_LONG / TOO_MANY / SENSITIVE） | AC-22 |
| CHECKIN_CODE_INVALID | 400 | 签到口令错误 | AC-12 |
| ALREADY_REGISTERED | 409 | 您已报名该活动 | AC-05 |
| ALREADY_WAITLISTED | 409 | 您已在候补队列中（第 N 位） | AC-05 |
| REG_DEADLINE_PASSED | 409 | 报名已截止 | AC-08 |
| ACTIVITY_STARTED | 409 | 活动已开始（取消时提示「活动已开始，无法取消」） | AC-09 |
| ACTIVITY_CANCELLED | 409 | 活动已取消 | AC-13 |
| NOT_REGISTERED | 409 | 您没有可取消的报名 | — |
| CANCEL_AFTER_CHECKIN | 409 | 已签到，不能取消报名 | — |
| CHECKIN_NOT_OPEN | 409 | 签到尚未开始 | AC-12 |
| CHECKIN_CLOSED | 409 | 签到已结束 | AC-12 |
| CHECKIN_NOT_REGISTERED | 409 | 您未报名该活动 | AC-12 |
| CHECKIN_WAITLISTED | 409 | 您在候补中，未获得名额，无法签到 | AC-12 |
| ALREADY_CHECKED_IN | 409 | 您已于 HH:MM 签到，请勿重复签到（HH:MM 按配置时区；details.checked_in_at 为完整时间） | AC-11 |
| ACTIVITY_NOT_EDITABLE | 409 | 当前状态不允许此操作 | — |
| USE_CHANGE_FLOW | 409 | 已发布活动的名额、时间、地点、截止时间需通过「预览 → 确认」修改 | — |
| CHANGE_LOCKED | 409 | 签到已开放，活动不可再调整或取消 | AC-18 |
| PREVIEW_STALE | 409 | 报名数据已变化，请重新预览 | AC-16 |
| SYSTEM_BUSY | 503 | 系统繁忙，请稍后重试 | — |
| INTERNAL_ERROR | 500 | 服务器内部错误 | — |

实现：`app/errors.py` 的 `ERROR_TABLE` 即本表；业务代码只抛 `AppError(code, message=None, details=None)`，`message` 为空时取表中的默认提示，带变量的提示（如候补位次、签到时间）由调用方传入。`main.py` 中的全局处理器把 `AppError`、Pydantic 校验错误、框架层 HTTP 错误和未预期异常都转成 `{code, message, details?}`；500 响应不包含异常内容。

---

## 6. 主流程时序

### 6.1 报名（名额未满 / 满员进入候补）

```mermaid
sequenceDiagram
  autonumber
  actor S as 学生
  participant FE as Vue 前端
  participant API as FastAPI 路由
  participant RS as registration_service
  participant DB as SQLite
  S->>FE: 点击「报名」
  FE->>API: POST /api/activities/{id}/registration（带 X-User-Id）
  API->>API: 解析身份，校验角色为学生
  API->>RS: register(activity_id, student_id, now)
  RS->>DB: BEGIN IMMEDIATE（获取写锁，其他写事务排队等待）
  RS->>DB: 读取活动
  alt 活动不可见 / 已取消 / 已开始 / 已截止
    RS->>DB: ROLLBACK
    RS-->>API: 业务错误
    API-->>FE: 404 或 409 {code, message}
  else 可以报名
    RS->>DB: 读取该学生在本活动的记录
    alt 已报名或候补中
      RS->>DB: ROLLBACK
      RS-->>API: ALREADY_REGISTERED 或 ALREADY_WAITLISTED
      API-->>FE: 409
    else 无记录或已取消
      RS->>DB: 统计已报名人数
      alt 已报名人数小于名额
        RS->>DB: 插入或复用记录，状态 REGISTERED，registered_at = now
        RS->>DB: 写日志 REGISTER
      else 已满
        RS->>DB: 插入或复用记录，状态 WAITLISTED，wait_seq = 当前最大值 + 1
        RS->>DB: 写日志 WAITLIST
      end
      RS->>DB: COMMIT（释放写锁）
      RS-->>API: 状态与候补位次
      API-->>FE: 201
    end
  end
  FE-->>S: 「报名成功」/「名额已满，已加入候补，第 N 位」/ 错误提示
```

### 6.2 取消 → 自动递补 → 通知变为已读

```mermaid
sequenceDiagram
  autonumber
  actor S1 as 学生 S1（已报名）
  actor S3 as 学生 S3（候补第 1 位）
  participant API as FastAPI
  participant RS as registration_service
  participant PO as policies
  participant DB as SQLite
  S1->>API: DELETE /api/activities/{id}/registration
  API->>RS: cancel(activity_id, S1, now)
  RS->>DB: BEGIN IMMEDIATE
  RS->>DB: 读取活动与 S1 的记录
  alt 活动已取消 / 已开始 / S1 无有效记录 / S1 已签到
    RS->>DB: ROLLBACK
    RS-->>API: 业务错误
  else 允许取消
    RS->>DB: S1 改为 CANCELLED（BY_STUDENT），写日志 CANCEL
    opt S1 原状态为 REGISTERED，且活动未开始
      loop 已报名人数小于名额，且仍有候补
        RS->>PO: 选出下一位递补者
        PO-->>RS: 候补序号最小者 S3
        RS->>DB: S3 改为 REGISTERED，registered_at = now，wait_seq 置空
        RS->>DB: S3 的通知状态置为 UNREAD，写入通知内容
        RS->>DB: 写日志 PROMOTE（操作人：系统）
      end
    end
    RS->>DB: COMMIT（取消与递补在同一事务内生效）
    RS-->>API: 取消成功，promoted_count = 1
  end
  API-->>S1: 「已取消报名」
  Note over S3,DB: 之后 S3 打开「我的报名」
  S3->>API: GET /api/me/registrations
  API-->>S3: 显示「您已从候补递补为正式报名」（未读）
  S3->>API: POST /api/me/notifications/read
  API->>DB: UNREAD 改为 READ（写事务）
```

### 6.3 签到与重复签到拦截

```mermaid
sequenceDiagram
  autonumber
  actor O as 组织者
  actor S as 学生
  participant API as FastAPI
  participant CS as checkin_service
  participant DB as SQLite
  O->>API: POST /api/organizer/activities/{id}/checkin-code
  API->>DB: 写事务：用 secrets 生成 6 位口令并覆盖旧口令，写日志 CODE_RESET
  API-->>O: 482915（大字显示）
  S->>API: POST /api/activities/{id}/checkin {code}
  API->>CS: checkin(activity_id, student_id, code, now)
  CS->>DB: BEGIN IMMEDIATE
  CS->>DB: 读取活动与该学生的记录
  alt 活动已取消 / 不在签到窗口 / 未报名 / 候补中
    CS->>DB: ROLLBACK
    CS-->>API: 对应错误码
  else 已有签到时间
    CS->>DB: ROLLBACK
    CS-->>API: ALREADY_CHECKED_IN（附首次签到时间）
  else 口令不一致
    CS->>DB: ROLLBACK
    CS-->>API: CHECKIN_CODE_INVALID
  else 全部通过
    CS->>DB: 写入签到时间，写日志 CHECKIN
    CS->>DB: COMMIT
    CS-->>API: 签到时间
  end
  API-->>S: 签到成功，或中文错误提示
```

同一学生并发提交两次签到时，第二个请求会在写锁上等待；拿到锁后读到已有签到时间，返回 ALREADY_CHECKED_IN（AC-11）。

### 6.4 发布后变更：预览 → 确认（含过期检测）

```mermaid
sequenceDiagram
  autonumber
  actor O as 组织者
  participant API as FastAPI
  participant CH as change_service
  participant PO as policies
  participant DB as SQLite
  O->>API: POST .../changes/preview {capacity: 2}
  API->>CH: preview(activity_id, change, now)
  CH->>DB: 只读事务（BEGIN DEFERRED）：读取活动与全部报名记录
  CH->>CH: 校验时机（签到窗口未开放）与字段合法性
  CH->>PO: 选出退回候补的人（成为已报名最晚的 k 人）
  CH->>CH: 计算影响：退回候补 / 递补 / 需通知 / 调整后的候补顺序
  CH->>CH: preview_token = 哈希(活动字段 + 各报名记录的状态与序号 + 变更参数)
  CH-->>O: 影响列表 + preview_token（数据未修改）
  O->>API: POST .../changes/confirm {capacity: 2, preview_token}
  API->>CH: confirm(activity_id, change, token, now)
  CH->>DB: BEGIN IMMEDIATE
  CH->>DB: 重新读取，重新计算指纹
  alt 指纹不一致（预览后有人报名或取消，或字段被改过）
    CH->>DB: ROLLBACK
    CH-->>O: 409 PREVIEW_STALE「报名数据已变化，请重新预览」
  else 指纹一致
    CH->>DB: 更新活动字段
    CH->>DB: 按计算结果更新报名记录：退回候补 / 递补 / 通知 UNREAD
    CH->>DB: 写日志 CHANGE_CONFIRM、DEMOTE、PROMOTE
    CH->>DB: COMMIT（任一步异常则全部 ROLLBACK，满足 AC-18）
    CH-->>O: 200 调整完成
  end
```

实现要点（`services/change.py`）：
- 预览和确认共用同一套检查（已发布 → 签到窗口未开放 → 字段合法）和同一个影响计算函数；确认时先检查，再比对指纹。
- 指纹内容：活动的标题、简介、标签、注意事项、状态、updated_at 和 5 个可调整字段，全部报名记录的 (id, 状态, 候补序号, registered_at, checked_in_at)，以及本次变更参数。确认参数与预览不同也会被拒绝。
- 退回候补的人选由 `policies.pick_demotions` 决定（registered_at 最晚者优先，同一时刻按记录先后）；递补复用 `registration.promote_waitlist`，与预览使用同一套 FIFO 规则，结果不一致时抛异常回滚。
- 通知文案：时间或地点变更「活动时间或地点已变更：<活动名>，请查看最新信息」；退回候补「活动名额调整，您已退回候补：<活动名>」；被递补者使用递补通知（BR-07），后写的通知覆盖先写的。
- 只改报名截止时间时不通知，也不改变任何记录的状态（BR-15）。

### 6.5 并发报名的串行化（两个请求抢最后 1 个名额）

```mermaid
sequenceDiagram
  participant A as 请求 A（学生 S7）
  participant B as 请求 B（学生 S8）
  participant DB as SQLite（只剩 1 个名额）
  A->>DB: BEGIN IMMEDIATE
  Note right of DB: A 拿到写锁
  B->>DB: BEGIN IMMEDIATE
  Note right of DB: B 拿不到锁，在 busy_timeout 内反复重试
  A->>DB: 统计已报名人数 = 名额 − 1，还有余量
  A->>DB: 插入 REGISTERED
  A->>DB: COMMIT（释放写锁）
  Note right of DB: B 拿到写锁
  B->>DB: 统计已报名人数 = 名额，已满
  B->>DB: 插入 WAITLISTED（候补第 1 位）
  B->>DB: COMMIT
```

---

## 7. 并发与事务设计


### 7.1 连接与事务
- **连接参数**：每个请求使用一个独立连接，请求结束后关闭；连接不在请求之间共享。参数如下：
  - `isolation_level=None`：关闭驱动的隐式事务（见 7.3）；
  - `timeout=<DB_BUSY_TIMEOUT_MS>`；
  - `check_same_thread=False`：FastAPI 的同步依赖项和接口函数可能运行在线程池的不同线程上，连接只被当前请求使用，因此安全。
- **`read_tx`**：`BEGIN DEFERRED … COMMIT`。在 WAL 模式下拿到一致快照，不阻塞写入。用于列表、详情、预览。
- **`write_tx`**：`BEGIN IMMEDIATE … COMMIT`。事务一开始就拿写锁，所以「读取 → 判断 → 写入」整体原子。出现异常就 ROLLBACK；等锁超时（`database is locked`）则转成 503 SYSTEM_BUSY。

### 7.2 写路径清单（全部经过 `write_tx`，代码审查时逐条核对）
报名、取消（含递补）、签到、生成口令、创建/编辑/发布活动、取消活动（含联动取消）、变更确认（含退回候补与递补）、通知置为已读、写 AI 调用日志。

### 7.3 驱动陷阱
Python 3.11 的 `sqlite3` 默认只在执行 INSERT、UPDATE、DELETE 前隐式开启事务，执行 SELECT 时不开。如果沿用默认行为，「统计已报名人数」会在事务和写锁之外执行，多个请求可能同时读到「还剩 1 个名额」，然后先后都写入成功，造成超卖。所以必须设置 `isolation_level=None`，并显式执行 `BEGIN IMMEDIATE`。并发测试专门验证这一点，结果见 §7.6。

第二个陷阱：`executescript()` 执行前会先隐式 COMMIT 当前事务。所以建表脚本 `schema.sql` 不用 `executescript`，而是用 `sqlite3.complete_statement` 切成单条语句，在 `write_tx` 内逐条执行；这样 `reset` 的「删表 → 建表 → 导入种子」是一个事务，要么全部生效，要么全部回滚。

### 7.4 不变量（每个并发测试结束后都检查）
| 编号 | 不变量 | 保证方式 |
|---|---|---|
| I1 | 每个活动的已报名人数 ≤ 名额 | 写锁事务（锁内计数） |
| I2 | 每个「活动 + 学生」只有一条记录 | UNIQUE 约束 + 锁内检查 |
| I3 | 同一活动的候补序号不重复 | 部分唯一索引 + 锁内分配序号 |
| I4 | 只有已报名的记录才可能有签到时间 | CHECK 约束 |

检查实现：`tests/helpers.py` 的 `assert_invariants(conn)`，用 SQL 对全库逐条检查 I1–I4。

### 7.5 已知限制
- 写锁是整库级别的，不同活动的写操作也要排队。演示规模下每个写事务只需几毫秒，没有问题。
- SQLite 的等锁重试不是先来先得，所以毫秒级并发时，候补顺序等于「拿到写锁的顺序」，不严格等于请求到达的顺序。
- 只能单进程、单实例部署。迁移到 PostgreSQL 时，把整库写锁换成对活动行的 `SELECT … FOR UPDATE`，业务服务层不用改。

### 7.6 并发验证结果

测试文件 `tests/test_concurrency.py`。每个线程使用独立连接（与「每个请求一个连接」一致），用 `threading.Barrier` 让所有线程同时开始。

| 测试 | 做法 | 结果 |
|---|---|---|
| 20 人抢 5 个名额 | 分两组：不加等待；在「统计已报名人数」后人为等待 20 ms，放大竞态窗口 | 两组都是恰好 5 人已报名、15 人候补，位次 1–15 不重复，没有异常，I1–I4 成立 |
| 同一学生并发报名 2 次 | 分两组：有余量（走已报名路径）；已满（走候补路径） | 只产生 1 条记录；另一个请求得到 ALREADY_REGISTERED / ALREADY_WAITLISTED |
| 对照组：不用写锁 | 沿用驱动默认的隐式事务，SELECT 在事务外，「查人数 → 等 50 ms → 写入」 | 必然超卖（单独运行 3 次，名额 5 时已报名都是 20 人），证明上面的测试是真并发，不是碰巧串行 |

并发测试连续运行 10 轮全部通过。结论：写锁方案（DEC-02 方案 B）有效，不需要启用 RK1 的备选方案。

M2 补充经过 HTTP 接口的并发测试（多个线程共用 FastAPI TestClient；同步接口在线程池中执行）：

| 测试 | 结果 |
|---|---|
| 20 个报名请求同时发出（AC-07） | 全部 201，没有 5xx；恰好 5 人已报名，候补位次 1–15 |
| 同一学生同时提交 2 次签到（AC-11） | 一个 200、一个 409 ALREADY_CHECKED_IN；签到日志只有 1 条 |
| 3 个「已报名者取消」与 5 个「新报名」同时发出 | 递补恰好 3 次；结束时已报名仍为 5，候补 7 人，I1–I4 成立 |

另外用一次性探针确认请求在服务端是真并发：20 个请求同时进入报名函数的峰值为 20，最终由写锁串行化。

---

## 8. AI 调用链


### 8.1 A1 活动内容生成

```mermaid
flowchart TD
  F["组织者填写结构化字段 + 一句话描述"] --> G["POST /api/organizer/ai/generate"]
  G --> K{"是否配置了密钥"}
  K -- 否 --> T["模板生成器<br/>关键词匹配标签 + 通用注意事项"]
  K -- 是 --> P["组装提示词<br/>字段作为 JSON 数据注入<br/>要求不写日期、时刻、地点、人数，只输出 JSON"]
  P --> C["DeepSeek chat/completions<br/>JSON 输出模式，超时 15 秒"]
  C -- "超时或调用失败" --> T
  C --> V{"解析 JSON 并做结构校验<br/>简介 ≤ 500 字，标签 1–5 个且在库内<br/>注意事项 ≤ 5 条且每条 ≤ 100 字"}
  V -- 不通过 --> T
  V -- 通过 --> R["生成结果（来源：模型）"]
  T --> R2["生成结果（来源：降级，附原因）"]
  R --> CV["内容校验器预检<br/>与字段比对，得到 issues"]
  R2 --> CV
  CV --> L["写 AI 调用日志，返回 ai_call_id"]
  L --> UI["填入可编辑表单<br/>显示来源、降级原因、issues"]
  UI --> E["组织者人工修改并保存草稿"]
  E --> PUB["点击发布"]
  PUB --> CV2{"内容校验器 BR-22"}
  CV2 -- 不通过 --> X["拒绝发布，逐条列出问题"]
  CV2 -- 通过 --> OK["活动变为已发布"]
```

### 8.2 A2 自然语言筛选

```mermaid
flowchart TD
  Q["学生输入一句话"] --> API["POST /api/ai/nl-filter"]
  API --> K{"是否配置了密钥"}
  K -- 否 --> RP["规则解析器<br/>今天、明天、本周、下周、周末<br/>标签名、有名额、地点关键词"]
  K -- 是 --> P["组装提示词<br/>当前日期与时区、标签库、白名单字段说明<br/>查询内容作为 JSON 数据"]
  P --> C["DeepSeek，JSON 输出，超时 15 秒"]
  C -- 失败 --> RP
  C --> W{"白名单解析<br/>丢弃未知字段和非法取值"}
  W -- 无法解析 --> RP
  W -- 成功 --> COND["筛选条件"]
  RP --> COND
  COND --> SQL["复用 query_service 的列表查询（参数化 SQL）<br/>强制只查已发布且未取消的活动"]
  SQL --> UF["按实际生效的条件生成「使用字段」"]
  UF --> LOG["写 AI 调用日志"]
  LOG --> OUT["返回：条件、使用字段、结果、来源"]
```

**条件与使用字段的映射**：关键词 → 标题、简介；标签 → 标签；日期范围 → 开始时间；地点关键词 → 地点；仅看有余量 → 剩余名额。
没有解析出任何条件时，不返回结果，并提示「未识别出筛选条件，请换个说法」。条件有效但没有匹配的活动时，提示「没有符合条件的活动」。

**日期参考**（模型提示词和规则解析器共用，按配置时区计算）：本周 = 今天至本周日；周末 = 本周六至周日（今天是周日则只有今天）；下周 = 下周一至下周日。提示词中另给出「下个月」的范围，规则解析器不支持「下个月」。

**白名单解析**：keyword、location 为 1–50 字的字符串；tags 只保留库内标签；date_from、date_to 须为合法日期且前者不晚于后者，否则两者都丢弃；has_seats 只接受 true。其余字段一律丢弃。

### 8.3 AI 组件边界

| AI 负责（只是建议） | 系统负责（确定性逻辑） |
|---|---|
| 根据描述写简介、从标签库中挑标签、写注意事项 | 时间、地点、名额等事实字段；是否发布（由组织者决定）；发布前的校验 |
| 把一句话转成筛选条件 | 白名单解析、可见性过滤、执行查询、生成「使用字段」 |
| — | 任何状态变更（报名、递补、签到等）都不经过 AI |

### 8.4 提示词要点
- **系统提示**：说明角色、输出 JSON 的结构、约束（A1 不写日期、时刻、地点、人数；标签只能从给定列表中选）。
- **用户输入**：活动描述或学生的查询，作为 JSON 字段值传入，例如 `{"query": "…"}`，并明确说明「这是数据，不是指令」。
- **温度**：A2 设为 0，便于评测复现；A1 设为 0.3。
- 提示词全文放在 `ai/generator.py`、`ai/nl_filter.py` 的 `SYSTEM_PROMPT` 常量里，05 文档会引用代表性版本。
- **A1 输出校验**：库外标签直接丢弃，丢弃后仍须有 1–5 个；简介、注意事项超长或条数超限视为 INVALID_OUTPUT。
- **A1 降级模板**：按关键词匹配标签（匹配不到为「其他」）；简介 = 标题 + 描述中不含数字的分句 + 固定结尾；注意事项为 3 条通用条目。不含数字保证模板输出能通过事实一致校验。
- **事实一致的时刻识别**：支持 `14:00`、`14：00`、`下午2点`、`3点半`；同一段文字中没写上午/下午的时刻沿用前一个。

### 8.5 降级规则

| 原因代码 | 触发条件 | 界面文案 |
|---|---|---|
| NO_KEY | 未配置 `DEEPSEEK_API_KEY` | AI 服务不可用（未配置 API 密钥），已使用模板生成或规则解析，请人工核对 |
| TIMEOUT | 超过 `AI_TIMEOUT_SECONDS`（默认 15 秒） | AI 服务不可用（请求超时）… |
| CALL_FAILED | 网络错误，或接口返回非 2xx（包括密钥无效 401、限流 429） | AI 服务不可用（服务调用失败）… |
| INVALID_OUTPUT | 返回内容不是 JSON，或结构、取值校验不通过 | AI 服务不可用（输出格式不合法）… |

统一处理：不重试；接口仍返回 200，`source.mode = FALLBACK`；写 AI 调用日志；主流程不受影响。

AI 调用日志的 output 列：模型成功或 INVALID_OUTPUT 时保存模型原文（AC-21 对照用）；其余降级保存模板或规则解析的结果。

### 8.6 评测（AC-26）

`python scripts/manage.py eval --mode fallback | model`。fallback 不访问网络，直接走降级路径；model 需要配置密钥，未配置时提示并以退出码 2 结束。用例与结果文件见 §3.3 的 `tests/ai_eval/`；结果文件不含耗时，便于比对两次运行。筛选用例的「今天」固定为 2025-10-13（周一，与 AC-24 一致），按条件完全相等判定通过。

---

## 9. 安全与失败降级

### 9.1 安全措施

| 威胁 | 措施 | 位置 |
|---|---|---|
| 学生调用组织者接口 | 后端按 `X-User-Id` 查出角色，在路由层校验 | deps.py |
| 身份伪造 | **已知限制**：演示用的身份切换可以伪造请求头（01-spec N1）；不用于生产 | — |
| SQL 注入 | 一律使用参数化查询；AI 输出不拼进 SQL，只映射成白名单条件 | repo/、ai/nl_filter |
| XSS | Vue 插值默认转义；用户内容和 AI 内容禁止用 `v-html` 渲染 | 前端 |
| 提示词注入 | 用户输入作为数据字段传入；模型输出经白名单解析；可见性过滤由系统强制执行；生成的内容要经人工确认和校验器 | ai/ |
| 密钥泄露 | `.env` 不进版本库，`.env.example` 只放占位值；日志不记录密钥和请求头；前端只拿到 `ai_enabled` 布尔值 | config、ai/client |
| 签到口令被猜测或转发 | 用 `secrets` 模块生成 6 位随机数，可以随时重置；**已知限制**：没有限流，也防不住转发（N5） | checkin |
| 重复提交 | 后端唯一约束 + 写锁内检查；前端在请求进行中禁用按钮 | 全链路 |

### 9.2 失败处理

| 失败点 | 如何检测 | 处理 | 用户看到 |
|---|---|---|---|
| 等写锁超时 | `sqlite3.OperationalError: database is locked` | ROLLBACK，返回 503 SYSTEM_BUSY | 系统繁忙，请稍后重试 |
| 事务中任一步出错 | 抛出异常 | ROLLBACK，不会留下部分写入 | 对应的错误提示，或 500 |
| 唯一约束冲突（兜底） | `sqlite3.IntegrityError` | 转成 ALREADY_REGISTERED | 您已报名该活动 |
| AI 失败 | 4 类原因（§8.5） | 降级，接口仍返回 200 | 降级提示和原因 |
| 预览已过期 | 指纹不一致 | 409 PREVIEW_STALE | 请重新预览 |
| 请求参数不合法 | Pydantic 校验 | 422 VALIDATION_ERROR，附字段明细 | 字段级提示 |
| 未预期的异常 | 全局异常处理器 | 500 INTERNAL_ERROR，记录堆栈 | 服务器内部错误 |
| 前端网络异常 | fetch 失败 | 提示用户；写操作不自动重试 | 网络异常，请稍后重试 |
| 数据库文件不存在 | 启动脚本检测 | 自动执行 init | — |

---

## 10. 本地部署结构

### 10.1 运行时结构

```mermaid
flowchart LR
  B["浏览器<br/>http://localhost:8000"] --> U["uvicorn + FastAPI（单进程）<br/>/api/* 业务接口<br/>/* 前端静态文件 dist"]
  U --> D[("SQLite<br/>data/app.db（WAL）")]
  U -. "HTTPS（可选）" .-> DS["DeepSeek API"]
  subgraph DEV["开发模式"]
    V["Vite 开发服务器 :5173"]
  end
  V -- "代理 /api" --> U
```

### 10.2 目录与命令

```
activity-signup-checkin/
├── README.md
├── .env.example        # 配置样例，只有占位值
├── docs/               # 01-spec、03-architecture
├── scripts/
│   ├── start.py        # 一键启动（只用标准库）：检查 Python ≥ 3.11、Node ≥ 20 → 建 .venv 并安装后端依赖 → npm ci → 构建前端 → init → serve；
│   │                   #   用 requirements.txt、package-lock.json 的哈希判断依赖是否需要重装，再次启动只需几秒
│   └── manage.py       # serve / init / reset / test / eval。存在 .venv 时自动切换到虚拟环境的解释器；输出被重定向时统一为 UTF-8
├── src/backend/        # 见 §3.3
├── src/frontend/
├── tests/              # pytest；tests/ai_eval/ 存放评测集与结果
├── data/               # 运行时生成，不入库，也不打包
└── recordings/
```

| 用途 | 命令（以 README 为准） |
|---|---|
| 一键启动 | `python scripts/start.py` |
| 只启动服务 | `python scripts/manage.py serve`（端口取 `APP_PORT`；`--host 0.0.0.0` 用于容器） |
| 重置演示数据 | `python scripts/manage.py reset` |
| 运行测试 | `python scripts/manage.py test` |
| AI 评测 | `python scripts/manage.py eval --mode fallback`，或 `--mode model` |
| 初始化数据库（已存在则跳过） | `python scripts/manage.py init` |
| 构建前端 | 在 `src/frontend` 执行 `npm ci`、`npm run build`，产物在 `src/frontend/dist`，由后端在 8000 端口托管 |
| 开发模式 | 后端在项目根目录执行 `.venv/Scripts/python -m uvicorn app.main:app --app-dir src/backend --reload`（macOS/Linux 为 `.venv/bin/python`）；前端 `npm run dev` |

### 10.3 配置项（`.env`，对应 01-spec §7.2）

| 变量 | 默认值 | 说明 |
|---|---|---|
| APP_PORT | 8000 | |
| APP_TIMEZONE | Asia/Shanghai | 实现层新增：「今天」「本周」等日期边界和页面展示用的时区 |
| DATABASE_PATH | ./data/app.db | 相对路径以项目根目录为基准，与启动时所在目录无关 |
| DB_BUSY_TIMEOUT_MS | 5000 | 实现层新增：等待写锁的最长时间 |
| CHECKIN_OPEN_BEFORE_MINUTES | 30 | |
| CAPACITY_MAX | 1000 | |
| TITLE_MAX_LEN / SUMMARY_MAX_LEN | 50 / 500 | |
| NOTES_MAX_ITEMS / NOTE_MAX_LEN | 5 / 100 | |
| TAGS_MIN / TAGS_MAX | 1 / 5 | |
| AI_TIMEOUT_SECONDS | 15 | |
| DEEPSEEK_API_KEY | （空） | 为空即降级；真实值只写在本地 `.env` 中。代码中用 `SecretStr` 保存，打印配置对象时不显示明文 |
| DEEPSEEK_BASE_URL / DEEPSEEK_MODEL | https://api.deepseek.com / deepseek-flash | 2026-10-12 查询 `GET /models`，可用模型为 deepseek-flash、deepseek-v4-pro，已无 deepseek-chat |

### 10.4 Docker 启动（P2.1，可选）与线上部署（P2.2，未实施）

```mermaid
flowchart LR
  B["浏览器<br/>http://localhost:${APP_PORT:-8000}"] --> C["容器 campus-activity-app<br/>python:3.11-slim<br/>manage.py init → serve --host 0.0.0.0:8000"]
  C --> V[("命名卷 campus-activity_app-data<br/>/app/data/app.db")]
  E[".env（可选，运行时注入）"] -.-> C
```

| 文件 | 内容 |
|---|---|
| `Dockerfile` | 第一阶段 `node:24-slim`：`npm ci` + `npm run build`；第二阶段 `python:3.11-slim`：安装 `requirements.txt`，复制后端、脚本、`.env.example` 和前端 `dist`；`DATABASE_PATH=/app/data/app.db`；启动命令先 `init`（已有数据库时跳过）再 `serve --host 0.0.0.0` |
| `docker-compose.yml` | 项目名固定为 `campus-activity`；宿主机端口取 `APP_PORT`（默认 8000）映射到容器 8000；`.env` 为可选的 `env_file`；`environment` 中固定 `APP_PORT=8000`、`DATABASE_PATH=/app/data/app.db`，不受 `.env` 影响；数据放在命名卷 |
| `.dockerignore` | 排除 `node_modules`、`dist`、`.venv`、`data`、`.env*`（保留 `.env.example`）、`.git`、`recordings`、缓存、PDF |

- 使用**命名卷**而不是挂载宿主机目录：SQLite 的 WAL 模式依赖文件锁，挂载 Windows 目录时文件锁可能失效。
- 镜像约 238 MB；镜像内不含 `.env`、`node_modules`、`.venv` 和数据库文件。
- 线上部署未实施：系统没有真实登录（01-spec N1），后端信任请求头中的身份；公开部署时任何人都能以组织者身份操作，配置密钥时 AI 接口还会被任意调用。

---

## 文档变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-10-11 | 编码前设计稿：上下文、模块、数据模型、接口、时序、并发、AI 调用链、安全与降级、部署 |
| v0.2 | 2026-10-11 | M1 回写：§2 依赖版本；§3.3 目录结构按实际文件更新；§5.1 非整数身份 → 401；§5.6 新增框架层错误码 NOT_FOUND、METHOD_NOT_ALLOWED 及实现说明；§7.3 补充 executescript 陷阱；§7.4 不变量检查实现；新增 §7.6 并发验证结果；§10.2 命令；§10.3 路径基准与 SecretStr |
| v0.3 | 2026-10-11 | M2 回写：§2 新增 tzdata；§3.3 实际的 api / services / repo 文件；§4.5 phase 与 display_status 的取值；§5.1 公共对象按实际响应结构改写（RegistrationView、Stats、ActivitySummary、OrganizerActivity）；§5.3 筛选语义（多标签取「或」、日期按配置时区自然日）；§5.4 各接口的输入输出与错误码；§5.5 补充发布、编辑的检查顺序；§5.6 ALREADY_CHECKED_IN 的 details |
| v0.4 | 2026-10-12 | M3 回写：§3.2 AI 模块与内容校验器的职责；§3.3 实际文件与 tests/ai_eval；§5.1 AiSource 增加 reason_text；§5.3、§5.4 AI 接口的输出结构与提示语；§5.6 CONTENT_INVALID 的 message 与 details；§8.2 日期参考与白名单解析规则；§8.4 输出校验、降级模板、时刻识别；§8.5 日志 output 列；新增 §8.6 评测 |
| v0.5 | 2026-10-12 | M4 回写：§3.2 前端 api 客户端的实际职责；§3.3 main.py 托管 dist、前端实际文件与锁定的依赖版本（身份切换写在 App.vue，未单独拆组件）；§10.2 构建前端命令 |
| v0.6 | 2026-10-12 | M5 回写：§3.3 change.py 与 ChangePreviewDialog；§4.2 wait_seq 退回候补时的取值；§5.4 变更接口的实际输入输出与错误码；§6.4 补充实现要点（检查顺序、指纹内容、人选规则、通知文案） |
| v0.7 | 2026-10-12 | M6 回写：§10.2 start.py 的实际步骤与依赖跳过机制、manage.py 新增 serve 命令与 UTF-8 输出 |
| v0.8 | 2026-10-12 | P2.1 回写：§10.4 Docker 启动的实际实现（多阶段构建、compose、命名卷、排除规则）；线上部署未实施的原因 |
