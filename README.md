# 基金练习室 · Fund Lab

一个面向个人的基金投资模拟项目，参考支付宝基金理财的使用流程，让用户通过虚拟资金练习基金买入、卖出、持仓管理与交易记录查询。

项目重点是模拟基金按正式净值确认份额、按持有期计算费用以及等待赎回到账的过程。首版计划在本机运行，通过浏览器使用，无需购买服务器。

> **当前进度：工程基础已搭建。** React 前端、FastAPI 后端和 PostgreSQL 已打通，支持服务检查及历史样本基金搜索。已完成 12 页设计；登录注册、持仓和模拟交易仍待实现，当前页面用于基础联调，不是完整业务版。

## 项目目标

- 使用虚拟本金练习基金投资，不发生真实资金交易。
- 区分可用余额、基金持仓、买入在途、冻结份额及赎回在途。
- 展示申购、赎回的费用与确认进度，帮助理解基金交易规则。
- 保留订单与资金流水，让每次模拟操作可查询、可追溯。
- 优先满足个人本地使用，后续再考虑托管部署与多设备同步。

这是独立模拟项目，与支付宝及其关联公司无隶属或合作关系，不需要提供支付宝账号或绑定银行卡。设计稿中的基金名称、净值、收益和费率均为演示数据。

## 计划功能

| 模块 | 功能 |
| --- | --- |
| 账户 | 注册、登录、退出、修改密码、首次发放 100,000 元虚拟本金 |
| 基金发现 | 基金名称/代码搜索、分类、排序、分页、自选 |
| 基金详情 | 基础信息、正式净值、历史走势、区间收益、交易规则 |
| 模拟买入 | 金额校验、费用试算、资金预留、等待净值、份额确认 |
| 模拟卖出 | 按份额赎回、批次费用计算、份额冻结、赎回确认与到账 |
| 我的持仓 | 总资产、收益、现金、持仓市值、在途资金与可卖份额 |
| 交易记录 | 搜索、类型/状态/日期筛选、订单详情、规则允许时撤单 |
| 账户与数据 | 交易 CSV 导出、本地数据备份与恢复、使用说明 |
| 数据与结算 | 基金数据同步、交易日判断、自动结算、重启补处理、资金对账 |

首版计划支持规则完整、数据可用的普通境内开放式债券型、指数型和混合型基金。**债券型基金不等于直接买卖单只债券**，后者不在首版范围内。

基金数据源已完成第一轮样本验证，暂不承诺完整覆盖支付宝代销的全部基金。货币基金、QDII、场内交易及其他特殊规则基金将在具备相应处理能力后另行支持。

完整范围与验收标准见 [功能清单与开发规划](docs/功能清单与开发规划.md)。

## 技术栈与版本

以下是当前开发电脑实测的环境基线，**不是最低版本要求，也不代表所有版本已完成业务兼容性测试**。

| 技术 / 工具 | 当前版本 | 用途与状态 |
| --- | --- | --- |
| Node.js | **24.19.0** | 前端开发和构建，项目使用 24.x |
| npm | **11.17.0** | 已安装；前端包管理 |
| Conda | **4.13.0** | 当前环境管理工具；独立创建项目环境，不修改 base |
| Python | **3.13.15** | 使用 Conda 的 `simulate-alipay` 环境；版本约束见 `environment.yml` |
| pip | **26.2.1** | Conda 环境内的 Python 包管理工具 |
| PostgreSQL | **17.11** | 使用电脑上独立安装的 PostgreSQL 服务；项目只创建自己的数据库 |
| React / React DOM | **19.3.0** | 前端界面 |
| TypeScript | **7.0.2** | 前端类型检查 |
| Vite | **8.3.0** | 开发服务与生产构建 |
| FastAPI | **0.141.1** | Python HTTP API |
| Uvicorn | **0.52.4** | API 服务进程 |
| SQLAlchemy | **2.0.52** | 数据模型和数据库访问 |
| Alembic | **1.20.0** | 数据库版本迁移 |
| Psycopg | **3.3.5** | PostgreSQL 驱动，使用 binary 包 |
| Git | 2.35.1.windows.2 | 当前版本；用于版本管理 |
| PowerShell | 7.6.5 | 当前版本；用于 Windows 本地脚本 |

前端准确版本与依赖树见 `frontend/package.json` 和 `frontend/package-lock.json`；后端完整版本见 `backend/requirements.txt`，直接依赖的升级范围见 `backend/requirements.in`。新电脑按锁定文件安装，不需要全局安装这些框架。

## 需要安装哪些软件

在新电脑准备开发环境时，需要以下工具：

