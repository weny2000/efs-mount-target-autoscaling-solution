# パフォーマンスチューニングガイド

このドキュメントでは、EFS Mount Target Auto-scaling Systemのパフォーマンス最適化について説明します。

## 目次

1. [パフォーマンスの概要](#パフォーマンスの概要)
2. [Lambda関数の最適化](#lambda関数の最適化)
3. [Fargateタスクの最適化](#fargateタスクの最適化)
4. [EFSの最適化](#efsの最適化)
5. [ネットワークの最適化](#ネットワークの最適化)
6. [コスト最適化](#コスト最適化)
7. [パフォーマンステスト](#パフォーマンステスト)

## パフォーマンスの概要

### パフォーマンス目標

- **Lambda実行時間**: 30秒以内
- **Fargateタスク起動時間**: 2分以内
- **EFSスループット**: 100 MB/s以上
- **Mount Target作成時間**: 90秒以内
- **ファイル数カウント**: 100万ファイルを5分以内

### パフォーマンスボトルネック

一般的なボトルネック：

1. **Lambda関数**: ファイル数カウントの処理時間
2. **EFS**: I/Oスループットの制限
3. **ネットワーク**: VPC間の通信遅延
4. **Fargate**: タスク起動時間とリソース不足

## Lambda関数の最適化

### メモリ設定の最適化

Lambda関数のメモリを増やすとCPUも比例して増加します：

```hcl
# terraform/lambda.tf
resource "aws_lambda_function" "file_monitor" {
  # ...
  memory_size = 1024  # デフォルト: 512MB
  timeout     = 60    # デフォルト: 30秒
  # ...
}
```

メモリサイズの推奨値：

- 小規模（10万ファイル未満）: 512MB
- 中規模（10-50万ファイル）: 1024MB
- 大規模（50万ファイル以上）: 2048MB

### 並列処理の実装

```python
# lambda/file_monitor.py
import concurrent.futures
from pathlib import Path

def count_files_parallel(directory, max_workers=4):
    """並列でファイル数をカウント"""
    subdirs = [d for d in Path(directory).iterdir() if d.is_dir()]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(count_files_in_dir, subdir) for subdir in subdirs]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    return sum(results)

def count_files_in_dir(directory):
    """単一ディレクトリのファイル数をカウント"""
    return sum(1 for _ in Path(directory).rglob('*') if _.is_file())
```


### キャッシュの活用

```python
# lambda/file_monitor.py
import boto3
from datetime import datetime, timedelta

ssm = boto3.client('ssm')

def get_cached_file_count(cache_key, ttl_minutes=5):
    """SSM Parameter Storeからキャッシュされたファイル数を取得"""
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
    """ファイル数をキャッシュ"""
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

### Lambda Layersの活用

共通ライブラリをLayerとして分離：

```bash
# Lambda Layerの作成
mkdir -p lambda-layer/python
pip install boto3 -t lambda-layer/python/
cd lambda-layer
zip -r ../lambda-layer.zip .

# Layerをアップロード
aws lambda publish-layer-version \
  --layer-name efs-mount-autoscaling-common \
  --zip-file fileb://../lambda-layer.zip \
  --compatible-runtimes python3.11
```

## Fargateタスクの最適化

### リソース設定の最適化

```hcl
# terraform/ecs.tf
resource "aws_ecs_task_definition" "fargate" {
  # ...
  cpu    = "4096"  # 4 vCPU
  memory = "8192"  # 8 GB
  # ...
}
```

リソースサイズの推奨値：

| ワークロード | CPU | メモリ | 用途 |
|------------|-----|--------|------|
| 軽量 | 512 | 1024 | テスト環境 |
| 標準 | 2048 | 4096 | 通常の本番環境 |
| 高負荷 | 4096 | 8192 | 大量ファイル処理 |

### タスク数の最適化

```hcl
# terraform/ecs.tf
resource "aws_ecs_service" "fargate" {
  # ...
  desired_count = 3  # タスク数
  
  # Auto Scalingの設定
  # ...
}
```

### EFS マウントオプションの最適化

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

### コンテナイメージの最適化

```dockerfile
# fargate/Dockerfile
FROM python:3.11-slim

# 不要なパッケージを削除
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# マルチステージビルドの活用
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["python", "app.py"]
```

## EFSの最適化

### パフォーマンスモードの選択

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  # General Purpose: 低レイテンシ、最大7,000 IOPS
  # Max I/O: 高スループット、無制限IOPS
  performance_mode = "generalPurpose"  # または "maxIO"
  
  # ...
}
```

選択基準：

- **General Purpose**: ほとんどのユースケースに適している
- **Max I/O**: 数百以上の同時接続、高いIOPS要件がある場合

### スループットモードの選択

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  # ...
  
  # Bursting: 標準、ストレージサイズに応じたスループット
  # Provisioned: 固定スループット、追加コスト
  throughput_mode = "bursting"  # または "provisioned"
  
  # Provisionedモードの場合
  # provisioned_throughput_in_mibps = 100
}
```

### EFS Access Pointの活用

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

### ファイルシステムの最適化

```bash
# EFSマウント時のオプション
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

推奨マウントオプション：

- `rsize=1048576`: 読み取りバッファサイズ（1MB）
- `wsize=1048576`: 書き込みバッファサイズ（1MB）
- `hard`: ハードマウント（推奨）
- `timeo=600`: タイムアウト値（60秒）

## ネットワークの最適化

### VPC エンドポイントの活用

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

### セキュリティグループの最適化

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

### サブネット配置の最適化

```hcl
# terraform/network.tf
# 各AZにMount Targetを配置
resource "aws_efs_mount_target" "main" {
  count = length(var.availability_zones)
  
  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}
```

## コスト最適化

### Lambda関数のコスト削減

```hcl
# terraform/lambda.tf
resource "aws_lambda_function" "file_monitor" {
  # ...
  
  # 必要最小限のメモリを設定
  memory_size = 512
  
  # タイムアウトを適切に設定
  timeout = 30
  
  # 予約済み同時実行数を設定（オプション）
  reserved_concurrent_executions = 1
}
```

### Fargateのコスト削減

```hcl
# terraform/ecs.tf
resource "aws_ecs_service" "fargate" {
  # ...
  
  # Fargate Spotの活用
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

### EFSのコスト削減

```hcl
# terraform/efs.tf
resource "aws_efs_file_system" "main" {
  # ...
  
  # ライフサイクル管理を有効化
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
  
  lifecycle_policy {
    transition_to_primary_storage_class = "AFTER_1_ACCESS"
  }
}
```

### CloudWatch Logsのコスト削減

```hcl
# terraform/main.tf
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}-file-monitor"
  retention_in_days = 7  # ログ保持期間を短縮
}

resource "aws_cloudwatch_log_group" "fargate" {
  name              = "/ecs/${var.project_name}-fargate"
  retention_in_days = 7
}
```

## パフォーマンステスト

### Lambda関数の負荷テスト

```python
# tests/load_test_lambda.py
import boto3
import concurrent.futures
import time

lambda_client = boto3.client('lambda')

def invoke_lambda():
    """Lambda関数を呼び出し"""
    start = time.time()
    response = lambda_client.invoke(
        FunctionName='efs-mount-autoscaling-file-monitor',
        InvocationType='RequestResponse',
        Payload='{}'
    )
    duration = time.time() - start
    return duration, response['StatusCode']

def load_test(num_requests=100, max_workers=10):
    """負荷テストを実行"""
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

### EFSのスループットテスト

```bash
# EFSマウントポイントでのスループットテスト
# 書き込みテスト
dd if=/dev/zero of=/mnt/efs/testfile bs=1M count=1024 oflag=direct

# 読み取りテスト
dd if=/mnt/efs/testfile of=/dev/null bs=1M iflag=direct

# ランダムI/Oテスト
fio --name=random-write --ioengine=libaio --iodepth=32 \
    --rw=randwrite --bs=4k --direct=1 --size=1G \
    --numjobs=4 --runtime=60 --group_reporting \
    --directory=/mnt/efs
```

### Fargateタスクのベンチマーク

```python
# fargate/benchmark.py
import time
import os
from pathlib import Path

def benchmark_file_operations(directory, num_files=10000):
    """ファイル操作のベンチマーク"""
    
    # 書き込みテスト
    start = time.time()
    for i in range(num_files):
        with open(f"{directory}/test_{i}.txt", 'w') as f:
            f.write(f"Test data {i}\n")
    write_duration = time.time() - start
    
    # 読み取りテスト
    start = time.time()
    for i in range(num_files):
        with open(f"{directory}/test_{i}.txt", 'r') as f:
            _ = f.read()
    read_duration = time.time() - start
    
    # 削除テスト
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

## ベストプラクティス

1. **段階的な最適化**: 測定 → 分析 → 最適化 → 検証のサイクルを繰り返す
2. **ボトルネックの特定**: CloudWatch メトリクスで最も遅い部分を特定
3. **適切なリソース配分**: 過剰なリソースはコスト増、不足はパフォーマンス低下
4. **定期的な見直し**: ワークロードの変化に応じて設定を調整
5. **本番環境でのテスト**: 実際の負荷でパフォーマンスを検証

## 関連ドキュメント

- [デプロイメントガイド](DEPLOYMENT.md)
- [監視とアラート設定](MONITORING.md)
- [セキュリティベストプラクティス](SECURITY.md)
