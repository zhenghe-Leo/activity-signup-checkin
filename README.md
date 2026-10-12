# 活动报名与签到系统

学生社团和学院发布活动，学生报名、候补、递补和签到，组织者管理活动并查看统计；AI 辅助组织者撰写活动内容，帮助学生用一句话筛选活动。

- 需求与验收标准：[docs/01-spec.md](docs/01-spec.md)
- 架构、接口、错误码：[docs/03-architecture.md](docs/03-architecture.md)

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+、FastAPI、标准库 `sqlite3`（不用 ORM） |
| 数据库 | SQLite（WAL 模式），单文件 `data/app.db` |
| 前端 | Vue 3、Vite、Vue Router、Element Plus |
| AI | DeepSeek（OpenAI 兼容接口，默认模型 `deepseek-flash`）；未配置密钥或调用失败时自动降级为本地规则/模板 |
| 测试 | pytest（含并发测试）；AI 评测集 |

前后端通过同一个端口访问：FastAPI 提供 `/api` 接口，同时托管前端构建产物。

## 快速开始

### 环境要求

- Python ≥ 3.11
- Node.js ≥ 20（只用于构建前端）
- 首次启动需要联网下载依赖

### 一键启动

在项目根目录执行：

```bash
python scripts/start.py
```

脚本会依次：检查 Python 和 Node 版本 → 创建虚拟环境 `.venv` 并安装后端依赖 → `npm ci` 并构建前端 → 首次运行时初始化数据库并导入演示数据 → 启动服务。看到 `服务地址：http://localhost:8000` 后，用浏览器（最新版 Chrome 或 Edge）打开该地址。按 `Ctrl+C` 停止。

- 首次启动需要下载依赖，通常 1–3 分钟；之后再启动会跳过安装，几秒即可。
- 重启服务不会清空数据。需要恢复演示数据时执行下面的 `reset`。
- Windows 上如果 `python` 指向的不是 3.11+，可以用 `py -3.11 scripts/start.py`。macOS / Linux 可能需要写成 `python3`。

### Docker 启动（可选）

本机没有 Python 或 Node、但装有 Docker（Docker Desktop 需先启动）时，在项目根目录执行：

```bash
docker compose up --build
```

首次构建会拉取 Node 和 Python 基础镜像（国内网络较慢时，可在 Docker Desktop 中配置镜像加速）。看到服务启动后打开 http://localhost:8000 ，按 `Ctrl+C` 停止。

- **数据**：数据库保存在 Docker 数据卷 `campus-activity_app-data` 中，`docker compose down` 后再启动数据仍在；`docker compose down -v` 会同时删除数据卷。容器日志中的地址是容器内部端口，以宿主机端口为准。
- **重置演示数据**：`docker compose exec app python scripts/manage.py reset`
- **AI 密钥**：项目根目录有 `.env` 时自动读取；没有 `.env` 时 AI 自动降级。镜像中不包含 `.env`。
- **已配置密钥时演示降级**：终端里设置的环境变量不会传入容器，需要在启动时用 `-e` 覆盖（等号后面是一个空格）：`docker compose run --rm -e "DEEPSEEK_API_KEY= " -p 8001:8000 app`，然后打开 http://localhost:8001 ，按 `Ctrl+C` 停止。
- **端口被占用**：`APP_PORT=8001 docker compose up --build`（PowerShell 先执行 `$env:APP_PORT = '8001'`）。


| 用途 | 命令 |
|---|---|
| 一键启动 | `python scripts/start.py` |
| 重置演示数据（清库后重新导入，服务运行中也可执行） | `python scripts/manage.py reset` |
| 运行全部自动化测试 | `python scripts/manage.py test` |
| AI 评测（降级模式，不联网，结果可复现） | `python scripts/manage.py eval --mode fallback` |
| AI 评测（真实模型，需要配置密钥） | `python scripts/manage.py eval --mode model` |
| 只启动服务（依赖已安装、前端已构建时） | `python scripts/manage.py serve` |

`manage.py` 会自动使用 `.venv` 中的 Python，需要先执行过一次 `start.py`。测试和降级评测不访问网络，也不需要密钥。

开发模式（可选）：后端执行 `python scripts/manage.py serve`，前端在 `src/frontend` 执行 `npm run dev`，然后打开 http://localhost:5173（`/api` 会代理到 8000 端口）。

