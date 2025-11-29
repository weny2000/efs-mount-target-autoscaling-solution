# Lambda Function for EFS Mount Target Auto-scaling
# This function monitors file count and creates new mount targets when threshold is exceeded

import os
import json
import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
efs_client = boto3.client('efs')
ec2_client = boto3.client('ec2')
ssm_client = boto3.client('ssm')
ecs_client = boto3.client('ecs')


def get_config_from_env():
    """
    Read configuration from environment variables
    
    Returns:
        dict: Configuration dictionary with the following keys:
            - target_directory: Path to the directory to monitor
            - file_count_threshold: Threshold for file count
            - efs_file_system_id: EFS file system ID
            - vpc_id: VPC ID
            - security_group_id: Security group ID (optional)
    
    Raises:
        ValueError: If required environment variables are missing
    """
    target_directory = os.environ.get('TARGET_DIRECTORY')
    if not target_directory:
        raise ValueError("TARGET_DIRECTORY environment variable is required")
    
    threshold_str = os.environ.get('FILE_COUNT_THRESHOLD', '100000')
    try:
        file_count_threshold = int(threshold_str)
    except ValueError:
        raise ValueError(f"FILE_COUNT_THRESHOLD must be a valid integer, got: {threshold_str}")
    
    efs_file_system_id = os.environ.get('EFS_FILE_SYSTEM_ID')
    if not efs_file_system_id:
        raise ValueError("EFS_FILE_SYSTEM_ID environment variable is required")
    
    vpc_id = os.environ.get('VPC_ID')
    if not vpc_id:
        raise ValueError("VPC_ID environment variable is required")
    
    # Optional security group ID
    security_group_id = os.environ.get('SECURITY_GROUP_ID')
    
    # SSM Parameter Store parameter name
    ssm_parameter_name = os.environ.get('SSM_PARAMETER_NAME')
    if not ssm_parameter_name:
        raise ValueError("SSM_PARAMETER_NAME environment variable is required")
    
    # ECS cluster and service names
    ecs_cluster_name = os.environ.get('ECS_CLUSTER_NAME')
    if not ecs_cluster_name:
        raise ValueError("ECS_CLUSTER_NAME environment variable is required")
    
    ecs_service_name = os.environ.get('ECS_SERVICE_NAME')
    if not ecs_service_name:
        raise ValueError("ECS_SERVICE_NAME environment variable is required")
    
    config = {
        'target_directory': target_directory,
        'file_count_threshold': file_count_threshold,
        'efs_file_system_id': efs_file_system_id,
        'vpc_id': vpc_id,
        'ssm_parameter_name': ssm_parameter_name,
        'ecs_cluster_name': ecs_cluster_name,
        'ecs_service_name': ecs_service_name
    }
    
    if security_group_id:
        config['security_group_id'] = security_group_id
    
    return config


def count_files_in_directory(directory_path):
    """
    Count the number of files in the specified directory
    
    Args:
        directory_path (str): Path to the directory to count files in
    
    Returns:
        int: Number of files in the directory
    
    Raises:
        FileNotFoundError: If the directory does not exist
        PermissionError: If the directory cannot be accessed
    """
    if not os.path.exists(directory_path):
        raise FileNotFoundError(f"Directory not found: {directory_path}")
    
    if not os.path.isdir(directory_path):
        raise NotADirectoryError(f"Path is not a directory: {directory_path}")
    
    try:
        file_count = 0
        for entry in os.listdir(directory_path):
            entry_path = os.path.join(directory_path, entry)
            if os.path.isfile(entry_path):
                file_count += 1
        
        return file_count
    except PermissionError as e:
        logger.error(f"Permission denied accessing directory: {directory_path}")
        raise


def check_threshold_exceeded(file_count, threshold):
    """
    Check if file count exceeds the threshold
    
    Args:
        file_count (int): Current number of files
        threshold (int): Threshold value
    
    Returns:
        bool: True if file count exceeds threshold, False otherwise
    """
    return file_count > threshold


