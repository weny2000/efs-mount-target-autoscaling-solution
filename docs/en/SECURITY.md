# Security Best Practices

This document explains security configuration and best practices for the EFS Mount Target Auto-scaling System.

## Table of Contents

1. [Security Overview](#security-overview)
2. [IAM Permission Management](#iam-permission-management)
3. [Network Security](#network-security)
4. [Data Encryption](#data-encryption)
5. [Logging and Monitoring](#logging-and-monitoring)
6. [Compliance](#compliance)
7. [Security Auditing](#security-auditing)

## Security Overview

### Security Principles

This system is designed based on the following security principles:

1. **Principle of Least Privilege**: Grant only minimum required permissions
2. **Defense in Depth**: Protect with multiple security layers
3. **Encryption**: Encrypt data in transit and at rest
4. **Audit and Logging**: Record all operations
5. **Regular Reviews**: Periodic security configuration audits

### Shared Responsibility Model

- **AWS Responsibility**: Infrastructure security
- **Customer Responsibility**: Data, applications, access management

## IAM Permission Management

### Lambda Function IAM Role

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

### Fargate Task Roles

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

# Fargate execution role
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


### IAM Policy Best Practices

1. **Conditional Access**: Restrict resources and regions

```json
{
  "Condition": {
    "StringEquals": {
      "aws:RequestedRegion": "ap-northeast-1"
    }
  }
}
```

2. **Resource-Based Policies**: Allow access to specific resources only

```json
{
  "Resource": "arn:aws:efs:ap-northeast-1:123456789012:file-system/fs-xxxxx"
}
```

3. **Tag-Based Access Control**:

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

## Network Security

### VPC Design

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

# Private subnets (recommended)
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

### Security Group Configuration

```hcl
# terraform/network.tf
# EFS security group
resource "aws_security_group" "efs" {
  name        = "${var.project_name}-efs-sg"
  description = "Security group for EFS mount targets"
  vpc_id      = aws_vpc.main.id
  
  # Allow NFS access only from specific security groups
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

# Fargate security group
resource "aws_security_group" "fargate" {
  name        = "${var.project_name}-fargate-sg"
  description = "Security group for Fargate tasks"
  vpc_id      = aws_vpc.main.id
  
  # Allow outbound only
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

### Network ACL

```hcl
# terraform/network.tf
resource "aws_network_acl" "private" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = aws_subnet.private[*].id
  
  # Inbound rules
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
  
  # Outbound rules
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

### VPC Flow Logs

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

## Data Encryption

### EFS Encryption

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  creation_token = var.project_name
  
  # Enable encryption at rest
  encrypted  = true
  kms_key_id = aws_kms_key.efs.arn
  
  # Enforce encryption in transit
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  
  tags = {
    Name = "${var.project_name}-efs"
  }
}

# Create KMS key
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

### Encryption in Transit

```hcl
# terraform/efs.tf
resource "aws_efs_mount_target" "main" {
  count = length(var.availability_zones)
  
  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

# Enable encryption in transit in ECS task definition
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

### Secrets Manager Utilization

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

# Access from Lambda function
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

## Logging and Monitoring

### Enable CloudTrail

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

### AWS Config Configuration

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

### Enable GuardDuty

```bash
# Enable GuardDuty
aws guardduty create-detector \
  --enable \
  --finding-publishing-frequency FIFTEEN_MINUTES

# Check findings
aws guardduty list-findings \
  --detector-id <detector-id>
```

## Compliance

### Tagging Policy

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

### Resource Naming Convention

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

### Backup Policy

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

## Security Auditing

### Regular Security Checks

```bash
# Check IAM role permissions
aws iam get-role-policy \
  --role-name efs-mount-autoscaling-lambda-role \
  --policy-name efs-mount-autoscaling-lambda-policy

# Check security group rules
aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=efs-mount-autoscaling-*"

# Check EFS encryption status
aws efs describe-file-systems \
  --query 'FileSystems[*].[FileSystemId,Encrypted]' \
  --output table
```

### AWS Security Hub

```bash
# Enable Security Hub
aws securityhub enable-security-hub

# Enable security standards
aws securityhub batch-enable-standards \
  --standards-subscription-requests StandardsArn=arn:aws:securityhub:ap-northeast-1::standards/aws-foundational-security-best-practices/v/1.0.0

# Check findings
aws securityhub get-findings \
  --filters '{"ProductName":[{"Value":"Security Hub","Comparison":"EQUALS"}]}'
```

### Vulnerability Scanning

```bash
# Scan ECR images
aws ecr start-image-scan \
  --repository-name efs-mount-autoscaling-fargate \
  --image-id imageTag=latest

# Check scan results
aws ecr describe-image-scan-findings \
  --repository-name efs-mount-autoscaling-fargate \
  --image-id imageTag=latest
```

## Incident Response

### Security Incident Response Procedure

1. **Detection**: CloudWatch Alarms, GuardDuty, Security Hub
2. **Isolation**: Modify security groups, stop resources
3. **Investigation**: Analyze CloudTrail, VPC Flow Logs
4. **Recovery**: Restore affected resources
5. **Post-Incident Analysis**: Identify root cause and prevention measures

### Emergency Commands

```bash
# Disable Lambda function
aws lambda update-function-configuration \
  --function-name efs-mount-autoscaling-file-monitor \
  --environment Variables={DISABLED=true}

# Stop ECS Service
aws ecs update-service \
  --cluster efs-mount-autoscaling-cluster \
  --service efs-mount-autoscaling-fargate-service \
  --desired-count 0

# Remove security group rules
aws ec2 revoke-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 2049 \
  --source-group sg-yyyyy
```

## Best Practices Checklist

- [ ] All IAM roles follow the principle of least privilege
- [ ] EFS file system is encrypted
- [ ] Encryption in transit is enabled
- [ ] Security groups are properly configured
- [ ] CloudTrail is enabled
- [ ] VPC Flow Logs are enabled
- [ ] GuardDuty is enabled
- [ ] Backup policy is configured
- [ ] Tagging policy is applied
- [ ] Regular security audits are conducted

## Related Documents

- [Deployment Guide](DEPLOYMENT.md)
- [Monitoring and Alerting Setup](MONITORING.md)
- [Performance Tuning](PERFORMANCE.md)
