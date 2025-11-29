# デプロイメントガイド

このドキュメントでは、EFS Mount Target Auto-scaling Systemの詳細なデプロイ手順を説明します。

## 目次

1. [前提条件](#前提条件)
2. [初回デプロイ](#初回デプロイ)
3. [更新デプロイ](#更新デプロイ)
4. [設定のカスタマイズ](#設定のカスタマイズ)
5. [デプロイ後の確認](#デプロイ後の確認)
6. [ロールバック](#ロールバック)
7. [削除](#削除)

## 前提条件

### 必要なツール

以下のツールがインストールされている必要があります：

```bash
# AWS CLI
aws --version
# 出力例: aws-cli/2.x.x

# Terraform
terraform --version
# 出力例: Terraform v1.x.x

# Docker
docker --version
# 出力例: Docker version 24.x.x

# Python
python3 --version
# 出力例: Python 3.11.x

# pip
pip --version
# 出力例: pip 23.x.x
```

### AWS認証情報の設定

```bash
# AWS CLIの設定
aws configure

# 入力項目:
# AWS Access Key ID: <YOUR_ACCESS_KEY>
# AWS Secret Access Key: <YOUR_SECRET_KEY>
# Default region name: ap-northeast-1
# Default output format: json

# 認証情報の確認
aws sts get-caller-identity
```

### 必要なIAM権限

デプロイを実行するIAMユーザー/ロールには、以下のサービスに対する権限が必要です：

- VPC (作成、削除、変更)
- EFS (ファイルシステム、Mount Target作成)
- Lambda (関数作成、更新)
- ECS/Fargate (クラスター、サービス、タスク定義作成)
- ECR (リポジトリ作成、イメージプッシュ)
- IAM (ロール、ポリシー作成)
- EventBridge (ルール作成)
- SSM Parameter Store (パラメータ作成、更新)
- CloudWatch Logs (ロググループ作成)

推奨: `AdministratorAccess` または同等の権限

## 初回デプロイ

### ステップ1: リポジトリのクローン

```bash
git clone <repository-url>
cd efs-mount-target-autoscaling
```

### ステップ2: 依存関係のインストール

```bash
# 開発用依存関係
pip install -r requirements-dev.txt

# Lambda依存関係
pip install -r lambda/requirements.txt

# Fargate依存関係
pip install -r fargate/requirements.txt
```

### ステップ3: テストの実行（オプション）

```bash
# 全てのテストを実行
pytest

# テストが成功することを確認
```

### ステップ4: Terraform変数の設定

`terraform/terraform.tfvars` ファイルを作成：

```hcl
# 基本設定
aws_region  = "ap-northeast-1"
environment = "dev"
project_name = "efs-mount-autoscaling"

# ネットワーク設定
vpc_cidr = "10.0.0.0/16"
availability_zones = [
  "ap-northeast-1a",
  "ap-northeast-1c",
  "ap-northeast-1d"
]

# Lambda設定
file_count_threshold = 100000
lambda_schedule_expression = "rate(5 minutes)"
efs_target_directory = "/data"

# Fargate設定
fargate_cpu = 2048
fargate_memory = 4096
fargate_desired_count = 2

# タグ
tags = {
  Owner = "your-name"
  Team  = "your-team"
}
```

### ステップ5: 統合デプロイの実行

```bash
# デプロイスクリプトに実行権限を付与
chmod +x scripts/*.sh

# 統合デプロイを実行
bash scripts/deploy_all.sh
```

デプロイスクリプトは以下を自動的に実行します：

1. **前提条件チェック**: 必要なツールがインストールされているか確認
2. **AWS認証確認**: AWS認証情報が有効か確認
3. **Lambda関数パッケージング**: Lambda関数コードをZIPファイルにパッケージ
4. **Terraformデプロイ**: インフラストラクチャをAWSにデプロイ
5. **Fargateイメージビルド**: Dockerイメージをビルド
6. **ECRプッシュ**: イメージをECRにプッシュ
7. **ECS Service更新**: 新しいイメージでサービスを更新

### ステップ6: デプロイの確認

デプロイが完了すると、以下の情報が表示されます：

```
Infrastructure Resources:
  VPC ID:              vpc-xxxxx
  EFS File System ID:  fs-xxxxx
  Lambda Function:     efs-mount-autoscaling-file-monitor
  ECS Cluster:         efs-mount-autoscaling-cluster
  ECS Service:         efs-mount-autoscaling-fargate-service
  SSM Parameter:       /efs-mount-autoscaling/mount-targets
  ECR Repository:      xxxxx.dkr.ecr.ap-northeast-1.amazonaws.com/efs-mount-autoscaling-fargate
```

## 更新デプロイ

### Lambda関数の更新

Lambda関数のコードを変更した場合：

```bash
# Lambda関数を再パッケージ
bash scripts/deploy_lambda.sh

# Terraformで更新を適用
cd terraform
terraform apply
```

### Fargateアプリケーションの更新

Fargateアプリケーションのコードを変更した場合：

```bash
# 新しいイメージをビルドしてプッシュ
bash scripts/build_and_push_fargate.sh

# ECS Serviceを強制的に再デプロイ
aws ecs update-service \
  --cluster efs-mount-autoscaling-cluster \
  --service efs-mount-autoscaling-fargate-service \
  --force-new-deployment
```

### インフラストラクチャの更新

Terraformの設定を変更した場合：

```bash
cd terraform

# 変更内容を確認
terraform plan

# 変更を適用
terraform apply
```

## 設定のカスタマイズ

### ファイル数閾値の変更

```hcl
# terraform/terraform.tfvars
file_count_threshold = 200000  # 20万ファイルに変更
```

```bash
cd terraform
terraform apply
```

### Lambda実行間隔の変更

```hcl
# terraform/terraform.tfvars
lambda_schedule_expression = "rate(10 minutes)"  # 10分ごとに変更
```

```bash
cd terraform
terraform apply
```

### Fargateタスク数の変更

```hcl
# terraform/terraform.tfvars
fargate_desired_count = 4  # 4タスクに変更
```

```bash
cd terraform
terraform apply
```

### EFSパフォーマンスモードの変更

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  # ...
  performance_mode = "maxIO"  # General Purpose から Max I/O に変更
  # ...
}
```

**注意**: パフォーマンスモードの変更には、EFSファイルシステムの再作成が必要です。

## デプロイ後の確認

### Lambda関数の動作確認

```bash
# Lambda関数を手動で実行
aws lambda invoke \
  --function-name efs-mount-autoscaling-file-monitor \
  --payload '{}' \
  response.json

# 実行結果を確認
cat response.json

# CloudWatch Logsを確認
aws logs tail /aws/lambda/efs-mount-autoscaling-file-monitor --follow
```

### ECS Serviceの状態確認

```bash
# ECS Serviceの状態を確認
aws ecs describe-services \
  --cluster efs-mount-autoscaling-cluster \
  --services efs-mount-autoscaling-fargate-service

# タスクの状態を確認
aws ecs list-tasks \
  --cluster efs-mount-autoscaling-cluster \
  --service-name efs-mount-autoscaling-fargate-service

# タスクのログを確認
aws logs tail /ecs/efs-mount-autoscaling-fargate --follow
```

### Mount Targetの確認

```bash
# EFSファイルシステムIDを取得
EFS_ID=$(cd terraform && terraform output -raw efs_file_system_id)

# Mount Targetの一覧を確認
aws efs describe-mount-targets --file-system-id $EFS_ID
```

### SSM Parameter Storeの確認

```bash
# Mount Targetリストを確認
aws ssm get-parameter \
  --name /efs-mount-autoscaling/mount-targets \
  --query 'Parameter.Value' \
  --output text | jq .
```

## ロールバック

### Lambda関数のロールバック

```bash
# 以前のバージョンを確認
aws lambda list-versions-by-function \
  --function-name efs-mount-autoscaling-file-monitor

# 特定のバージョンにエイリアスを更新
aws lambda update-alias \
  --function-name efs-mount-autoscaling-file-monitor \
  --name PROD \
  --function-version <VERSION_NUMBER>
```

### Fargateアプリケーションのロールバック

```bash
# 以前のタスク定義を確認
aws ecs list-task-definitions \
  --family-prefix efs-mount-autoscaling-fargate

# 以前のタスク定義でサービスを更新
aws ecs update-service \
  --cluster efs-mount-autoscaling-cluster \
  --service efs-mount-autoscaling-fargate-service \
  --task-definition efs-mount-autoscaling-fargate:<REVISION>
```

### Terraformのロールバック

```bash
cd terraform

# 以前の状態を確認
terraform state list

# 特定のリソースを以前の状態に戻す
# (Gitで管理している場合)
git checkout <PREVIOUS_COMMIT> -- terraform/

# 変更を適用
terraform apply
```

## 削除

### 全リソースの削除

```bash
cd terraform

# 削除するリソースを確認
terraform plan -destroy

# 全リソースを削除
terraform destroy
```

**注意**: 
- EFSファイルシステム内のデータは削除されます
- ECRリポジトリ内のイメージは削除されます
- CloudWatch Logsは削除されます

### 特定のリソースのみ削除

```bash
# 特定のリソースを削除
terraform destroy -target=aws_ecs_service.fargate

# 削除を確認
terraform plan
```

## トラブルシューティング

### デプロイが失敗する

#### エラー: "Error creating Lambda function: InvalidParameterValueException"

**原因**: Lambda関数のパッケージサイズが大きすぎる

**解決策**:
```bash
# 不要なファイルを削除してパッケージを再作成
bash scripts/deploy_lambda.sh
```

#### エラー: "Error creating ECS service: InvalidParameterException"

**原因**: ECRにイメージがプッシュされていない

**解決策**:
```bash
# Fargateイメージをビルドしてプッシュ
bash scripts/build_and_push_fargate.sh
```

#### エラー: "Error creating Mount Target: MountTargetConflict"

**原因**: 既にMount Targetが存在する

**解決策**: これは正常な動作です。Lambda関数は既存のMount Targetをスキップします。

### Lambda関数が実行されない

```bash
# EventBridgeルールの状態を確認
aws events describe-rule --name efs-mount-autoscaling-lambda-schedule

# Lambda関数の権限を確認
aws lambda get-policy --function-name efs-mount-autoscaling-file-monitor
```

### Fargateタスクが起動しない

```bash
# ECS Serviceのイベントを確認
aws ecs describe-services \
  --cluster efs-mount-autoscaling-cluster \
  --services efs-mount-autoscaling-fargate-service \
  --query 'services[0].events[0:5]'

# タスクの停止理由を確認
aws ecs describe-tasks \
  --cluster efs-mount-autoscaling-cluster \
  --tasks <TASK_ARN>
```

## サポート

問題が発生した場合は、以下を確認してください：

1. [README.md](../README.md) - 基本的な使用方法
2. [設計ドキュメント](../.kiro/specs/efs-mount-target-autoscaling/design.md) - システムの詳細設計
3. CloudWatch Logs - エラーログの確認
4. AWS Support - AWSサービスの問題

## 次のステップ

- [監視とアラートの設定](MONITORING.md)
- [パフォーマンスチューニング](PERFORMANCE.md)
- [セキュリティベストプラクティス](SECURITY.md)
