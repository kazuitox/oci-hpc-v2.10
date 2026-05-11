# OCI HPC クラスター構築スタック

[![Deploy to Oracle Cloud](https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg)](https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/kazuitox/oci-hpc-v2.10/archive/refs/heads/master.zip)

本リポジトリは、Oracle Cloud Infrastructure (OCI) 上に HPC 環境を短時間で構築し、PoC や初期検証をすばやく開始することを目的としています。
この目的に合わせて、現時点では Oracle Linux 8 を対象 OS として動作確認しています。その他の OS やバージョンについては未検証のため、利用する場合は個別に検証してください。

Terraform / Oracle Resource Manager スタックとして、コントローラ、計算ノード、Slurm、LDAP、共有ストレージ、Autoscaling、監視、Open OnDemand などをまとめて構成します。

`schema.yaml` は日本語 UI 向けに整備されており、`SIMPLE` モードでは最小限の入力、`ADVANCED` モードでは詳細な構成項目を表示します。

## 主な構成

- コントローラノードを 1 台作成します。
- 計算ノードは Cluster Network、Compute Cluster、または Instance Pool で作成できます。
- Slurm をインストールし、ジョブ投入とキュー単位の Autoscaling を構成します。
- LDAP を有効にした場合、コントローラがクラスター内のユーザー管理を行います。
- `/home`、クラスター共有領域、scratch 領域を NFS または FSS / Block Volume / NVMe で構成できます。
- 追加 Login Node、Slurm バックアップコントローラ、Open OnDemand、Spack、Enroot / Pyxis、PAM、Healthcheck、監視をオプションで有効化できます。
- RDMA NIC メトリックを Object Storage にアップロードするための PAR を作成できます。

## IAM とポリシー

スタックを実行するユーザーは、Administratorsグループに所属していることを想定しており、それによりデフォルトでオートスケーリングの利用に必要なポリシーと動的グループを自動で追加します。
Administratorグループの権限がない場合には【Autoscaling 用 IAM Policy / Dynamic Group を作成】のチェックを外し、テナント管理者にて以下のポリシーと動的グループを適切に設定をしてください。`

ポリシー1:
```text
allow service compute_management to use tag-namespace in tenancy
allow service compute_management to manage compute-management-family in tenancy
allow service compute_management to read app-catalog-listing in tenancy
```


動的グループ(名前: dynamic-group):
```text
Any {instance.compartment.id = '作成した CompartmentID を記入'}
```

動的グループを利用したポリシー2:

```text
allow dynamic-group autoscaling_dg to read app-catalog-listing in tenancy
allow dynamic-group autoscaling_dg to use tag-namespace in tenancy
allow dynamic-group autoscaling_dg to manage all-resources in tenancy
```


## OS とイメージ

デフォルトでは、コントローラと Login Node は Marketplace の `HPC_OL8` を使用します。計算ノードは、デフォルトで Object Storage URI から Oracle Linux 8.10 ベースのカスタムイメージを登録して使用する設定です。


```text
HPC_OL8
```


## 主要な入力項目

| 項目 | 説明 |
| --- | --- |
| `ui_mode` | `SIMPLE` または `ADVANCED`。詳細項目を出す場合は `ADVANCED`。 |
| `cluster_network` | RoCEv2 対応の Cluster Network を使用します。デフォルトは `true`。 |
| `compute_cluster` | Cluster Network の代わりに Compute Cluster を使用します。 |
| `node_count` | 初期クラスターの計算ノード数。 |
| `autoscaling` | Slurm ジョブに応じてクラスターを作成・削除します。デフォルトは `true`。 |
| `queue` | 初期キュー名。デフォルトは `compute`。 |
| `ldap` | LDAP を構成します。デフォルトは `true`。 |
| `home_nfs` / `home_fss` | `/home` の共有方法を選択します。 |
| `use_cluster_nfs` | クラスター共有領域をコントローラから NFS 共有します。 |
| `use_scratch_nfs` | scratch 領域を計算ノードから NFS 共有します。 |
| `private_deployment` | コントローラに Public IP を付与せず、Resource Manager Private Endpoint 経由で構成します。 |
| `login_node` | ユーザー用の追加 Login Node を作成します。 |
| `slurm_ha` | バックアップ Slurm Controller を作成します。 |
| `use_ood` | Open OnDemand をインストールします。 |
| `monitoring` | Grafana / Telegraf / InfluxDB によるシステム監視を有効化します。 |
| `autoscaling_monitoring` | Autoscaling の状態を Grafana ダッシュボードで確認できるようにします。 |
| `controller_object_storage_par` | RDMA NIC メトリックアップロード用の PAR を作成します。 |

## Autoscaling

Autoscaling は「ジョブごとにクラスターを作成する」方式です。Slurm の pending ジョブを cron で確認し、ジョブのノード数、キュー、インスタンスタイプに合わせて新しいクラスターを作成します。アイドル状態のクラスターは、デフォルトで 600 秒経過後に削除対象になります。

既存クラスターのノード数を途中で増減する運用は、非推奨で現状対象外です。現行の cron タスクも、既存クラスターのノード数を変更せず、クラスター単位の作成・削除を行うスクリプトを有効化します。

Autoscaling の設定ファイルはコントローラ上の次のパスに配置されます。

```text
/opt/oci-hpc/conf/queues.conf
```

サンプルはリポジトリ内の次のファイルです。

```text
conf/queues.conf.example
```

`queues.conf` では、キューごとに複数の `instance_types` を定義できます。重要な項目は次の通りです。

- `name`: Slurm の constraint として指定するインスタンスタイプ名。
- `instance_keyword`: 作成されるクラスター名と Slurm ノード名に使う短い識別子。
- `permanent`: `true` の場合、Autoscaling の削除対象にしません。
- `max_number_nodes`: キュー / インスタンスタイプ単位の最大ノード数。
- `max_cluster_size`: 1 クラスターあたりの最大ノード数。
- `max_cluster_count`: 同時に保持できる最大クラスター数。
- `cluster_network` / `compute_cluster`: 作成方式を指定します。
- `ad`: 複数 AD を空白区切りで指定すると、作成失敗時に別 AD を試行します。

設定を変更した後は、Slurm 設定を再生成します。

```bash
/opt/oci-hpc/bin/slurm_config.sh
```

Slurm の状態を初期状態に戻したい場合は、次を実行します。

```bash
/opt/oci-hpc/bin/slurm_config.sh --initial
```

## ジョブ投入

Slurm ジョブは通常通り `sbatch` で投入できます。`queues.conf` の `instance_types[].name` を constraint に指定すると、そのインスタンスタイプに対応するクラスターが作成されます。

例:

```bash
#!/bin/sh
#SBATCH -n 72
#SBATCH --ntasks-per-node 36
#SBATCH --exclusive
#SBATCH --job-name sleep_job
#SBATCH --constraint hpc-default