def get_existing_mount_targets(file_system_id):
    """
    Get existing mount targets for the specified EFS file system
    
    Args:
        file_system_id (str): EFS file system ID
    
    Returns:
        list: List of mount target dictionaries with the following keys:
            - mount_target_id: Mount target ID
            - ip_address: IP address
            - availability_zone: Availability zone
            - subnet_id: Subnet ID
            - lifecycle_state: Lifecycle state
    
    Raises:
        ClientError: If AWS API call fails
    """
    try:
        logger.info(f"Retrieving existing mount targets for file system: {file_system_id}")
        
        response = efs_client.describe_mount_targets(FileSystemId=file_system_id)
        
        mount_targets = []
        for mt in response.get('MountTargets', []):
            mount_targets.append({
                'mount_target_id': mt['MountTargetId'],
                'ip_address': mt['IpAddress'],
                'availability_zone': mt['AvailabilityZoneName'],
                'subnet_id': mt['SubnetId'],
                'lifecycle_state': mt['LifeCycleState']
            })
        
        logger.info(f"Found {len(mount_targets)} existing mount targets")
        return mount_targets
    
    except ClientError as e:
        logger.error(f"Failed to retrieve mount targets: {e}")
        raise


def find_available_subnet(vpc_id, existing_mount_targets):
    """
    Find an available subnet in the VPC that doesn't have a mount target
    
    Args:
        vpc_id (str): VPC ID
        existing_mount_targets (list): List of existing mount target dictionaries
    
    Returns:
        dict or None: Subnet information with the following keys if available:
            - subnet_id: Subnet ID
            - availability_zone: Availability zone
        Returns None if no available subnet is found
    
    Raises:
        ClientError: If AWS API call fails
    """
    try:
        logger.info(f"Finding available subnets in VPC: {vpc_id}")
        
        # Get all subnets in the VPC
        response = ec2_client.describe_subnets(
            Filters=[
                {
                    'Name': 'vpc-id',
                    'Values': [vpc_id]
                }
            ]
        )
        
        # Extract subnet IDs that already have mount targets
        used_subnet_ids = {mt['subnet_id'] for mt in existing_mount_targets}
        
        # Find first available subnet
        for subnet in response.get('Subnets', []):
            subnet_id = subnet['SubnetId']
            if subnet_id not in used_subnet_ids:
                available_subnet = {
                    'subnet_id': subnet_id,
                    'availability_zone': subnet['AvailabilityZone']
                }
                logger.info(f"Found available subnet: {subnet_id} in AZ: {subnet['AvailabilityZone']}")
                return available_subnet
        
        logger.warning("No available subnets found in VPC")
        return None
    
    except ClientError as e:
        logger.error(f"Failed to find available subnets: {e}")
        raise


def create_mount_target(file_system_id, subnet_id, security_group_id=None):
    """
    Create a new mount target for the EFS file system
    
    Args:
        file_system_id (str): EFS file system ID
        subnet_id (str): Subnet ID where the mount target will be created
        security_group_id (str, optional): Security group ID for the mount target
    
    Returns:
        dict: Mount target information with the following keys:
            - mount_target_id: Mount target ID
            - ip_address: IP address
            - availability_zone: Availability zone
            - subnet_id: Subnet ID
            - lifecycle_state: Lifecycle state
        Returns None if creation fails
    
    Raises:
        ClientError: If AWS API call fails
    """
    import time
    
    try:
        logger.info(f"Creating mount target in subnet: {subnet_id}")
        
        # Prepare create mount target parameters
        create_params = {
            'FileSystemId': file_system_id,
            'SubnetId': subnet_id
        }
        
        # Add security group if provided
        if security_group_id:
            create_params['SecurityGroups'] = [security_group_id]
        
        # Create mount target
        response = efs_client.create_mount_target(**create_params)
        
        mount_target_id = response['MountTargetId']
        logger.info(f"Mount target creation initiated: {mount_target_id}")
        
        # Wait for mount target to become available
        max_wait_time = 300  # 5 minutes
        poll_interval = 10  # 10 seconds
        elapsed_time = 0
        
        while elapsed_time < max_wait_time:
            try:
                # Check mount target status
                mt_response = efs_client.describe_mount_targets(
                    MountTargetId=mount_target_id
                )
                
                if mt_response['MountTargets']:
                    mt = mt_response['MountTargets'][0]
                    lifecycle_state = mt['LifeCycleState']
                    
                    logger.info(f"Mount target {mount_target_id} state: {lifecycle_state}")
                    
                    if lifecycle_state == 'available':
                        logger.info(f"Mount target {mount_target_id} is now available")
                        return {
                            'mount_target_id': mt['MountTargetId'],
                            'ip_address': mt['IpAddress'],
                            'availability_zone': mt['AvailabilityZoneName'],
                            'subnet_id': mt['SubnetId'],
                            'lifecycle_state': mt['LifeCycleState']
                        }
                    elif lifecycle_state in ['creating', 'updating']:
                        # Still in progress, continue waiting
                        time.sleep(poll_interval)
                        elapsed_time += poll_interval
                    else:
                        # Failed state
                        logger.error(f"Mount target creation failed with state: {lifecycle_state}")
                        return None
                        
            except ClientError as e:
                logger.error(f"Error checking mount target status: {e}")
                time.sleep(poll_interval)
                elapsed_time += poll_interval
        
        logger.error(f"Mount target creation timed out after {max_wait_time} seconds")
        return None
    
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        
        if error_code == 'MountTargetConflict':
            logger.warning(f"Mount target already exists in subnet: {subnet_id}")
            return None
        else:
            logger.error(f"Failed to create mount target: {e}")
            raise


