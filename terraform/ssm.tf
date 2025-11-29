# SSM Parameter Store

# SSM Parameter for Mount Target List
resource "aws_ssm_parameter" "mount_targets" {
  name        = "/${var.project_name}/mount-targets"
  description = "EFS Mount Target list for Fargate service"
  type        = "String"
  
  # Initial value with the first 2 mount targets
  value = jsonencode({
    mount_targets = [
      for i, mt in aws_efs_mount_target.initial : {
        mount_target_id   = mt.id
        ip_address        = mt.ip_address
        availability_zone = mt.availability_zone_name
        subnet_id         = mt.subnet_id
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-mount-targets"
  }

  lifecycle {
    ignore_changes = [value]
  }
}
