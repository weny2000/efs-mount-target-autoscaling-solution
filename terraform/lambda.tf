# Lambda Function Resources

# Archive Lambda function code
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/lambda_function.zip"
  excludes    = ["__pycache__", "*.pyc", ".pytest_cache"]
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda" {
  name_prefix = "${var.project_name}-lambda-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-lambda-role"
  }
}

# IAM Policy for Lambda
resource "aws_iam_role_policy" "lambda" {
  name_prefix = "${var.project_name}-lambda-policy-"
  role        = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "elasticfilesystem:DescribeMountTargets",
          "elasticfilesystem:CreateMountTarget",
          "elasticfilesystem:DescribeFileSystems"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ssm:PutParameter",
          "ssm:GetParameter"
        ]
        Resource = aws_ssm_parameter.mount_targets.arn
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices"
        ]
        Resource = aws_ecs_service.fargate.id
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeSubnets",
          "ec2:DescribeNetworkInterfaces",
          "ec2:CreateNetworkInterface",
          "ec2:DeleteNetworkInterface",
          "ec2:DescribeSecurityGroups"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-file-monitor*"
      }
    ]
  })
}

# Attach VPC execution policy to Lambda role
resource "aws_iam_role_policy_attachment" "lambda_vpc_execution" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Lambda Function
resource "aws_lambda_function" "file_monitor" {
  filename         = data.archive_file.lambda.output_path
  function_name    = "${var.project_name}-file-monitor"
  role             = aws_iam_role.lambda.arn
  handler          = "file_monitor.lambda_handler"
  source_code_hash = data.archive_file.lambda.output_base64sha256
  runtime          = "python3.11"
  timeout          = 300
  memory_size      = 1024

  # VPC Configuration
  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  # EFS Configuration
  file_system_config {
    arn              = aws_efs_access_point.lambda.arn
    local_mount_path = "/mnt/efs"
  }

  # Environment Variables
  environment {
    variables = {
      TARGET_DIRECTORY      = "/mnt/efs"
      FILE_COUNT_THRESHOLD  = var.file_count_threshold
      EFS_FILE_SYSTEM_ID    = aws_efs_file_system.main.id
      VPC_ID                = aws_vpc.main.id
      SECURITY_GROUP_ID     = aws_security_group.efs.id
      SSM_PARAMETER_NAME    = aws_ssm_parameter.mount_targets.name
      ECS_CLUSTER_NAME      = aws_ecs_cluster.main.name
      ECS_SERVICE_NAME      = aws_ecs_service.fargate.name
    }
  }

  # Reserved concurrent executions to prevent multiple simultaneous executions
  reserved_concurrent_executions = 1

  depends_on = [
    aws_efs_mount_target.initial,
    aws_iam_role_policy.lambda,
    aws_iam_role_policy_attachment.lambda_vpc_execution
  ]

  tags = {
    Name = "${var.project_name}-file-monitor"
  }
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.file_monitor.function_name}"
  retention_in_days = 14

  tags = {
    Name = "${var.project_name}-lambda-logs"
  }
}