## 演示账号

系统不需要登录。打开页面后，在右上角的「当前身份」下拉框中切换身份。

| 身份 | 角色 | 说明 |
|---|---|---|
| O1 王老师 | 组织者 | 创建、编辑、发布、取消活动，AI 生成内容，发布后调整，生成签到口令，查看名单与统计 |
| S1 李明 ~ S6 赵磊 | 学生 | 浏览筛选活动、一句话筛选、报名、取消、签到、查看我的报名 |

演示数据中的活动时间都相对于初始化或重置的时刻生成，任何时候重置后都可以直接演示：

| 活动 | 用于演示 |
|---|---|
| 【演示】职业规划讲座 | 名额 2，无人报名：名额未满报名 → 满员进入候补 → 取消后自动递补；发布后调整名额 |
| 【演示】数据库原理学术报告 | 签到窗口已开放，S2、S3、S5 已报名，S4 候补：签到、重复签到、口令错误。签到窗口在重置后约 2 小时内有效 |
| 【演示】校园摄影展志愿者招募 | 已截止、未开始、已满且有候补：截止后拒绝报名、允许取消并继续递补 |
| Go 后端面试经验分享会（草稿） | AI 生成内容 → 人工修改 → 发布 |
| 校园歌手大赛初赛（已取消） | 已取消的活动出现在 S1 的「我的报名」中 |
| 其余 10 个活动 | 不同标签和日期，用于搜索和一句话筛选；其中「AI 前沿讲座（名额已满）」已满 |

## AI 能力与降级

| 能力 | 说明 |
|---|---|
| 活动内容生成（组织者） | 根据一句话描述和已填写的字段，生成简介、标签（限预置标签库）、注意事项，只填入表单，人工修改后再保存发布 |
| 内容校验 | 发布前检查简介和注意事项：日期、时刻、人数必须与活动字段一致；长度；敏感词。不通过时逐条列出原因。对人工撰写的内容同样生效 |
| 一句话筛选（学生） | 把「这周还有名额的讲座」这类句子转成筛选条件，由系统查询，并标明解析出的条件和使用的活动字段 |

**配置密钥（可选）**：把 `.env.example` 复制为 `.env`，填写 `DEEPSEEK_API_KEY`。不要把真实密钥写进 `.env.example` 或提交到仓库。同名的环境变量优先于 `.env`：如果配置了密钥仍显示「AI 未配置」，检查当前终端是否残留了 `DEEPSEEK_API_KEY` 环境变量（例如演示降级时设置的空格），删除或换一个新终端即可。

**降级方式**：未配置密钥、请求超时（默认 15 秒）、调用失败、模型输出不合法时，不重试，直接改用本地模板（内容生成）或规则解析器（一句话筛选），接口照常返回结果。页面会标明「AI 服务不可用（原因），已使用模板生成，请人工核对」或「AI 降级（原因）」，主流程不受影响。**不配置密钥也能完成全部验收。**

**已配置密钥时演示降级**：启动前把密钥临时设为一个空格（注意是空格，不是空字符串；PowerShell 中赋空字符串会删除变量，程序会改读 `.env`）。

```powershell
# Windows PowerShell（只影响当前终端，不修改 .env）
$env:DEEPSEEK_API_KEY = ' '
python scripts/manage.py serve
```

```bash
# macOS / Linux
DEEPSEEK_API_KEY=' ' python scripts/manage.py serve
```

AI 评测结果：降级模式筛选解析正确率 87.5%，真实模型（deepseek-flash）93.8%，生成内容结构合规 100%、事实冲突 0。

## 已完成功能

- **活动管理**：创建草稿、编辑、发布（字段校验 + 内容校验）、取消活动（联动取消全部报名并通知）、生成和重置 6 位签到口令。
- **浏览与报名**：活动列表，按关键词、标签、日期、仅看有余量筛选；活动详情；报名、取消、我的报名。
- **候补与递补**：满员进入候补并显示位次；有人取消后按先后顺序自动递补；通知状态记录在报名记录上，导航显示未读数量。
- **签到**：签到窗口为活动开始前 30 分钟至结束；按原因区分拒绝提示；重复签到提示首次签到时间。
- **统计**：单个活动统计（已报名、候补中、已签到、已取消、签到率、递补人次）和组织者全部活动汇总表。
- **发布后调整**：名额、截止时间、时间与地点按「预览影响 → 确认」修改，在一个事务内完成；预览之后数据有变化时拒绝确认；签到开放后不允许调整。
- **一致性**：所有写操作在 SQLite 写锁事务中执行，并发报名不超卖，同一学生不会重复报名或重复签到（有并发测试）。
- **可追踪**：操作日志（组织者可在活动管理页查看）和 AI 调用日志。

