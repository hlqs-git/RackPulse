# Kubernetes 部署

保留 Docker Compose，同时提供 Kustomize 部署：单实例 RackPulse Deployment + ClusterIP Service、PostgreSQL StatefulSet + 20Gi PVC、机柜 ConfigMap 和独立 Secret。使用现有应用内北京时间08:00调度，不额外创建CronJob。

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

更新Secret可用 `kubectl ... create secret ... --dry-run=client -o yaml | kubectl apply -f -`，注意不要把输出或环境文件提交到仓库。变更环境变量后需重启应用。数据库初始密码仅在空数据卷首次初始化时生效；已有数据库密码轮换需同步修改数据库角色密码。

## 3. 校验并部署

```sh
kubectl kustomize deploy/k8s
kubectl apply --dry-run=server -k deploy/k8s
kubectl apply -k deploy/k8s
kubectl -n rackpulse rollout status statefulset/postgres --timeout=300s
kubectl -n rackpulse rollout status deployment/rackpulse --timeout=300s
kubectl -n rackpulse logs deployment/rackpulse -c migrate
kubectl -n rackpulse logs deployment/rackpulse -c app
```

initContainer执行数据库迁移，成功后应用才启动；数据库尚未就绪时迁移容器可能失败重试。启动/存活探针使用 `/health`，就绪探针使用 `/ready`，数据库或机柜配置未就绪时不接收Service流量。

维持 **replicas: 1、Recreate、单个uvicorn worker**，不要配置HPA或手动扩容。目前每实例都有调度、任务恢复及发送状态恢复逻辑；数据库日期锁不是多实例调度的完整替代。Recreate在升级时有短暂中断，但避免新旧调度器重叠。数据库使用单副本，生产HA/备份可使用已有受管PostgreSQL：删除postgres资源引用并修改Secret里的DATABASE_URL。

## 4. 访问与手动操作

默认仅集群内访问；从本机管理可转发：

```sh
kubectl -n rackpulse port-forward service/rackpulse 8000:8000
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse validate-config
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse test-webhook
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse run --date 2026-11-09
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse send --date 2026-11-09
```

API仍要求Bearer token，详见项目README。外部访问可按现有集群规范另配Ingress/TLS。

## 更新、备份与卸载

修改机柜文件后重新apply，ConfigMap内容哈希变化会触发Recreate；仅修改Secret需执行 `kubectl -n rackpulse rollout restart deployment/rackpulse`。升级镜像时为两个容器统一更新镜像映射，并提前备份数据库；回滚应用镜像不会自动回滚数据库迁移。

可使用 `kubectl -n rackpulse exec statefulset/postgres -- pg_dump -U rackpulse -d rackpulse -Fc > rackpulse.dump` 备份，在独立数据库验证恢复。Windows PowerShell请使用支持原始字节重定向的版本或采用本地pg_dump，避免二进制备份被文本重定向损坏。

`kubectl delete -k deploy/k8s` 包含删除命名空间，会连同PVC和Secret一起删除，PVC底层数据能否恢复取决于存储回收策略。需要保留数据库时仅删除应用Deployment/Service，先确认备份，勿将删除命名空间当作重启操作。

本次仅提供清单，开发环境没有kubectl或Docker，也没有集群连接，尚未进行服务端校验、镜像构建或真实部署。
