# 工学云实习助手 · GongXueYun Console

**自托管的工学云（GongXueYun / 蘑菇丁）多账号考勤、节假日日历与实习报告管理台。**

基于 **FastAPI + Vue 3 + TypeScript**，支持管理员与子账号、三种打卡类型、三源节假日同步、地图选点、报告草稿和执行记录。桌面与手机浏览器均可使用。

> **非官方项目，与工学云及相关平台无隶属或合作关系。**
> 仅在获得授权、符合学校和平台规则的前提下使用。项目不提供绕过本人实名/人脸验证的能力，不保证任意学校、账号或接口版本可用。

[快速部署](#快速部署docker-compose) · [本地运行](#本地运行) · [日历规则](#日历与自动排班) · [文档](#文档) · [安全与限制](#安全与限制)

## 能做什么

| 模块 | 功能 |
| --- | --- |
| 账号管理 | 多个工学云账号、管理员/子账号权限、登录检测、打卡地点与时间设置 |
| 考勤 | 上班 `START`、下班 `END`、休息/节假日 `HOLIDAY`，手动提交与补卡入口 |
| 自动排班 | 普通日期默认每日上下班；官方放假区间一次休息卡；调休补班正常上下班；支持按账号、按日期覆盖 |
| 打卡日历 | 月历展示放假/补班标记、每日预计任务、已确认/待确认/异常统计，点击日期查看安排与记录 |
| 节假日同步 | 中国政府网 + holiday-cn + 提莫 API；启动及每日自动更新、本地缓存、来源与冲突状态可见 |
| 地图与地址 | Leaflet 选点、WGS-84/GCJ-02 换算、地址搜索与反查、可配置底图与高德 Web 服务 Key |
| 实习报告 | 岗位人设、周/月写作大纲、日报/周报/月报草稿；OpenAI 兼容 AI 接口与模板回退 |
| 验证与日志 | 待本人验证任务、手动点选入口、执行结果、通知；提交响应与记录确认分开显示 |

**“请求已提交”不等于“打卡成功”。** 系统会查询服务端考勤记录；未确认、待验证与失败分别展示。日历统计按账号、日期、打卡类型去重，不把重试次数当作完成次数。

## 快速部署（Docker Compose）

需要 Git、Docker Engine 和 Docker Compose v2。

```bash
git clone https://github.com/404-Wont-Fix/gongxueyun-console.git
cd gongxueyun-console
cp .env.example .env
```

编辑 `.env`，**至少修改以下两项**：

```dotenv
APP_SECRET=替换为至少32位的随机密钥
ADMIN_PASSWORD=替换为独立的强密码
```

可用 Python 生成随机密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

然后启动：

```bash
mkdir -p data models
# Linux：后端容器以 UID 10001 运行，确保数据目录可写
sudo chown -R 10001:10001 data models
docker compose up -d --build
```

Windows/macOS 请使用相应的目录创建方式，并确保 Docker Desktop 可以访问挂载目录；通常无需执行上述 `chown`。

- **管理台**：<http://localhost:8080>
- **健康检查**：<http://localhost:8000/api/health>
- **登录账号**：`.env` 中的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`
- **持久化数据**：`data/`，默认数据库为 `data/gxy.db`

```bash
docker compose logs -f backend     # 查看服务日志
docker compose stop               # 停止服务，保留数据
docker compose up -d              # 再次启动
```

首次启动会创建管理员。**修改 `.env` 的管理员密码不会重置已有用户密码**；已有账号请在管理台修改。升级前备份数据库和 `APP_SECRET`，不要随意更换密钥。

> 从旧名称的 Compose 部署升级时，先停止旧项目，再启动 `gongxueyun-console`，避免旧、新容器同时运行调度器。保留原来的 `data/` 与 `.env`。

## 本地运行

建议使用 **Python 3.12+、Node.js 22 LTS**。以下命令从仓库根目录执行。

### 1. 配置环境

复制 `.env.example` 为 `.env`，设置强密码和随机密钥。本地运行时将数据库地址改为：

```dotenv
DATABASE_URL=sqlite:///./data/gxy.db
# 本地开发建议先关闭打卡/报告调度，避免意外写入真实账号
SCHEDULER_ENABLED=false
```

节假日日历同步独立于打卡调度，仍会联网读取公开日历数据。

### 2. 后端

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell 改用：.\.venv\Scripts\Activate.ps1

python -m pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### 3. 前端（另开终端）

```bash
cd frontend
npm ci
npm run dev
```

打开 <http://localhost:5173>。Vite 已将 `/api` 代理到本机 `8000` 端口。

也可以执行 `npm run build`，然后从仓库根目录启动后端，使用 <http://localhost:8000> 访问已构建的静态页面。首次构建完成后需要重新启动后端，以注册静态资源路由。

## 首次使用

1. 登录管理台，在 **账号管理** 中添加自己的工学云账号。
2. 执行 **登录检测**，确认能获取实习计划；配置真实打卡地址与坐标。
3. 设置上下班时间、普通日期执行星期，以及是否跟随官方放假/调休。
4. 打开 **打卡日历**，核对来源状态、未来安排；按需为某一天设置覆盖。
5. 需要自动执行时，再开启账号的 **自动打卡**，并确认服务端 `SCHEDULER_ENABLED=true`。
6. 日历选中一个账号后，可点击 **同步该账号工学云记录**。该操作只查询，不提交打卡。
7. 需要报告时填写岗位人设，再配置 AI 或使用模板；检查草稿后提交。
8. 遇到本人验证，请按 **验证中心** 提示使用官方渠道处理，不要连续重试提交。

## 日历与自动排班

### 三个来源怎么用

- **[中国政府网](https://www.gov.cn/)**：读取国务院办公厅年度放假通知，是官方日期依据。
- **[holiday-cn](https://github.com/NateScarlet/holiday-cn)**：提供全年 JSON 及政府公告链接。
- **[提莫节假日 API](https://timor.tech/api/holiday/)**：提供结构化放假与补班数据。

后两个来源为第三方项目，**不是政府官方 API**。系统启动时获取当年和下一年，此后每 24 小时更新；只核对日期性质，不要求各源对节日名称的文字完全一致。

- 政府完整原文可解析，或两个结构化源完整且一致时，才采用年度数据。
- 来源冲突不覆盖上一次可信缓存，页面显示冲突状态。
- 断网保留缓存；新一年未公布或没有可信数据时，暂停依赖该日历的自动打卡，不猜测日期。
- 政府网页结构与第三方接口可能变化，无法承诺永久可用。

### 规则优先级

**账号单日覆盖 → 官方放假/调休 → 账号普通执行星期。**

- 新账号普通日期默认一周七天上下班，包括普通周末；已有账号保留工作日选择。
- 官方整个放假区间：每天按该账号的上班时间提交一次 `HOLIDAY`，不再安排上下班卡。
- 调休补班日期：按上、下班开关与时间执行。
- 单日可覆盖为正常上下班、休息卡或不自动打卡；设置安排不会立即提交。

日历中的预计任务依据**当前配置**计算，不是历史排班快照。已知记录来自本系统确认结果和主动同步的工学云记录，不意味着每次打开页面都会登录全部账号。详见 [日历与自动排班](docs/日历与自动排班.md)。

## 地图与 AI 配置

**地图**：在“设置 → 地图与地址”配置。高德地址搜索/反查需要申请 **Web 服务**类型的 Key；Nominatim 公共服务通常无需 Key，但受网络和使用限额约束。账号的“坐标系”决定坐标数据格式，不是底图选择器。

当前高德栅格模板请求不带 Key，**这不代表官方授权无限免费使用**；地图、瓦片与地址服务的许可、配额和费用以提供方条款为准。反查失败时可以保留坐标、手动填地址。

**AI**：在“设置 → AI 写作”填写 OpenAI 兼容的 Base URL、模型和 Key。未配置时回退到模板。密钥加密保存，页面的圆点仅代表已保存，不回传真值。AI 内容需自行核对，尤其是启用自动报告前。

## 技术结构

```text
gongxueyun-console/
├── backend/
│   ├── app/api/           鉴权、账号、日历、记录、报告等 REST API
│   ├── app/gxy/           工学云请求、签名与载荷模型
│   ├── app/services/      调度、日历同步、地图、AI、报告与验证
│   └── tests/             后端离线测试
├── frontend/
│   ├── src/views/         Vue 管理页面
│   ├── src/components/    通用界面组件
│   └── tests/             Playwright CLI 浏览器回归脚本
├── docs/                  架构、协议与部署说明
├── .env.example           配置模板，不含实际凭据
└── docker-compose.yml     FastAPI + nginx 部署配置
```

后端使用 FastAPI、SQLAlchemy、SQLite、APScheduler；前端使用 Vue 3、TypeScript、Vite、Pinia 和 Leaflet。管理员密码使用 scrypt，托管账号密码、会话及服务 Key 使用基于 `APP_SECRET` 的 Fernet 加密。

## 开发与验证

```bash
python -m pip install -r backend/requirements-dev.txt
cd backend
python -m pytest -q -p no:cacheprovider

# 回到仓库根目录后
cd ../frontend
npm ci
npm run typecheck
npm run build
```

浏览器回归脚本需已启动且登录的本地预览和 Playwright CLI；从仓库根目录运行：

```bash
playwright-cli run-code --filename=frontend/tests/map-settings.browser.js
playwright-cli run-code --filename=frontend/tests/calendar.browser.js
```

这些浏览器脚本模拟配置写入，不用于真实打卡。测试通过不代表真实工学云账号已完成端到端验证。

## 安全与限制

- **不要公开暴露管理后台**。建议使用本机、VPN 或受访问控制的 HTTPS 反向代理；Compose 默认发布的端口需要自行配置防火墙。
- 不要提交 `.env`、数据库/备份、日志、浏览器登录态、抓包或真实账号信息。提交 Issue 时也应先脱敏。
- `APP_SECRET` 与数据库应一起安全备份；丢失或更换密钥可能导致已保存的密码和会话无法解密。
- AI 和通知服务可能接收到实习信息或操作摘要，请确认接收方可信。
- 定时器在后端进程内运行。建议单副本部署，避免多个进程同时调度。
- 项目仍处于开发阶段，未完成所有学校规则、验证续提分支和真实账号流程的验证；附件、审批、频控等能力存在限制。
- 自动报告会尝试生成并提交内容，不是强制人工审核模式；初次使用请保持关闭。
- 本地测试不等同于安全审计或生产可用性保证；Docker Compose 配置仍需在你的环境实际验证。

## 文档

- [部署与运维](docs/部署与运维.md)
- [架构设计](docs/架构设计.md)
- [日历与自动排班](docs/日历与自动排班.md)
- [休息/节假日打卡](docs/休息节假日打卡.md)
- [协议实现说明与未确认事项](docs/协议实现说明.md)

## 实现参考与使用边界

实现参考了工学云 5.41.6 的分析记录及较新的公开实现，主要包括：

- [tangqingfeng7/AutoCheck-in-GongXueYun](https://github.com/tangqingfeng7/AutoCheck-in-GongXueYun)
- [27xk/gongxueyun](https://github.com/27xk/gongxueyun)

本独立仓库不分发 APK、反编译产物、参考仓库副本或用户运行数据。协议文档中的 `analysis/`、`APK/`、`repos/` 路径属于开发阶段的外部研究目录，并非本仓库文件。第三方项目、接口及素材的权利和许可归各自权利人所有。

请勿用于虚假考勤、伪造实习内容、绕过验证或未经授权操作他人账号。使用者需自行确认学校、平台及法律要求。公开源码不代表获得第三方平台授权；本仓库尚未附加开源许可证，不据此承诺商用或再分发授权。