## 未完成项与已知限制

以下内容明确不做（完整列表见 [01-spec §9](docs/01-spec.md)）：

- 登录与密码：用预置账号切换身份；后端信任请求头中的身份，**不适用于生产环境**。
- 删除活动、复制活动、撤回为草稿、自定义标签。
- 一个活动多个场次（场次 = 时间段 + 地点）。
- 消息中心和外部推送（短信、邮件等）：只在报名记录上记录通知状态。
- 二维码签到、防代签、口令防暴力猜测。
- 对话式活动问答（学生侧 AI 只做一句话筛选）。
- 分页、全文检索、移动端适配。
- 线上部署：未实施（系统没有真实登录，公开部署存在数据被篡改和 AI 额度被消耗的风险）。Docker 启动方式已提供。

已知问题：内容校验对日期、时刻、人数采用保守策略，可能误报（例如「3 人一组」会被判为与名额不一致），组织者可以改写表述；毫秒级并发时，候补顺序等于拿到写锁的顺序。

## 目录结构

```
├── scripts/            # start.py 一键启动；manage.py init / reset / test / eval / serve
├── Dockerfile          # 多阶段构建（Node 构建前端 → Python 运行）
├── docker-compose.yml  # Docker 启动（可选），数据放在命名卷中
├── src/backend/        # FastAPI 后端（app/：api、services、repo、ai、db、schema.sql）
├── src/frontend/       # Vue 3 前端
├── tests/              # pytest 测试；tests/ai_eval/ 为 AI 评测集与结果
├── docs/               # 需求规格（01-spec）与架构设计（03-architecture）
├── data/               # 运行时数据库（不入库）
└── .env.example        # 配置样例（只有占位值）
```

## 常见问题

- **端口 8000 被占用**：在 `.env` 中设置 `APP_PORT=8001`（或其他端口）后重新启动；也可以只对本次启动生效：PowerShell 执行 `$env:APP_PORT = '8001'` 后再启动，macOS / Linux 执行 `APP_PORT=8001 python scripts/start.py`。
- **依赖下载慢**：pip 可设置环境变量 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`；npm 可执行 `npm config set registry https://registry.npmmirror.com`。
- **签到演示提示「签到已结束」或「签到尚未开始」**：签到演示活动的时间相对重置时刻生成，执行 `python scripts/manage.py reset` 后再演示。

## 开源依赖与许可证

| 依赖 | 版本 | 许可证 | 来源 |
|---|---|---|---|
| FastAPI | 0.143.0 | MIT | https://pypi.org/project/fastapi/ |
| Uvicorn | 0.54.0 | BSD-3-Clause | https://pypi.org/project/uvicorn/ |
| Pydantic | 2.14.0 | MIT | https://pypi.org/project/pydantic/ |
| pydantic-settings | 2.15.0 | MIT | https://pypi.org/project/pydantic-settings/ |
| HTTPX | 0.28.1 | BSD-3-Clause | https://pypi.org/project/httpx/ |
| pytest | 9.1.1 | MIT | https://pypi.org/project/pytest/ |
| tzdata | 2026.5 | Apache-2.0 | https://pypi.org/project/tzdata/ |
| Vue | 3.5.43 | MIT | https://www.npmjs.com/package/vue |
| Vue Router | 5.4.0 | MIT | https://www.npmjs.com/package/vue-router |
| Element Plus | 2.14.7 | MIT | https://www.npmjs.com/package/element-plus |
| Vite | 8.3.4 | MIT | https://www.npmjs.com/package/vite |
| @vitejs/plugin-vue | 6.0.10 | MIT | https://www.npmjs.com/package/@vitejs/plugin-vue |
| SQLite | 随 Python 标准库提供 | Public Domain | https://www.sqlite.org/copyright.html |

AI 服务：DeepSeek API（商业服务，可选）。不配置密钥时系统完全可用。