1. **Git**：克隆仓库和管理代码。
2. **Node.js 与 npm**：准备前端开发环境，可先参照上表中的版本基线。
3. **Conda（Miniconda 或 Anaconda）**：按 `environment.yml` 创建 Python 环境；已有 Conda 无需重复安装，也无需另装独立 Python。
4. **PostgreSQL 17.11**：在电脑上独立安装并启动服务，记下端口、用户名和密码；多个项目可以共用服务，各自使用独立数据库。
5. **PowerShell**：运行仓库中的 Windows 脚本。
6. **浏览器**：查看设计预览，后续访问本地应用。

VS Code 等代码编辑器、pgAdmin 等数据库管理工具为可选项。Docker、云服务器、Figma 和浏览器自动化工具都不是首版本地运行的必装项。

React、TypeScript、Vite 和 FastAPI 属于项目依赖，按下面的初始化命令统一安装。

## 当前仓库可以怎么使用

### 查看设计与规划

克隆仓库后，可以直接打开以下文件，无需安装 Python 或数据库：

- [V2 设计预览](design/v2/preview.html)：在文件管理器中用浏览器打开，查看 12 页主界面与边界状态。
- [设计交付记录](design/FIGMA-PROGRESS.md)：查看设计范围、Figma 链接和当前限制。
- [功能清单与开发规划](docs/功能清单与开发规划.md)：查看分阶段任务与验收条件。

GitHub 文件页面不会直接运行 HTML 预览，需要将仓库下载到本机后打开。设计稿目前是静态页面，不包含可点击的业务交互。

### 首次安装（Windows / PowerShell）

以下命令从仓库根目录执行。已有环境、数据库或 `.env` 时直接复用，不要重复创建或覆盖。你当前电脑已完成安装和迁移，可直接跳到“日常启动”。

1. 安装 Git、Node.js 24.x（含 npm）、Conda 和 PostgreSQL 17，并启动 PostgreSQL 服务。
2. 克隆仓库并进入目录：

```powershell
git clone https://github.com/zjgsuzjx/fund-lab.git
Set-Location fund-lab
```

3. 创建 Python 环境并安装锁定依赖：

```powershell
# 仅在同名环境不存在时创建；可先用 conda env list 查看
conda env create -f environment.yml
conda run -n simulate-alipay python -m pip install --no-user -r backend/requirements.txt
npm --prefix frontend ci --cache .local/npm-cache
```

这里使用 `conda run`，不依赖激活脚本或 PowerShell 的 Conda hook。框架不需要全局安装；已有环境只执行依赖安装命令。

4. 准备数据库：打开 PostgreSQL 客户端，密码在提示时输入，不写在命令中。

```powershell
psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -W
```

若 `psql` 不在 PATH，可使用安装路径。原开发电脑的示例：

```powershell
& 'D:\Program Files\PostgreSQL\17\bin\psql.exe' -h 127.0.0.1 -p 5432 -U postgres -d postgres -W
```

进入 SQL 终端后先列出数据库：

```sql
\l
```

**只有列表中不存在 `simulate_alipay` 时**，才执行创建命令（需要建库权限）：

```sql
CREATE DATABASE simulate_alipay;
```

连接项目库并检查，然后退出：

```sql
\connect simulate_alipay
SELECT current_database(), version();
\q
```

5. 创建本地配置，已有 `.env` 时保留：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

用编辑器填写根目录 `.env`：

| 配置项 | 填写方式 |
| --- | --- |
| `PGHOST` | 本机通常为 `127.0.0.1` |
| `PGPORT` | 通常为 `5432` |
| `PGDATABASE` | `simulate_alipay` |
| `PGUSER` | `postgres` 或已授权的项目用户 |
| `PGPASSWORD` | 数据库密码，仅保存在被 Git 忽略的 `.env` |

这些配置由 Python 后端读取；`psql` 不会自动读取项目 `.env`。非空同名进程环境变量优先。配置值不做变量插值，密码中的 `#` 是字面字符，不要添加行内注释。无需配置 `PG_BIN`，客户端路径直接写在命令中即可。

6. 创建或升级业务表结构：

```powershell
conda run -n simulate-alipay python -m alembic -c backend/alembic.ini upgrade head
conda run -n simulate-alipay python -m alembic -c backend/alembic.ini current
```

`upgrade head` 可重复执行，不会重复建表，也不清空现有业务数据。不要用删除数据库或回滚迁移的方式进行日常初始化。

7. 可选：导入历史验证样本。

```powershell
conda run -n simulate-alipay --cwd backend python -m app.seed
```

导入 5 只境内基金和 15 行历史净值，跳过已有基金，不创建用户、不发放本金、不开放交易。样本来自 2026-09-13 验证快照，不是实时行情。省略此步也能启动，基金列表为空。

### 日常启动

确认 PostgreSQL 服务已启动，然后打开两个终端，**都先进入仓库根目录**。

终端 1：启动后端，保留实时日志。

