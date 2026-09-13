# 本地开发环境

完整安装和启动顺序见 [README](README.md)。应用不依赖 PowerShell 包装脚本，统一使用命令行。

## 原开发电脑的环境

| 工具 | 环境或路径 |
| --- | --- |
| Conda | 4.13.0，安装于 `D:\code` |
| Python | 3.13.15，环境 `simulate-alipay`，路径 `D:\code\envs\simulate-alipay` |
| PostgreSQL | 17.11，Windows 服务 `postgresql-x64-17` |
| PostgreSQL 客户端 | `D:\Program Files\PostgreSQL\17\bin\psql.exe` |
| 项目数据库 | `127.0.0.1:5432/simulate_alipay` |

其他开发者无需使用相同安装路径。Python 由 Conda 管理，PostgreSQL 是系统独立安装的共享服务；仓库不保存它们的程序或数据目录。

## 本机日常使用

在 `F:\code\simulate-alipay` 打开两个终端。

后端：

```powershell
conda run -n simulate-alipay --no-capture-output --cwd backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

前端：

```powershell
npm --prefix frontend run dev
```

浏览器访问 [本地应用](http://127.0.0.1:5173)。分别按 `Ctrl+C` 停止前后端。

## 配置及排错

- Python 后端读取根目录 `.env` 的 `PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSWORD`。非空同名进程环境变量优先，不插值，不支持行内注释。密码不提交 Git。
- `psql` 不读取项目 `.env`，在命令中指定主机、端口、用户名和库名，使用 `-W` 提示输入密码。无需 `PG_BIN` 配置。
- Conda 4.13.0 与 PowerShell 7.6.5 的激活 hook 有兼容问题，使用 `conda run` 可避免依赖该 hook，无须 `conda init`。找不到 Conda 时可使用 `& 'D:\code\Scripts\conda.exe' run ...`，或在已配置 Conda 的终端运行。
- 连接失败：检查 PostgreSQL 服务和 `.env`；表结构未就绪时执行 README 的 Alembic 升级命令。
- 端口占用：先确认是否已有本项目实例运行，不要批量终止其他程序。
- 本机已有环境、数据库和样本，不要重新创建或清空。依赖变更后按 README 安装锁定版本。

## 环境迁移记录

旧项目内 PostgreSQL 已停用、备份并清理；备份位于被 Git 忽略的 `backups/postgresql-project-before-system.sql`。当前系统数据库已包含基础表及 5 只历史样本，不再是空库。

旧 `.venv` 和 `.local/python313` 已移除。2026-09-13 按项目使用方式调整，移除了环境激活、数据库初始化/连接/检查、前后端启动等 PowerShell 包装脚本及配套 SQL 文件；数据源验证和测试工具继续保留在 `scripts/`。

## 启动时调用了 base Python

若错误路径为 `D:\code\python.exe`，实际调用的是 base，并不代表项目环境缺少 Uvicorn。已验证 `D:\code\envs\simulate-alipay\python.exe` 中安装了 Uvicorn 0.52.4。可按 README 的 CMD / PowerShell 示例直接指定该解释器，绕开当前终端的环境解析；不需要重新安装或启动脚本。
