# EFS Mount Target Auto-scaling System

AWS Serverlessアーキテクチャを使用したEFS Mount Targetの自動スケーリングシステム

## 概要

このシステムは、EFS上のファイル数が閾値を超えた際に自動的にMount Targetを追加し、ファイルアクセスを複数のネットワーク接続点に分散させることで、パフォーマンスを向上させます。

### アーキテクチャ図

```
┌─────────────────────────────────────────────────────────────────┐
│                    Serverless自動化レイヤー                      │
│  ┌──────────────┐         ┌─────────────────────────────────┐  │
│  │ EventBridge  │────────>│   Lambda Function               │  │
│  │ (5分ごと)    │         │   - ファイル数監視              │  │
│  └──────────────┘         │   - Mount Target作成            │  │
│                            │   - SSM更新                     │  │
│                            │   - ECS Service更新             │  │
│                            └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                            ┌──────────────────┐
                            │ SSM Parameter    │
                            │ Store            │
                            │ (Mount Target    │
                            │  リスト)         │
                            └──────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                  ファイルサービスレイヤー                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  ECS Fargate Tasks (アプリケーション)                    │  │
│  │  - SSM Parameter Storeから設定取得                       │  │
│  │  - 複数Mount Targetをマウント                            │  │
│  │  - ハッシュベースルーティングでファイルアクセス分散      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ Mount       │  │ Mount       │  │ Mount       │            │
│  │ Target 1    │  │ Target 2    │  │ Target 3    │            │
│  │ (AZ-1)      │  │ (AZ-2)      │  │ (AZ-3)      │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│         │                 │                 │                    │
│         └─────────────────┴─────────────────┘                    │
│                           │                                       │
│                  ┌────────────────┐                              │
│                  │ EFS File       │                              │
│                  │ System         │                              │
│                  └────────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

### 主要コンポーネント

1. **Lambda関数**: ファイル数を監視し、閾値超過時にMount Targetを作成
2. **Fargateアプリケーション**: 複数のMount Targetをマウントし、ハッシュベースでファイルアクセスを分散
3. **SSM Parameter Store**: Mount Target情報を保存・共有
4. **EventBridge**: Lambda関数を定期実行（デフォルト: 5分ごと）

## プロジェクト構造

```
.
├── lambda/                    # Lambda関数
│   ├── file_monitor.py       # メインのLambda関数
│   └── requirements.txt      # Lambda依存関係
├── fargate/                   # Fargateアプリケーション
│   ├── app.py                # メインアプリケーション
│   ├── Dockerfile            # コンテナイメージ定義
│   └── requirements.txt      # Fargate依存関係
├── terraform/                 # インフラストラクチャコード
│   ├── main.tf               # メイン設定
│   ├── variables.tf          # 変数定義
│   ├── outputs.tf            # 出力定義
│   ├── network.tf            # VPC・ネットワーク
│   ├── efs.tf                # EFSファイルシステム
│   ├── lambda.tf             # Lambda関数
│   ├── eventbridge.tf        # EventBridgeルール
│   ├── ssm.tf                # SSM Parameter Store
│   └── ecs.tf                # ECS/Fargate
├── scripts/                   # デプロイメントスクリプト
│   ├── deploy_lambda.sh      # Lambda関数デプロイ
│   ├── build_and_push_fargate.sh  # Fargateイメージビルド
│   └── deploy_all.sh         # 統合デプロイメント
├── tests/                     # テスト
│   ├── test_lambda.py        # Lambda関数のテスト
│   └── test_fargate.py       # Fargateアプリケーションのテスト
├── .kiro/specs/              # 設計ドキュメント
│   └── efs-mount-target-autoscaling/
│       ├── requirements.md   # 要件定義
│       ├── design.md         # 設計書
│       └── tasks.md          # 実装計画
├── requirements-dev.txt       # 開発・テスト用依存関係
├── pytest.ini                # Pytest設定
└── README.md                 # このファイル
```

## セットアップ

### 前提条件

- AWS CLI (設定済み)
- Terraform >= 1.0
- Docker
- Python 3.11以上
- pip

### 開発環境のセットアップ

```bash
# 開発用依存関係のインストール
pip install -r requirements-dev.txt

