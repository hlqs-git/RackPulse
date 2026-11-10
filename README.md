# RackPulse

**每天自动统计 GPU 机柜的运行状态，并把中文日报发送到飞书。**

0.2.0 将飞书正文精简为全局概览、机柜汇总表和最多10行重点事件；原始详细事件保留在数据库。升级方式与降噪口径见 [0.2.0说明](docs/releases/0.2.0.md)。

RackPulse 从现有 Prometheus / Thanos 读取数据，不安装新的采集器，也不修改监控系统。默认每天北京时间 **08:00** 统计前一天 **00:00–24:00** 的数据。

目前只做统计和通知，不调用 AI 或大模型。没有 Web 管理界面，日常查看使用飞书，手动操作使用命令行或 API。

## 能收到什么

每份日报包含：

- 各机柜 GPU 利用率、功率、采集数量和数据完整率。
- LiteOn / Delta PSU 输入功率、机柜可观测能耗。
- GPU / PSU 数据缺失、高低负载的起止时间及持续时间。
- 具备可比数据时，与前一天的能耗变化。

功率始终分成三种口径：**完整 48 路 PSU 实测、部分 PSU 实测、GPU 代理功率**。部分采集和代理值不会当作完整机柜功率；数据缺失不会补成零。

## 选择部署方式

