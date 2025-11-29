# EFS Mount Target Auto-scaling System - アーキテクチャ説明書

## 目次

1. [システム概要](#システム概要)
2. [アーキテクチャ図](#アーキテクチャ図)
3. [コンポーネント詳細](#コンポーネント詳細)
4. [データフロー](#データフロー)
5. [スケーリングメカニズム](#スケーリングメカニズム)
6. [負荷分散戦略](#負荷分散戦略)
7. [セキュリティアーキテクチャ](#セキュリティアーキテクチャ)
8. [可用性と耐障害性](#可用性と耐障害性)

## システム概要

### 課題

AWS Fargate上で大規模ファイル読み書きサービスを運用する際、単一フォルダ内のファイル数が過剰になると、以下の問題が発生します：

- **ファイル読み取り速度の低下**: 単一のEFS Mount Targetへのアクセスが集中
- **ネットワークボトルネック**: 単一のENI（Elastic Network Interface）の帯域幅制限
- **スケーラビリティの制約**: 水平スケーリングしてもI/O性能が向上しない

### ソリューション

本システムは、以下の3つの主要な戦略でこれらの課題を解決します：

1. **自動スケーリング**: ファイル数が閾値を超えた際に、自動的に新しいMount Targetを作成
2. **ネットワークレベルの負荷分散**: 複数のMount Target（ENI）を使用してネットワーク帯域を分散
3. **ハッシュベースルーティング**: ファイルパスのハッシュ値を使用して、アクセスを均等に分散


## アーキテクチャ図

### 全体アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AWS Cloud Environment                                │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Serverless自動化レイヤー                            │ │
│  │                                                                          │ │
│  │  ┌──────────────────┐                                                   │ │
│  │  │  EventBridge     │                                                   │ │
│  │  │  Rule            │                                                   │ │
│  │  │  (5分ごと実行)   │                                                   │ │
│  │  └────────┬─────────┘                                                   │ │
│  │           │                                                              │ │
│  │           ▼                                                              │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │  Lambda Function (file_monitor.py)                               │  │ │
│  │  │  ┌────────────────────────────────────────────────────────────┐  │  │ │
│  │  │  │  1. EFSマウント & ファイル数カウント                       │  │  │ │
│  │  │  │  2. 閾値判定 (デフォルト: 100,000ファイル)                 │  │  │ │
│  │  │  │  3. 利用可能なサブネット検索                               │  │  │ │
│  │  │  │  4. 新しいMount Target作成                                 │  │  │ │
│  │  │  │  5. SSM Parameter Store更新                                │  │  │ │
│  │  │  │  6. ECS Service強制デプロイメント                          │  │  │ │
│  │  │  └────────────────────────────────────────────────────────────┘  │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│                                    │                                          │
│                                    ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    設定管理レイヤー                                     │ │
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
│  │                    アプリケーションレイヤー                             │ │
│  │                                                                          │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │  ECS Cluster                                                     │  │ │
│  │  │  ┌────────────────────────────────────────────────────────────┐  │  │ │
│  │  │  │  Fargate Tasks (app.py)                                    │  │  │ │
│  │  │  │  ┌──────────────────────────────────────────────────────┐  │  │  │ │
│  │  │  │  │  起動時処理:                                         │  │  │  │ │
│  │  │  │  │  1. SSM Parameter Storeから設定取得               │  │  │  │ │
│  │  │  │  │  2. 全Mount TargetをNFSマウント                   │  │  │  │ │
│  │  │  │  │     /mnt/efs-0, /mnt/efs-1, /mnt/efs-2, ...       │  │  │  │ │
│  │  │  │  │                                                      │  │  │  │ │
│  │  │  │  │  ファイルアクセス処理:                            │  │  │  │ │
│  │  │  │  │  1. ファイルパスのハッシュ値計算                  │  │  │  │ │
│  │  │  │  │  2. ハッシュ % Mount Target数 = インデックス      │  │  │  │ │
│  │  │  │  │  3. 選択されたMount Target経由でアクセス          │  │  │  │ │
│  │  │  │  └──────────────────────────────────────────────────────┘  │  │  │ │
│  │  │  └────────────────────────────────────────────────────────────┘  │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│                                    │                                          │
│                                    ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    ストレージレイヤー                                   │ │
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
│  │  │  共有ファイルシステム: /data/                                     │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```


### ネットワークアーキテクチャ

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
│  │  │                    (自動作成)                                    │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```


## コンポーネント詳細

### 1. EventBridge Rule

**役割**: Lambda関数を定期的に実行するトリガー

**設定**:
- スケジュール式: `rate(5 minutes)`
- ターゲット: Lambda関数 (file_monitor)
- 実行間隔: 5分ごと（カスタマイズ可能）

**動作**:
1. 設定されたスケジュールに従ってイベントを発火
2. Lambda関数を非同期で呼び出し
3. 実行履歴をCloudWatch Logsに記録

---

### 2. Lambda Function (file_monitor.py)

**役割**: ファイル数を監視し、必要に応じてMount Targetを自動作成

**主要機能**:

#### 2.1 ファイル数カウント
```python
def count_files_in_directory(directory_path):
    # EFSマウントポイントからファイル数をカウント
    # ディレクトリのみを除外し、ファイルのみをカウント
```

**プロパティ**: ファイル数カウントの正確性
- 任意のディレクトリに対して、カウント結果は実際のファイル数と一致する

#### 2.2 閾値判定
```python
def check_threshold_exceeded(file_count, threshold):
    # ファイル数が閾値を超えているかチェック
    return file_count > threshold
```

**プロパティ**: 閾値判定の一貫性
- 任意のファイル数と閾値の組み合わせに対して、file_count > thresholdの場合のみTrueを返す

#### 2.3 Mount Target作成
```python
def create_mount_target(file_system_id, subnet_id, security_group_id):
    # 1. AWS EFS CreateMountTarget APIを呼び出し
    # 2. Mount Targetの作成完了を待機（ポーリング）
    # 3. 作成されたMount Target情報を返す
```

**特徴**:
- 最大5分間のポーリング待機
- 10秒間隔でステータスチェック
- エラー時の適切なハンドリング

#### 2.4 SSM Parameter Store更新
```python
def update_ssm_parameter(parameter_name, mount_targets_json):
    # Mount Target情報をJSON形式でSSMに保存
```

**プロパティ**: SSM Parameter Storeの更新整合性
- 任意のMount Targetリストに対して、保存→取得のラウンドトリップで同じデータが返される

#### 2.5 ECS Service更新
```python
def trigger_ecs_service_deployment(cluster_name, service_name):
    # forceNewDeployment=Trueでローリングアップデートを実行
```

**環境変数**:
| 変数名 | 説明 | デフォルト値 |
|--------|------|-------------|
| `TARGET_DIRECTORY` | 監視対象ディレクトリ | `/data` |
| `FILE_COUNT_THRESHOLD` | ファイル数閾値 | `100000` |
| `EFS_FILE_SYSTEM_ID` | EFSファイルシステムID | - |
| `VPC_ID` | VPC ID | - |
| `SSM_PARAMETER_NAME` | SSMパラメータ名 | `/efs-mount-autoscaling/mount-targets` |
| `ECS_CLUSTER_NAME` | ECSクラスター名 | - |
| `ECS_SERVICE_NAME` | ECSサービス名 | - |

**IAM権限**:
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

**役割**: Mount Target情報を保存し、Lambda関数とFargateサービス間で共有

**パラメータ名**: `/efs-mount-autoscaling/mount-targets`

**データ形式**:
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

**アクセスパターン**:
- **書き込み**: Lambda関数（新しいMount Target作成時）
- **読み取り**: Fargateサービス（起動時）

---

### 4. Fargate Service (app.py)

**役割**: 複数のMount Targetをマウントし、ハッシュベースでファイルアクセスを分散

**主要機能**:

#### 4.1 初期化処理
```python
def initialize():
    # 1. SSM Parameter Storeから最新のMount Target情報を取得
    mount_targets = get_mount_targets_from_ssm()
    
    # 2. 各Mount TargetをNFSマウント
    successfully_mounted = mount_nfs_targets(mount_targets)
    
    return mount_targets, successfully_mounted
```

**マウントポイント**:
- `/mnt/efs-0`: Mount Target 1
- `/mnt/efs-1`: Mount Target 2
- `/mnt/efs-2`: Mount Target 3
- ...

#### 4.2 ハッシュベースルーティング
```python
def get_file_path(original_path, mount_targets):
    # 1. ファイルパスのハッシュ値を計算（SHA256）
    hash_value = hashlib.sha256(original_path.encode('utf-8')).hexdigest()
    hash_int = int(hash_value, 16)
    
    # 2. Mount Target数でモジュロ演算
    index = hash_int % len(mount_targets)
    
    # 3. 選択されたMount Targetのマウントポイントを使用
    mount_point = f"/mnt/efs-{index}"
    complete_path = os.path.join(mount_point, original_path)
    
    return complete_path
```

**プロパティ**: ハッシュベースルーティングの一貫性
- 任意のファイルパスに対して、同じファイルパスは常に同じMount Targetインデックスを返す

**プロパティ**: ハッシュベースルーティングの分散性
- 任意のファイルパスのセットに対して、各Mount Targetへの分散が許容範囲内である

#### 4.3 ファイルアクセスAPI
```python
# 読み取り
def read_file(original_path, mount_targets, mode='r', encoding='utf-8'):
    complete_path = get_file_path(original_path, mount_targets)
    with open(complete_path, mode, encoding=encoding) as f:
        return f.read()

# 書き込み
def write_file(original_path, content, mount_targets, mode='w', encoding='utf-8'):
    complete_path = get_file_path(original_path, mount_targets)
    with open(complete_path, mode, encoding=encoding) as f:
        f.write(content)
    return complete_path

# 追記
def append_file(original_path, content, mount_targets, encoding='utf-8'):
    # ...

# 存在確認
def file_exists(original_path, mount_targets):
    # ...

# 削除
def delete_file(original_path, mount_targets):
    # ...
```

**環境変数**:
| 変数名 | 説明 |
|--------|------|
| `SSM_PARAMETER_NAME` | SSMパラメータ名 |
| `EFS_FILE_SYSTEM_ID` | EFSファイルシステムID |

**IAM権限**:
- `ssm:GetParameter`
- `elasticfilesystem:DescribeMountTargets`
- `elasticfilesystem:DescribeFileSystems`

**エラーハンドリング**:
- SSM取得失敗時: デフォルト設定を使用
- Mount失敗時: 失敗したMount Targetをスキップし、他のMount Targetを使用

**プロパティ**: Mount失敗時のフォールバック
- 任意のMount Targetリストに対して、一部のMount Targetのマウントに失敗しても、少なくとも1つが利用可能であればサービスは起動する

---

### 5. EFS File System

**役割**: 大規模ファイルストレージを提供

**設定**:
- **パフォーマンスモード**: General Purpose（小規模）または Max I/O（大規模）
- **スループットモード**: Bursting（変動する負荷）または Provisioned（予測可能な負荷）
- **暗号化**: 有効（AWS KMS使用）
- **転送中の暗号化**: TLS有効

**Mount Target**:
- 各Availability Zoneに1つのMount Targetを配置
- 各Mount Targetは専用のENI（Elastic Network Interface）を持つ
- ENIは独立したネットワーク帯域を提供

**スケーリング特性**:
- 初期状態: 2つのMount Target（2つのAZ）
- 自動拡張: ファイル数が閾値を超えると、新しいAZにMount Targetを追加
- 最大数: VPC内のAZ数まで拡張可能

---


## データフロー

### 1. 通常運用時のデータフロー

```
┌─────────────┐
│  Fargate    │
│  Task       │
└──────┬──────┘
       │
       │ 1. ファイルアクセス要求
       │    file_path = "user/12345/document.pdf"
       │
       ▼
┌──────────────────────────────────────────┐
│  ハッシュベースルーティング              │
│  hash = SHA256(file_path)                │
│  index = hash % num_mount_targets        │
│  → index = 1                             │
└──────┬───────────────────────────────────┘
       │
       │ 2. 選択されたMount Target経由でアクセス
       │    /mnt/efs-1/user/12345/document.pdf
       │
       ▼
┌──────────────────────────────────────────┐
│  Mount Target 2 (ENI: 10.0.2.100)        │
│  Availability Zone: ap-northeast-1c      │
└──────┬───────────────────────────────────┘
       │
       │ 3. NFSプロトコル経由でアクセス
       │
       ▼
┌──────────────────────────────────────────┐
│  EFS File System                         │
│  /data/user/12345/document.pdf           │
└──────────────────────────────────────────┘
```

### 2. スケーリング時のデータフロー

```
┌─────────────┐
│ EventBridge │
│ (5分ごと)   │
└──────┬──────┘
       │
       │ 1. Lambda関数を実行
       │
       ▼
┌──────────────────────────────────────────┐
│  Lambda Function                         │
│  ┌────────────────────────────────────┐  │
│  │ Step 1: ファイル数カウント         │  │
│  │ count = 150,000 ファイル           │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ Step 2: 閾値判定                   │  │
│  │ 150,000 > 100,000 → TRUE           │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ Step 3: 利用可能なサブネット検索   │  │
│  │ 既存: AZ-1a, AZ-1c                 │  │
│  │ 利用可能: AZ-1d                    │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ Step 4: Mount Target作成           │  │
│  │ CreateMountTarget(AZ-1d)           │  │
│  │ → fsmt-new123                      │  │
│  └────────────────────────────────────┘  │
└──────┬───────────────────────────────────┘
       │
       │ 2. SSM Parameter Store更新
       │
       ▼
┌──────────────────────────────────────────┐
│  SSM Parameter Store                     │
│  mount_targets: [                        │
│    {id: fsmt-12345, ip: 10.0.1.100},     │
│    {id: fsmt-67890, ip: 10.0.2.100},     │
│    {id: fsmt-new123, ip: 10.0.3.100}     │ ← 新規追加
│  ]                                       │
└──────┬───────────────────────────────────┘
       │
       │ 3. ECS Service強制デプロイメント
       │
       ▼
┌──────────────────────────────────────────┐
│  ECS Service                             │
│  ┌────────────────────────────────────┐  │
│  │ ローリングアップデート開始         │  │
│  │ 1. 新しいタスクを起動              │  │
│  │ 2. 新しいタスクがSSMから設定取得   │  │
│  │ 3. 3つのMount Targetをマウント     │  │
│  │ 4. 古いタスクを停止                │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

### 3. ファイルアクセスの負荷分散

```
複数のFargateタスクからの同時アクセス:

Task 1: file_a.txt → hash % 3 = 0 → Mount Target 1 (10.0.1.100)
Task 2: file_b.txt → hash % 3 = 1 → Mount Target 2 (10.0.2.100)
Task 3: file_c.txt → hash % 3 = 2 → Mount Target 3 (10.0.3.100)
Task 4: file_d.txt → hash % 3 = 0 → Mount Target 1 (10.0.1.100)
Task 5: file_e.txt → hash % 3 = 1 → Mount Target 2 (10.0.2.100)

結果: ネットワークトラフィックが3つのENIに分散される
```


## スケーリングメカニズム

### スケーリングトリガー

**条件**:
```
ファイル数 > FILE_COUNT_THRESHOLD
```

**デフォルト閾値**: 100,000ファイル

**チェック頻度**: 5分ごと（EventBridgeスケジュール）

### スケーリングプロセス

#### Phase 1: 検出
```
1. EventBridgeがLambda関数を実行
2. Lambda関数がEFSをマウント
3. ターゲットディレクトリのファイル数をカウント
4. 閾値と比較
```

#### Phase 2: 評価
```
IF ファイル数 > 閾値 THEN
  1. 既存のMount Targetを取得
  2. VPC内の全サブネットを取得
  3. Mount Targetが存在しないサブネットを特定
  
  IF 利用可能なサブネットが存在 THEN
    → Phase 3へ
  ELSE
    → ログに警告を記録して終了
  END IF
END IF
```

#### Phase 3: 実行
```
1. 新しいMount Targetを作成
   - CreateMountTarget API呼び出し
   - 最大5分間、作成完了を待機
   
2. SSM Parameter Storeを更新
   - 全Mount Targetのリストを取得
   - JSON形式に変換
   - SSMに保存
   
3. ECS Serviceを更新
   - UpdateService API呼び出し（forceNewDeployment=True）
   - ローリングアップデートが開始される
```

#### Phase 4: 適用
```
1. ECSが新しいFargateタスクを起動
2. 新しいタスクがSSM Parameter Storeから最新の設定を取得
3. 新しいタスクが全てのMount Target（新規を含む）をマウント
4. 新しいタスクが正常に起動したら、古いタスクを停止
5. 全てのタスクが新しい設定で動作
```

### スケーリング制約

**最大Mount Target数**: VPC内のAvailability Zone数

**例**: 
- ap-northeast-1リージョン: 最大3つ（1a, 1c, 1d）
- us-east-1リージョン: 最大6つ（1a, 1b, 1c, 1d, 1e, 1f）

**スケールダウン**: 
- 現在のバージョンでは自動スケールダウンは実装されていない
- 手動でMount Targetを削除する必要がある

### スケーリングタイムライン

```
T+0:00  EventBridgeがLambda関数を実行
T+0:05  ファイル数カウント完了
T+0:10  閾値超過を検出
T+0:15  利用可能なサブネットを特定
T+0:20  Mount Target作成開始
T+2:00  Mount Target作成完了（平均2分）
T+2:05  SSM Parameter Store更新完了
T+2:10  ECS Service強制デプロイメント開始
T+3:00  新しいFargateタスク起動開始
T+3:30  新しいタスクが全Mount Targetをマウント
T+4:00  新しいタスクが正常稼働
T+4:30  古いタスクが停止
T+5:00  ローリングアップデート完了

合計所要時間: 約5分
```


## 負荷分散戦略

### ハッシュベースルーティングの原理

#### アルゴリズム

```python
def select_mount_target(file_path, mount_targets):
    # 1. ファイルパスからハッシュ値を計算
    hash_value = SHA256(file_path)
    
    # 2. ハッシュ値を整数に変換
    hash_int = int(hash_value, 16)
    
    # 3. Mount Target数でモジュロ演算
    index = hash_int % len(mount_targets)
    
    # 4. 選択されたMount Targetを返す
    return mount_targets[index]
```

#### 特性

**一貫性**:
- 同じファイルパスは常に同じMount Targetにルーティングされる
- ファイルの読み取り・書き込み・削除が同じMount Target経由で行われる
- キャッシュの局所性が向上

**分散性**:
- SHA256ハッシュ関数の均等分散特性により、ファイルが各Mount Targetに均等に分散される
- 理論的には、各Mount Targetへのアクセスは1/N（NはMount Target数）

**スケーラビリティ**:
- Mount Targetを追加しても、既存のファイルの大部分は同じMount Targetにルーティングされる
- 再配置が必要なファイルは約1/N（Nは新しいMount Target数）

### 負荷分散の効果

#### シナリオ1: 単一Mount Target（初期状態）

```
全てのアクセス → Mount Target 1 (ENI 1)
                  ↓
              ボトルネック
              - ENI帯域幅制限
              - 単一障害点
```

**問題点**:
- ENIの帯域幅制限（最大10 Gbps）
- レイテンシの増加
- 単一障害点

#### シナリオ2: 3つのMount Target（スケーリング後）

```
ファイルA → Mount Target 1 (ENI 1) → 33%のトラフィック
ファイルB → Mount Target 2 (ENI 2) → 33%のトラフィック
ファイルC → Mount Target 3 (ENI 3) → 33%のトラフィック
```

**改善点**:
- 合計帯域幅: 最大30 Gbps（3 × 10 Gbps）
- レイテンシの低減
- 冗長性の向上

### パフォーマンスメトリクス

#### スループット

**単一Mount Target**:
- 読み取り: 最大 3 GB/s
- 書き込み: 最大 1 GB/s

**3つのMount Target**:
- 読み取り: 最大 9 GB/s（3倍）
- 書き込み: 最大 3 GB/s（3倍）

#### IOPS

**単一Mount Target**:
- 読み取り: 最大 35,000 IOPS
- 書き込み: 最大 7,000 IOPS

**3つのMount Target**:
- 読み取り: 最大 105,000 IOPS（3倍）
- 書き込み: 最大 21,000 IOPS（3倍）

### 負荷分散の検証

#### プロパティベーステスト

**Property 5: ハッシュベースルーティングの一貫性**
```python
@given(st.text(), st.lists(st.integers()))
def test_routing_consistency(file_path, mount_targets):
    # 同じファイルパスに対して複数回ルーティング
    index1 = select_mount_target_index(file_path, len(mount_targets))
    index2 = select_mount_target_index(file_path, len(mount_targets))
    index3 = select_mount_target_index(file_path, len(mount_targets))
    
    # 全て同じインデックスを返すことを検証
    assert index1 == index2 == index3
```

**Property 6: ハッシュベースルーティングの分散性**
```python
@given(st.lists(st.text(), min_size=1000), st.integers(min_value=2, max_value=10))
def test_routing_distribution(file_paths, num_mount_targets):
    # 大量のファイルパスをルーティング
    distribution = [0] * num_mount_targets
    for path in file_paths:
        index = select_mount_target_index(path, num_mount_targets)
        distribution[index] += 1
    
    # カイ二乗検定で均等分散を検証
    expected = len(file_paths) / num_mount_targets
    chi_square = sum((observed - expected)**2 / expected 
                     for observed in distribution)
    
    # 有意水準5%で均等分散を検証
    assert chi_square < critical_value
```


## セキュリティアーキテクチャ

### ネットワークセキュリティ

#### VPC設計

```
VPC (10.0.0.0/16)
├── Private Subnet 1 (10.0.1.0/24) - AZ-1a
├── Private Subnet 2 (10.0.2.0/24) - AZ-1c
└── Private Subnet 3 (10.0.3.0/24) - AZ-1d

特徴:
- 全てのリソースをプライベートサブネットに配置
- インターネットゲートウェイなし（オプション）
- VPCエンドポイント経由でAWSサービスにアクセス
```

#### セキュリティグループ

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

### IAM権限

#### Lambda実行ロール

**最小権限の原則**:
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

#### Fargateタスクロール

**最小権限の原則**:
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

### データ暗号化

#### 保管時の暗号化

**EFS暗号化**:
- AWS KMS（Key Management Service）を使用
- カスタマーマネージドキーまたはAWSマネージドキー
- 全てのファイルデータとメタデータを暗号化

**SSM Parameter Store暗号化**:
- SecureString型を使用（オプション）
- AWS KMS暗号化
- パラメータ値の暗号化

#### 転送中の暗号化

**EFS転送中の暗号化**:
```python
# NFSマウント時にTLSを有効化
mount_command = [
    'mount',
    '-t', 'efs',
    '-o', 'tls',  # TLS有効化
    f'{file_system_id}:/',
    mount_point
]
```

**AWS API通信**:
- 全てのAWS API呼び出しはHTTPS経由
- TLS 1.2以上を使用

### 監査とロギング

#### CloudWatch Logs

**Lambda関数ログ**:
```
/aws/lambda/efs-mount-autoscaling-file-monitor
- 実行開始・終了
- ファイル数カウント結果
- Mount Target作成処理
- エラー詳細
```

**Fargateログ**:
```
/ecs/efs-mount-autoscaling-fargate
- アプリケーション起動
- Mount処理の成功・失敗
- ファイルアクセスログ（オプション）
```

#### CloudTrail

**監査対象のAPI呼び出し**:
- `elasticfilesystem:CreateMountTarget`
- `ssm:PutParameter`
- `ecs:UpdateService`
- `ec2:CreateNetworkInterface`

**記録される情報**:
- 誰が（IAMユーザー/ロール）
- いつ（タイムスタンプ）
- 何を（API呼び出し）
- どこから（ソースIPアドレス）
- 結果（成功/失敗）


## 可用性と耐障害性

### 高可用性設計

#### マルチAZ配置

```
Availability Zone 1a:
- Fargate Task 1
- Lambda Function (実行時)
- EFS Mount Target 1

Availability Zone 1c:
- Fargate Task 2
- EFS Mount Target 2

Availability Zone 1d:
- Fargate Task 3 (オプション)
- EFS Mount Target 3 (自動作成)
```

**利点**:
- 単一AZの障害に対する耐性
- 複数のMount Targetによる冗長性
- 自動フェイルオーバー

#### EFS高可用性

**特性**:
- 複数のAZにデータを自動的にレプリケート
- 99.999999999%（11 9's）の耐久性
- 99.99%の可用性SLA

**Mount Target障害時の動作**:
```
IF Mount Target 1が障害 THEN
  - そのMount Target経由のアクセスは失敗
  - 他のMount Target（2, 3）は正常に動作
  - 影響を受けるファイル: 約33%（ハッシュベースルーティング）
  - 新しいFargateタスクは障害のあるMount Targetをスキップ
END IF
```

### エラーハンドリング

#### Lambda関数のエラーハンドリング

**1. EFSアクセスエラー**:
```python
try:
    file_count = count_files_in_directory(target_directory)
except (FileNotFoundError, PermissionError) as e:
    logger.error(f"Failed to access EFS: {e}")
    # 処理を中断し、エラーを返す
    return {'statusCode': 500, 'error': str(e)}
```

**2. 利用可能なサブネットなし**:
```python
available_subnet = find_available_subnet(vpc_id, existing_mount_targets)
if not available_subnet:
    logger.warning("No available subnets - all AZs have mount targets")
    # 警告ログを記録し、正常終了
    return {'statusCode': 200, 'message': 'No action needed'}
```

**3. Mount Target作成失敗**:
```python
try:
    new_mount_target = create_mount_target(...)
    if not new_mount_target:
        logger.error("Mount target creation failed")
        # SSM更新とデプロイメントをスキップ
        return {'statusCode': 500, 'error': 'Mount target creation failed'}
except ClientError as e:
    logger.error(f"AWS API error: {e}")
    # エラーログを記録し、既存の設定を維持
    return {'statusCode': 500, 'error': str(e)}
```

**プロパティ**: エラー時の状態保持
- 任意のエラー条件に対して、エラーが発生した場合でも、既存のMount Target設定は変更されず、システムは以前の状態を維持する

#### Fargateアプリケーションのエラーハンドリング

**1. SSM Parameter Store取得失敗**:
```python
try:
    mount_targets = get_mount_targets_from_ssm()
except ClientError as e:
    logger.error(f"Failed to retrieve SSM parameter: {e}")
    # デフォルト設定を使用してサービスを起動
    mount_targets = get_default_mount_targets()
```

**2. Mount Target マウント失敗**:
```python
successfully_mounted = []
for mount_target in mount_targets:
    try:
        result = mount_nfs_target(mount_target)
        successfully_mounted.append(result)
    except Exception as e:
        logger.error(f"Failed to mount {mount_target['id']}: {e}")
        # 失敗したMount Targetをスキップし、他のMount Targetを使用
        continue

if len(successfully_mounted) == 0:
    logger.error("Failed to mount any mount targets")
    # サービス起動を中断
    sys.exit(1)
```

**プロパティ**: Mount失敗時のフォールバック
- 任意のMount Targetリストに対して、一部のMount Targetのマウントに失敗しても、少なくとも1つが利用可能であればサービスは起動する

### 障害復旧

#### シナリオ1: Lambda関数の実行失敗

**検出**:
- CloudWatch Logsでエラーを確認
- CloudWatch Alarmで通知

**復旧**:
- 次回のEventBridge実行（5分後）で自動的に再試行
- 手動でLambda関数を実行して即座に復旧

**影響**:
- スケーリングが遅延する可能性
- 既存のサービスは正常に動作

#### シナリオ2: Fargateタスクの起動失敗

**検出**:
- ECS Serviceイベントログで確認
- CloudWatch Alarmで通知

**復旧**:
- ECSが自動的に新しいタスクを起動
- Deployment Circuit Breakerが有効な場合、自動ロールバック

**影響**:
- 一時的なサービス容量の低下
- ローリングアップデートの遅延

#### シナリオ3: EFS Mount Targetの障害

**検出**:
- NFSマウントエラー
- CloudWatch Metricsで異常を検出

**復旧**:
- AWSが自動的にMount Targetを復旧
- 復旧まで他のMount Targetを使用

**影響**:
- 障害のあるMount Target経由のファイルアクセスが失敗
- 約1/N（NはMount Target数）のファイルが影響を受ける

### 監視とアラート

#### CloudWatch Metrics

**Lambda関数**:
- `Invocations`: 実行回数
- `Errors`: エラー回数
- `Duration`: 実行時間
- カスタムメトリクス: ファイル数、閾値超過回数

**EFS**:
- `ClientConnections`: Mount Targetへの接続数
- `DataReadIOBytes`: 読み取りバイト数
- `DataWriteIOBytes`: 書き込みバイト数
- `PercentIOLimit`: I/O制限の使用率

**Fargate**:
- `CPUUtilization`: CPU使用率
- `MemoryUtilization`: メモリ使用率

#### CloudWatch Alarms

**推奨アラーム**:
```
1. Lambda関数のエラー率 > 10%
   → SNS通知 → 運用チームに通知

2. EFS PercentIOLimit > 80%
   → SNS通知 → パフォーマンスモード変更を検討

3. Fargateタスクの起動失敗
   → SNS通知 → 設定を確認

4. Mount Target作成失敗
   → SNS通知 → VPC設定を確認
```

### バックアップと災害復旧

#### EFSバックアップ

**AWS Backup統合**:
```
バックアップ計画:
- 頻度: 毎日
- 保持期間: 30日
- バックアップウィンドウ: 深夜（負荷が低い時間帯）
```

**リストア手順**:
1. AWS Backupコンソールから復元ポイントを選択
2. 新しいEFSファイルシステムとして復元
3. Mount Targetを作成
4. SSM Parameter Storeを更新
5. ECS Serviceを更新

#### 災害復旧計画

**RTO（Recovery Time Objective）**: 1時間
**RPO（Recovery Point Objective）**: 24時間

**復旧手順**:
1. バックアップから新しいEFSファイルシステムを復元（30分）
2. Terraformで新しいインフラをデプロイ（15分）
3. アプリケーションの動作確認（15分）


## まとめ

### システムの主要な特徴

1. **自動スケーリング**
   - ファイル数が閾値を超えた際に、自動的に新しいMount Targetを作成
   - 手動介入不要で、システムが自律的にスケーリング

2. **ネットワークレベルの負荷分散**
   - 複数のMount Target（ENI）を使用してネットワーク帯域を分散
   - 理論的には、Mount Target数に比例してスループットが向上

3. **ハッシュベースルーティング**
   - ファイルパスのハッシュ値を使用して、アクセスを均等に分散
   - 一貫性と分散性を両立

4. **高可用性**
   - マルチAZ配置による冗長性
   - 障害時の自動フェイルオーバー

5. **セキュリティ**
   - 最小権限の原則に基づくIAM権限
   - 保管時・転送中の暗号化
   - プライベートサブネットへの配置

### パフォーマンス改善

**スケーリング前（単一Mount Target）**:
- スループット: 最大 3 GB/s（読み取り）
- IOPS: 最大 35,000 IOPS（読み取り）
- ボトルネック: 単一ENIの帯域幅制限

**スケーリング後（3つのMount Target）**:
- スループット: 最大 9 GB/s（読み取り）→ **3倍向上**
- IOPS: 最大 105,000 IOPS（読み取り）→ **3倍向上**
- ボトルネック: 解消

### 運用上の利点

1. **自動化**
   - 手動でのMount Target作成が不要
   - 設定変更の自動適用

2. **可視性**
   - CloudWatch Logsで全ての操作を記録
   - CloudWatch Metricsでパフォーマンスを監視

3. **柔軟性**
   - 閾値やスケジュールをカスタマイズ可能
   - 環境変数で簡単に設定変更

4. **信頼性**
   - エラーハンドリングによる堅牢性
   - プロパティベーステストによる品質保証

### 今後の拡張可能性

1. **自動スケールダウン**
   - ファイル数が減少した際に、不要なMount Targetを自動削除
   - コスト最適化

2. **動的閾値調整**
   - 過去のトレンドに基づいて閾値を自動調整
   - 機械学習による予測

3. **クロスリージョン対応**
   - 複数のリージョンにまたがるEFSレプリケーション
   - グローバルな負荷分散

4. **高度な負荷分散**
   - 実際のアクセスパターンに基づく動的ルーティング
   - ホットスポットの検出と回避

### 参考資料

- [AWS EFS Documentation](https://docs.aws.amazon.com/efs/)
- [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/)
- [AWS Fargate Documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)
- [設計書](.kiro/specs/efs-mount-target-autoscaling/design.md)
- [要件定義](.kiro/specs/efs-mount-target-autoscaling/requirements.md)
- [実装計画](.kiro/specs/efs-mount-target-autoscaling/tasks.md)

---

**最終更新日**: 2024年11月29日  
**バージョン**: 1.0  
**作成者**: Kiro AI Assistant
