# EFS Mount Target Auto-scaling System - Architecture Documentation

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Diagrams](#architecture-diagrams)
3. [Component Details](#component-details)
4. [Data Flow](#data-flow)
5. [Scaling Mechanism](#scaling-mechanism)
6. [Load Balancing Strategy](#load-balancing-strategy)
7. [Security Architecture](#security-architecture)
8. [Availability and Fault Tolerance](#availability-and-fault-tolerance)

## System Overview

### Problem Statement

When operating large-scale file read/write services on AWS Fargate, excessive file counts in a single folder cause the following issues:

- **Degraded file read performance**: Concentrated access to a single EFS Mount Target
- **Network bottleneck**: Bandwidth limitations of a single ENI (Elastic Network Interface)
- **Scalability constraints**: Horizontal scaling doesn't improve I/O performance

### Solution

This system solves these challenges with three main strategies:

1. **Auto-scaling**: Automatically creates new Mount Targets when file count exceeds threshold
2. **Network-level load balancing**: Distributes network bandwidth using multiple Mount Targets (ENIs)
3. **Hash-based routing**: Uses file path hash values to evenly distribute access


## Architecture Diagrams

### Overall Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AWS Cloud Environment                                │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Serverless Automation Layer                         │ │
│  │                                                                          │ │
│  │  ┌──────────────────┐                                                   │ │
│  │  │  EventBridge     │                                                   │ │
│  │  │  Rule            │                                                   │ │
│  │  │  (Every 5 min)   │                                                   │ │
│  │  └────────┬─────────┘                                                   │ │
│  │           │                                                              │ │
│  │           ▼                                                              │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │  Lambda Function (file_monitor.py)                               │  │ │
│  │  │  ┌────────────────────────────────────────────────────────────┐  │  │ │
│  │  │  │  1. Mount EFS & Count files                               │  │  │ │
│  │  │  │  2. Threshold check (Default: 100,000 files)              │  │  │ │
│  │  │  │  3. Search available subnets                              │  │  │ │
│  │  │  │  4. Create new Mount Target                               │  │  │ │
│  │  │  │  5. Update SSM Parameter Store                            │  │  │ │
│  │  │  │  6. Force ECS Service deployment                          │  │  │ │
│  │  │  └────────────────────────────────────────────────────────────┘  │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│                                    │                                          │
│                                    ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Configuration Management Layer                       │ │
│  │                                                                          │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │  SSM Parameter Store                                             │  │ │
│  │  │  Parameter: /efs-mount-autoscaling/mount-targets                 │  │ │
│  │  │  ┌────────────────────────────────────────────────────────────┐  │  │ │
│  │  │  │  {                                                           │  │  │ │
│  │  │  │    "mount_targets": [                                        │  │  │ │
│  │  │  │      {                                                       │  │  │ │
│  │  │  │        "mount_target_id": "fsmt-12345678",                   │  │  │ │
│  │  │  │        "ip_address": "10.0.1.100",                           │  │  │ │
│  │  │  │        "availability_zone": "ap-northeast-1a",               │  │  │ │
│  │  │  │        "subnet_id": "subnet-12345678"                        │  │  │ │
│  │  │  │      },                                                      │  │  │ │
│  │  │  │      ...                                                     │  │  │ │
│  │  │  │    ]                                                         │  │  │ │
│  │  │  │  }                                                           │  │  │ │
│  │  │  └────────────────────────────────────────────────────────────┘  │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│                                    │                                          │
│                                    ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Application Layer                                    │ │
│  │                                                                          │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │  ECS Cluster                                                     │  │ │
│  │  │  ┌────────────────────────────────────────────────────────────┐  │  │ │
│  │  │  │  Fargate Tasks (app.py)                                    │  │  │ │
│  │  │  │  ┌──────────────────────────────────────────────────────┐  │  │  │ │
│  │  │  │  │  Startup Process:                                    │  │  │  │ │
│  │  │  │  │  1. Retrieve config from SSM Parameter Store        │  │  │  │ │
│  │  │  │  │  2. Mount all Mount Targets via NFS                 │  │  │  │ │
│  │  │  │  │     /mnt/efs-0, /mnt/efs-1, /mnt/efs-2, ...         │  │  │  │ │
│  │  │  │  │                                                      │  │  │  │ │
│  │  │  │  │  File Access Process:                               │  │  │  │ │
│  │  │  │  │  1. Calculate hash value of file path               │  │  │  │ │
│  │  │  │  │  2. hash % Mount Target count = index               │  │  │  │ │
│  │  │  │  │  3. Access via selected Mount Target                │  │  │  │ │
│  │  │  │  └──────────────────────────────────────────────────────┘  │  │  │ │
│  │  │  └────────────────────────────────────────────────────────────┘  │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│                                    │                                          │
│                                    ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Storage Layer                                        │ │
│  │                                                                          │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │  EFS File System (fs-xxxxxxxx)                                   │  │ │
│  │  │                                                                    │  │ │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │  │ │
│  │  │  │ Mount       │  │ Mount       │  │ Mount       │             │  │ │
│  │  │  │ Target 1    │  │ Target 2    │  │ Target 3    │             │  │ │
│  │  │  │             │  │             │  │             │             │  │ │
│  │  │  │ ENI         │  │ ENI         │  │ ENI         │             │  │ │
│  │  │  │ 10.0.1.100  │  │ 10.0.2.100  │  │ 10.0.3.100  │             │  │ │
│  │  │  │             │  │             │  │             │             │  │ │
│  │  │  │ AZ-1a       │  │ AZ-1c       │  │ AZ-1d       │             │  │ │
│  │  │  └─────────────┘  └─────────────┘  └─────────────┘             │  │ │
│  │  │                                                                    │  │ │
│  │  │  Shared File System: /data/                                       │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```


### Network Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  VPC (10.0.0.0/16)                                                           │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Availability Zone 1a                                                  │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │  Private Subnet (10.0.1.0/24)                                    │  │  │
│  │  │                                                                   │  │  │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │  │  │
│  │  │  │ Fargate Task │  │ Lambda       │  │ EFS Mount    │          │  │  │
│  │  │  │              │  │ Function     │  │ Target 1     │          │  │  │
│  │  │  │ ENI          │  │ ENI          │  │ ENI          │          │  │  │
│  │  │  └──────────────┘  └──────────────┘  └──────────────┘          │  │  │
│  │  │         │                 │                 │                    │  │  │
│  │  │         └─────────────────┴─────────────────┘                    │  │  │
│  │  │                           │                                       │  │  │
│  │  │                  Security Groups                                 │  │  │
│  │  │                  - Fargate SG: Port 2049 → EFS                   │  │  │
│  │  │                  - Lambda SG: Port 2049 → EFS                    │  │  │
│  │  │                  - EFS SG: Port 2049 ← Fargate, Lambda           │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Availability Zone 1c                                                  │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │  Private Subnet (10.0.2.0/24)                                    │  │  │
│  │  │                                                                   │  │  │
│  │  │  ┌──────────────┐  ┌──────────────┐                             │  │  │
│  │  │  │ Fargate Task │  │ EFS Mount    │                             │  │  │
│  │  │  │              │  │ Target 2     │                             │  │  │
│  │  │  │ ENI          │  │ ENI          │                             │  │  │
│  │  │  └──────────────┘  └──────────────┘                             │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Availability Zone 1d                                                  │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │  Private Subnet (10.0.3.0/24)                                    │  │  │
│  │  │                                                                   │  │  │
│  │  │  ┌──────────────┐  ┌──────────────┐                             │  │  │
│  │  │  │ Fargate Task │  │ EFS Mount    │                             │  │  │
│  │  │  │              │  │ Target 3     │                             │  │  │
│  │  │  │ ENI          │  │ ENI          │                             │  │  │
│  │  │  └──────────────┘  └──────────────┘                             │  │  │
│  │  │                    (Auto-created)                                │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```


## Component Details

### 1. EventBridge Rule

**Role**: Trigger to periodically execute Lambda function

**Configuration**:
- Schedule expression: `rate(5 minutes)`
- Target: Lambda function (file_monitor)
- Execution interval: Every 5 minutes (customizable)

**Operation**:
1. Fires events according to configured schedule
2. Invokes Lambda function asynchronously
3. Records execution history in CloudWatch Logs

---

### 2. Lambda Function (file_monitor.py)

**Role**: Monitors file count and automatically creates Mount Targets when needed

**Key Functions**:

#### 2.1 File Count
```python
def count_files_in_directory(directory_path):
    # Count files from EFS mount point
    # Exclude directories, count only files
```

**Property**: File count accuracy
- For any directory, count result matches actual file count

#### 2.2 Threshold Check
```python
def check_threshold_exceeded(file_count, threshold):
    # Check if file count exceeds threshold
    return file_count > threshold
```

**Property**: Threshold check consistency
- For any file count and threshold combination, returns True only when file_count > threshold


#### 2.3 Mount Target Creation
```python
def create_mount_target(file_system_id, subnet_id, security_group_id):
    # 1. Call AWS EFS CreateMountTarget API
    # 2. Wait for Mount Target creation completion (polling)
    # 3. Return created Mount Target information
```

**Features**:
- Maximum 5 minutes polling wait
- Status check every 10 seconds
- Proper error handling

#### 2.4 SSM Parameter Store Update
```python
def update_ssm_parameter(parameter_name, mount_targets_json):
    # Save Mount Target information in JSON format to SSM
```

**Property**: SSM Parameter Store update consistency
- For any Mount Target list, save→retrieve round-trip returns same data

#### 2.5 ECS Service Update
```python
def trigger_ecs_service_deployment(cluster_name, service_name):
    # Execute rolling update with forceNewDeployment=True
```

**Environment Variables**:
| Variable | Description | Default Value |
|----------|-------------|---------------|
| `TARGET_DIRECTORY` | Monitored directory | `/data` |
| `FILE_COUNT_THRESHOLD` | File count threshold | `100000` |
| `EFS_FILE_SYSTEM_ID` | EFS file system ID | - |
| `VPC_ID` | VPC ID | - |
| `SSM_PARAMETER_NAME` | SSM parameter name | `/efs-mount-autoscaling/mount-targets` |
| `ECS_CLUSTER_NAME` | ECS cluster name | - |
| `ECS_SERVICE_NAME` | ECS service name | - |

**IAM Permissions**:
- `elasticfilesystem:DescribeMountTargets`
- `elasticfilesystem:CreateMountTarget`
- `elasticfilesystem:DescribeFileSystems`
- `ssm:PutParameter`
- `ssm:GetParameter`
- `ecs:UpdateService`
- `ecs:DescribeServices`
- `ec2:DescribeSubnets`
- `ec2:CreateNetworkInterface`
- `ec2:DeleteNetworkInterface`


---

### 3. SSM Parameter Store

**Role**: Store Mount Target information and share between Lambda function and Fargate service

**Parameter Name**: `/efs-mount-autoscaling/mount-targets`

**Data Format**:
```json
{
  "mount_targets": [
    {
      "mount_target_id": "fsmt-12345678",
      "ip_address": "10.0.1.100",
      "availability_zone": "ap-northeast-1a",
      "subnet_id": "subnet-12345678"
    },
    {
      "mount_target_id": "fsmt-87654321",
      "ip_address": "10.0.2.100",
      "availability_zone": "ap-northeast-1c",
      "subnet_id": "subnet-87654321"
    }
  ]
}
```

**Access Patterns**:
- **Write**: Lambda function (when creating new Mount Target)
- **Read**: Fargate service (at startup)

---

### 4. Fargate Service (app.py)

**Role**: Mount multiple Mount Targets and distribute file access using hash-based routing

**Key Functions**:

#### 4.1 Initialization
```python
def initialize():
    # 1. Retrieve latest Mount Target information from SSM Parameter Store
    mount_targets = get_mount_targets_from_ssm()
    
    # 2. Mount each Mount Target via NFS
    successfully_mounted = mount_nfs_targets(mount_targets)
    
    return mount_targets, successfully_mounted
```

**Mount Points**:
- `/mnt/efs-0`: Mount Target 1
- `/mnt/efs-1`: Mount Target 2
- `/mnt/efs-2`: Mount Target 3
- ...


#### 4.2 Hash-based Routing
```python
def get_file_path(original_path, mount_targets):
    # 1. Calculate hash value of file path (SHA256)
    hash_value = hashlib.sha256(original_path.encode('utf-8')).hexdigest()
    hash_int = int(hash_value, 16)
    
    # 2. Modulo operation with Mount Target count
    index = hash_int % len(mount_targets)
    
    # 3. Use mount point of selected Mount Target
    mount_point = f"/mnt/efs-{index}"
    complete_path = os.path.join(mount_point, original_path)
    
    return complete_path
```

**Property**: Hash-based routing consistency
- For any file path, same file path always returns same Mount Target index

**Property**: Hash-based routing distribution
- For any set of file paths, distribution to each Mount Target is within acceptable range

#### 4.3 File Access API
```python
# Read
def read_file(original_path, mount_targets, mode='r', encoding='utf-8'):
    complete_path = get_file_path(original_path, mount_targets)
    with open(complete_path, mode, encoding=encoding) as f:
        return f.read()

# Write
def write_file(original_path, content, mount_targets, mode='w', encoding='utf-8'):
    complete_path = get_file_path(original_path, mount_targets)
    with open(complete_path, mode, encoding=encoding) as f:
        f.write(content)
    return complete_path

# Append
def append_file(original_path, content, mount_targets, encoding='utf-8'):
    # ...

# Exists check
def file_exists(original_path, mount_targets):
    # ...

# Delete
def delete_file(original_path, mount_targets):
    # ...
```

**Environment Variables**:
| Variable | Description |
|----------|-------------|
| `SSM_PARAMETER_NAME` | SSM parameter name |
| `EFS_FILE_SYSTEM_ID` | EFS file system ID |

**IAM Permissions**:
- `ssm:GetParameter`
- `elasticfilesystem:DescribeMountTargets`
- `elasticfilesystem:DescribeFileSystems`

**Error Handling**:
- SSM retrieval failure: Use default configuration
- Mount failure: Skip failed Mount Target and use other Mount Targets

**Property**: Fallback on mount failure
- For any Mount Target list, if some Mount Targets fail to mount but at least one is available, service starts


---

### 5. EFS File System

**Role**: Provide large-scale file storage

**Configuration**:
- **Performance Mode**: General Purpose (small scale) or Max I/O (large scale)
- **Throughput Mode**: Bursting (variable load) or Provisioned (predictable load)
- **Encryption**: Enabled (using AWS KMS)
- **Encryption in transit**: TLS enabled

**Mount Targets**:
- One Mount Target per Availability Zone
- Each Mount Target has dedicated ENI (Elastic Network Interface)
- ENI provides independent network bandwidth

**Scaling Characteristics**:
- Initial state: 2 Mount Targets (2 AZs)
- Auto-expansion: When file count exceeds threshold, add Mount Target in new AZ
- Maximum: Can expand up to number of AZs in VPC

---


## Data Flow

### 1. Normal Operation Data Flow

```
┌─────────────┐
│  Fargate    │
│  Task       │
└──────┬──────┘
       │
       │ 1. File access request
       │    file_path = "user/12345/document.pdf"
       │
       ▼
┌──────────────────────────────────────────┐
│  Hash-based Routing                      │
│  hash = SHA256(file_path)                │
│  index = hash % num_mount_targets        │
│  → index = 1                             │
└──────┬───────────────────────────────────┘
       │
       │ 2. Access via selected Mount Target
       │    /mnt/efs-1/user/12345/document.pdf
       │
       ▼
┌──────────────────────────────────────────┐
│  Mount Target 2 (ENI: 10.0.2.100)        │
│  Availability Zone: ap-northeast-1c      │
└──────┬───────────────────────────────────┘
       │
       │ 3. Access via NFS protocol
       │
       ▼
┌──────────────────────────────────────────┐
│  EFS File System                         │
│  /data/user/12345/document.pdf           │
└──────────────────────────────────────────┘
```


### 2. Scaling Data Flow

```
┌─────────────┐
│ EventBridge │
│ (Every 5min)│
└──────┬──────┘
       │
       │ 1. Execute Lambda function
       │
       ▼
┌──────────────────────────────────────────┐
│  Lambda Function                         │
│  ┌────────────────────────────────────┐  │
│  │ Step 1: Count files                │  │
│  │ count = 150,000 files              │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ Step 2: Threshold check            │  │
│  │ 150,000 > 100,000 → TRUE           │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ Step 3: Search available subnets   │  │
│  │ Existing: AZ-1a, AZ-1c             │  │
│  │ Available: AZ-1d                   │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ Step 4: Create Mount Target        │  │
│  │ CreateMountTarget(AZ-1d)           │  │
│  │ → fsmt-new123                      │  │
│  └────────────────────────────────────┘  │
└──────┬───────────────────────────────────┘
       │
       │ 2. Update SSM Parameter Store
       │
       ▼
┌──────────────────────────────────────────┐
│  SSM Parameter Store                     │
│  mount_targets: [                        │
│    {id: fsmt-12345, ip: 10.0.1.100},     │
│    {id: fsmt-67890, ip: 10.0.2.100},     │
│    {id: fsmt-new123, ip: 10.0.3.100}     │ ← Newly added
│  ]                                       │
└──────┬───────────────────────────────────┘
       │
       │ 3. Force ECS Service deployment
       │
       ▼
┌──────────────────────────────────────────┐
│  ECS Service                             │
│  ┌────────────────────────────────────┐  │
│  │ Start rolling update               │  │
│  │ 1. Launch new tasks                │  │
│  │ 2. New tasks retrieve config       │  │
│  │ 3. Mount 3 Mount Targets           │  │
│  │ 4. Stop old tasks                  │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

### 3. File Access Load Balancing

```
Concurrent access from multiple Fargate tasks:

Task 1: file_a.txt → hash % 3 = 0 → Mount Target 1 (10.0.1.100)
Task 2: file_b.txt → hash % 3 = 1 → Mount Target 2 (10.0.2.100)
Task 3: file_c.txt → hash % 3 = 2 → Mount Target 3 (10.0.3.100)
Task 4: file_d.txt → hash % 3 = 0 → Mount Target 1 (10.0.1.100)
Task 5: file_e.txt → hash % 3 = 1 → Mount Target 2 (10.0.2.100)

Result: Network traffic distributed across 3 ENIs
```



## Scaling Mechanism

### Scaling Trigger

**Condition**:
```
File count > FILE_COUNT_THRESHOLD
```

**Default Threshold**: 100,000 files

**Check Frequency**: Every 5 minutes (EventBridge schedule)

### Scaling Process

#### Phase 1: Detection
```
1. EventBridge executes Lambda function
2. Lambda function mounts EFS
3. Count files in target directory
4. Compare with threshold
```

#### Phase 2: Evaluation
```
IF file count > threshold THEN
  1. Get existing Mount Targets
  2. Get all subnets in VPC
  3. Identify subnets without Mount Targets
  
  IF available subnets exist THEN
    → Proceed to Phase 3
  ELSE
    → Log warning and exit
  END IF
END IF
```

#### Phase 3: Execution
```
1. Create new Mount Target
   - Call CreateMountTarget API
   - Wait up to 5 minutes for completion
   
2. Update SSM Parameter Store
   - Retrieve all Mount Target list
   - Convert to JSON format
   - Save to SSM
   
3. Update ECS Service
   - Call UpdateService API (forceNewDeployment=True)
   - Rolling update starts
```

#### Phase 4: Application
```
1. ECS launches new Fargate tasks
2. New tasks retrieve latest config from SSM Parameter Store
3. New tasks mount all Mount Targets (including new one)
4. Once new tasks are healthy, stop old tasks
5. All tasks operate with new configuration
```

### Scaling Constraints

**Maximum Mount Targets**: Number of Availability Zones in VPC

**Examples**: 
- ap-northeast-1 region: Maximum 3 (1a, 1c, 1d)
- us-east-1 region: Maximum 6 (1a, 1b, 1c, 1d, 1e, 1f)

**Scale Down**: 
- Automatic scale down not implemented in current version
- Manual Mount Target deletion required

### Scaling Timeline

```
T+0:00  EventBridge executes Lambda function
T+0:05  File count complete
T+0:10  Threshold exceeded detected
T+0:15  Available subnets identified
T+0:20  Mount Target creation starts
T+2:00  Mount Target creation complete (average 2 min)
T+2:05  SSM Parameter Store update complete
T+2:10  ECS Service force deployment starts
T+3:00  New Fargate task launch starts
T+3:30  New task mounts all Mount Targets
T+4:00  New task healthy
T+4:30  Old task stops
T+5:00  Rolling update complete

Total time: Approximately 5 minutes
```



## Load Balancing Strategy

### Hash-based Routing Principles

#### Algorithm

```python
def select_mount_target(file_path, mount_targets):
    # 1. Calculate hash value from file path
    hash_value = SHA256(file_path)
    
    # 2. Convert hash value to integer
    hash_int = int(hash_value, 16)
    
    # 3. Modulo operation with Mount Target count
    index = hash_int % len(mount_targets)
    
    # 4. Return selected Mount Target
    return mount_targets[index]
```

#### Characteristics

**Consistency**:
- Same file path always routed to same Mount Target
- File read/write/delete operations go through same Mount Target
- Improved cache locality

**Distribution**:
- SHA256 hash function's uniform distribution property distributes files evenly across Mount Targets
- Theoretically, access to each Mount Target is 1/N (N = Mount Target count)

**Scalability**:
- Adding Mount Targets doesn't affect routing of most existing files
- Files requiring redistribution: approximately 1/N (N = new Mount Target count)

### Load Balancing Effects

#### Scenario 1: Single Mount Target (Initial State)

```
All access → Mount Target 1 (ENI 1)
                  ↓
              Bottleneck
              - ENI bandwidth limit
              - Single point of failure
```

**Issues**:
- ENI bandwidth limit (max 10 Gbps)
- Increased latency
- Single point of failure

#### Scenario 2: 3 Mount Targets (After Scaling)

```
File A → Mount Target 1 (ENI 1) → 33% of traffic
File B → Mount Target 2 (ENI 2) → 33% of traffic
File C → Mount Target 3 (ENI 3) → 33% of traffic
```

**Improvements**:
- Total bandwidth: Max 30 Gbps (3 × 10 Gbps)
- Reduced latency
- Improved redundancy

### Performance Metrics

#### Throughput

**Single Mount Target**:
- Read: Max 3 GB/s
- Write: Max 1 GB/s

**3 Mount Targets**:
- Read: Max 9 GB/s (3x)
- Write: Max 3 GB/s (3x)

#### IOPS

**Single Mount Target**:
- Read: Max 35,000 IOPS
- Write: Max 7,000 IOPS

**3 Mount Targets**:
- Read: Max 105,000 IOPS (3x)
- Write: Max 21,000 IOPS (3x)

### Load Balancing Verification

#### Property-based Testing

**Property 5: Hash-based routing consistency**
```python
@given(st.text(), st.lists(st.integers()))
def test_routing_consistency(file_path, mount_targets):
    # Route same file path multiple times
    index1 = select_mount_target_index(file_path, len(mount_targets))
    index2 = select_mount_target_index(file_path, len(mount_targets))
    index3 = select_mount_target_index(file_path, len(mount_targets))
    
    # Verify all return same index
    assert index1 == index2 == index3
```

**Property 6: Hash-based routing distribution**
```python
@given(st.lists(st.text(), min_size=1000), st.integers(min_value=2, max_value=10))
def test_routing_distribution(file_paths, num_mount_targets):
    # Route large number of file paths
    distribution = [0] * num_mount_targets
    for path in file_paths:
        index = select_mount_target_index(path, num_mount_targets)
        distribution[index] += 1
    
    # Verify uniform distribution with chi-square test
    expected = len(file_paths) / num_mount_targets
    chi_square = sum((observed - expected)**2 / expected 
                     for observed in distribution)
    
    # Verify uniform distribution at 5% significance level
    assert chi_square < critical_value
```



## Security Architecture

### Network Security

#### VPC Design

```
VPC (10.0.0.0/16)
├── Private Subnet 1 (10.0.1.0/24) - AZ-1a
├── Private Subnet 2 (10.0.2.0/24) - AZ-1c
└── Private Subnet 3 (10.0.3.0/24) - AZ-1d

Features:
- All resources in private subnets
- No Internet Gateway (optional)
- Access AWS services via VPC endpoints
```

#### Security Groups

**Lambda Function Security Group**:
```
Outbound Rules:
- Port 2049 (NFS) → EFS Security Group
- Port 443 (HTTPS) → AWS Services (SSM, ECS, EFS API)
```

**Fargate Security Group**:
```
Outbound Rules:
- Port 2049 (NFS) → EFS Security Group
- Port 443 (HTTPS) → AWS Services (SSM, EFS API)
```

**EFS Security Group**:
```
Inbound Rules:
- Port 2049 (NFS) ← Lambda Security Group
- Port 2049 (NFS) ← Fargate Security Group

Outbound Rules:
- All traffic denied (stateful connection only)
```

### IAM Permissions

#### Lambda Execution Role

**Principle of Least Privilege**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "elasticfilesystem:DescribeMountTargets",
        "elasticfilesystem:CreateMountTarget",
        "elasticfilesystem:DescribeFileSystems"
      ],
      "Resource": "arn:aws:elasticfilesystem:*:*:file-system/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ssm:PutParameter",
        "ssm:GetParameter"
      ],
      "Resource": "arn:aws:ssm:*:*:parameter/efs-mount-autoscaling/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecs:UpdateService",
        "ecs:DescribeServices"
      ],
      "Resource": "arn:aws:ecs:*:*:service/efs-mount-autoscaling-cluster/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeSubnets",
        "ec2:DescribeNetworkInterfaces",
        "ec2:CreateNetworkInterface",
        "ec2:DeleteNetworkInterface"
      ],
      "Resource": "*"
    }
  ]
}
```


#### Fargate Task Role

**Principle of Least Privilege**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter"
      ],
      "Resource": "arn:aws:ssm:*:*:parameter/efs-mount-autoscaling/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "elasticfilesystem:DescribeMountTargets",
        "elasticfilesystem:DescribeFileSystems"
      ],
      "Resource": "arn:aws:elasticfilesystem:*:*:file-system/*"
    }
  ]
}
```

### Data Encryption

#### Encryption at Rest

**EFS Encryption**:
- Uses AWS KMS (Key Management Service)
- Customer-managed key or AWS-managed key
- Encrypts all file data and metadata

**SSM Parameter Store Encryption**:
- Uses SecureString type (optional)
- AWS KMS encryption
- Encrypts parameter values

#### Encryption in Transit

**EFS Encryption in Transit**:
```python
# Enable TLS when mounting NFS
mount_command = [
    'mount',
    '-t', 'efs',
    '-o', 'tls',  # Enable TLS
    f'{file_system_id}:/',
    mount_point
]
```

**AWS API Communication**:
- All AWS API calls via HTTPS
- Uses TLS 1.2 or higher

### Audit and Logging

#### CloudWatch Logs

**Lambda Function Logs**:
```
/aws/lambda/efs-mount-autoscaling-file-monitor
- Execution start/end
- File count results
- Mount Target creation process
- Error details
```

**Fargate Logs**:
```
/ecs/efs-mount-autoscaling-fargate
- Application startup
- Mount process success/failure
- File access logs (optional)
```

#### CloudTrail

**Audited API Calls**:
- `elasticfilesystem:CreateMountTarget`
- `ssm:PutParameter`
- `ecs:UpdateService`
- `ec2:CreateNetworkInterface`

**Recorded Information**:
- Who (IAM user/role)
- When (timestamp)
- What (API call)
- Where from (source IP address)
- Result (success/failure)



## Availability and Fault Tolerance

### High Availability Design

#### Multi-AZ Deployment

```
Availability Zone 1a:
- Fargate Task 1
- Lambda Function (at runtime)
- EFS Mount Target 1

Availability Zone 1c:
- Fargate Task 2
- EFS Mount Target 2

Availability Zone 1d:
- Fargate Task 3
- EFS Mount Target 3 (auto-created)
```

**Benefits**:
- Resilience against single AZ failure
- Redundancy through multiple Mount Targets
- Automatic failover

#### EFS High Availability

**Characteristics**:
- Automatically replicates data across multiple AZs
- 99.999999999% (11 9's) durability
- 99.99% availability SLA

**Behavior on Mount Target Failure**:
```
IF Mount Target 1 fails THEN
  - Access via that Mount Target fails
  - Other Mount Targets (2, 3) operate normally
  - Affected files: approximately 33% (hash-based routing)
  - New Fargate tasks skip failed Mount Target
END IF
```

### Error Handling

#### Lambda Function Error Handling

**1. EFS Access Error**:
```python
try:
    file_count = count_files_in_directory(target_directory)
except (FileNotFoundError, PermissionError) as e:
    logger.error(f"Failed to access EFS: {e}")
    # Abort process and return error
    return {'statusCode': 500, 'error': str(e)}
```

**2. No Available Subnets**:
```python
available_subnet = find_available_subnet(vpc_id, existing_mount_targets)
if not available_subnet:
    logger.warning("No available subnets - all AZs have mount targets")
    # Log warning and exit normally
    return {'statusCode': 200, 'message': 'No action needed'}
```

**3. Mount Target Creation Failure**:
```python
try:
    new_mount_target = create_mount_target(...)
    if not new_mount_target:
        logger.error("Mount target creation failed")
        # Skip SSM update and deployment
        return {'statusCode': 500, 'error': 'Mount target creation failed'}
except ClientError as e:
    logger.error(f"AWS API error: {e}")
    # Log error and maintain existing configuration
    return {'statusCode': 500, 'error': str(e)}
```

**Property**: State preservation on error
- For any error condition, existing Mount Target configuration remains unchanged and system maintains previous state


#### Fargate Application Error Handling

**1. SSM Parameter Store Retrieval Failure**:
```python
try:
    mount_targets = get_mount_targets_from_ssm()
except ClientError as e:
    logger.error(f"Failed to retrieve SSM parameter: {e}")
    # Use default configuration to start service
    mount_targets = get_default_mount_targets()
```

**2. Mount Target Mount Failure**:
```python
successfully_mounted = []
for mount_target in mount_targets:
    try:
        result = mount_nfs_target(mount_target)
        successfully_mounted.append(result)
    except Exception as e:
        logger.error(f"Failed to mount {mount_target['id']}: {e}")
        # Skip failed Mount Target and use others
        continue

if len(successfully_mounted) == 0:
    logger.error("Failed to mount any mount targets")
    # Abort service startup
    sys.exit(1)
```

**Property**: Fallback on mount failure
- For any Mount Target list, if some Mount Targets fail to mount but at least one is available, service starts

### Disaster Recovery

#### Scenario 1: Lambda Function Execution Failure

**Detection**:
- Check errors in CloudWatch Logs
- Notification via CloudWatch Alarm

**Recovery**:
- Automatic retry on next EventBridge execution (5 minutes later)
- Manual Lambda function execution for immediate recovery

**Impact**:
- Potential scaling delay
- Existing service operates normally

#### Scenario 2: Fargate Task Launch Failure

**Detection**:
- Check ECS Service event logs
- Notification via CloudWatch Alarm

**Recovery**:
- ECS automatically launches new task
- Automatic rollback if Deployment Circuit Breaker enabled

**Impact**:
- Temporary service capacity reduction
- Rolling update delay

#### Scenario 3: EFS Mount Target Failure

**Detection**:
- NFS mount errors
- Anomaly detection in CloudWatch Metrics

**Recovery**:
- AWS automatically recovers Mount Target
- Use other Mount Targets until recovery

**Impact**:
- File access via failed Mount Target fails
- Approximately 1/N (N = Mount Target count) of files affected


### Monitoring and Alerting

#### CloudWatch Metrics

**Lambda Function**:
- `Invocations`: Execution count
- `Errors`: Error count
- `Duration`: Execution time
- Custom metrics: File count, threshold exceeded count

**EFS**:
- `ClientConnections`: Connections to Mount Target
- `DataReadIOBytes`: Read bytes
- `DataWriteIOBytes`: Write bytes
- `PercentIOLimit`: I/O limit usage percentage

**Fargate**:
- `CPUUtilization`: CPU usage
- `MemoryUtilization`: Memory usage

#### CloudWatch Alarms

**Recommended Alarms**:
```
1. Lambda function error rate > 10%
   → SNS notification → Notify operations team

2. EFS PercentIOLimit > 80%
   → SNS notification → Consider performance mode change

3. Fargate task launch failure
   → SNS notification → Check configuration

4. Mount Target creation failure
   → SNS notification → Check VPC configuration
```

### Backup and Disaster Recovery

#### EFS Backup

**AWS Backup Integration**:
```
Backup Plan:
- Frequency: Daily
- Retention: 30 days
- Backup window: Midnight (low load period)
```

**Restore Procedure**:
1. Select restore point from AWS Backup console
2. Restore as new EFS file system
3. Create Mount Targets
4. Update SSM Parameter Store
5. Update ECS Service

#### Disaster Recovery Plan

**RTO (Recovery Time Objective)**: 1 hour
**RPO (Recovery Point Objective)**: 24 hours

**Recovery Procedure**:
1. Restore new EFS file system from backup (30 min)
2. Deploy new infrastructure with Terraform (15 min)
3. Verify application operation (15 min)



## Summary

### Key System Features

1. **Auto-scaling**
   - Automatically creates new Mount Targets when file count exceeds threshold
   - No manual intervention required, system scales autonomously

2. **Network-level Load Balancing**
   - Distributes network bandwidth using multiple Mount Targets (ENIs)
   - Theoretically, throughput improves proportionally to Mount Target count

3. **Hash-based Routing**
   - Uses file path hash values to evenly distribute access
   - Balances consistency and distribution

4. **High Availability**
   - Redundancy through multi-AZ deployment
   - Automatic failover on failure

5. **Security**
   - IAM permissions based on principle of least privilege
   - Encryption at rest and in transit
   - Deployment in private subnets

### Performance Improvements

**Before Scaling (Single Mount Target)**:
- Throughput: Max 3 GB/s (read)
- IOPS: Max 35,000 IOPS (read)
- Bottleneck: Single ENI bandwidth limit

**After Scaling (3 Mount Targets)**:
- Throughput: Max 9 GB/s (read) → **3x improvement**
- IOPS: Max 105,000 IOPS (read) → **3x improvement**
- Bottleneck: Resolved

### Operational Benefits

1. **Automation**
   - No manual Mount Target creation required
   - Automatic configuration change application

2. **Visibility**
   - All operations recorded in CloudWatch Logs
   - Performance monitoring via CloudWatch Metrics

3. **Flexibility**
   - Customizable thresholds and schedules
   - Easy configuration changes via environment variables

4. **Reliability**
   - Robustness through error handling
   - Quality assurance via property-based testing

### Future Extensibility

1. **Auto Scale-down**
   - Automatically delete unnecessary Mount Targets when file count decreases
   - Cost optimization

2. **Dynamic Threshold Adjustment**
   - Automatically adjust thresholds based on historical trends
   - Machine learning-based prediction

3. **Cross-region Support**
   - EFS replication across multiple regions
   - Global load balancing

4. **Advanced Load Balancing**
   - Dynamic routing based on actual access patterns
   - Hot spot detection and avoidance

### References

- [AWS EFS Documentation](https://docs.aws.amazon.com/efs/)
- [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/)
- [AWS Fargate Documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)