```powershell
conda run -n simulate-alipay --no-capture-output --cwd backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

如果提示 `D:\code\python.exe: No module named uvicorn`，说明实际调用了 base 的解释器。项目环境已安装 Uvicorn，不要向 base 重复安装。原开发电脑可直接指定项目解释器，在根目录运行：

```powershell
# PowerShell
& 'D:\code\envs\simulate-alipay\python.exe' -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

```bat
:: CMD / Anaconda Prompt
D:\code\envs\simulate-alipay\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

其他电脑先用 `conda env list` 查找实际环境路径。已激活环境时可用 `python -c "import sys; print(sys.executable)"` 核实解释器；只有路径指向项目环境时，才直接用 `python`。以上两种终端的命令任选一种，不要重复启动。

终端 2：启动前端。

```powershell
npm --prefix frontend run dev
```

- 应用：[http://127.0.0.1:5173](http://127.0.0.1:5173)
- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 就绪检查：[http://127.0.0.1:8000/api/health/ready](http://127.0.0.1:8000/api/health/ready)

两个终端分别按 `Ctrl+C` 停止应用，不停止其他项目共用的 PostgreSQL 服务。前后端仅监听本机；若 8000 或 5173 已占用，先检查是否已有本项目实例运行，不会自动切换端口。前端将 `/api` 代理到后端，数据库凭据不要放入 `VITE_*` 变量。

### 更新代码后

在根目录依次执行，任何一步报错时先处理该错误：

```powershell
git pull
conda run -n simulate-alipay python -m pip install --no-user -r backend/requirements.txt
npm --prefix frontend ci --cache .local/npm-cache
conda run -n simulate-alipay python -m alembic -c backend/alembic.ini upgrade head
```

再按“日常启动”运行。更多测试及迁移说明见[开发指南](docs/开发指南.md)，原电脑路径和常见问题见[本地环境说明](LOCAL-SETUP.md)。

## 开发路线

| 阶段 | 主要工作 | 完成标志 |
| --- | --- | --- |
| 0 | 核验数据源，冻结支持范围、交易规则与收益口径 | 数据和交易边界明确 |
| 1 | 初始化前后端、数据库迁移、配置与命令行启动说明 | 本机可启动基础应用 |
| 2 | 实现账户、会话、初始本金和界面骨架 | 注册登录及账户隔离可用 |
| 3 | 实现基金同步、搜索、详情、图表与自选 | 基金浏览流程可用 |
| 4 | 实现买入、资金预留、份额确认与撤单 | 完成一次正确的模拟买入 |
| 5 | 实现批次赎回、到账、收益及补结算 | 买入到卖出到账闭环可用 |
| 6 | 完善交易记录、设置、导出、备份和异常状态 | 设计稿中的入口均可用 |
| 7 | 联调、对账、恢复演练与本地交付 | 首版可稳定使用 |

阶段 1 的可启动工程和基础表已完成本机验收；原规划中的交易规则、订单、批次、流水及任务表尚未建立，将随相应业务规则一起迁移。阶段 0 的完整交易规则仍待核验，阶段 2～7 尚未完成。

已完成第一轮公开数据源样本验证：6 只基金共 60 个日期的净值与基金公司官网一致。支付宝全量在售覆盖及完整交易规则尚未验证，暂不开放模拟买卖。详见[数据源验证报告](docs/数据源验证报告.md)，其中包含结果、来源、待办和复现命令。

## 仓库结构

```text
simulate-alipay/
├── frontend/                  # React / TypeScript / Vite
├── backend/                   # FastAPI、模型、Alembic 迁移和测试
├── data/validation/           # 小量历史验证快照，非实时行情
├── design/                    # 设计源文件、SVG、预览和交付记录
│   └── v2/                    # 已定稿的第二版设计
├── docs/                      # 功能清单与开发规划
├── scripts/                   # 独立数据源验证工具（启动应用不依赖）
├── .env.example               # 可提交的数据库连接配置模板
├── environment.yml            # Conda 环境定义（Python / pip）
├── .gitignore
├── LOCAL-SETUP.md             # 原开发电脑的环境说明
└── README.md
```

当前仅提供基础接口和样本浏览，完整业务按开发路线逐阶段实现。

## 提交到 GitHub 前

- `.gitignore` 已排除本地运行时、数据库目录、虚拟环境、环境变量文件、依赖目录和浏览器自动化日志。
- 不提交数据库密码、访问令牌、真实账户数据或数据库备份；发布前用 `git status` 和 `git diff --cached` 检查实际待提交内容。
- `.env.example` 提供不含真实凭据的数据库配置模板；个人填写的 `.env` 不提交。
- 本项目采用 [MIT License](LICENSE)。设计中使用的 Lucide 搜索图标保留其[上游许可证](design/assets/LICENSE-lucide)。
