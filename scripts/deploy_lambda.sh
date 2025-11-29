#!/bin/bash
# Lambda Function Deployment Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Lambda Function Deployment ===${NC}"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LAMBDA_DIR="$PROJECT_ROOT/lambda"
BUILD_DIR="$PROJECT_ROOT/build/lambda"

# Check if lambda directory exists
if [ ! -d "$LAMBDA_DIR" ]; then
    echo -e "${RED}Error: Lambda directory not found at $LAMBDA_DIR${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1: Creating build directory...${NC}"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo -e "${YELLOW}Step 2: Copying Lambda function code...${NC}"
cp "$LAMBDA_DIR"/*.py "$BUILD_DIR/"
cp "$LAMBDA_DIR/requirements.txt" "$BUILD_DIR/"

echo -e "${YELLOW}Step 3: Installing dependencies...${NC}"
cd "$BUILD_DIR"
pip install -r requirements.txt -t . --upgrade

echo -e "${YELLOW}Step 4: Cleaning up unnecessary files...${NC}"
# Remove unnecessary files to reduce package size
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true

echo -e "${YELLOW}Step 5: Creating deployment package...${NC}"
ZIP_FILE="$PROJECT_ROOT/terraform/lambda_function.zip"
rm -f "$ZIP_FILE"
zip -r "$ZIP_FILE" . -x "*.git*" "*.pytest_cache*" "__pycache__/*"

echo -e "${GREEN}Lambda deployment package created: $ZIP_FILE${NC}"

# Get package size
PACKAGE_SIZE=$(du -h "$ZIP_FILE" | cut -f1)
echo -e "${GREEN}Package size: $PACKAGE_SIZE${NC}"

# Check if package size is within Lambda limits (50MB zipped, 250MB unzipped)
PACKAGE_SIZE_BYTES=$(stat -f%z "$ZIP_FILE" 2>/dev/null || stat -c%s "$ZIP_FILE" 2>/dev/null)
MAX_SIZE=$((50 * 1024 * 1024)) # 50MB

if [ "$PACKAGE_SIZE_BYTES" -gt "$MAX_SIZE" ]; then
    echo -e "${RED}Warning: Package size exceeds 50MB Lambda limit!${NC}"
    echo -e "${YELLOW}Consider using Lambda layers or reducing dependencies.${NC}"
fi

echo -e "${GREEN}=== Lambda Deployment Complete ===${NC}"
echo -e "${YELLOW}Note: Run 'terraform apply' to deploy the Lambda function to AWS${NC}"
