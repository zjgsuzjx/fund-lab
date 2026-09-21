# 基金练习室 · Fund Lab

## 项目介绍

参考支付宝基金模块的本地基金投资模拟应用，支持基金浏览、自选、模拟买卖、持仓收益和交易记录。注册即获 100,000 元虚拟本金，可在“我的”中重置个人数据。

使用 React + TypeScript + FastAPI + PostgreSQL，不涉及真实资金交易。

## 构建与运行

准备 **Node.js 24、Conda、PostgreSQL 17 和 Git**，启动 PostgreSQL。以下命令使用 PowerShell，在仓库根目录执行。

**1. 下载并安装依赖**

```powershell
git clone https://github.com/zjgsuzjx/fund-lab.git
cd fund-lab
conda env create -f environment.yml
conda run -n simulate-alipay python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
```

**2. 配置数据库（首次运行）**

在 PostgreSQL 中创建数据库 `simulate_alipay`（已有则跳过）：

```sql
CREATE DATABASE simulate_alipay;
```

复制配置文件，在 `.env` 中填写数据库用户名、密码及连接信息；已有配置请保留。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

完成配置后，初始化表结构和演示基金数据：

```powershell
conda run -n simulate-alipay python -m alembic -c backend/alembic.ini upgrade head
conda run -n simulate-alipay --cwd backend python -m app.seed
```

演示数据为历史样本，默认不开放交易。后端启动后自动导入全市场目录并分批同步净值，支持的普通净值型基金同步成功后开放通用模拟交易。覆盖范围、模拟费率及定时策略见[多基金与自动同步](docs/多基金与自动同步.md)。

**3. 启动应用**

打开两个终端，均进入仓库根目录，分别执行：

```powershell
conda run -n simulate-alipay --no-capture-output --cwd backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
npm --prefix frontend run dev
```

访问 [http://localhost:5173](http://localhost:5173)。之后使用只需启动 PostgreSQL，再执行这两条命令。

需要构建前端产物时，执行 `npm --prefix frontend run build`，输出至 `frontend/dist`；运行应用仍需后端和数据库。

## 项目责任声明

- 本项目仅供学习和模拟练习，所有资金均为虚拟资金，不构成投资建议或收益承诺。数据与规则可能延迟或存在偏差，请勿据此进行真实投资。
- 本项目与支付宝及其关联公司无隶属、合作或授权关系，不需要提供支付宝账号、支付密码或银行卡信息。
- 数据保存在本地，请自行妥善保管账号和数据库配置，并在重置或迁移前备份。
- 本项目按 [MIT License](LICENSE) 提供，不作任何担保；使用者自行承担使用风险，作者责任以许可证及适用法律为准。