cd /nfs/scratch
mkdir "$SLURM_JOB_ID"
cd "$SLURM_JOB_ID"

MACHINEFILE="hostfile"
scontrol show hostnames "$SLURM_JOB_NODELIST" > "$MACHINEFILE"
sed -i "s/$/:${SLURM_NTASKS_PER_NODE}/" "$MACHINEFILE"

cat "$MACHINEFILE"
sleep 1000
```

デフォルトでは、ジョブがインスタンスタイプを指定しない場合、キュー内で `default: true` のインスタンスタイプが使われます。デフォルト以外のキューへ投入する場合は、SBATCH ファイルに `#SBATCH --partition <queue_name>` を追加するか、コマンドラインで `sbatch -p <queue_name> job.sh` を指定します。

Ubuntu 22.04 かつ Hyperthreading を無効化した環境で `error: task_g_set_affinity: Invalid argument` が出る場合は、`--cpu-bind=none` または `--cpu-bind=sockets` を試してください。

## ディレクトリとログ

コントローラ上では、クラスター管理用ファイルが次の場所に配置されます。

```text
/opt/oci-hpc
```

Autoscaling で作成されたクラスターごとの Terraform 作業ディレクトリ:

```text
/opt/oci-hpc/autoscaling/clusters/<cluster_name>
```

ログ:

```text
/opt/oci-hpc/logs
```

クラスターごとに `create_<cluster_name>_<date>.log` と `delete_<cluster_name>_<date>.log` が作成されます。cron のログは日付付きの `crontab_slurm_<yyyymmdd>.log` に出力されます。

## 手動クラスター操作

Autoscaling と同じ仕組みを使って、クラスターを手動で作成・削除できます。

作成:

```bash
/opt/oci-hpc/bin/create_cluster.sh <node_count> <cluster_name> <instance_type> <queue_name>
```

例:

```bash
/opt/oci-hpc/bin/create_cluster.sh 4 compute2-1-hpc HPC_instance compute2
```

クラスター名は次の形式にします。

```text
<queue_name>-<cluster_number>-<instance_keyword>
```

`instance_keyword` は `queues.conf` の値と一致させてください。

削除:

```bash
/opt/oci-hpc/bin/delete_cluster.sh <cluster_name>
```

削除中に問題が起きた場合は、強制削除を指定できます。

```bash
/opt/oci-hpc/bin/delete_cluster.sh <cluster_name> FORCE
```

削除処理中のクラスターには、次のファイルが作成されます。

```text
/opt/oci-hpc/autoscaling/clusters/<cluster_name>/currently_destroying
```

## Autoscaling モニタリング

`autoscaling_monitoring` を有効にすると、Grafana でクラスターの作成・削除状況と Slurm ジョブ状況を確認できます。Grafana API の制約により、ダッシュボードのインポートは手動で行います。

