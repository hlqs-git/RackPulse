# Kubernetes 部署

保留 Docker Compose，同时提供 Kustomize 部署：单实例 RackPulse Deployment + ClusterIP Service、PostgreSQL StatefulSet + 20Gi PVC、机柜 ConfigMap 和独立 Secret。使用现有应用内北京时间08:00调度，不额外创建CronJob。

**完成标准：** 数据库和应用Ready → 飞书收到测试消息 → 指定日期生成真实日报 → 飞书收到该日报。只看到Pod Running不代表数据源和通知已接通。

以下为Linux/Bash命令，所有路径均相对项目根目录；先执行：

```sh
git clone git@github.com:hlqs-git/RackPulse.git
cd RackPulse
kubectl config current-context
kubectl get nodes
kubectl get storageclass
```

确认当前context是要部署的集群，节点Ready；StorageClass列表应有默认类，否则按下一节指定存储类。机柜配置字段和Thanos指标要求见 [项目README](../../README.md#部署前先准备这些信息)。

## 前提

需要可用集群、kubectl（内置Kustomize）、默认动态StorageClass，以及集群可拉取的RackPulse镜像。集群需能访问Thanos和飞书HTTPS。没有默认StorageClass时，在 `postgres.yaml` 的volumeClaimTemplates.spec中填写storageClassName。资源限额是初始值，按真实采集量调整。

## 1. 准备镜像

在项目根目录执行，替换示例镜像仓库：

```sh
docker build -t registry.example.com/infra/rackpulse:0.1.0 .
docker push registry.example.com/infra/rackpulse:0.1.0
```

在 `kustomization.yaml` 追加镜像映射，会同时替换迁移和应用容器：

```yaml
images:
  - name: rackpulse
    newName: registry.example.com/infra/rackpulse
    newTag: 0.1.0
```

私有仓库需另外创建imagePullSecret并在Deployment.spec.template.spec.imagePullSecrets中引用。本地kind等集群也可预加载 `rackpulse:0.1.0`。

如果镜像仓库要求登录，应先在构建机执行 `docker login registry.example.com`。集群拉取凭据与构建机登录是两回事：按集群现有方式创建仓库Secret后，在 `app.yaml` 的 `spec.template.spec` 添加：

```yaml
imagePullSecrets:
  - name: 你的仓库拉取Secret名称
```

该Secret必须位于 `rackpulse` 命名空间，创建步骤应放在下文创建命名空间之后。

## 2. 配置机柜与凭据

在项目根目录复制并编辑：

```sh
cp config/racks.example.yaml deploy/k8s/racks.yaml
cp deploy/k8s/secrets.env.example deploy/k8s/secrets.env
```

补齐全部32柜GPU映射和PSU品牌。`secrets.env` 中使用K8s数据库地址 `postgres:5432`，不要照搬Compose的 `db:5432`。DATABASE_URL密码须URL编码，POSTGRES_PASSWORD保持原始值。填入Thanos地址与鉴权、API token及飞书Webhook。两个本地文件已被Git忽略。

先创建命名空间和Secret，凭据不写入普通清单：

```sh
kubectl apply -f deploy/k8s/namespace.yaml
kubectl -n rackpulse create secret generic rackpulse-secrets --from-env-file=deploy/k8s/secrets.env
```

后续更新已有Secret时使用完整命令：

```sh
kubectl -n rackpulse create secret generic rackpulse-secrets \
  --from-env-file=deploy/k8s/secrets.env --dry-run=client -o yaml | kubectl apply -f -
kubectl -n rackpulse rollout restart deployment/rackpulse
```

不要把管道中间的Secret YAML或环境文件提交到仓库。数据库初始密码仅在空数据卷首次初始化时生效；已有数据库密码轮换需同步修改数据库角色密码。

## 3. 校验并部署

```sh
kubectl kustomize deploy/k8s
kubectl apply --dry-run=server -k deploy/k8s
kubectl apply -k deploy/k8s
kubectl -n rackpulse rollout status statefulset/postgres --timeout=300s
kubectl -n rackpulse rollout status deployment/rackpulse --timeout=300s
kubectl -n rackpulse get pods,pvc,svc
kubectl -n rackpulse logs deployment/rackpulse -c migrate
kubectl -n rackpulse logs deployment/rackpulse -c app
```

initContainer执行数据库迁移，成功后应用才启动；数据库尚未就绪时迁移容器可能失败重试。启动/存活探针使用 `/health`，就绪探针使用 `/ready`，数据库或机柜配置未就绪时不接收Service流量。

维持 **replicas: 1、Recreate、单个uvicorn worker**，不要配置HPA或手动扩容。目前每实例都有调度、任务恢复及发送状态恢复逻辑；数据库日期锁不是多实例调度的完整替代。Recreate在升级时有短暂中断，但避免新旧调度器重叠。数据库使用单副本，生产HA/备份可使用已有受管PostgreSQL：删除postgres资源引用并修改Secret里的DATABASE_URL。

## 4. 访问与手动操作

默认仅集群内访问；从本机管理可转发：

```sh
kubectl -n rackpulse port-forward service/rackpulse 8000:8000
```

保持该终端运行，另开一个终端执行：

```sh
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
```

预期分别返回 `status: ok` 和 `status: ready`。然后检查配置和真实推送链路，将日期替换成Thanos中有数据的完整自然日：

```sh
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse validate-config
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse test-webhook
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse run --date 2026-11-09
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse report --date 2026-11-09
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse send --date 2026-11-09
```

validate-config应返回valid；test-webhook应返回sent且飞书收到测试消息；report应有真实设备数据而不是全量缺失；最后send应返回sent且飞书收到日报。run仅返回task_id不能代表采集成功，失败或partial状态可用任务API核查。手动run不会自动发送，send才会推送。正常运行后每天北京时间08:00自动统计并发送上一日首次日报。

API仍要求Bearer token，详见项目README。外部访问可按现有集群规范另配Ingress/TLS。停机错过的日报需手动补跑。

## 常见部署故障

| 现象 | 检查方式 |
|---|---|
| PVC一直Pending | `kubectl -n rackpulse describe pvc data-postgres-0`，检查StorageClass及存储配额 |
| ImagePullBackOff | 检查镜像映射、标签、集群到仓库的网络及imagePullSecrets |
| 应用停在Init或迁移重试 | 查看migrate日志和postgres Pod状态；核对DATABASE_URL主机名、密码及URL编码 |
| CrashLoopBackOff | 查看 `kubectl -n rackpulse logs deployment/rackpulse -c app --previous`；检查32柜配置是否完整 |
| Pod运行但未Ready | 查看 `/ready` 和数据库状态；Ready不检查Thanos或飞书 |
| 部署成功但没有日报 | 执行手动run/report，检查目标日期、Thanos指标和标签；用test-webhook单独验证通知 |

## 更新、备份与卸载

修改机柜文件后重新apply，ConfigMap内容哈希变化会触发Recreate；仅修改Secret需执行 `kubectl -n rackpulse rollout restart deployment/rackpulse`。升级镜像时为两个容器统一更新镜像映射，并提前备份数据库；回滚应用镜像不会自动回滚数据库迁移。

可使用 `kubectl -n rackpulse exec statefulset/postgres -- pg_dump -U rackpulse -d rackpulse -Fc > rackpulse.dump` 备份，在独立数据库验证恢复。Windows PowerShell请使用支持原始字节重定向的版本或采用本地pg_dump，避免二进制备份被文本重定向损坏。

`kubectl delete -k deploy/k8s` 包含删除命名空间，会连同PVC和Secret一起删除，PVC底层数据能否恢复取决于存储回收策略。需要保留数据库时仅删除应用Deployment/Service，先确认备份，勿将删除命名空间当作重启操作。

本次仅提供清单，开发环境没有kubectl或Docker，也没有集群连接，尚未进行服务端校验、镜像构建或真实部署。
