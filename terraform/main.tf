# EFS Mount Target Autoscaling Infrastructure
# Main Terraform configuration file

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        Project     = var.project_name
        ManagedBy   = "Terraform"
        Environment = var.environment
      },
      var.tags
    )
  }
}

# Data sources
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
