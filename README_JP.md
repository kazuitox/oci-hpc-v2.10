# HPC クラスター構築スタック

[![Oracle Cloud へデプロイ](https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg)](https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/kazuitox/oci-hpc-v2.10/archive/refs/heads/master.zip)

---

## スタックをデプロイするためのポリシー

```text
allow service compute_management to use tag-namespace in tenancy
allow service compute_management to manage compute-management-family in tenancy
allow service compute_management to read app-catalog-listing in tenancy
allow group user to manage all-resources in compartment compartmentName
```

---

## オートスケーリング／リサイズ用のポリシー

変数設定で認証方式に *instance‑principal* を選択した場合は、動的グループを作成し、次のポリシーを付与してください。

```text
Allow dynamic-group instance_principal to read app-catalog-listing in tenancy
Allow dynamic-group instance_principal to use tag-namespace in tenancy
```

さらに、以下のいずれかを追加します。

```text
Allow dynamic-group instance_principal to manage compute-management-family in compartment compartmentName
Allow dynamic-group instance_principal to manage instance-family in compartment compartmentName
Allow dynamic-group instance_principal to use virtual-network-family in compartment compartmentName
Allow dynamic-group instance_principal to use volumes in compartment compartmentName
```

または

```text
Allow dynamic-group instance_principal to manage all-resources in compartment compartmentName
```

---

## 対応 OS 組み合わせ

下表は動作確認済みの組み合わせです。記載以外の組み合わせは保証対象外です。

| コントローラ         | コンピュート         |
| -------------- | -------------- |
| Oracle Linux 7 | Oracle Linux 7 |
| Oracle Linux 7 | Oracle Linux 8 |
| Oracle Linux 7 | CentOS 7       |
| Oracle Linux 8 | Oracle Linux 8 |
| Oracle Linux 8 | Oracle Linux 7 |
| Ubuntu 20.04   | Ubuntu 20.04   |

Ubuntu を利用する場合は、ORM でコントローラ／コンピュート両方のユーザー名を `opc` から `ubuntu` に変更してください。

---

## リサイズとオートスケーリングの違い

* **オートスケーリング**: キュー内のジョブごとに新しいクラスターを起動します。
* **リサイズ**: 既存クラスターのノード数を変更します。Oracle Cloud の RDMA は非仮想化のため高性能ですが、ネットワークブロック単位でキャパシティが分割されています。そのため、データセンターに空きがあっても現在のクラスターを拡張できない場合があります。

---

# クラスターネットワークのリサイズ（resize.sh）

リサイズは次の 2 段階で実行されます。

1. **ノードの追加／削除**（IaaS プロビジョニング） — OCI Python SDK を使用
2. **ノードの設定**（Ansible）

   * 追加ノードのジョブ実行準備
   * Slurm などのサービスを全ノードで再設定
   * ノード削除時の `/etc/hosts`・Slurm 設定更新

オートスケーリングで作成したクラスターも `--cluster_name cluster-1-hpc` を指定すればリサイズ可能です。

## resize.sh の使い方

`resize.sh` はコントローラの `/opt/oci-hpc/bin/` に配置されています。インベントリ内で SSH できないノードがある場合、`--remove_unreachable` を付けない限りクラスター変更を行いません。

```text
/opt/oci-hpc/bin/resize.sh -h
usage: resize.sh ... {add,remove,list,reconfigure} [number]
```

主なオプション（抜粋）

* `--nodes`    削除対象ノードを列挙
* `--no_reconfigure` 追加/削除後に Ansible を実行しない
* `--force`    削除時に Playbook が失敗してもノードを強制削除
* `--remove_unreachable` 事前に SSH 不可ノードを削除
* `--quiet`    削除時の確認プロンプトとデータ保存リマインダーを省略

### ノード追加

```bash
/opt/oci-hpc/bin/resize.sh add 1                       # 1 ノード追加
/opt/oci-hpc/bin/resize.sh add 3 --cluster_name compute-1-hpc
```

### ノード削除

```bash
/opt/oci-hpc/bin/resize.sh remove --nodes inst-xxxx
/opt/oci-hpc/bin/resize.sh remove 1
/opt/oci-hpc/bin/resize.sh remove 3 --cluster_name compute-1-hpc --quiet
```

### ノード再設定

```bash
/opt/oci-hpc/bin/resize.sh reconfigure
```

## OCI コンソールからのリサイズ時の注意

* 縮小時は OCI が（通常は最も古い）ノードを選択して終了します。
* コンソール操作だけでは Ansible が実行されないため、`/etc/hosts` や Slurm 設定は手動更新が必要です。

---

# オートスケーリング

「クラスター per ジョブ」方式でジョブごとにクラスターを起動・削除します。デフォルトではアイドル 10 分後にクラスターを削除します。スタック展開時の初期クラスターは削除されません。

* 設定ファイル: `/opt/oci-hpc/conf/queues.conf`（サンプル: `.example`）
* 変更後は `sudo /opt/oci-hpc/bin/slurm_config.sh` を実行
* 初期化したい場合は `--initial` を付与
* オートスケーリングを有効化するには `crontab -e` で以下を有効化

  ```text
  * * * * * /opt/oci-hpc/autoscaling/crontab/autoscale_slurm.sh >> /opt/oci-hpc/logs/crontab_slurm.log 2>&1
  ```

  `/etc/ansible/hosts` で `autoscaling = true` も設定

