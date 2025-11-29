#!/bin/bash
# Fargate Container Image Build and Push Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Fargate Container Build and Push ===${NC}"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
FARGATE_DIR="$PROJECT_ROOT/fargate"

# Check if fargate directory exists
if [ ! -d "$FARGATE_DIR" ]; then
    echo -e "${RED}Error: Fargate directory not found at $FARGATE_DIR${NC}"
    exit 1
fi

# Check if Dockerfile exists
if [ ! -f "$FARGATE_DIR/Dockerfile" ]; then
    echo -e "${RED}Error: Dockerfile not found at $FARGATE_DIR/Dockerfile${NC}"
    exit 1
fi

# Get AWS account ID and region
echo -e "${YELLOW}Step 1: Getting AWS account information...${NC}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=$(aws configure get region)

if [ -z "$AWS_REGION" ]; then
    AWS_REGION="ap-northeast-1"
    echo -e "${YELLOW}No region configured, using default: $AWS_REGION${NC}"
fi

echo -e "${GREEN}AWS Account ID: $AWS_ACCOUNT_ID${NC}"
echo -e "${GREEN}AWS Region: $AWS_REGION${NC}"

# Get ECR repository name from Terraform output
echo -e "${YELLOW}Step 2: Getting ECR repository information...${NC}"
cd "$PROJECT_ROOT/terraform"

if [ ! -f "terraform.tfstate" ]; then
    echo -e "${RED}Error: Terraform state not found. Please run 'terraform apply' first.${NC}"
    exit 1
fi

ECR_REPO_URL=$(terraform output -raw ecr_repository_url 2>/dev/null)

if [ -z "$ECR_REPO_URL" ]; then
    echo -e "${RED}Error: Could not get ECR repository URL from Terraform output${NC}"
    echo -e "${YELLOW}Make sure Terraform has been applied successfully${NC}"
    exit 1
fi

echo -e "${GREEN}ECR Repository URL: $ECR_REPO_URL${NC}"

# Login to ECR
echo -e "${YELLOW}Step 3: Logging in to ECR...${NC}"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# Build Docker image
echo -e "${YELLOW}Step 4: Building Docker image...${NC}"
cd "$FARGATE_DIR"
docker build -t efs-mount-autoscaling-fargate:latest .

# Tag image for ECR
echo -e "${YELLOW}Step 5: Tagging image for ECR...${NC}"
docker tag efs-mount-autoscaling-fargate:latest "$ECR_REPO_URL:latest"
docker tag efs-mount-autoscaling-fargate:latest "$ECR_REPO_URL:$(date +%Y%m%d-%H%M%S)"

# Push image to ECR
echo -e "${YELLOW}Step 6: Pushing image to ECR...${NC}"
docker push "$ECR_REPO_URL:latest"
docker push "$ECR_REPO_URL:$(date +%Y%m%d-%H%M%S)"

echo -e "${GREEN}=== Fargate Container Build and Push Complete ===${NC}"
echo -e "${GREEN}Image pushed to: $ECR_REPO_URL${NC}"
echo -e "${YELLOW}Note: ECS service will automatically pull the new image on next deployment${NC}"
