# Deployment Guide

This document provides detailed deployment instructions for the EFS Mount Target Auto-scaling System.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Initial Deployment](#initial-deployment)
3. [Update Deployment](#update-deployment)
4. [Configuration Customization](#configuration-customization)
5. [Post-Deployment Verification](#post-deployment-verification)
6. [Rollback](#rollback)
7. [Cleanup](#cleanup)

## Prerequisites

### Required Tools

The following tools must be installed:

```bash
# AWS CLI
aws --version
# Example output: aws-cli/2.x.x

# Terraform
terraform --version
# Example output: Terraform v1.x.x

# Docker
docker --version
# Example output: Docker version 24.x.x

# Python
python3 --version
# Example output: Python 3.11.x

# pip
pip --version
# Example output: pip 23.x.x
```

### AWS Credentials Configuration

```bash
# Configure AWS CLI
aws configure

# Input items:
# AWS Access Key ID: <YOUR_ACCESS_KEY>
# AWS Secret Access Key: <YOUR_SECRET_KEY>
# Default region name: ap-northeast-1
# Default output format: json

# Verify credentials
aws sts get-caller-identity
```

### Required IAM Permissions

The IAM user/role executing the deployment requires permissions for the following services:

- VPC (create, delete, modify)
- EFS (file system, mount target creation)
- Lambda (function creation, updates)
- ECS/Fargate (cluster, service, task definition creation)
- ECR (repository creation, image push)
- IAM (role, policy creation)
- EventBridge (rule creation)
- SSM Parameter Store (parameter creation, updates)
- CloudWatch Logs (log group creation)

Recommended: `AdministratorAccess` or equivalent permissions

## Initial Deployment

### Step 1: Clone Repository

```bash
git clone <repository-url>
cd efs-mount-target-autoscaling
```

### Step 2: Install Dependencies

```bash
# Development dependencies
pip install -r requirements-dev.txt

# Lambda dependencies
pip install -r lambda/requirements.txt

# Fargate dependencies
pip install -r fargate/requirements.txt
```


### Step 3: Run Tests (Optional)

```bash
# Run all tests
pytest

# Verify tests pass successfully
```

### Step 4: Configure Terraform Variables

Create `terraform/terraform.tfvars` file:

```hcl
# Basic configuration
aws_region  = "ap-northeast-1"
environment = "dev"
project_name = "efs-mount-autoscaling"

# Network configuration
vpc_cidr = "10.0.0.0/16"
availability_zones = [
  "ap-northeast-1a",
  "ap-northeast-1c",
  "ap-northeast-1d"
]

# Lambda configuration
file_count_threshold = 100000
lambda_schedule_expression = "rate(5 minutes)"
efs_target_directory = "/data"

# Fargate configuration
fargate_cpu = 2048
fargate_memory = 4096
fargate_desired_count = 2

# Tags
tags = {
  Owner = "your-name"
  Team  = "your-team"
}
```

### Step 5: Execute Integrated Deployment

```bash
# Grant execution permissions to deployment scripts
chmod +x scripts/*.sh

# Execute integrated deployment
bash scripts/deploy_all.sh
```

The deployment script automatically performs the following:

1. **Prerequisites Check**: Verify required tools are installed
2. **AWS Authentication Verification**: Confirm AWS credentials are valid
3. **Lambda Function Packaging**: Package Lambda function code into ZIP file
4. **Terraform Deployment**: Deploy infrastructure to AWS
5. **Fargate Image Build**: Build Docker image
6. **ECR Push**: Push image to ECR
7. **ECS Service Update**: Update service with new image

### Step 6: Verify Deployment

Upon completion, the following information will be displayed:

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

## Update Deployment

### Updating Lambda Function

When Lambda function code is modified:

```bash
# Repackage Lambda function
bash scripts/deploy_lambda.sh

# Apply updates with Terraform
cd terraform
terraform apply
```

### Updating Fargate Application

When Fargate application code is modified:

```bash
# Build and push new image
bash scripts/build_and_push_fargate.sh

# Force ECS Service redeployment
aws ecs update-service \
  --cluster efs-mount-autoscaling-cluster \
  --service efs-mount-autoscaling-fargate-service \
  --force-new-deployment
```

### Updating Infrastructure

When Terraform configuration is modified:

```bash
cd terraform

# Review changes
terraform plan

# Apply changes
terraform apply
```

## Configuration Customization

### Changing File Count Threshold

```hcl
# terraform/terraform.tfvars
file_count_threshold = 200000  # Change to 200,000 files
```

```bash
cd terraform
terraform apply
```

### Changing Lambda Execution Interval

```hcl
# terraform/terraform.tfvars
lambda_schedule_expression = "rate(10 minutes)"  # Change to every 10 minutes
```

```bash
cd terraform
terraform apply
```

### Changing Fargate Task Count

```hcl
# terraform/terraform.tfvars
fargate_desired_count = 4  # Change to 4 tasks
```

```bash
cd terraform
terraform apply
```

### Changing EFS Performance Mode

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  # ...
  performance_mode = "maxIO"  # Change from General Purpose to Max I/O
  # ...
}
```

**Note**: Changing performance mode requires recreating the EFS file system.

## Post-Deployment Verification

### Verify Lambda Function Operation

```bash
# Manually invoke Lambda function
aws lambda invoke \
  --function-name efs-mount-autoscaling-file-monitor \
  --payload '{}' \
  response.json

# Check execution result
cat response.json

# Check CloudWatch Logs
aws logs tail /aws/lambda/efs-mount-autoscaling-file-monitor --follow
```

### Verify ECS Service Status

```bash
# Check ECS Service status
aws ecs describe-services \
  --cluster efs-mount-autoscaling-cluster \
  --services efs-mount-autoscaling-fargate-service

# Check task status
aws ecs list-tasks \
  --cluster efs-mount-autoscaling-cluster \
  --service-name efs-mount-autoscaling-fargate-service

# Check task logs
aws logs tail /ecs/efs-mount-autoscaling-fargate --follow
```

### Verify Mount Targets

```bash
# Get EFS file system ID
EFS_ID=$(cd terraform && terraform output -raw efs_file_system_id)

# List mount targets
aws efs describe-mount-targets --file-system-id $EFS_ID
```

### Verify SSM Parameter Store

```bash
# Check mount target list
aws ssm get-parameter \
  --name /efs-mount-autoscaling/mount-targets \
  --query 'Parameter.Value' \
  --output text | jq .
```

## Rollback

### Lambda Function Rollback

```bash
# Check previous versions
aws lambda list-versions-by-function \
  --function-name efs-mount-autoscaling-file-monitor

# Update alias to specific version
aws lambda update-alias \
  --function-name efs-mount-autoscaling-file-monitor \
  --name PROD \
  --function-version <VERSION_NUMBER>
```

### Fargate Application Rollback

```bash
# Check previous task definitions
aws ecs list-task-definitions \
  --family-prefix efs-mount-autoscaling-fargate

# Update service with previous task definition
aws ecs update-service \
  --cluster efs-mount-autoscaling-cluster \
  --service efs-mount-autoscaling-fargate-service \
  --task-definition efs-mount-autoscaling-fargate:<REVISION>
```

### Terraform Rollback

```bash
cd terraform

# Check previous state
terraform state list

# Revert specific resources to previous state
# (if managed with Git)
git checkout <PREVIOUS_COMMIT> -- terraform/

# Apply changes
terraform apply
```

## Cleanup

### Delete All Resources

```bash
cd terraform

# Review resources to be deleted
terraform plan -destroy

# Delete all resources
terraform destroy
```

**Note**: 
- Data in EFS file system will be deleted
- Images in ECR repository will be deleted
- CloudWatch Logs will be deleted

### Delete Specific Resources Only

```bash
# Delete specific resource
terraform destroy -target=aws_ecs_service.fargate

# Verify deletion
terraform plan
```

## Troubleshooting

### Deployment Fails

#### Error: "Error creating Lambda function: InvalidParameterValueException"

**Cause**: Lambda function package size is too large

**Solution**:
```bash
# Remove unnecessary files and recreate package
bash scripts/deploy_lambda.sh
```

#### Error: "Error creating ECS service: InvalidParameterException"

**Cause**: Image not pushed to ECR

**Solution**:
```bash
# Build and push Fargate image
bash scripts/build_and_push_fargate.sh
```

#### Error: "Error creating Mount Target: MountTargetConflict"

**Cause**: Mount target already exists

**Solution**: This is normal behavior. Lambda function skips existing mount targets.

### Lambda Function Not Executing

```bash
# Check EventBridge rule status
aws events describe-rule --name efs-mount-autoscaling-lambda-schedule

# Check Lambda function permissions
aws lambda get-policy --function-name efs-mount-autoscaling-file-monitor
```

### Fargate Tasks Not Starting

```bash
# Check ECS Service events
aws ecs describe-services \
  --cluster efs-mount-autoscaling-cluster \
  --services efs-mount-autoscaling-fargate-service \
  --query 'services[0].events[0:5]'

# Check task stop reason
aws ecs describe-tasks \
  --cluster efs-mount-autoscaling-cluster \
  --tasks <TASK_ARN>
```

## Support

If you encounter issues, please check:

1. [README.md](../README.md) - Basic usage
2. [Design Document](../.kiro/specs/efs-mount-target-autoscaling/design.md) - Detailed system design
3. CloudWatch Logs - Error log review
4. AWS Support - AWS service issues

## Next Steps

- [Monitoring and Alerting Setup](MONITORING.md)
- [Performance Tuning](PERFORMANCE.md)
- [Security Best Practices](SECURITY.md)
