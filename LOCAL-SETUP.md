# 本地开发环境

## Python：使用 Conda 环境

项目改用 Conda 管理的 `simulate-alipay` 环境，Python 3.13.15、pip 26.2.1，版本约束见根目录 `environment.yml`。原开发电脑的 Conda 版本为 4.13.0，安装于 `D:\code`，新环境位于 `D:\code\envs\simulate-alipay`；其他开发者不需要使用相同路径。base 和其他环境不修改。

```powershell
conda env create -f environment.yml
conda activate simulate-alipay
python --version
python -m pip --version
```

已有同名环境时直接激活。普通 PowerShell 可以点调用 `. .\scripts\activate-dev.ps1`，加载 Conda 自身的 PowerShell hook 并激活环境，不执行全局 `conda init`。如果找不到 Conda，请从已配置 Conda 的 PowerShell 打开项目。退出环境使用 `conda deactivate`。

现有 Conda 4.13.0 与 PowerShell 7.6.5 存在空参数传递差异。激活脚本对当前终端加载的 Conda 模块启用兼容参数传递，不修改 Conda 安装文件或其他命令的参数传递模式。若直接 `conda activate` 遇到解析错误，优先使用上述点调用脚本或 `conda run`。

也可以使用 `conda run -n simulate-alipay python ...`，无须激活。当前没有业务依赖，原虚拟环境仅含 pip。验证完成后已移除旧 `.venv`、`.local/python313` 和下载的 Python 安装包；项目不再携带 Python 运行时。

## PostgreSQL：使用独立安装的服务

原开发电脑已验证的安装信息（其他开发者无需使用相同安装路径）：

- 服务端与客户端：PostgreSQL 17.11。
- 程序目录：`D:\Program Files\PostgreSQL\17\bin`。
- 数据目录：`D:\Program Files\PostgreSQL\17\data`，由系统安装的服务管理。
- Windows 服务：`postgresql-x64-17`。
- 项目连接：`127.0.0.1:5432`，数据库 `simulate_alipay`。

项目不携带 PostgreSQL 程序和数据目录，也不启停共享服务。通过 Windows“服务”应用管理服务及其开机启动设置。

## 配置和使用

从项目根目录执行；已有 `.env` 时保留现有配置：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

编辑 `.env`，填写 `PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSWORD`。`PG_BIN` 可选，填写包含 `psql.exe` 的目录；留空时依次查找 `PATH` 和 Windows PostgreSQL 安装注册表。非空同名进程环境变量优先。

配置支持整行注释及成对引号，不执行代码、不展开变量，不支持行内注释。个人密码只保存在 `.env`，不应提交或分享该文件。

```powershell
. .\scripts\activate-dev.ps1
python --version
.\scripts\init-db.ps1
.\scripts\test-db.ps1
.\scripts\db-shell.ps1
```

- `init-db.ps1`：连接维护库 `postgres`，仅当项目数据库不存在时创建它。要求用户有相应权限；不创建业务表，不清空现有库。
- `test-db.ps1`：验证服务版本、数据库和用户名，并在事务中创建临时表、读写、回滚，不留下业务数据。
- `db-shell.ps1`：打开 `psql`，输入 `\q` 退出，也支持 `-c 'SELECT current_database();'` 等参数。
- 初始化与检查使用非交互连接，需事先配置密码或 PostgreSQL 密码文件；交互终端可提示输入密码。

## 常见问题

| 现象 | 检查项 |
| --- | --- |
| 找不到 psql | 安装 PostgreSQL 客户端工具；将安装目录的 `bin` 写入 `PG_BIN` |
| 连接被拒绝 | 服务是否启动，`PGHOST`、`PGPORT` 是否与本机安装一致 |
| 密码认证失败 | `.env` 中的用户和密码是否正确，是否被进程环境变量覆盖 |
| 数据库不存在 | 先运行初始化，或请数据库管理员建立 `PGDATABASE` 对应库 |
| 没有创建数据库权限 | 请管理员建库并授权；不要修改或删除其他项目数据库 |

## 从项目内数据库切换的记录

已临时启动旧实例检查：只有 `postgres` 与 `simulate_alipay` 两个非模板库，没有业务表；已保留逻辑备份 `backups/postgresql-project-before-system.sql`，未导出角色密码。

系统实例原本只有 `postgres` 库，现已创建空的 `simulate_alipay` 并通过读写与重复初始化检查。旧实例已正常停止，其程序、数据目录、旧连接配置和下载包已清理。原来的 `start-db.ps1` / `stop-db.ps1` 已移除，避免误操作共享服务。

备份仅用于本次迁移留档，不要未经检查直接向已有系统实例恢复整个集群备份。`.local`、`.venv`、`.env` 和 `backups/` 均被 Git 忽略；可提交的连接模板是 `.env.example`。