# Lambda関数の依存関係のインストール
pip install -r lambda/requirements.txt

# Fargateアプリケーションの依存関係のインストール
pip install -r fargate/requirements.txt
```

### テストの実行

```bash
# 全てのテストを実行
pytest

# 特定のテストファイルを実行
pytest tests/test_lambda.py

# カバレッジ付きでテストを実行
pytest --cov=lambda --cov=fargate

# プロパティベーステストのみ実行
pytest -k "Property"
```

## デプロイ

### クイックスタート（統合デプロイ）

```bash
# 全てのコンポーネントを一括デプロイ
bash scripts/deploy_all.sh
```

このスクリプトは以下を自動的に実行します：
1. Lambda関数のパッケージング
2. Terraformによるインフラデプロイ
3. Fargateコンテナイメージのビルドとプッシュ
4. ECS Serviceの更新

### 個別デプロイ

#### 1. Lambda関数のみデプロイ

```bash
bash scripts/deploy_lambda.sh
cd terraform
terraform apply
```

#### 2. Fargateコンテナのみ更新

```bash
bash scripts/build_and_push_fargate.sh
```

#### 3. インフラストラクチャのみ更新

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

## 設定

### 環境変数（Terraform）

主要な設定は `terraform/variables.tf` で定義されています：

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `aws_region` | `ap-northeast-1` | AWSリージョン |
| `environment` | `dev` | 環境名 |
| `file_count_threshold` | `100000` | ファイル数閾値 |
| `lambda_schedule_expression` | `rate(5 minutes)` | Lambda実行間隔 |
| `efs_target_directory` | `/data` | 監視対象ディレクトリ |
| `fargate_cpu` | `2048` | Fargate CPU (vCPU) |
| `fargate_memory` | `4096` | Fargateメモリ (MB) |
| `fargate_desired_count` | `2` | Fargateタスク数 |

### カスタマイズ

`terraform.tfvars` ファイルを作成して設定を上書きできます：

```hcl
aws_region            = "us-east-1"
environment           = "prod"
file_count_threshold  = 200000
fargate_desired_count = 4
```

## 監視とトラブルシューティング

### CloudWatch Logs

- **Lambda関数**: `/aws/lambda/efs-mount-autoscaling-file-monitor`
- **Fargate**: `/ecs/efs-mount-autoscaling-fargate`

### 主要なメトリクス

```bash
# Lambda関数の実行状況を確認
aws logs tail /aws/lambda/efs-mount-autoscaling-file-monitor --follow

# ECS Serviceの状態を確認
aws ecs describe-services \
  --cluster efs-mount-autoscaling-cluster \
  --services efs-mount-autoscaling-fargate-service

# Mount Targetの一覧を確認
aws efs describe-mount-targets \
  --file-system-id <EFS_FILE_SYSTEM_ID>

# SSM Parameter Storeの内容を確認
aws ssm get-parameter \
  --name /efs-mount-autoscaling/mount-targets
```

### よくある問題

#### Lambda関数がMount Targetを作成しない

- CloudWatch Logsでファイル数と閾値を確認
- 全てのAZに既にMount Targetが存在していないか確認
- Lambda関数のIAM権限を確認

#### Fargateタスクが起動しない

- ECRにコンテナイメージがプッシュされているか確認
- ECS Serviceのイベントログを確認
- セキュリティグループの設定を確認

#### ファイルアクセスが遅い

- EFSのパフォーマンスモードを確認（Max I/Oに変更を検討）
- Mount Targetが複数のAZに分散されているか確認
- CloudWatchメトリクスでEFSのI/O使用率を確認

## 開発ガイドライン

- Python 3.11以上を使用
- テストは必ずpytestとHypothesisを使用
- AWS SDKはboto3を使用
- ログは標準のloggingモジュールを使用
- コードスタイル: PEP 8に準拠

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## 参考資料

- [設計ドキュメント](.kiro/specs/efs-mount-target-autoscaling/design.md)
- [要件定義](.kiro/specs/efs-mount-target-autoscaling/requirements.md)
- [AWS EFS Documentation](https://docs.aws.amazon.com/efs/)
- [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/)
- [AWS Fargate Documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)
