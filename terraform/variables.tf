# Variables for EFS Mount Target Autoscaling Infrastructure

variable "aws_region" {
  description = "AWS region where resources will be created"
  type        = string
  default     = "ap-northeast-1"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "efs-mount-autoscaling"
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones to use"
  type        = list(string)
  default     = ["ap-northeast-1a", "ap-northeast-1c", "ap-northeast-1d"]
}

variable "file_count_threshold" {
  description = "File count threshold for triggering mount target creation"
  type        = number
  default     = 100000
}

variable "lambda_schedule_expression" {
  description = "EventBridge schedule expression for Lambda function"
  type        = string
  default     = "rate(5 minutes)"
}

variable "efs_target_directory" {
  description = "Target directory path on EFS to monitor"
  type        = string
  default     = "/data"
}

variable "fargate_cpu" {
  description = "CPU units for Fargate task (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 2048
}

variable "fargate_memory" {
  description = "Memory for Fargate task in MB"
  type        = number
  default     = 4096
}

variable "fargate_desired_count" {
  description = "Desired number of Fargate tasks"
  type        = number
  default     = 2
}

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