def convert_mount_targets_to_json(mount_targets):
    """
    Convert mount target list to JSON format for SSM Parameter Store
    
    Args:
        mount_targets (list): List of mount target dictionaries with the following keys:
            - mount_target_id: Mount target ID
            - ip_address: IP address
            - availability_zone: Availability zone
            - subnet_id: Subnet ID
            - lifecycle_state: Lifecycle state (optional, will be excluded from output)
    
    Returns:
        str: JSON string representation of mount targets in the format:
            {
                "mount_targets": [
                    {
                        "mount_target_id": "fsmt-12345678",
                        "ip_address": "10.0.1.100",
                        "availability_zone": "ap-northeast-1a",
                        "subnet_id": "subnet-12345678"
                    },
                    ...
                ]
            }
    """
    # Filter out lifecycle_state and only include required fields
    filtered_targets = []
    for mt in mount_targets:
        filtered_mt = {
            'mount_target_id': mt['mount_target_id'],
            'ip_address': mt['ip_address'],
            'availability_zone': mt['availability_zone'],
            'subnet_id': mt['subnet_id']
        }
        filtered_targets.append(filtered_mt)
    
    # Create the data structure according to the design document
    data = {
        'mount_targets': filtered_targets
    }
    
    # Convert to JSON string
    return json.dumps(data, indent=2)


def update_ssm_parameter(parameter_name, mount_targets_json):
    """
    Update SSM Parameter Store with the mount target list
    
    Args:
        parameter_name (str): SSM Parameter Store parameter name
        mount_targets_json (str): JSON string representation of mount targets
    
    Returns:
        bool: True if update was successful, False otherwise
    
    Raises:
        ClientError: If AWS API call fails (except for expected error conditions)
    """
    try:
        logger.info(f"Updating SSM Parameter Store: {parameter_name}")
        
        # Update the parameter (or create if it doesn't exist)
        ssm_client.put_parameter(
            Name=parameter_name,
            Value=mount_targets_json,
            Type='String',
            Overwrite=True,
            Description='EFS Mount Target list for Fargate service'
        )
        
        logger.info(f"Successfully updated SSM Parameter Store: {parameter_name}")
        return True
    
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        error_message = e.response.get('Error', {}).get('Message', '')
        
        logger.error(f"Failed to update SSM Parameter Store: {error_code} - {error_message}")
        
        # Log the error but don't raise - this allows the function to continue
        # and maintain existing configuration as per requirement 6.3
        return False


