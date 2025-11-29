# セキュリティベストプラクティス

このドキュメントでは、EFS Mount Target Auto-scaling Systemのセキュリティ設定とベストプラクティスについて説明します。

## 目次

1. [セキュリティの概要](#セキュリティの概要)
2. [IAM権限管理](#iam権限管理)
3. [ネットワークセキュリティ](#ネットワークセキュリティ)
4. [データ暗号化](#データ暗号化)
5. [ログとモニタリング](#ログとモニタリング)
6. [コンプライアンス](#コンプライアンス)
7. [セキュリティ監査](#セキュリティ監査)

## セキュリティの概要

### セキュリティの原則

このシステムは以下のセキュリティ原則に基づいて設計されています：

1. **最小権限の原則**: 必要最小限の権限のみを付与
2. **多層防御**: 複数のセキュリティレイヤーで保護
3. **暗号化**: 転送中および保存時のデータを暗号化
4. **監査とログ**: すべての操作を記録
5. **定期的な見直し**: セキュリティ設定の定期的な監査

### セキュリティ責任共有モデル

- **AWS責任**: インフラストラクチャのセキュリティ
- **お客様責任**: データ、アプリケーション、アクセス管理

## IAM権限管理

### Lambda関数のIAMロール

```hcl
# terraform/lambda.tf
resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-lambda-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${var.project_name}-lambda-policy"
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "efs:DescribeFileSystems",
          "efs:DescribeMountTargets",
          "efs:CreateMountTarget"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestedRegion" = var.aws_region
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeSubnets",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeAvailabilityZones"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:PutParameter"
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-*"
      }
    ]
  })
}
```


### Fargateタスクのロール

```hcl
# terraform/ecs.tf
resource "aws_iam_role" "fargate_task" {
  name = "${var.project_name}-fargate-task-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "fargate_task" {
  name = "${var.project_name}-fargate-task-policy"
  role = aws_iam_role.fargate_task.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "elasticfilesystem:ClientMount",
          "elasticfilesystem:ClientWrite",
          "elasticfilesystem:ClientRootAccess"
        ]
        Resource = aws_efs_file_system.main.arn
        Condition = {
          StringEquals = {
            "elasticfilesystem:AccessPointArn" = aws_efs_access_point.fargate.arn
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter"
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/*"
      }
    ]
  })
}

# Fargate実行ロール
resource "aws_iam_role" "fargate_execution" {
  name = "${var.project_name}-fargate-execution-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "fargate_execution" {
  role       = aws_iam_role.fargate_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
```

### IAMポリシーのベストプラクティス

1. **条件付きアクセス**: リソースやリージョンを制限

```json
{
  "Condition": {
    "StringEquals": {
      "aws:RequestedRegion": "ap-northeast-1"
    }
  }
}
```

2. **リソースベースのポリシー**: 特定のリソースのみアクセス許可

```json
{
  "Resource": "arn:aws:efs:ap-northeast-1:123456789012:file-system/fs-xxxxx"
}
```

3. **タグベースのアクセス制御**:

```hcl
resource "aws_iam_role_policy" "tag_based" {
  policy = jsonencode({
    Statement = [{
      Effect = "Allow"
      Action = ["efs:*"]
      Resource = "*"
      Condition = {
        StringEquals = {
          "aws:ResourceTag/Environment" = "production"
        }
      }
    }]
  })
}
```

## ネットワークセキュリティ

### VPC設計

```hcl
# terraform/network.tf
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  
  tags = {
    Name = "${var.project_name}-vpc"
  }
}

# プライベートサブネット（推奨）
resource "aws_subnet" "private" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = var.availability_zones[count.index]
  
  tags = {
    Name = "${var.project_name}-private-subnet-${count.index + 1}"
  }
}
```

### セキュリティグループの設定

```hcl
# terraform/network.tf
# EFS用セキュリティグループ
resource "aws_security_group" "efs" {
  name        = "${var.project_name}-efs-sg"
  description = "Security group for EFS mount targets"
  vpc_id      = aws_vpc.main.id
  
  # NFSアクセスを特定のセキュリティグループからのみ許可
  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.fargate.id]
    description     = "NFS access from Fargate tasks"
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "${var.project_name}-efs-sg"
  }
}

# Fargate用セキュリティグループ
resource "aws_security_group" "fargate" {
  name        = "${var.project_name}-fargate-sg"
  description = "Security group for Fargate tasks"
  vpc_id      = aws_vpc.main.id
  
  # アウトバウンドのみ許可
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  tags = {
    Name = "${var.project_name}-fargate-sg"
  }
}
```

### ネットワークACL

```hcl
# terraform/network.tf
resource "aws_network_acl" "private" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = aws_subnet.private[*].id
  
  # インバウンドルール
  ingress {
    protocol   = "tcp"
    rule_no    = 100
    action     = "allow"
    cidr_block = var.vpc_cidr
    from_port  = 2049
    to_port    = 2049
  }
  
  ingress {
    protocol   = -1
    rule_no    = 200
    action     = "allow"
    cidr_block = var.vpc_cidr
    from_port  = 0
    to_port    = 0
  }
  
  # アウトバウンドルール
  egress {
    protocol   = -1
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 0
    to_port    = 0
  }
  
  tags = {
    Name = "${var.project_name}-private-nacl"
  }
}
```

### VPCフローログ

```hcl
# terraform/network.tf
resource "aws_flow_log" "main" {
  iam_role_arn    = aws_iam_role.flow_log.arn
  log_destination = aws_cloudwatch_log_group.flow_log.arn
  traffic_type    = "ALL"
  vpc_id          = aws_vpc.main.id
  
  tags = {
    Name = "${var.project_name}-vpc-flow-log"
  }
}

resource "aws_cloudwatch_log_group" "flow_log" {
  name              = "/aws/vpc/${var.project_name}-flow-log"
  retention_in_days = 30
}

resource "aws_iam_role" "flow_log" {
  name = "${var.project_name}-flow-log-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "vpc-flow-logs.amazonaws.com"
      }
    }]
  })
}
```

## データ暗号化

### EFS暗号化

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  creation_token = var.project_name
  
  # 保存時の暗号化を有効化
  encrypted  = true
  kms_key_id = aws_kms_key.efs.arn
  
  # 転送時の暗号化を強制
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  
  tags = {
    Name = "${var.project_name}-efs"
  }
}

# KMSキーの作成
resource "aws_kms_key" "efs" {
  description             = "KMS key for EFS encryption"
  deletion_window_in_days = 10
  enable_key_rotation     = true
  
  tags = {
    Name = "${var.project_name}-efs-kms"
  }
}

resource "aws_kms_alias" "efs" {
  name          = "alias/${var.project_name}-efs"
  target_key_id = aws_kms_key.efs.key_id
}
```

### 転送時の暗号化

```hcl
# terraform/efs.tf
resource "aws_efs_mount_target" "main" {
  count = length(var.availability_zones)
  
  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

# ECS タスク定義で転送時の暗号化を有効化
resource "aws_ecs_task_definition" "fargate" {
  # ...
  
  volume {
    name = "efs-storage"
    
    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.main.id
      transit_encryption      = "ENABLED"
      transit_encryption_port = 2049
      
      authorization_config {
        access_point_id = aws_efs_access_point.fargate.id
        iam             = "ENABLED"
      }
    }
  }
}
```

### Secrets Managerの活用

```hcl
# terraform/main.tf
resource "aws_secretsmanager_secret" "api_key" {
  name = "${var.project_name}/api-key"
  
  kms_key_id = aws_kms_key.secrets.arn
}

resource "aws_secretsmanager_secret_version" "api_key" {
  secret_id     = aws_secretsmanager_secret.api_key.id
  secret_string = jsonencode({
    api_key = var.api_key
  })
}

# Lambda関数からのアクセス
resource "aws_iam_role_policy" "lambda_secrets" {
  role = aws_iam_role.lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Resource = aws_secretsmanager_secret.api_key.arn
    }]
  })
}
```

## ログとモニタリング

### CloudTrail の有効化

```hcl
# terraform/main.tf
resource "aws_cloudtrail" "main" {
  name                          = "${var.project_name}-trail"
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true
  
  event_selector {
    read_write_type           = "All"
    include_management_events = true
    
    data_resource {
      type   = "AWS::Lambda::Function"
      values = ["arn:aws:lambda:*:${data.aws_caller_identity.current.account_id}:function/*"]
    }
    
    data_resource {
      type   = "AWS::EFS::FileSystem"
      values = ["arn:aws:elasticfilesystem:*:${data.aws_caller_identity.current.account_id}:file-system/*"]
    }
  }
  
  tags = {
    Name = "${var.project_name}-cloudtrail"
  }
}

resource "aws_s3_bucket" "cloudtrail" {
  bucket = "${var.project_name}-cloudtrail-logs"
  
  tags = {
    Name = "${var.project_name}-cloudtrail-logs"
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

### AWS Config の設定

```hcl
# terraform/main.tf
resource "aws_config_configuration_recorder" "main" {
  name     = "${var.project_name}-config-recorder"
  role_arn = aws_iam_role.config.arn
  
  recording_group {
    all_supported = true
    
    resource_types = [
      "AWS::EFS::FileSystem",
      "AWS::Lambda::Function",
      "AWS::ECS::Service",
      "AWS::EC2::SecurityGroup"
    ]
  }
}

resource "aws_config_delivery_channel" "main" {
  name           = "${var.project_name}-config-delivery"
  s3_bucket_name = aws_s3_bucket.config.bucket
  
  depends_on = [aws_config_configuration_recorder.main]
}
```

### GuardDuty の有効化

```bash
# GuardDutyを有効化
aws guardduty create-detector \
  --enable \
  --finding-publishing-frequency FIFTEEN_MINUTES

# 検出結果の確認
aws guardduty list-findings \
  --detector-id <detector-id>
```

## コンプライアンス

### タグ付けポリシー

```hcl
# terraform/main.tf
locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
    Owner       = var.owner
    CostCenter  = var.cost_center
  }
}

resource "aws_efs_file_system" "main" {
  # ...
  tags = merge(local.common_tags, {
    Name = "${var.project_name}-efs"
  })
}
```

### リソースの命名規則

```hcl
# terraform/variables.tf
variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  
  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "Project name must contain only lowercase letters, numbers, and hyphens."
  }
}
```

### バックアップポリシー

```hcl
# terraform/efs.tf
resource "aws_backup_plan" "efs" {
  name = "${var.project_name}-efs-backup-plan"
  
  rule {
    rule_name         = "daily_backup"
    target_vault_name = aws_backup_vault.main.name
    schedule          = "cron(0 2 * * ? *)"
    
    lifecycle {
      delete_after = 30
    }
  }
}

resource "aws_backup_vault" "main" {
  name        = "${var.project_name}-backup-vault"
  kms_key_arn = aws_kms_key.backup.arn
}

resource "aws_backup_selection" "efs" {
  name         = "${var.project_name}-efs-backup-selection"
  plan_id      = aws_backup_plan.efs.id
  iam_role_arn = aws_iam_role.backup.arn
  
  resources = [
    aws_efs_file_system.main.arn
  ]
}
```

## セキュリティ監査

### 定期的なセキュリティチェック

```bash
# IAMロールの権限を確認
aws iam get-role-policy \
  --role-name efs-mount-autoscaling-lambda-role \
  --policy-name efs-mount-autoscaling-lambda-policy

# セキュリティグループのルールを確認
aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=efs-mount-autoscaling-*"

# EFSの暗号化状態を確認
aws efs describe-file-systems \
  --query 'FileSystems[*].[FileSystemId,Encrypted]' \
  --output table
```

### AWS Security Hub

```bash
# Security Hubを有効化
aws securityhub enable-security-hub

# セキュリティ基準を有効化
aws securityhub batch-enable-standards \
  --standards-subscription-requests StandardsArn=arn:aws:securityhub:ap-northeast-1::standards/aws-foundational-security-best-practices/v/1.0.0

# 検出結果の確認
aws securityhub get-findings \
  --filters '{"ProductName":[{"Value":"Security Hub","Comparison":"EQUALS"}]}'
```

### 脆弱性スキャン

```bash
# ECRイメージのスキャン
aws ecr start-image-scan \
  --repository-name efs-mount-autoscaling-fargate \
  --image-id imageTag=latest

# スキャン結果の確認
aws ecr describe-image-scan-findings \
  --repository-name efs-mount-autoscaling-fargate \
  --image-id imageTag=latest
```

## インシデント対応

### セキュリティインシデント対応手順

1. **検出**: CloudWatch Alarms、GuardDuty、Security Hub
2. **隔離**: セキュリティグループの変更、リソースの停止
3. **調査**: CloudTrail、VPCフローログの分析
4. **復旧**: 影響を受けたリソースの復元
5. **事後分析**: 根本原因の特定と再発防止策

### 緊急時のコマンド

```bash
# Lambda関数を無効化
aws lambda update-function-configuration \
  --function-name efs-mount-autoscaling-file-monitor \
  --environment Variables={DISABLED=true}

# ECS Serviceを停止
aws ecs update-service \
  --cluster efs-mount-autoscaling-cluster \
  --service efs-mount-autoscaling-fargate-service \
  --desired-count 0

# セキュリティグループのルールを削除
aws ec2 revoke-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 2049 \
  --source-group sg-yyyyy
```

## ベストプラクティスチェックリスト

- [ ] すべてのIAMロールが最小権限の原則に従っている
- [ ] EFSファイルシステムが暗号化されている
- [ ] 転送時の暗号化が有効化されている
- [ ] セキュリティグループが適切に設定されている
- [ ] CloudTrailが有効化されている
- [ ] VPCフローログが有効化されている
- [ ] GuardDutyが有効化されている
- [ ] バックアップポリシーが設定されている
- [ ] タグ付けポリシーが適用されている
- [ ] 定期的なセキュリティ監査が実施されている

## 関連ドキュメント

- [デプロイメントガイド](DEPLOYMENT.md)
- [監視とアラート設定](MONITORING.md)
- [パフォーマンスチューニング](PERFORMANCE.md)
