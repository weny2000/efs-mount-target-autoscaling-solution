# 要件定義書

## はじめに

本要件定義書は、AWS Fargate上にデプロイされた大規模ファイル読み書きサービスにおいて、単一フォルダ内のファイル数が過剰になった際に発生するファイル読み取り速度低下の課題を解決するためのシステムを定義する。AWS Serverlessコンポーネント（Lambda、EventBridge）を活用し、EFS（Elastic File System）のマウントターゲットを動的に追加することで、ネットワークレベルでの負荷分散を実現する。

## 用語集

- **EFS (Elastic File System)**: AWSが提供するマネージドNFSファイルシステムサービス
- **Mount Target**: EFSファイルシステムへのネットワークアクセスポイント。各Availability Zone（AZ）に配置される
- **Fargate Service**: AWS ECS上でコンテナをサーバーレスで実行するサービス
- **Lambda Function**: イベント駆動型のサーバーレス関数実行環境
- **EventBridge**: AWSのイベントバスサービス。定期実行やイベントトリガーを管理
- **SSM Parameter Store**: AWS Systems Managerの機能。設定値を安全に保存・取得するサービス
- **File Count Threshold**: ファイル数の閾値。この値を超えるとスケーリングが実行される
- **Rolling Update**: サービスを停止せずに段階的に新しいバージョンに更新する手法

## 要件

### 要件 1

**ユーザーストーリー:** システム管理者として、EFS上のファイル数が閾値を超えた際に自動的にスケーリングが実行されることを望む。これにより、手動介入なしでシステムのパフォーマンスを維持できる。

#### 受入基準

1. WHEN EventBridge が定期的にトリガーを発火する THEN Lambda Function SHALL 実行される
2. WHEN Lambda Function が実行される THEN Lambda Function SHALL EFS をマウントしてターゲットディレクトリ内のファイル数をカウントする
3. WHEN ファイル数が File Count Threshold を超える THEN Lambda Function SHALL 新しい Mount Target の作成処理を開始する
4. WHEN 新しい Mount Target が作成される THEN Lambda Function SHALL 利用可能な VPC サブネットを特定して Mount Target を作成する
5. WHEN Mount Target の作成が完了する THEN Lambda Function SHALL SSM Parameter Store のパラメータを更新する

### 要件 2

**ユーザーストーリー:** 開発者として、Fargateサービスが最新のMount Target情報を自動的に取得して適用することを望む。これにより、アプリケーションが常に最適な構成で動作できる。

#### 受入基準

1. WHEN Fargate Service が起動する THEN Fargate Service SHALL SSM Parameter Store から最新の Mount Target リストを取得する
2. WHEN Mount Target リストが取得される THEN Fargate Service SHALL 全ての Mount Target をコンテナ内の異なるディレクトリにマウントする
3. WHEN Lambda Function が SSM Parameter Store を更新する THEN Lambda Function SHALL ECS UpdateService API を呼び出して forceNewDeployment を実行する
4. WHEN forceNewDeployment が実行される THEN Fargate Service SHALL ローリングアップデートを開始して新しいタスクを起動する

### 要件 3

**ユーザーストーリー:** アプリケーション開発者として、ファイルアクセスが複数のMount Targetに自動的に分散されることを望む。これにより、ネットワークレベルでの負荷分散が実現される。

#### 受入基準

1. WHEN アプリケーションがファイルにアクセスする THEN Fargate Service SHALL ファイルパスのハッシュ値を計算する
2. WHEN ハッシュ値が計算される THEN Fargate Service SHALL ハッシュ値を Mount Target 数でモジュロ演算して使用する Mount Target を決定する
3. WHEN 使用する Mount Target が決定される THEN Fargate Service SHALL 決定された Mount Target 経由でファイルにアクセスする
4. WHEN 同じファイルパスに複数回アクセスする THEN Fargate Service SHALL 常に同じ Mount Target を使用する

### 要件 4

**ユーザーストーリー:** システム管理者として、Lambda関数が適切な権限を持ち、必要なAWSリソースにアクセスできることを望む。これにより、自動化処理が確実に実行される。

#### 受入基準

1. WHEN Lambda Function が実行される THEN Lambda Function SHALL EFS ファイルシステムへの読み取りアクセス権限を持つ
2. WHEN Lambda Function が Mount Target を作成する THEN Lambda Function SHALL EFS CreateMountTarget API を呼び出す権限を持つ
3. WHEN Lambda Function が SSM Parameter Store を更新する THEN Lambda Function SHALL SSM PutParameter API を呼び出す権限を持つ
4. WHEN Lambda Function が Fargate Service を更新する THEN Lambda Function SHALL ECS UpdateService API を呼び出す権限を持つ
5. WHEN Lambda Function が VPC リソースにアクセスする THEN Lambda Function SHALL ENI 作成および VPC 内通信の権限を持つ

### 要件 5

**ユーザーストーリー:** システム管理者として、システムの動作状況を監視し、問題発生時に適切なログを確認できることを望む。これにより、トラブルシューティングが容易になる。

#### 受入基準

1. WHEN Lambda Function が実行される THEN Lambda Function SHALL 実行開始と終了をログに記録する
2. WHEN Lambda Function がファイル数をカウントする THEN Lambda Function SHALL カウント結果をログに記録する
3. WHEN Lambda Function が Mount Target を作成する THEN Lambda Function SHALL 作成処理の開始、進行状況、完了をログに記録する
4. WHEN Lambda Function がエラーに遭遇する THEN Lambda Function SHALL エラーの詳細情報をログに記録する
5. WHEN Fargate Service が Mount Target をマウントする THEN Fargate Service SHALL マウント処理の成功または失敗をログに記録する

### 要件 6

**ユーザーストーリー:** システム管理者として、システムが異常な状態やエラー条件を適切に処理することを望む。これにより、システムの信頼性と安定性が確保される。

#### 受入基準

1. WHEN Lambda Function が EFS へのアクセスに失敗する THEN Lambda Function SHALL エラーをログに記録して処理を中断する
2. WHEN Lambda Function が利用可能なサブネットを見つけられない THEN Lambda Function SHALL エラーをログに記録して Mount Target 作成をスキップする
3. WHEN Mount Target の作成が失敗する THEN Lambda Function SHALL エラーをログに記録して SSM Parameter Store の更新をスキップする
4. WHEN Fargate Service が SSM Parameter Store からの取得に失敗する THEN Fargate Service SHALL デフォルト設定を使用してサービスを起動する
5. WHEN Fargate Service が Mount Target のマウントに失敗する THEN Fargate Service SHALL 失敗した Mount Target をスキップして他の Mount Target を使用する

### 要件 7

**ユーザーストーリー:** システム管理者として、システムの設定を柔軟に変更できることを望む。これにより、異なる環境や要件に対応できる。

#### 受入基準

1. WHEN Lambda Function が起動する THEN Lambda Function SHALL 環境変数から File Count Threshold を読み取る
2. WHEN Lambda Function が起動する THEN Lambda Function SHALL 環境変数から監視対象ディレクトリパスを読み取る
3. WHEN Lambda Function が起動する THEN Lambda Function SHALL 環境変数から EFS ファイルシステム ID を読み取る
4. WHEN EventBridge ルールが設定される THEN EventBridge SHALL 環境変数または設定から実行間隔を読み取る
5. WHEN Fargate Service が起動する THEN Fargate Service SHALL 環境変数から SSM Parameter Store のパラメータ名を読み取る
