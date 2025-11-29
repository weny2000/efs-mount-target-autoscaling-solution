#!/bin/bash
# Complete Deployment Script for EFS Mount Target Autoscaling System

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║   EFS Mount Target Autoscaling - Complete Deployment      ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Function to print section header
print_section() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

# Function to check command exists
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}Error: $1 is not installed${NC}"
        echo -e "${YELLOW}Please install $1 and try again${NC}"
        exit 1
    fi
}

# Check prerequisites
print_section "Checking Prerequisites"
check_command "aws"
check_command "terraform"
check_command "docker"
check_command "python3"
check_command "pip"

echo -e "${GREEN}✓ All prerequisites are installed${NC}"

# Verify AWS credentials
echo -e "\n${YELLOW}Verifying AWS credentials...${NC}"
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: AWS credentials not configured${NC}"
    echo -e "${YELLOW}Please run 'aws configure' and try again${NC}"
    exit 1
fi

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=$(aws configure get region || echo "ap-northeast-1")
echo -e "${GREEN}✓ AWS Account: $AWS_ACCOUNT_ID${NC}"
echo -e "${GREEN}✓ AWS Region: $AWS_REGION${NC}"

# Step 1: Deploy Lambda function package
print_section "Step 1: Building Lambda Deployment Package"
bash "$SCRIPT_DIR/deploy_lambda.sh"

# Step 2: Initialize and apply Terraform
print_section "Step 2: Deploying Infrastructure with Terraform"
cd "$PROJECT_ROOT/terraform"

echo -e "${YELLOW}Initializing Terraform...${NC}"
terraform init

echo -e "\n${YELLOW}Planning Terraform deployment...${NC}"
terraform plan -out=tfplan

echo -e "\n${YELLOW}Applying Terraform configuration...${NC}"
read -p "Do you want to proceed with Terraform apply? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo -e "${RED}Deployment cancelled${NC}"
    exit 1
fi

terraform apply tfplan
rm -f tfplan

echo -e "${GREEN}✓ Infrastructure deployed successfully${NC}"

# Step 3: Build and push Fargate container image
print_section "Step 3: Building and Pushing Fargate Container Image"
bash "$SCRIPT_DIR/build_and_push_fargate.sh"

# Step 4: Update ECS service to use new image
print_section "Step 4: Updating ECS Service"
ECS_CLUSTER=$(terraform output -raw ecs_cluster_name)
ECS_SERVICE=$(terraform output -raw ecs_service_name)

echo -e "${YELLOW}Forcing new deployment of ECS service...${NC}"
aws ecs update-service \
    --cluster "$ECS_CLUSTER" \
    --service "$ECS_SERVICE" \
    --force-new-deployment \
    --region "$AWS_REGION" \
    > /dev/null

echo -e "${GREEN}✓ ECS service deployment triggered${NC}"

# Step 5: Display deployment information
print_section "Deployment Summary"

echo -e "${GREEN}Infrastructure Resources:${NC}"
echo -e "  VPC ID:              $(terraform output -raw vpc_id)"
echo -e "  EFS File System ID:  $(terraform output -raw efs_file_system_id)"
echo -e "  Lambda Function:     $(terraform output -raw lambda_function_name)"
echo -e "  ECS Cluster:         $(terraform output -raw ecs_cluster_name)"
echo -e "  ECS Service:         $(terraform output -raw ecs_service_name)"
echo -e "  SSM Parameter:       $(terraform output -raw ssm_parameter_name)"
echo -e "  ECR Repository:      $(terraform output -raw ecr_repository_url)"

echo -e "\n${GREEN}EventBridge Schedule:${NC}"
echo -e "  Rule Name:           $(terraform output -raw eventbridge_rule_name)"
echo -e "  Schedule:            Every 5 minutes"

echo -e "\n${YELLOW}Next Steps:${NC}"
echo -e "  1. Monitor Lambda function logs in CloudWatch"
echo -e "  2. Check ECS service status: aws ecs describe-services --cluster $ECS_CLUSTER --services $ECS_SERVICE"
echo -e "  3. View mount targets: aws efs describe-mount-targets --file-system-id $(terraform output -raw efs_file_system_id)"

echo -e "\n${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║            Deployment Completed Successfully!             ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
