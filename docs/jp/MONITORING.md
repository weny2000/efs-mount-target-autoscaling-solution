# 監視とアラート設定ガイド

このドキュメントでは、EFS Mount Target Auto-scaling Systemの監視とアラート設定について説明します。

## 目次

1. [監視の概要](#監視の概要)
2. [CloudWatch メトリクス](#cloudwatch-メトリクス)
3. [CloudWatch アラーム設定](#cloudwatch-アラーム設定)
4. [ログ監視](#ログ監視)
5. [ダッシュボード作成](#ダッシュボード作成)
6. [通知設定](#通知設定)
7. [トラブルシューティング](#トラブルシューティング)

## 監視の概要

### 監視対象コンポーネント

このシステムでは以下のコンポーネントを監視します：

- **Lambda関数**: ファイル数監視とMount Target作成
- **ECS/Fargate**: ファイル処理タスク
- **EFS**: ファイルシステムのパフォーマンスとストレージ
- **EventBridge**: Lambda関数のスケジュール実行
- **VPC**: ネットワーク接続性

### 監視の重要性

適切な監視により以下が可能になります：

- システムの健全性の把握
- パフォーマンスボトルネックの特定
- 問題の早期検出と対応
- コスト最適化の機会の発見

## CloudWatch メトリクス

### Lambda関数のメトリクス

#### 標準メトリクス

```bash
# Lambda関数の実行回数
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# Lambda関数のエラー数
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# Lambda関数の実行時間
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Average,Maximum
```

#### カスタムメトリクス

Lambda関数から送信されるカスタムメトリクス：

- `FileCount`: 検出されたファイル数
- `MountTargetsCreated`: 作成されたMount Target数
- `MountTargetsSkipped`: スキップされたMount Target数

```python
# Lambda関数内でのカスタムメトリクス送信例
import boto3

cloudwatch = boto3.client('cloudwatch')

cloudwatch.put_metric_data(
    Namespace='EFSMountAutoscaling',
    MetricData=[
        {
            'MetricName': 'FileCount',
            'Value': file_count,
            'Unit': 'Count',
            'Timestamp': datetime.utcnow()
        },
        {
            'MetricName': 'MountTargetsCreated',
            'Value': created_count,
            'Unit': 'Count',
            'Timestamp': datetime.utcnow()
        }
    ]
)
```

### ECS/Fargate のメトリクス

```bash
# CPU使用率
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ServiceName,Value=efs-mount-autoscaling-fargate-service \
               Name=ClusterName,Value=efs-mount-autoscaling-cluster \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 300 \
  --statistics Average,Maximum

# メモリ使用率
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name MemoryUtilization \
  --dimensions Name=ServiceName,Value=efs-mount-autoscaling-fargate-service \
               Name=ClusterName,Value=efs-mount-autoscaling-cluster \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 300 \
  --statistics Average,Maximum
```

### EFS のメトリクス

```bash
# EFSファイルシステムIDを取得
EFS_ID=$(cd terraform && terraform output -raw efs_file_system_id)

# データ読み取りバイト数
aws cloudwatch get-metric-statistics \
  --namespace AWS/EFS \
  --metric-name DataReadIOBytes \
  --dimensions Name=FileSystemId,Value=$EFS_ID \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# データ書き込みバイト数
aws cloudwatch get-metric-statistics \
  --namespace AWS/EFS \
  --metric-name DataWriteIOBytes \
  --dimensions Name=FileSystemId,Value=$EFS_ID \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# クライアント接続数
aws cloudwatch get-metric-statistics \
  --namespace AWS/EFS \
  --metric-name ClientConnections \
  --dimensions Name=FileSystemId,Value=$EFS_ID \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 300 \
  --statistics Average,Maximum
```

## CloudWatch アラーム設定

### Lambda関数のアラーム

#### エラー率アラーム

```bash
# Lambda関数のエラー率が5%を超えた場合にアラーム
aws cloudwatch put-metric-alarm \
  --alarm-name efs-mount-autoscaling-lambda-error-rate \
  --alarm-description "Lambda function error rate exceeds 5%" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --alarm-actions arn:aws:sns:ap-northeast-1:123456789012:efs-mount-autoscaling-alerts
```

#### 実行時間アラーム

```bash
# Lambda関数の実行時間が30秒を超えた場合にアラーム
aws cloudwatch put-metric-alarm \
  --alarm-name efs-mount-autoscaling-lambda-duration \
  --alarm-description "Lambda function duration exceeds 30 seconds" \
  --metric-name Duration \
  --namespace AWS/Lambda \
  --statistic Average \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 30000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --alarm-actions arn:aws:sns:ap-northeast-1:123456789012:efs-mount-autoscaling-alerts
```

### ECS/Fargate のアラーム

#### CPU使用率アラーム

```bash
# CPU使用率が80%を超えた場合にアラーム
aws cloudwatch put-metric-alarm \
  --alarm-name efs-mount-autoscaling-fargate-cpu \
  --alarm-description "Fargate CPU utilization exceeds 80%" \
  --metric-name CPUUtilization \
  --namespace AWS/ECS \
  --statistic Average \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=ServiceName,Value=efs-mount-autoscaling-fargate-service \
               Name=ClusterName,Value=efs-mount-autoscaling-cluster \
  --alarm-actions arn:aws:sns:ap-northeast-1:123456789012:efs-mount-autoscaling-alerts
```

#### メモリ使用率アラーム

```bash
# メモリ使用率が80%を超えた場合にアラーム
aws cloudwatch put-metric-alarm \
  --alarm-name efs-mount-autoscaling-fargate-memory \
  --alarm-description "Fargate memory utilization exceeds 80%" \
  --metric-name MemoryUtilization \
  --namespace AWS/ECS \
  --statistic Average \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=ServiceName,Value=efs-mount-autoscaling-fargate-service \
               Name=ClusterName,Value=efs-mount-autoscaling-cluster \
  --alarm-actions arn:aws:sns:ap-northeast-1:123456789012:efs-mount-autoscaling-alerts
```

### EFS のアラーム

#### スループットアラーム

```bash
EFS_ID=$(cd terraform && terraform output -raw efs_file_system_id)

# EFSスループットが閾値を超えた場合にアラーム
aws cloudwatch put-metric-alarm \
  --alarm-name efs-mount-autoscaling-efs-throughput \
  --alarm-description "EFS throughput exceeds threshold" \
  --metric-name TotalIOBytes \
  --namespace AWS/EFS \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 1073741824 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=FileSystemId,Value=$EFS_ID \
  --alarm-actions arn:aws:sns:ap-northeast-1:123456789012:efs-mount-autoscaling-alerts
```

## ログ監視

### Lambda関数のログ

#### ログストリームの確認

```bash
# 最新のログストリームを表示
aws logs describe-log-streams \
  --log-group-name /aws/lambda/efs-mount-autoscaling-file-monitor \
  --order-by LastEventTime \
  --descending \
  --max-items 5

# ログをリアルタイムで監視
aws logs tail /aws/lambda/efs-mount-autoscaling-file-monitor --follow
```

#### エラーログの検索

```bash
# エラーログを検索
aws logs filter-log-events \
  --log-group-name /aws/lambda/efs-mount-autoscaling-file-monitor \
  --filter-pattern "ERROR" \
  --start-time $(date -u -d '1 hour ago' +%s)000

# 特定のエラーパターンを検索
aws logs filter-log-events \
  --log-group-name /aws/lambda/efs-mount-autoscaling-file-monitor \
  --filter-pattern "MountTargetConflict" \
  --start-time $(date -u -d '1 hour ago' +%s)000
```

### Fargate タスクのログ

```bash
# Fargateタスクのログをリアルタイムで監視
aws logs tail /ecs/efs-mount-autoscaling-fargate --follow

# エラーログを検索
aws logs filter-log-events \
  --log-group-name /ecs/efs-mount-autoscaling-fargate \
  --filter-pattern "ERROR" \
  --start-time $(date -u -d '1 hour ago' +%s)000
```

### CloudWatch Logs Insights

#### Lambda関数の分析クエリ

```sql
-- エラー発生頻度の分析
fields @timestamp, @message
| filter @message like /ERROR/
| stats count() by bin(5m)

-- 実行時間の分析
fields @timestamp, @duration
| stats avg(@duration), max(@duration), min(@duration)

-- ファイル数の推移
fields @timestamp, @message
| filter @message like /File count:/
| parse @message "File count: *" as file_count
| stats avg(file_count) by bin(1h)
```

#### Fargate タスクの分析クエリ

```sql
-- タスクのエラー分析
fields @timestamp, @message
| filter @message like /ERROR/
| stats count() by bin(5m)

-- 処理時間の分析
fields @timestamp, @message
| filter @message like /Processing completed/
| parse @message "Processing completed in * seconds" as duration
| stats avg(duration), max(duration) by bin(1h)
```

## ダッシュボード作成

### CloudWatch ダッシュボードの作成

```bash
# ダッシュボードの作成
aws cloudwatch put-dashboard \
  --dashboard-name efs-mount-autoscaling-dashboard \
  --dashboard-body file://dashboard.json
```

### ダッシュボード定義 (dashboard.json)

```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/Lambda", "Invocations", {"stat": "Sum", "label": "Lambda Invocations"}],
          [".", "Errors", {"stat": "Sum", "label": "Lambda Errors"}]
        ],
        "period": 300,
        "stat": "Sum",
        "region": "ap-northeast-1",
        "title": "Lambda Function Metrics",
        "yAxis": {
          "left": {
            "min": 0
          }
        }
      }
    },
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/ECS", "CPUUtilization", {"stat": "Average"}],
          [".", "MemoryUtilization", {"stat": "Average"}]
        ],
        "period": 300,
        "stat": "Average",
        "region": "ap-northeast-1",
        "title": "Fargate Resource Utilization",
        "yAxis": {
          "left": {
            "min": 0,
            "max": 100
          }
        }
      }
    },
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/EFS", "DataReadIOBytes", {"stat": "Sum"}],
          [".", "DataWriteIOBytes", {"stat": "Sum"}]
        ],
        "period": 3600,
        "stat": "Sum",
        "region": "ap-northeast-1",
        "title": "EFS Throughput",
        "yAxis": {
          "left": {
            "min": 0
          }
        }
      }
    },
    {
      "type": "log",
      "properties": {
        "query": "SOURCE '/aws/lambda/efs-mount-autoscaling-file-monitor'\n| fields @timestamp, @message\n| filter @message like /ERROR/\n| sort @timestamp desc\n| limit 20",
        "region": "ap-northeast-1",
        "title": "Recent Lambda Errors"
      }
    }
  ]
}
```

## 通知設定

### SNS トピックの作成

```bash
# SNSトピックを作成
aws sns create-topic \
  --name efs-mount-autoscaling-alerts

# メールサブスクリプションを追加
aws sns subscribe \
  --topic-arn arn:aws:sns:ap-northeast-1:123456789012:efs-mount-autoscaling-alerts \
  --protocol email \
  --notification-endpoint your-email@example.com

# Slackへの通知（Lambda経由）
aws sns subscribe \
  --topic-arn arn:aws:sns:ap-northeast-1:123456789012:efs-mount-autoscaling-alerts \
  --protocol lambda \
  --notification-endpoint arn:aws:lambda:ap-northeast-1:123456789012:function:slack-notifier
```

### アラーム通知のカスタマイズ

```python
# Slack通知用Lambda関数の例
import json
import urllib3
import os

http = urllib3.PoolManager()

def lambda_handler(event, context):
    message = json.loads(event['Records'][0]['Sns']['Message'])
    
    alarm_name = message['AlarmName']
    new_state = message['NewStateValue']
    reason = message['NewStateReason']
    
    slack_message = {
        'text': f"🚨 CloudWatch Alarm: {alarm_name}",
        'attachments': [{
            'color': 'danger' if new_state == 'ALARM' else 'good',
            'fields': [
                {'title': 'State', 'value': new_state, 'short': True},
                {'title': 'Reason', 'value': reason, 'short': False}
            ]
        }]
    }
    
    encoded_msg = json.dumps(slack_message).encode('utf-8')
    resp = http.request('POST', os.environ['SLACK_WEBHOOK_URL'], body=encoded_msg)
    
    return {
        'statusCode': 200,
        'body': json.dumps('Notification sent')
    }
```

## トラブルシューティング

### アラームが発火しない

```bash
# アラームの状態を確認
aws cloudwatch describe-alarms \
  --alarm-names efs-mount-autoscaling-lambda-error-rate

# メトリクスデータが存在するか確認
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum
```

### ログが表示されない

```bash
# ロググループが存在するか確認
aws logs describe-log-groups \
  --log-group-name-prefix /aws/lambda/efs-mount-autoscaling

# Lambda関数のロググループへの書き込み権限を確認
aws lambda get-function \
  --function-name efs-mount-autoscaling-file-monitor \
  --query 'Configuration.Role'
```

### メトリクスが更新されない

```bash
# Lambda関数が実行されているか確認
aws lambda get-function \
  --function-name efs-mount-autoscaling-file-monitor

# EventBridgeルールが有効か確認
aws events describe-rule \
  --name efs-mount-autoscaling-lambda-schedule
```

## ベストプラクティス

1. **複数の評価期間を設定**: 一時的なスパイクによる誤検知を防ぐ
2. **適切な閾値を設定**: 本番環境の実際の負荷に基づいて調整
3. **段階的なアラート**: Warning と Critical の2段階でアラートを設定
4. **定期的なレビュー**: アラーム設定を定期的に見直し、最適化
5. **ログの保持期間**: コストと要件のバランスを考慮して設定

## 関連ドキュメント

- [デプロイメントガイド](DEPLOYMENT.md)
- [パフォーマンスチューニング](PERFORMANCE.md)
- [セキュリティベストプラクティス](SECURITY.md)