---

# ジョブ投入例

`/opt/oci-hpc/samples/submit/` の例:

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

* **インスタンスタイプ**: `--constraint` に queues.conf で定義したタイプを指定可能
* **cpu-bind**: Ubuntu 22.04 + HT 無効環境で `task_g_set_affinity` エラーが出る場合は `--cpu-bind=none` などを指定

---

## クラスター関連ディレクトリ

```text
/opt/oci-hpc/autoscaling/clusters/<clustername>
```

## ログ

```text
/opt/oci-hpc/logs
```

クラスターごとに `create_<clustername>_<date>.log` と `delete_<clustername>_<date>.log` が生成されます。Cron のログは `crontab_slurm.log` です。

---

## 手動クラスター操作

### 作成

```bash
/opt/oci-hpc/bin/create_cluster.sh <ノード数> <clustername> <instance_type> <queue_name>
例:
/opt/oci-hpc/bin/create_cluster.sh 4 compute2-1-hpc HPC_instance compute2
```

クラスター名は `queueName-clusterNumber-instanceType_keyword` の形式とし、`keyword` は queues.conf の定義と一致させます。

### 削除

```bash
/opt/oci-hpc/bin/delete_cluster.sh <clustername>
/opt/oci-hpc/bin/delete_cluster.sh <clustername> FORCE  # 強制削除
```

削除中は `.../clusters/<clustername>/currently_destroying` ファイルが作成されます。

---

## オートスケーリングモニタリング

Grafana ダッシュボードでスケールイン／アウト状況とジョブ状態を閲覧できます（Dashboard のインポートのみ手動）。

1. ブラウザで `http://<controllerIP>:3000` へアクセス（初期 ID/PW: `admin/admin`）。
2. **Configuration → Data Sources** で `autoscaling` を選択し、Password に `Monitor1234!` を入力し **Save & Test**。
3. 左メニューの **＋ → Import** で `/opt/oci-hpc/playbooks/roles/autoscaling_mon/files/dashboard.json` をアップロードし、Data Source に **autoscaling (MySQL)** を選択。

---

# LDAP

コントローラはクラスター用 LDAP サーバーとして動作します（ホームディレクトリ共有を推奨）。
ユーザー管理は `cluster` コマンドで実行します。例:

```bash
cluster user add <name> --gid 9876 --nossh
```

グループ `privilege`（GID 9876）は NFS と sudo 権限を持ちます（スタック作成時に変更可能）。

---

# 共有ホームディレクトリ

デフォルトではコントローラから NFS で `/home` を共有します。FSS を利用する場合は `/home` を直接マウントせず、`$nfsshare/home` を作成・マウントします（スタックが自動で設定）。

---

# プライベートサブネットでのデプロイ

`true` を選択すると、Resource Manager がプライベートサブネット内のコントローラと将来のノードを設定するためのプライベートエンドポイントを作成します。

* **新規サブネット**を使用しない場合は、コントローラ用プライベートサブネットを指定してください。コンピュートノードは同一または別サブネットに配置できます。
* コントローラはプライベートサブネットに配置されるため、Controller Services、VPN/FastConnect、ジャンプホスト、または VCN ピアリングを介したアクセスが必要です。

---

## max\_nodes\_partition.py の使い方

```bash
max_nodes                                # すべてのパーティションと最大ノード数を表示
max_nodes --include_cluster_names A B C  # 指定クラスターのみ対象
```

---

## validation.py の使い方

```bash
validate -n y                                # ノード数整合性チェック
validate -n y -cn clusters.txt               # 特定クラスター対象
validate -p y -cn clusters.txt               # PCIe 帯域チェック
validate -p hosts.txt                        # 指定ホストで PCIe チェック
validate -g y -cn clusters.txt               # GPU スロットルチェック
validate -e y -cn clusters.txt               # /etc/hosts MD5 チェック
validate -n y -p y -g y -e y -cn clusters.txt # まとめて実行
```

---

## /opt/oci-hpc/scripts/collect\_logs.py

指定ノードの **NVIDIA bug report**、**sosreport**、**コンソール履歴** を収集します（コントローラで実行）。

```bash
python3 collect_logs.py --hostname <HOSTNAME> [--compartment-id <COMPARTMENT_OCID>]
```

収集結果は `/home/<user>/<hostname>_<timestamp>` に保存されます。

---

## RDMA NIC メトリクスの収集と Object Storage へのアップロード

OCI‑HPC はテナンシごとにデプロイされるため、OCI サービスチームは直接メトリクスへアクセスできません。本機能では RDMA NIC メトリクスを収集し、Object Storage にアップロードして共有できます。

1. **PAR（Pre‑Authenticated Request）を作成**
   スタック作成時に *Create Object Storage PAR* チェックボックスを有効にします（デフォルトで有効）。
2. **upload\_rdma\_nic\_metrics.sh を実行**
   `upload_rdma_nic_metrics.sh` がメトリクスを収集し、Object Storage へアップロードします。収集対象と間隔は `rdma_metrics_collection_config.conf` で設定できます。