| 方式 | 适用场景 | 启动的组件 | 操作入口 |
|---|---|---|---|
| [Docker Compose](#docker-compose-部署) | 单台服务器，快速部署 | 应用 + PostgreSQL | `docker compose exec app …` |
| [Kubernetes](deploy/k8s/README.md) | 已有 K8s 集群 | 应用 Deployment + PostgreSQL StatefulSet/PVC | `kubectl -n rackpulse exec …` |

两种方式功能相同，**选一种运行即可**。当前应用需保持单实例，避免重复调度和恢复任务。

## 部署前先准备这些信息

| 项目 | 需要提供的内容 | 填写位置 |
|---|---|---|
| Thanos | 可访问的基础地址，例如 `https://thanos.example.com`；不是Graph页面地址，也不用追加 `/api/v1/query_range` | `THANOS_URL` |
| Thanos鉴权 | 如有Bearer token则填写；当前不支持其他鉴权方式的专用配置 | `THANOS_TOKEN`，无鉴权可留空 |
| 机柜映射 | 每个机柜对应的GPU `host` 正则 | `gpu_host_pattern` |
| PSU品牌 | 每柜为 `liteon` 或 `delta`，只能选一种 | `psu_vendor` |
| 飞书机器人 | 自定义机器人的Webhook地址；如启用签名，再提供签名密钥 | `FEISHU_WEBHOOK_URL` / `FEISHU_SIGNING_SECRET` |
| 数据库密码 | 自行设置一个强密码 | `POSTGRES_PASSWORD`，同时更新 `DATABASE_URL` |
| 管理API令牌 | 自行设置一个长随机字符串 | `API_TOKEN` |

部署主机或Pod必须能访问Thanos和飞书。Thanos需保留目标日期的原始分钟数据，并具有以下指标：

| 数据 | 指标 | 必需标签 |
|---|---|---|
| GPU利用率（0–100） | `gpu_utilization_percent` | `host`, `gpu_id` |
| GPU功率（W） | `gpu_power_watts` | `host`, `gpu_id` |
| LiteOn PSU输入功率（W） | `liteon_psu_input_power_watts` | `rack`, `host`, `psu_id` |
| Delta PSU输入功率（W） | `delta_psu_input_power_watts` | `rack`, `host`, `psu_id` |

## 先理解机柜配置

模板已经列出32个机柜，每柜默认72张GPU、48路PSU。**模板不是可直接运行的真实配置**：需要补齐所有机柜的映射和品牌，未配置时应用会拒绝启动定时任务。

配置示意如下，`delta`仅为格式示例，不代表现场GB200-2-7的实际品牌：

```yaml
racks:
  - rack_id: GB200-2-7
    gpu_host_pattern: 'GB200-POD2-E15-.*'
    psu_vendor: delta
    expected_gpu: 72
    expected_psu: 48
```

保留模板中的其他机柜并逐个补齐。已知GB200-2-7对应 `GB200-POD2-E15-.*`；其他映射需从现场确认。一个GPU host只能匹配一个机柜。PSU按指标的 `rack` 标签归属，不使用GPU的host正则；编号从0或1开始均可。

模板采用JSON格式，也是合法YAML；可以直接编辑，也可以整体改为上面的YAML写法。

## Docker Compose 部署

以下命令在 **Linux服务器的Bash终端** 中执行，需要Git、Docker Engine和Compose插件；Windows PowerShell复制文件使用 `Copy-Item`，编辑操作可用自己的文本编辑器。

### 1. 下载项目

```bash
git clone git@github.com:hlqs-git/RackPulse.git
cd RackPulse
docker --version
docker compose version
```

下载依赖和构建镜像需要网络。服务器无需另外安装Python或PostgreSQL。

### 2. 创建并编辑配置

```bash
cp .env.example .env
cp config/racks.example.yaml config/racks.yaml
```

编辑 `config/racks.yaml`，按上一节补齐32柜配置；编辑 `.env`，至少修改下面这些值：

```dotenv
POSTGRES_PASSWORD=替换成你的数据库密码
DATABASE_URL=postgresql+psycopg://rackpulse:URL编码后的数据库密码@db:5432/rackpulse
API_TOKEN=替换成长随机字符串
THANOS_URL=https://你的Thanos地址
THANOS_TOKEN=
FEISHU_WEBHOOK_URL=https://你的飞书机器人Webhook地址
FEISHU_SIGNING_SECRET=
SCHEDULER_ENABLED=true
RACK_CONFIG=config/racks.yaml
```

不要直接复制示例占位值启动。`DATABASE_URL`中的用户名和数据库名都是 `rackpulse`，Compose数据库主机名是 **`db`**。两个位置的密码必须一致；URL中的特殊字符需要百分号编码，例如 `@` 编成 `%40`。飞书未启用签名时，签名密钥留空。真实 `.env` 与机柜配置已被Git忽略。

### 3. 检查配置并启动

```bash
# 校验Compose变量和配置，不打印展开后的密钥
docker compose config --quiet

# 先启动数据库
docker compose up -d db

# 构建镜像并检查机柜配置；此命令不会采集或推送
docker compose build app
docker compose run --rm --no-deps app rackpulse validate-config

# 上一步应输出 status: valid，再启动应用
docker compose up -d app
```

应用会自动创建/升级数据库表，然后启动API和定时任务。数据库健康检查通过前，应用不会启动。

### 4. 确认服务可用

```bash
docker compose ps
docker compose logs --tail=100 app
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
```

预期：两个容器运行且健康；`/health`返回 `{"status":"ok"}`，`/ready`返回 `{"status":"ready"}`。仅容器启动不等于指标接入成功，继续执行下一步。

API默认只绑定部署服务器的 `127.0.0.1:8000`，从其他电脑直接访问服务器IP不会打开。需要远程访问时使用SSH端口转发或受控反向代理。

### 5. 立即验证日报和飞书

不用等到第二天08:00。将下面日期换成Thanos中**已有完整数据的一天**，例如昨天：

```bash
# 先验证机器人：飞书应收到一条带“测试”标识的消息
docker compose exec app rackpulse test-webhook

# 统计指定日期，只生成日报，不发送
docker compose exec app rackpulse run --date 2026-11-09

# 查看日报，确认不是全量缺失，并核对设备归属和功率来源
docker compose exec app rackpulse report --date 2026-11-09

# 明确发送刚生成的日报
docker compose exec app rackpulse send --date 2026-11-09
```

`run`返回task_id，**不能仅凭task_id判断采集成功**。查看日报内容，必要时通过下文任务状态API检查 `succeeded` / `partial` / `failed`。推送命令应返回 `status: sent`，并在飞书确认收到。至此才完成真实数据和通知的联调。

### 6. 日常运行和更新

服务持续运行后，默认每天北京时间08:00生成上一日首次日报并推送。手动重跑不会自动发送修订稿，需要单独执行 `send`。应用不是周期补跑所有遗漏日期的系统；停机错过的日期请手动补跑。

```bash
# 修改机柜映射后重启，使进程重新读取配置
docker compose restart app

# 修改.env后重建容器，使环境变量生效
docker compose up -d --force-recreate app

# 更新代码和镜像
git pull --ff-only
docker compose up -d --build app

# 停止服务，保留数据库卷
docker compose down
```

数据库存在命名卷 `postgres-data` 中。**不要执行 `docker compose down -v` 来排障，它会删除数据库卷。** 修改已有数据库的密码还需要同步修改数据库角色密码，仅修改 `.env` 不会更改已初始化的数据库。

## Kubernetes 部署

完整步骤见 **[Kubernetes部署手册](deploy/k8s/README.md)**，包括镜像仓库、存储、Secret和健康验证。执行顺序是：

1. 构建镜像并上传到集群可拉取的仓库，在Kustomize中配置镜像地址。
2. 准备 `deploy/k8s/racks.yaml` 和 `deploy/k8s/secrets.env`。
3. 创建命名空间及Secret，再应用Kustomize清单。
4. 等待数据库和应用Ready，测试机器人、生成并发送一份真实日报。

K8s数据库地址是 **`postgres:5432`**，与Compose的 `db:5432` 不同。需要一个动态StorageClass或自行配置PV。应用保持 **1个副本**，使用Recreate更新策略；不要另外添加日报CronJob。

## 手动操作与API

### 命令行

| 命令（接在 `docker compose exec app rackpulse` 后） | 效果 |
|---|---|
| `validate-config` | 检查机柜配置是否完整，不测试远端连接 |
| `discover --date YYYY-MM-DD` | 只读发现PSU品牌，辅助配置；不自动修改文件 |
| `run --date YYYY-MM-DD` | 生成或重算日报，不发送 |
| `report --date YYYY-MM-DD` | 读取最新日报 |
| `test-webhook` | 发送飞书测试消息 |
| `send --date YYYY-MM-DD` | 推送已有日报；相同内容已领取发送记录则跳过 |
| `send --date YYYY-MM-DD --force` | 强制再次发送，可能重复；仅在人工核实后使用 |

### HTTP API

交互文档：`http://127.0.0.1:8000/docs`。除健康检查外，业务API需要 `Authorization: Bearer <API_TOKEN>`。

| 方法 | 路径 | 请求 / 用途 |
|---|---|---|
| GET | `/health`、`/ready` | 进程存活 / 数据库与配置就绪 |
| POST | `/jobs` | `{"day":"2026-11-09"}`，返回202和task_id |
| GET | `/jobs/{task_id}` | 查看任务状态 |
| GET | `/reports/{day}` | 日报正文、统计值和配置快照 |
| POST | `/notifications/test` | 发送测试消息 |
| POST | `/notifications/send` | `{"day":"2026-11-09","force":false}` |

Bash调用示例，先把令牌填入当前终端变量，不要把真实令牌提交到仓库：

```bash
read -rs -p 'API token: ' RACKPULSE_TOKEN; echo
curl --fail -H "Authorization: Bearer $RACKPULSE_TOKEN" \
  http://127.0.0.1:8000/jobs/替换成返回的task_id
```

## 常见问题

| 现象 | 检查与处理 |
|---|---|
| `configuration_incomplete` 或校验失败 | 补齐所有机柜的host正则与PSU品牌；检查正则和品牌拼写 |
| 数据库报连接失败 | Compose用 `db`，K8s用 `postgres`；检查密码、URL编码、数据库健康状态 |
| 服务Ready，但日报全是缺失 | Ready不检查Thanos。核对查询地址、鉴权、日期、四个指标名和host/rack标签；检查数据源查询错误 |
| PSU只有部分数据 | 查看有效设备数量和覆盖分钟；不能把部分PSU和当完整机柜功率 |
| 飞书没有消息 | 先执行test-webhook，核对Webhook、签名、机器人安全设置和网络；查看返回的status |
| 推送返回 `unknown` | 请求可能已经送达，先在飞书确认，再决定是否强制发送；不会盲目自动重试 |
| 推送返回 `skipped` | 同内容已有发送领取记录，包含已发送或待核实的情况；先核查历史结果 |
| 历史日报 `needs_recompute=true` | 前一天被重算过，按日期顺序重新生成后续日报以更新跨日状态 |
| 昨日对比“不可比” | 缺少全天完整、同品牌、同设备集合的PSU数据，不生成误导性差值 |

## 统计口径

- 时间统一Asia/Shanghai，窗口为 `[00:00, 次日00:00)`，1440个分钟桶。默认原始样本年龄超过120秒即视为无效。
- 完整率按有效设备分钟计算。日内见过72卡不代表全天完整；零值有效，NaN/Inf、负功率及冲突副本排除。
- 能耗为有效分钟的功率积分，只表示可观测能耗，不外推缺失时间。
- 高负载≥80%、低负载<10%持续60分钟标记Info；数量不足标记Warning；全无数据持续10分钟标记Critical。高负载本身不表示故障。
- 完整PSU功率相对历史基线偏离30%时标记Warning。基线需要前7日至少3个覆盖≥95%的同设备集合有效日；历史不足则不判断。
- 日报有修订记录、小时采集检查点和内容去重。分钟数据不长期复制存储，历史原始数据继续由Thanos保留。

## 开发与验证状态

本地开发需要Python3.12或更新版本；生产镜像使用Python3.12。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest
python -m compileall src
```

Windows PowerShell激活命令为 `.venv\Scripts\Activate.ps1`。PostgreSQL集成测试需设置专用 `TEST_DATABASE_URL`，不要使用生产数据库。

目前已运行本地夹具测试；Docker镜像构建、K8s服务端校验、真实PostgreSQL、现场Thanos与飞书投递尚未完成验收。部署清单和示例需要先填写真实配置，不能视作已验证的现场部署。7/30日趋势、多渠道、AI和Web界面暂不在当前范围。