1. ブラウザで `http://<controller_ip>:3000` にアクセスします。
2. 初期ユーザー名 / パスワードは `admin/admin` です。
3. `Configuration -> Data Sources` で `autoscaling` を選択します。
4. Password に `Monitor1234!` を入力し、`Save & test` を実行します。
5. 左メニューの `+` から `Import` を選択し、次の JSON をアップロードします。

```text
/opt/oci-hpc/playbooks/roles/autoscaling_mon/files/dashboard.json
```

Data Source には `autoscaling (MySQL)` を選択します。

## LDAP とユーザー管理

`ldap` を有効にした場合、コントローラはクラスター用 LDAP サーバーとして動作します。ホームディレクトリは共有構成のまま使うことを推奨します。

ユーザー管理はコントローラ上の `cluster` コマンドで行います。

```bash
cluster user add <name>
```

デフォルトでは `privilege` グループが作成されます。このグループは NFS へのアクセス権を持ち、設定により全ノードで sudo 権限を持ちます。デフォルト GID は `9876` です。

```bash
cluster user add <name> --gid 9876
cluster user add <name> --nossh --gid 9876
```

`--nossh` を指定すると、ノード間パスワードレス SSH 用のユーザー固有鍵を作成しません。

## 共有ホームディレクトリ

デフォルトでは、コントローラが `/home` を NFS で全ノードに共有します。FSS を使う場合は、既存 FSS の IP / パスを指定するか、スタックで FSS を作成できます。

既存 FSS を使う場合、マウントポイントに `/home` を直接指定しないでください。スタックは `$nfs_source_path/home` を作成し、必要なファイルをコピーしたうえで `/home` にマウントします。

## 追加ストレージ

`use_cluster_nfs` を有効にすると、コントローラから `cluster_nfs_path` を NFS 共有します。デフォルトは `/nfs/cluster` です。

`use_scratch_nfs` を有効にすると、計算ノード側の NVMe または Block Volume を使って scratch 領域を NFS 共有します。デフォルトの scratch マウントポイントは `/nfs/scratch` です。

追加 NFS / FSS を `nfs_target_path` にマウントすることもできます。ただし、追加 NFS の設定から `/home` を直接構成しないでください。`/home` にはストレージ詳細オプションの専用設定を使います。

## プライベートサブネットへのデプロイ

`private_deployment` を `true` にすると、コントローラに Public IP を付与せず、Resource Manager Private Endpoint 経由で構成します。

- 新規 VCN を作成する場合、コントローラ用と計算ノード用のプライベートサブネットを作成します。
- 既存 VCN を使う場合は、コントローラ用 subnet と計算ノード用 private subnet を指定します。
- コントローラへ SSH 接続するには、Controller Service、VPN、FastConnect、踏み台ホスト、または到達可能な VCN Peering が必要です。

## Open OnDemand

`use_ood` を有効にすると、Open OnDemand をインストールします。ユーザーはブラウザからファイル操作、ジョブ投入、アプリケーション実行を行えます。スタックは Open OnDemand 用の初期パスワードも生成し、構成に反映します。

## collect_logs.py

`/opt/oci-hpc/scripts/collect_logs.py` は、指定ノードの NVIDIA bug report、sosreport、console history log を収集します。コントローラ上で実行します。

到達可能なノードでは NVIDIA bug report と sosreport も取得します。SSH できないノードでは console history log のみを取得します。

必須引数:

```text
--hostname <hostname>
```

任意引数:

```text
--compartment-id <compartment_ocid>
```

例:

```bash
cd /opt/oci-hpc/scripts
python3 collect_logs.py --hostname compute-permanent-node-467
python3 collect_logs.py --hostname inst-jxwf6-keen-drake --compartment-id <compartment_ocid>
```

出力ファイルは `/home/<user>/<hostname>_<timestamp>` に保存されます。

複数ノードを処理する例:

```bash
for host in $(cat /home/opc/hostlist); do
  echo "$host"
  python3 collect_logs.py --hostname "$host"
done
```

## RDMA NIC メトリックの Object Storage アップロード

OCI-HPC はユーザー tenancy にデプロイされるため、OCI service team がクラスター内のメトリックを直接確認することはできません。`controller_object_storage_par` を有効にすると、RDMA NIC メトリックを Object Storage にアップロードするための PAR を作成できます。

Resource Manager の stack 作成時に `Create Object Storage PAR` を選択すると、PAR が作成され、`PAR_file_for_metrics` に保存されます。

メトリック収集とアップロードはコントローラ上で実行します。

```bash
/opt/oci-hpc/bin/upload_rdma_nic_metrics.sh
```

オプション:

```bash
/opt/oci-hpc/bin/upload_rdma_nic_metrics.sh -l 24 -i 5 -c <cluster_name>
```

- `-l`: 現在から何時間前までを収集するか。デフォルトは `24`。
- `-i`: メトリック集計間隔。デフォルトは `5` 分。
- `-c`: アップロードファイル名に付けるクラスター名。

デフォルト値は次の設定ファイルで変更できます。

```text
/opt/oci-hpc/bin/rdma_metrics_collection_config.conf
```
