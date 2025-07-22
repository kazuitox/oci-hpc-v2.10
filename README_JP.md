# HPC クラスター構築用スタック

[![Oracle Cloud へデプロイ](https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg)](https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/kazuitox/oci-hpc-v2.10/archive/refs/heads/master.zip)

## スタックをデプロイするためのポリシー

```
allow service compute_management to use tag-namespace in tenancy
allow service compute_management to manage compute-management-family in tenancy
allow service compute_management to read app-catalog-listing in tenancy
allow group user to manage all-resources in compartment compartmentName
```

## オートスケーリング／リサイズ用のポリシー

変数の設定時に認証方式として *instance‑principal* を選択する場合は、動的グループを作成し、以下のポリシーを付与してください。

```
Allow dynamic-group instance_principal to read app-catalog-listing in tenancy
Allow dynamic-group instance_principal to use tag-namespace in tenancy
```

さらに、次のいずれかを追加します。

```
Allow dynamic-group instance_principal to manage compute-management-family in compartment compartmentName
Allow dynamic-group instance_principal to manage instance-family in compartment compartmentName
Allow dynamic-group instance_principal to use virtual-network-family in compartment compartmentName
Allow dynamic-group instance_principal to use volumes in compartment compartmentName
```

または

```
Allow dynamic-group instance_principal to manage all-resources in compartment compartmentName
```

## 対応 OS

このスタックでは複数の OS 組み合わせを選択できます。以下は動作確認済みの組み合わせであり、その他は保証外です。

| コントローラ       | コンピュート       |
| ------------ | ------------ |
| OL7          | OL7          |
| OL7          | OL8          |
| OL7          | CentOS7      |
| OL8          | OL8          |
| OL8          | OL7          |
| Ubuntu 20.04 | Ubuntu 20.04 |

Ubuntu を使用する場合は、ORM でコントローラ／コンピュート両方のユーザー名を `opc` から `ubuntu` に変更してください。

## リサイズとオートスケーリングの違い

* **オートスケーリング**: キューにあるジョブごとに新しいクラスターを起動します。
* **リサイズ**: 既存クラスターのノード数を変更します。拡張時にはキャパシティ不足となる場合がある点に注意してください。Oracle Cloud の RDMA は仮想化されていないため高性能ですが、ネットワークブロックごとに容量が分割されています。そのため、データセンターに空き容量があっても現在のクラスターを拡張できない場合があります。

# クラスターネットワークのリサイズ（resize.sh）

クラスターリサイズは既存クラスターへのノード追加・削除、または再設定を行います。

1. **ノードの追加／削除（IaaS プロビジョニング）** – OCI Python SDK を使用
2. **ノードの設定（Ansible）**

   * 追加ノードのジョブ実行準備
   * Slurm などのサービス再設定
   * ノード削除時に残りのノードを更新（`/etc/hosts` や Slurm 設定など）

オートスケーリングで作成されたクラスターも `--cluster_name cluster-1-hpc` を指定すればリサイズ可能です。

## resize.sh の使い方

`resize.sh` はスタック展開時にコントローラノードの `/opt/oci-hpc/bin/` に配置されます。インベントリ内に SSH 不可ノードがある場合、`--remove_unreachable` を付けない限りクラスター変更を行いません。

```
/opt/oci-hpc/bin/resize.sh -h
usage: resize.sh ... [{add,remove,list,reconfigure}] [number]
```

### ノード追加

```
/opt/oci-hpc/bin/resize.sh add 1
/opt/oci-hpc/bin/resize.sh add 3 --cluster_name compute-1-hpc
```

### ノード削除

```
/opt/oci-hpc/bin/resize.sh remove --nodes inst-dpi8e-assuring-woodcock
/opt/oci-hpc/bin/resize.sh remove --nodes inst-dpi8e-assuring-woodcock inst-ed5yh-assuring-woodcock
/opt/oci-hpc/bin/resize.sh remove 1
/opt/oci-hpc/bin/resize.sh remove 3 --cluster_name compute-1-hpc --quiet
```

### ノード再設定

```
/opt/oci-hpc/bin/resize.sh reconfigure
```

## OCI コンソールからのリサイズ

* サイズ縮小時には最も古いノードが優先的に終了されます。
* コンソール上のリサイズはノード設定を行わないため、`/etc/hosts` や Slurm 設定は手動で更新する必要があります。

# オートスケーリング

ジョブごとにクラスターを作成・削除する「クラスター per ジョブ」方式です。デフォルトでは 10 分間アイドル状態が続くとクラスターを削除します。初期クラスター（スタック展開時のもの）は削除されません。

設定ファイル `/opt/oci-hpc/conf/queues.conf`（サンプル: `.example`）で複数キューやインスタンスタイプを定義できます。変更後は

```
/opt/oci-hpc/bin/slurm_config.sh
```

を実行してください。

オートスケーリングを有効にするには `crontab -e` で以下をアンコメントします。

```
* * * * * /opt/oci-hpc/autoscaling/crontab/autoscale_slurm.sh >> /opt/oci-hpc/logs/crontab_slurm.log 2>&1
```

さらに `/etc/ansible/hosts` で

```
autoscaling = true
```

とします。

# ジョブの投入例

`/opt/oci-hpc/samples/submit/` に例があります。

```bash
#!/bin/sh
#SBATCH -n 72
#SBATCH --ntasks-per-node 36
#SBATCH --exclusive
#SBATCH --job-name sleep_job
#SBATCH --constraint hpc-default
...
sleep 1000
```

* **インスタンスタイプ指定**: `--constraint` で `/opt/oci-hpc/conf/queues.conf` に定義したタイプを指定できます。
* **cpu-bind**: Ubuntu 22.04 でハイパースレッディング無効時に `task_g_set_affinity` エラーが出る場合は `--cpu-bind=none` などを試してください。

## クラスター関連ディレクトリ

* クラスターデータ: `/opt/oci-hpc/autoscaling/clusters/clustername`
* ログ: `/opt/oci-hpc/logs`

## 手動クラスター操作

### 作成

```
/opt/oci-hpc/bin/create_cluster.sh 4 compute2-1-hpc HPC_instance compute2
```

### 削除

```
/opt/oci-hpc/bin/delete_cluster.sh clustername
/opt/oci-hpc/bin/delete_cluster.sh clustername FORCE
```

# LDAP

コントローラが LDAP サーバーとして動作（デフォルト）。ユーザー管理は `cluster` コマンドで行います。例:

```
cluster user add name --gid 9876 --nossh
```

# 共有ホームディレクトリ

デフォルトではコントローラから NFS で `/home` を共有します。FSS を使用する場合は `/home` ではなく `$nfsshare/home` をマウントします。

# プライベートサブネット内でのデプロイ

`true` を選択すると、Resource Manager がプライベートサブネット内のコントローラ／ノードを設定するためのプライベートエンドポイントを作成します。アクセスには Controller Services、VPN/FastConnect、ジャンプホスト、あるいは VCN ピアリングが必要です。

# スクリプト・ユーティリティ

## max\_nodes\_partition.py

```
max_nodes
max_nodes --include_cluster_names clusterA clusterB
```

## validation.py

```
validate -n y
validate -p y -cn cluster_list.txt
...
```

## collect\_logs.py

```
python3 collect_logs.py --hostname compute-node-1
```

## RDMA NIC メトリクスの収集と Object Storage へのアップロード

1. **PAR 作成**: スタック作成時に「Create Object Storage PAR」を有効化。
2. **スクリプト実行**: `upload_rdma_nic_metrics.sh` と `rdma_metrics_collection_config.conf` を使用し、メトリクスを収集してアップロード。

