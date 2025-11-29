# Performance Tuning Guide

This document explains performance optimization for the EFS Mount Target Auto-scaling System.

## Table of Contents

1. [Performance Overview](#performance-overview)
2. [Lambda Function Optimization](#lambda-function-optimization)
3. [Fargate Task Optimization](#fargate-task-optimization)
4. [EFS Optimization](#efs-optimization)
5. [Network Optimization](#network-optimization)
6. [Cost Optimization](#cost-optimization)
7. [Performance Testing](#performance-testing)

## Performance Overview

### Performance Goals

- **Lambda Execution Time**: Within 30 seconds
- **Fargate Task Startup Time**: Within 2 minutes
- **EFS Throughput**: 100 MB/s or higher
- **Mount Target Creation Time**: Within 90 seconds
- **File Count**: 1 million files within 5 minutes

### Performance Bottlenecks

Common bottlenecks:

1. **Lambda Function**: File count processing time
2. **EFS**: I/O throughput limitations
3. **Network**: VPC communication latency
4. **Fargate**: Task startup time and resource shortage

## Lambda Function Optimization

### Memory Configuration Optimization

Increasing Lambda function memory also proportionally increases CPU:

```hcl
# terraform/lambda.tf
resource "aws_lambda_function" "file_monitor" {
  # ...
  memory_size = 1024  # Default: 512MB
  timeout     = 60    # Default: 30 seconds
  # ...
}
```

Recommended memory sizes:

- Small scale (< 100k files): 512MB
- Medium scale (100k-500k files): 1024MB
- Large scale (> 500k files): 2048MB

### Parallel Processing Implementation

```python
# lambda/file_monitor.py
import concurrent.futures
from pathlib import Path

def count_files_parallel(directory, max_workers=4):
    """Count files in parallel"""
    subdirs = [d for d in Path(directory).iterdir() if d.is_dir()]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(count_files_in_dir, subdir) for subdir in subdirs]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    return sum(results)

def count_files_in_dir(directory):
    """Count files in a single directory"""
    return sum(1 for _ in Path(directory).rglob('*') if _.is_file())
```

### Caching Utilization

```python
# lambda/file_monitor.py
import boto3
from datetime import datetime, timedelta

ssm = boto3.client('ssm')

def get_cached_file_count(cache_key, ttl_minutes=5):
    """Get cached file count from SSM Parameter Store"""
    try:
        response = ssm.get_parameter(Name=cache_key)
        cached_data = json.loads(response['Parameter']['Value'])
        
        cached_time = datetime.fromisoformat(cached_data['timestamp'])
        if datetime.utcnow() - cached_time < timedelta(minutes=ttl_minutes):
            return cached_data['file_count']
    except:
        pass
    
    return None

def cache_file_count(cache_key, file_count):
    """Cache file count"""
    cache_data = {
        'file_count': file_count,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    ssm.put_parameter(
        Name=cache_key,
        Value=json.dumps(cache_data),
        Type='String',
        Overwrite=True
    )
```


### Lambda Layers Utilization

Separate common libraries as layers:

```bash
# Create Lambda Layer
mkdir -p lambda-layer/python
pip install boto3 -t lambda-layer/python/
cd lambda-layer
zip -r ../lambda-layer.zip .

# Upload layer
aws lambda publish-layer-version \
  --layer-name efs-mount-autoscaling-common \
  --zip-file fileb://../lambda-layer.zip \
  --compatible-runtimes python3.11
```

## Fargate Task Optimization

### Resource Configuration Optimization

```hcl
# terraform/ecs.tf
resource "aws_ecs_task_definition" "fargate" {
  # ...
  cpu    = "4096"  # 4 vCPU
  memory = "8192"  # 8 GB
  # ...
}
```

Recommended resource sizes:

| Workload | CPU | Memory | Use Case |
|----------|-----|--------|----------|
| Light | 512 | 1024 | Test environment |
| Standard | 2048 | 4096 | Normal production |
| Heavy | 4096 | 8192 | Large file processing |

### Task Count Optimization

```hcl
# terraform/ecs.tf
resource "aws_ecs_service" "fargate" {
  # ...
  desired_count = 3  # Number of tasks
  
  # Auto Scaling configuration
  # ...
}
```

### EFS Mount Options Optimization

```hcl
# terraform/ecs.tf
resource "aws_ecs_task_definition" "fargate" {
  # ...
  volume {
    name = "efs-storage"
    
    efs_volume_configuration {
      file_system_id = aws_efs_file_system.main.id
      transit_encryption = "ENABLED"
      
      authorization_config {
        access_point_id = aws_efs_access_point.fargate.id
      }
    }
  }
}
```

### Container Image Optimization

```dockerfile
# fargate/Dockerfile
FROM python:3.11-slim

# Remove unnecessary packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Use multi-stage builds
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["python", "app.py"]
```

## EFS Optimization

### Performance Mode Selection

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  # General Purpose: Low latency, max 7,000 IOPS
  # Max I/O: High throughput, unlimited IOPS
  performance_mode = "generalPurpose"  # or "maxIO"
  
  # ...
}
```

Selection criteria:

- **General Purpose**: Suitable for most use cases
- **Max I/O**: When hundreds of concurrent connections or high IOPS requirements

### Throughput Mode Selection

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  # ...
  
  # Bursting: Standard, throughput based on storage size
  # Provisioned: Fixed throughput, additional cost
  throughput_mode = "bursting"  # or "provisioned"
  
  # For Provisioned mode
  # provisioned_throughput_in_mibps = 100
}
```

### EFS Access Point Utilization

```hcl
# terraform/efs.tf
resource "aws_efs_access_point" "fargate" {
  file_system_id = aws_efs_file_system.main.id
  
  posix_user {
    gid = 1000
    uid = 1000
  }
  
  root_directory {
    path = "/data"
    creation_info {
      owner_gid   = 1000
      owner_uid   = 1000
      permissions = "755"
    }
  }
}
```

### File System Optimization

```bash
# Mount options for EFS
mount -t nfs4 -o \
  nfsvers=4.1,\
  rsize=1048576,\
  wsize=1048576,\
  hard,\
  timeo=600,\
  retrans=2,\
  noresvport \
  fs-xxxxx.efs.ap-northeast-1.amazonaws.com:/ /mnt/efs
```

Recommended mount options:

- `rsize=1048576`: Read buffer size (1MB)
- `wsize=1048576`: Write buffer size (1MB)
- `hard`: Hard mount (recommended)
- `timeo=600`: Timeout value (60 seconds)

## Network Optimization

### VPC Endpoint Utilization

```hcl
# terraform/network.tf
resource "aws_vpc_endpoint" "s3" {
  vpc_id       = aws_vpc.main.id
  service_name = "com.amazonaws.${var.aws_region}.s3"
  
  route_table_ids = [aws_route_table.private.id]
}

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
}
```

### Security Group Optimization

```hcl
# terraform/network.tf
resource "aws_security_group" "efs" {
  name        = "${var.project_name}-efs-sg"
  description = "Security group for EFS mount targets"
  vpc_id      = aws_vpc.main.id
  
  ingress {
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "NFS access from VPC"
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

### Subnet Placement Optimization

```hcl
# terraform/network.tf
# Deploy mount target in each AZ
resource "aws_efs_mount_target" "main" {
  count = length(var.availability_zones)
  
  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}
```

## Cost Optimization

### Lambda Function Cost Reduction

```hcl
# terraform/lambda.tf
resource "aws_lambda_function" "file_monitor" {
  # ...
  
  # Set minimum required memory
  memory_size = 512
  
  # Set appropriate timeout
  timeout = 30
  
  # Set reserved concurrent executions (optional)
  reserved_concurrent_executions = 1
}
```

### Fargate Cost Reduction

```hcl
# terraform/ecs.tf
resource "aws_ecs_service" "fargate" {
  # ...
  
  # Utilize Fargate Spot
  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
    base              = 0
  }
  
  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 0
    base              = 1
  }
}
```

### EFS Cost Reduction

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  # ...
  
  # Enable lifecycle management
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  
  lifecycle_policy {
    transition_to_primary_storage_class = "AFTER_1_ACCESS"
  }
}
```

### CloudWatch Logs Cost Reduction

```hcl
# terraform/main.tf
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}-file-monitor"
  retention_in_days = 7  # Reduce log retention period
}

resource "aws_cloudwatch_log_group" "fargate" {
  name              = "/ecs/${var.project_name}-fargate"
  retention_in_days = 7
}
```

## Performance Testing

### Lambda Function Load Testing

```python
# tests/load_test_lambda.py
import boto3
import concurrent.futures
import time

lambda_client = boto3.client('lambda')

def invoke_lambda():
    """Invoke Lambda function"""
    start = time.time()
    response = lambda_client.invoke(
        FunctionName='efs-mount-autoscaling-file-monitor',
        InvocationType='RequestResponse',
        Payload='{}'
    )
    duration = time.time() - start
    return duration, response['StatusCode']

def load_test(num_requests=100, max_workers=10):
    """Execute load test"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(invoke_lambda) for _ in range(num_requests)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    durations = [r[0] for r in results]
    success_count = sum(1 for r in results if r[1] == 200)
    
    print(f"Total requests: {num_requests}")
    print(f"Successful: {success_count}")
    print(f"Average duration: {sum(durations) / len(durations):.2f}s")
    print(f"Max duration: {max(durations):.2f}s")
    print(f"Min duration: {min(durations):.2f}s")

if __name__ == '__main__':
    load_test()
```

### EFS Throughput Testing

```bash
# Throughput test on EFS mount point
# Write test
dd if=/dev/zero of=/mnt/efs/testfile bs=1M count=1024 oflag=direct

# Read test
dd if=/mnt/efs/testfile of=/dev/null bs=1M iflag=direct

# Random I/O test
fio --name=random-write --ioengine=libaio --iodepth=32 \
    --rw=randwrite --bs=4k --direct=1 --size=1G \
    --numjobs=4 --runtime=60 --group_reporting \
    --directory=/mnt/efs
```

### Fargate Task Benchmarking

```python
# fargate/benchmark.py
import time
import os
from pathlib import Path

def benchmark_file_operations(directory, num_files=10000):
    """Benchmark file operations"""
    
    # Write test
    start = time.time()
    for i in range(num_files):
        with open(f"{directory}/test_{i}.txt", 'w') as f:
            f.write(f"Test data {i}\n")
    write_duration = time.time() - start
    
    # Read test
    start = time.time()
    for i in range(num_files):
        with open(f"{directory}/test_{i}.txt", 'r') as f:
            _ = f.read()
    read_duration = time.time() - start
    
    # Delete test
    start = time.time()
    for i in range(num_files):
        os.remove(f"{directory}/test_{i}.txt")
    delete_duration = time.time() - start
    
    print(f"Write: {write_duration:.2f}s ({num_files/write_duration:.0f} files/s)")
    print(f"Read: {read_duration:.2f}s ({num_files/read_duration:.0f} files/s)")
    print(f"Delete: {delete_duration:.2f}s ({num_files/delete_duration:.0f} files/s)")

if __name__ == '__main__':
    benchmark_file_operations('/mnt/efs/benchmark')
```

## Best Practices

1. **Incremental Optimization**: Repeat the cycle of measure → analyze → optimize → verify
2. **Identify Bottlenecks**: Use CloudWatch metrics to identify the slowest parts
3. **Appropriate Resource Allocation**: Excessive resources increase costs, insufficient resources degrade performance
4. **Regular Reviews**: Adjust settings according to workload changes
5. **Production Testing**: Verify performance under actual load

## Related Documents

- [Deployment Guide](DEPLOYMENT.md)
- [Monitoring and Alerting Setup](MONITORING.md)
- [Security Best Practices](SECURITY.md)
