# Changelog

このファイルには、OCI HPC Trial Pack の主な変更を記録します。

## [Unreleased]

### Changed

- Open OnDemandダッシュボードのOpenComposerリンクから、Slurmジョブ投入フォームを直接開くようにしました。
- Open OnDemandのAmazon DCV連携とNVIDIA A10 GPUデスクトップを独立したオプションに分離しました。
- Amazon DCVをCPU shapeで利用できるようにし、CPUノードでのGUI導入とGPUノードでのDCV-GL構成をAnsibleで分岐しました。
- Amazon DCVの検証用途、自動評価ライセンスの有効期間、継続利用時のライセンス責任をUIとドキュメントに明記しました。

## [v1.0.0] - 2026-08-23

### Added

- `oci-hpc-trial-pack` として最初の正式リリースを作成しました。
- Semantic Versioningに基づく新しいバージョン系列を開始しました。

### Changed

- リポジトリ名を `oci-hpc-v2.10` から `oci-hpc-trial-pack` に変更しました。
- OCI Resource ManagerのデプロイURLを新しいリポジトリ名に更新しました。

### Compatibility

- このリリースは `oci-hpc v2.10.6.23` をベースとしています。
- 既存の `v2.10.x` タグは旧系列の履歴として保持します。
- Object Storage上のカスタムイメージ名と実行環境の `/opt/oci-hpc` パスは変更していません。

[v1.0.0]: https://github.com/kazuitox/oci-hpc-trial-pack/releases/tag/v1.0.0