def trigger_ecs_service_deployment(cluster_name, service_name):
    """
    Trigger a forced deployment of the ECS service
    
    This function calls the ECS UpdateService API with forceNewDeployment=True
    to trigger a rolling update of the Fargate service. This ensures that new
    tasks will pick up the updated mount target configuration from SSM Parameter Store.
    
    Args:
        cluster_name (str): ECS cluster name
        service_name (str): ECS service name
    
    Returns:
        bool: True if deployment was triggered successfully, False otherwise
    
    Raises:
        ClientError: If AWS API call fails (except for expected error conditions)
    """
    try:
        logger.info(f"Triggering forced deployment for ECS service: {service_name} in cluster: {cluster_name}")
        
        # Call UpdateService API with forceNewDeployment=True
        response = ecs_client.update_service(
            cluster=cluster_name,
            service=service_name,
            forceNewDeployment=True
        )
        
        # Log deployment information
        service_info = response.get('service', {})
        deployment_count = len(service_info.get('deployments', []))
        
        logger.info(f"Successfully triggered forced deployment for service: {service_name}")
        logger.info(f"Active deployments: {deployment_count}")
        
        return True
    
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        error_message = e.response.get('Error', {}).get('Message', '')
        
        logger.error(f"Failed to trigger ECS service deployment: {error_code} - {error_message}")
        
        # Common error scenarios:
        # - ServiceNotFoundException: Service doesn't exist
        # - ClusterNotFoundException: Cluster doesn't exist
        # - AccessDeniedException: Insufficient permissions
        
        # Log the error but don't raise - this allows the function to continue
        # SSM Parameter Store has already been updated, so the new configuration
        # will be picked up on the next deployment
        return False


