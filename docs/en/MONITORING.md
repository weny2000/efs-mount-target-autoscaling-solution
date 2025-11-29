# Monitoring and Alerting Guide

This document explains monitoring and alerting configuration for the EFS Mount Target Auto-scaling System.

## Table of Contents

1. [Monitoring Overview](#monitoring-overview)
2. [CloudWatch Metrics](#cloudwatch-metrics)
3. [CloudWatch Alarms Configuration](#cloudwatch-alarms-configuration)
4. [Log Monitoring](#log-monitoring)
5. [Dashboard Creation](#dashboard-creation)
6. [Notification Setup](#notification-setup)
7. [Troubleshooting](#troubleshooting)

## Monitoring Overview

### Components to Monitor

This system monitors the following components:

- **Lambda Function**: File count monitoring and mount target creation
- **ECS/Fargate**: File processing tasks
- **EFS**: File system performance and storage
- **EventBridge**: Lambda function scheduled execution
- **VPC**: Network connectivity

### Importance of Monitoring

Proper monitoring enables:

- Understanding system health
- Identifying performance bottlenecks
- Early detection and response to issues
- Discovering cost optimization opportunities

## CloudWatch Metrics

### Lambda Function Metrics

#### Standard Metrics

```bash
# Lambda function invocation count
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# Lambda function error count
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# Lambda function duration
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Average,Maximum
```

#### Custom Metrics

Custom metrics sent from Lambda function:

- `FileCount`: Number of files detected
- `MountTargetsCreated`: Number of mount targets created
- `MountTargetsSkipped`: Number of mount targets skipped

```python
# Example of sending custom metrics from Lambda function
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


### ECS/Fargate Metrics

```bash
# CPU utilization
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ServiceName,Value=efs-mount-autoscaling-fargate-service \
               Name=ClusterName,Value=efs-mount-autoscaling-cluster \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 300 \
  --statistics Average,Maximum

# Memory utilization
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

### EFS Metrics

```bash
# Get EFS file system ID
EFS_ID=$(cd terraform && terraform output -raw efs_file_system_id)

# Data read bytes
aws cloudwatch get-metric-statistics \
  --namespace AWS/EFS \
  --metric-name DataReadIOBytes \
  --dimensions Name=FileSystemId,Value=$EFS_ID \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# Data write bytes
aws cloudwatch get-metric-statistics \
  --namespace AWS/EFS \
  --metric-name DataWriteIOBytes \
  --dimensions Name=FileSystemId,Value=$EFS_ID \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# Client connections
aws cloudwatch get-metric-statistics \
  --namespace AWS/EFS \
  --metric-name ClientConnections \
  --dimensions Name=FileSystemId,Value=$EFS_ID \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 300 \
  --statistics Average,Maximum
```

## CloudWatch Alarms Configuration

### Lambda Function Alarms

#### Error Rate Alarm

```bash
# Alarm when Lambda function error rate exceeds 5%
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

#### Duration Alarm

```bash
# Alarm when Lambda function duration exceeds 30 seconds
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

### ECS/Fargate Alarms

#### CPU Utilization Alarm

```bash
# Alarm when CPU utilization exceeds 80%
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

#### Memory Utilization Alarm

```bash
# Alarm when memory utilization exceeds 80%
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

### EFS Alarms

#### Throughput Alarm

```bash
EFS_ID=$(cd terraform && terraform output -raw efs_file_system_id)

# Alarm when EFS throughput exceeds threshold
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

## Log Monitoring

### Lambda Function Logs

#### Check Log Streams

```bash
# Display latest log streams
aws logs describe-log-streams \
  --log-group-name /aws/lambda/efs-mount-autoscaling-file-monitor \
  --order-by LastEventTime \
  --descending \
  --max-items 5

# Monitor logs in real-time
aws logs tail /aws/lambda/efs-mount-autoscaling-file-monitor --follow
```

#### Search Error Logs

```bash
# Search for error logs
aws logs filter-log-events \
  --log-group-name /aws/lambda/efs-mount-autoscaling-file-monitor \
  --filter-pattern "ERROR" \
  --start-time $(date -u -d '1 hour ago' +%s)000

# Search for specific error patterns
aws logs filter-log-events \
  --log-group-name /aws/lambda/efs-mount-autoscaling-file-monitor \
  --filter-pattern "MountTargetConflict" \
  --start-time $(date -u -d '1 hour ago' +%s)000
```

### Fargate Task Logs

```bash
# Monitor Fargate task logs in real-time
aws logs tail /ecs/efs-mount-autoscaling-fargate --follow

# Search for error logs
aws logs filter-log-events \
  --log-group-name /ecs/efs-mount-autoscaling-fargate \
  --filter-pattern "ERROR" \
  --start-time $(date -u -d '1 hour ago' +%s)000
```

### CloudWatch Logs Insights

#### Lambda Function Analysis Queries

```sql
-- Analyze error frequency
fields @timestamp, @message
| filter @message like /ERROR/
| stats count() by bin(5m)

-- Analyze execution time
fields @timestamp, @duration
| stats avg(@duration), max(@duration), min(@duration)

-- File count trends
fields @timestamp, @message
| filter @message like /File count:/
| parse @message "File count: *" as file_count
| stats avg(file_count) by bin(1h)
```

#### Fargate Task Analysis Queries

```sql
-- Task error analysis
fields @timestamp, @message
| filter @message like /ERROR/
| stats count() by bin(5m)

-- Processing time analysis
fields @timestamp, @message
| filter @message like /Processing completed/
| parse @message "Processing completed in * seconds" as duration
| stats avg(duration), max(duration) by bin(1h)
```

## Dashboard Creation

### Create CloudWatch Dashboard

```bash
# Create dashboard
aws cloudwatch put-dashboard \
  --dashboard-name efs-mount-autoscaling-dashboard \
  --dashboard-body file://dashboard.json
```

### Dashboard Definition (dashboard.json)

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

## Notification Setup

### Create SNS Topic

```bash
# Create SNS topic
aws sns create-topic \
  --name efs-mount-autoscaling-alerts

# Add email subscription
aws sns subscribe \
  --topic-arn arn:aws:sns:ap-northeast-1:123456789012:efs-mount-autoscaling-alerts \
  --protocol email \
  --notification-endpoint your-email@example.com

# Slack notification (via Lambda)
aws sns subscribe \
  --topic-arn arn:aws:sns:ap-northeast-1:123456789012:efs-mount-autoscaling-alerts \
  --protocol lambda \
  --notification-endpoint arn:aws:lambda:ap-northeast-1:123456789012:function:slack-notifier
```

### Customize Alarm Notifications

```python
# Example Lambda function for Slack notifications
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

## Troubleshooting

### Alarms Not Triggering

```bash
# Check alarm status
aws cloudwatch describe-alarms \
  --alarm-names efs-mount-autoscaling-lambda-error-rate

# Verify metric data exists
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=efs-mount-autoscaling-file-monitor \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum
```

### Logs Not Appearing

```bash
# Check if log group exists
aws logs describe-log-groups \
  --log-group-name-prefix /aws/lambda/efs-mount-autoscaling

# Verify Lambda function has write permissions to log group
aws lambda get-function \
  --function-name efs-mount-autoscaling-file-monitor \
  --query 'Configuration.Role'
```

### Metrics Not Updating

```bash
# Check if Lambda function is running
aws lambda get-function \
  --function-name efs-mount-autoscaling-file-monitor

# Verify EventBridge rule is enabled
aws events describe-rule \
  --name efs-mount-autoscaling-lambda-schedule
```

## Best Practices

1. **Set Multiple Evaluation Periods**: Prevent false positives from temporary spikes
2. **Configure Appropriate Thresholds**: Adjust based on actual production load
3. **Staged Alerting**: Set up two-tier alerts (Warning and Critical)
4. **Regular Reviews**: Periodically review and optimize alarm settings
5. **Log Retention Period**: Balance cost and requirements

## Related Documents

- [Deployment Guide](DEPLOYMENT.md)
- [Performance Tuning](PERFORMANCE.md)
- [Security Best Practices](SECURITY.md)
