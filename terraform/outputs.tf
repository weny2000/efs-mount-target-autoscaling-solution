# Outputs for EFS Mount Target Autoscaling Infrastructure

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "IDs of private subnets"
  value       = aws_subnet.private[*].id
}

output "efs_file_system_id" {
  description = "ID of the EFS file system"
  value       = aws_efs_file_system.main.id
}

output "efs_mount_target_ids" {
  description = "IDs of initial EFS mount targets"
  value       = aws_efs_mount_target.initial[*].id
}

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.file_monitor.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.file_monitor.arn
}

output "ssm_parameter_name" {
  description = "Name of the SSM parameter storing mount target list"
  value       = aws_ssm_parameter.mount_targets.name
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = aws_ecs_service.fargate.name
}

output "ecr_repository_url" {
  description = "URL of the ECR repository for Fargate container"
  value       = aws_ecr_repository.fargate.repository_url
}

output "eventbridge_rule_name" {
  description = "Name of the EventBridge rule"
  value       = aws_cloudwatch_event_rule.lambda_schedule.name
}