def lambda_handler(event, context):
    """
    Main Lambda handler function that orchestrates the entire EFS mount target auto-scaling process
    
    This function implements the following workflow:
    1. Read configuration from environment variables
    2. Count files in the target directory
    3. Check if file count exceeds threshold
    4. If threshold exceeded:
       a. Get existing mount targets
       b. Find available subnet
       c. Create new mount target
       d. Update SSM Parameter Store
       e. Trigger ECS service deployment
    
    Args:
        event: Lambda event object (from EventBridge)
        context: Lambda context object
    
    Returns:
        dict: Response with statusCode and execution details
    
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.3, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3
    """
    execution_result = {
        'timestamp': context.request_id if context else 'unknown',
        'file_count': 0,
        'threshold': 0,
        'threshold_exceeded': False,
        'new_mount_target_created': False,
        'deployment_triggered': False,
        'error': None
    }
    
    try:
        # Log execution start (Requirement 5.1)
        logger.info("=" * 80)
        logger.info("Lambda function execution started")
        logger.info(f"Request ID: {context.request_id if context else 'N/A'}")
        logger.info(f"Event: {json.dumps(event)}")
        logger.info("=" * 80)
        
        # Step 1: Read configuration from environment variables (Requirement 7.1, 7.2, 7.3)
        logger.info("Step 1: Reading configuration from environment variables")
        try:
            config = get_config_from_env()
            logger.info(f"Configuration loaded successfully:")
            logger.info(f"  - Target Directory: {config['target_directory']}")
            logger.info(f"  - File Count Threshold: {config['file_count_threshold']}")
            logger.info(f"  - EFS File System ID: {config['efs_file_system_id']}")
            logger.info(f"  - VPC ID: {config['vpc_id']}")
            logger.info(f"  - SSM Parameter Name: {config['ssm_parameter_name']}")
            logger.info(f"  - ECS Cluster: {config['ecs_cluster_name']}")
            logger.info(f"  - ECS Service: {config['ecs_service_name']}")
            
            execution_result['threshold'] = config['file_count_threshold']
        except ValueError as e:
            error_msg = f"Configuration error: {str(e)}"
            logger.error(error_msg)
            execution_result['error'] = error_msg
            return {
                'statusCode': 400,
                'body': json.dumps(execution_result)
            }
        
        # Step 2: Count files in target directory (Requirement 1.2)
        logger.info(f"Step 2: Counting files in directory: {config['target_directory']}")
        try:
            file_count = count_files_in_directory(config['target_directory'])
            execution_result['file_count'] = file_count
            
            # Log file count result (Requirement 5.2)
            logger.info(f"File count result: {file_count} files")
            logger.info(f"Threshold: {config['file_count_threshold']} files")
        except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
            # Error accessing EFS (Requirement 6.1)
            error_msg = f"Failed to access EFS directory: {str(e)}"
            logger.error(error_msg)
            logger.error("Aborting execution due to EFS access failure")
            execution_result['error'] = error_msg
            return {
                'statusCode': 500,
                'body': json.dumps(execution_result)
            }
        
        # Step 3: Check if threshold is exceeded (Requirement 1.3)
        logger.info("Step 3: Checking if threshold is exceeded")
        threshold_exceeded = check_threshold_exceeded(file_count, config['file_count_threshold'])
        execution_result['threshold_exceeded'] = threshold_exceeded
        
        if threshold_exceeded:
            logger.warning(f"⚠️  THRESHOLD EXCEEDED: {file_count} > {config['file_count_threshold']}")
            logger.info("Initiating mount target creation process")
        else:
            logger.info(f"✓ Threshold not exceeded: {file_count} <= {config['file_count_threshold']}")
            logger.info("No action required")
            logger.info("=" * 80)
            logger.info("Lambda function execution completed successfully")
            logger.info("=" * 80)
            return {
                'statusCode': 200,
                'body': json.dumps(execution_result)
            }
        
        # Step 4: Get existing mount targets (Requirement 1.4)
        logger.info("Step 4: Retrieving existing mount targets")
        try:
            existing_mount_targets = get_existing_mount_targets(config['efs_file_system_id'])
            logger.info(f"Found {len(existing_mount_targets)} existing mount targets:")
            for mt in existing_mount_targets:
                logger.info(f"  - {mt['mount_target_id']} in {mt['availability_zone']} (subnet: {mt['subnet_id']})")
        except ClientError as e:
            error_msg = f"Failed to retrieve existing mount targets: {str(e)}"
            logger.error(error_msg)
            execution_result['error'] = error_msg
            return {
                'statusCode': 500,
                'body': json.dumps(execution_result)
            }
        
        # Step 5: Find available subnet (Requirement 1.4)
        logger.info("Step 5: Finding available subnet for new mount target")
        try:
            available_subnet = find_available_subnet(config['vpc_id'], existing_mount_targets)
            
            if not available_subnet:
                # No available subnets (Requirement 6.2)
                warning_msg = "No available subnets found - all AZs already have mount targets"
                logger.warning(warning_msg)
                logger.info("Skipping mount target creation")
                logger.info("=" * 80)
                logger.info("Lambda function execution completed (no action taken)")
                logger.info("=" * 80)
                execution_result['error'] = warning_msg
                return {
                    'statusCode': 200,
                    'body': json.dumps(execution_result)
                }
            
            logger.info(f"Available subnet found: {available_subnet['subnet_id']} in {available_subnet['availability_zone']}")
        except ClientError as e:
            error_msg = f"Failed to find available subnet: {str(e)}"
            logger.error(error_msg)
            execution_result['error'] = error_msg
            return {
                'statusCode': 500,
                'body': json.dumps(execution_result)
            }
        
        # Step 6: Create new mount target (Requirement 1.4, 5.3)
        logger.info("Step 6: Creating new mount target")
        logger.info(f"Mount target creation started for subnet: {available_subnet['subnet_id']}")
        
        try:
            security_group_id = config.get('security_group_id')
            new_mount_target = create_mount_target(
                config['efs_file_system_id'],
                available_subnet['subnet_id'],
                security_group_id
            )
            
            if not new_mount_target:
                # Mount target creation failed (Requirement 6.3)
                error_msg = "Mount target creation failed"
                logger.error(error_msg)
                logger.error("Skipping SSM Parameter Store update and ECS deployment")
                execution_result['error'] = error_msg
                return {
                    'statusCode': 500,
                    'body': json.dumps(execution_result)
                }
            
            # Log mount target creation completion (Requirement 5.3)
            logger.info(f"✓ Mount target created successfully: {new_mount_target['mount_target_id']}")
            logger.info(f"  - IP Address: {new_mount_target['ip_address']}")
            logger.info(f"  - Availability Zone: {new_mount_target['availability_zone']}")
            logger.info(f"  - Subnet ID: {new_mount_target['subnet_id']}")
            logger.info(f"  - Lifecycle State: {new_mount_target['lifecycle_state']}")
            
            execution_result['new_mount_target_created'] = True
            execution_result['new_mount_target_id'] = new_mount_target['mount_target_id']
            
        except ClientError as e:
            # Mount target creation failed (Requirement 6.3)
            error_msg = f"Mount target creation failed: {str(e)}"
            logger.error(error_msg)
            logger.error("Skipping SSM Parameter Store update and ECS deployment")
            execution_result['error'] = error_msg
            return {
                'statusCode': 500,
                'body': json.dumps(execution_result)
            }
        
        # Step 7: Update SSM Parameter Store (Requirement 1.5)
        logger.info("Step 7: Updating SSM Parameter Store with new mount target list")
        
        # Get updated list of all mount targets
        try:
            all_mount_targets = get_existing_mount_targets(config['efs_file_system_id'])
            logger.info(f"Total mount targets after creation: {len(all_mount_targets)}")
        except ClientError as e:
            error_msg = f"Failed to retrieve updated mount target list: {str(e)}"
            logger.error(error_msg)
            execution_result['error'] = error_msg
            return {
                'statusCode': 500,
                'body': json.dumps(execution_result)
            }
        
        # Convert to JSON and update SSM
        mount_targets_json = convert_mount_targets_to_json(all_mount_targets)
        logger.info(f"Mount target list JSON: {mount_targets_json}")
        
        ssm_update_success = update_ssm_parameter(
            config['ssm_parameter_name'],
            mount_targets_json
        )
        
        if not ssm_update_success:
            # SSM update failed - log but continue (Requirement 6.3)
            logger.warning("SSM Parameter Store update failed, but mount target was created")
            logger.warning("Configuration will be updated on next successful execution")
            logger.info("Skipping ECS deployment due to SSM update failure")
            execution_result['error'] = "SSM Parameter Store update failed"
            return {
                'statusCode': 500,
                'body': json.dumps(execution_result)
            }
        
        logger.info("✓ SSM Parameter Store updated successfully")
        
        # Step 8: Trigger ECS service deployment (Requirement 2.3)
        logger.info("Step 8: Triggering ECS service deployment")
        
        deployment_success = trigger_ecs_service_deployment(
            config['ecs_cluster_name'],
            config['ecs_service_name']
        )
        
        if deployment_success:
            logger.info("✓ ECS service deployment triggered successfully")
            execution_result['deployment_triggered'] = True
        else:
            logger.warning("ECS service deployment failed to trigger")
            logger.warning("New mount target configuration will be applied on next deployment")
            execution_result['error'] = "ECS deployment trigger failed"
        
        # Log execution completion (Requirement 5.1)
        logger.info("=" * 80)
        logger.info("Lambda function execution completed successfully")
        logger.info(f"Summary:")
        logger.info(f"  - Files counted: {execution_result['file_count']}")
        logger.info(f"  - Threshold: {execution_result['threshold']}")
        logger.info(f"  - Threshold exceeded: {execution_result['threshold_exceeded']}")
        logger.info(f"  - New mount target created: {execution_result['new_mount_target_created']}")
        if execution_result['new_mount_target_created']:
            logger.info(f"  - Mount target ID: {execution_result.get('new_mount_target_id', 'N/A')}")
        logger.info(f"  - Deployment triggered: {execution_result['deployment_triggered']}")
        logger.info("=" * 80)
        
        return {
            'statusCode': 200,
            'body': json.dumps(execution_result)
        }
    
    except Exception as e:
        # Catch-all for unexpected errors (Requirement 5.4, 6.1)
        error_msg = f"Unexpected error occurred: {str(e)}"
        logger.error("=" * 80)
        logger.error("UNEXPECTED ERROR")
        logger.error(error_msg)
        logger.exception("Full exception details:")
        logger.error("=" * 80)
        
        execution_result['error'] = error_msg
        
        return {
            'statusCode': 500,
            'body': json.dumps(execution_result)
        }
