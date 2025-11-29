# Fargate Application for EFS Mount Target Auto-scaling
# This application mounts multiple EFS mount targets and distributes file access

import os
import json
import logging
import hashlib
import subprocess
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_mount_targets_from_ssm():
    """
    Retrieve mount target list from SSM Parameter Store
    
    Returns:
        list: List of mount target dictionaries, or default configuration on failure
        
    Requirements: 2.1, 6.4, 7.5
    """
    # Read SSM parameter name from environment variable
    ssm_parameter_name = os.environ.get('SSM_PARAMETER_NAME')
    
    if not ssm_parameter_name:
        logger.error("SSM_PARAMETER_NAME environment variable not set")
        return get_default_mount_targets()
    
    logger.info(f"Retrieving mount targets from SSM Parameter Store: {ssm_parameter_name}")
    
    try:
        # Create SSM client
        ssm_client = boto3.client('ssm')
        
        # Call GetParameter API
        response = ssm_client.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=False
        )
        
        # Parse JSON data
        parameter_value = response['Parameter']['Value']
        data = json.loads(parameter_value)
        
        # Extract mount targets list
        mount_targets = data.get('mount_targets', [])
        
        if not mount_targets:
            logger.warning("No mount targets found in SSM parameter, using default configuration")
            return get_default_mount_targets()
        
        logger.info(f"Successfully retrieved {len(mount_targets)} mount targets from SSM")
        return mount_targets
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"Failed to retrieve SSM parameter: {error_code} - {str(e)}")
        logger.info("Using default mount target configuration")
        return get_default_mount_targets()
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from SSM parameter: {str(e)}")
        logger.info("Using default mount target configuration")
        return get_default_mount_targets()
        
    except Exception as e:
        logger.error(f"Unexpected error retrieving mount targets: {str(e)}")
        logger.info("Using default mount target configuration")
        return get_default_mount_targets()


def get_default_mount_targets():
    """
    Return default mount target configuration
    
    Returns:
        list: Default mount target list (empty list or predefined defaults)
    """
    # Return empty list as default - application should handle this gracefully
    # In production, this could be populated with initial mount targets
    logger.info("Using default mount target configuration (empty list)")
    return []


def mount_nfs_targets(mount_targets):
    """
    Mount each NFS mount target to a unique mount point
    
    Args:
        mount_targets: List of mount target dictionaries with ip_address and mount_target_id
        
    Returns:
        list: List of successfully mounted mount points with their indices
        
    Requirements: 2.2, 5.5, 6.5
    """
    logger.info(f"Starting NFS mount process for {len(mount_targets)} mount targets")
    
    successfully_mounted = []
    
    for index, mount_target in enumerate(mount_targets):
        mount_point = f"/mnt/efs-{index}"
        mount_target_id = mount_target.get('mount_target_id', 'unknown')
        ip_address = mount_target.get('ip_address')
        
        if not ip_address:
            logger.error(f"Mount target {mount_target_id} missing ip_address, skipping")
            continue
        
        try:
            # Create mount point directory if it doesn't exist
            logger.info(f"Creating mount point directory: {mount_point}")
            os.makedirs(mount_point, exist_ok=True)
            
            # Mount the NFS target
            # NFS mount command: mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 <ip_address>:/ <mount_point>
            nfs_source = f"{ip_address}:/"
            mount_command = [
                'mount',
                '-t', 'nfs4',
                '-o', 'nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2',
                nfs_source,
                mount_point
            ]
            
            logger.info(f"Mounting {mount_target_id} ({ip_address}) to {mount_point}")
            
            # Execute mount command
            result = subprocess.run(
                mount_command,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info(f"Successfully mounted {mount_target_id} to {mount_point}")
                successfully_mounted.append({
                    'index': index,
                    'mount_point': mount_point,
                    'mount_target_id': mount_target_id,
                    'ip_address': ip_address
                })
            else:
                logger.error(f"Failed to mount {mount_target_id}: {result.stderr}")
                logger.info(f"Skipping mount target {mount_target_id} and continuing with others")
                
        except subprocess.TimeoutExpired:
            logger.error(f"Mount command timed out for {mount_target_id}")
            logger.info(f"Skipping mount target {mount_target_id} and continuing with others")
            
        except OSError as e:
            logger.error(f"Failed to create mount point {mount_point}: {str(e)}")
            logger.info(f"Skipping mount target {mount_target_id} and continuing with others")
            
        except Exception as e:
            logger.error(f"Unexpected error mounting {mount_target_id}: {str(e)}")
            logger.info(f"Skipping mount target {mount_target_id} and continuing with others")
    
    logger.info(f"NFS mount process complete: {len(successfully_mounted)}/{len(mount_targets)} mount targets successfully mounted")
    
    if len(successfully_mounted) == 0 and len(mount_targets) > 0:
        logger.error("Failed to mount any mount targets - service may not function correctly")
    
    return successfully_mounted


def initialize():
    """
    Initialize the Fargate application
    - Retrieve mount target list from SSM Parameter Store
    - Mount all mount targets
    
    Returns:
        tuple: (mount_targets, successfully_mounted)
    """
    logger.info("Initializing Fargate application")
    
    # Retrieve mount targets from SSM Parameter Store
    mount_targets = get_mount_targets_from_ssm()
    
    # Mount all mount targets
    successfully_mounted = mount_nfs_targets(mount_targets)
    
    logger.info(f"Initialization complete with {len(successfully_mounted)}/{len(mount_targets)} mount targets successfully mounted")
    return mount_targets, successfully_mounted


def calculate_file_path_hash(file_path):
    """
    Calculate hash value from file path
    
    Args:
        file_path: File path string
        
    Returns:
        int: Hash value as integer
        
    Requirements: 3.1
    """
    # Use hashlib to create a consistent hash
    # SHA256 provides good distribution and consistency
    hash_object = hashlib.sha256(file_path.encode('utf-8'))
    # Convert hex digest to integer
    hash_value = int(hash_object.hexdigest(), 16)
    return hash_value


def select_mount_target_index(file_path, num_mount_targets):
    """
    Select mount target index using hash-based routing
    
    Args:
        file_path: File path string
        num_mount_targets: Number of available mount targets
        
    Returns:
        int: Selected mount target index (0 to num_mount_targets-1)
        
    Requirements: 3.1, 3.2
    """
    if num_mount_targets <= 0:
        raise ValueError("Number of mount targets must be greater than 0")
    
    # Calculate hash value
    hash_value = calculate_file_path_hash(file_path)
    
    # Perform modulo operation to get index
    index = hash_value % num_mount_targets
    
    return index


def resolve_file_path(original_path, mount_target_index):
    """
    Construct complete file path from original path and mount target index
    
    Args:
        original_path: Original file path (relative or absolute)
        mount_target_index: Selected mount target index
        
    Returns:
        str: Complete file path with mount point prefix
        
    Requirements: 3.3
    """
    # Construct mount point path
    mount_point = f"/mnt/efs-{mount_target_index}"
    
    # Remove leading slash from original path if present to avoid double slashes
    clean_path = original_path.lstrip('/')
    
    # Construct complete file path
    complete_path = os.path.join(mount_point, clean_path)
    
    return complete_path


def get_file_path(original_path, mount_targets):
    """
    Calculate hash-based routing for file access and return complete file path
    
    This function implements the hash-based routing algorithm:
    1. Calculate hash value from file path
    2. Select mount target using modulo operation
    3. Construct complete file path with selected mount point
    
    Args:
        original_path: Original file path
        mount_targets: List of mount targets (or successfully mounted list)
        
    Returns:
        str: Complete file path with selected mount point
        
    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    if not mount_targets:
        raise ValueError("No mount targets available")
    
    # Get number of mount targets
    num_mount_targets = len(mount_targets)
    
    # Select mount target index using hash-based routing
    index = select_mount_target_index(original_path, num_mount_targets)
    
    # Resolve complete file path
    complete_path = resolve_file_path(original_path, index)
    
    return complete_path


def read_file(original_path, mount_targets, mode='r', encoding='utf-8'):
    """
    Read file content using hash-based routing
    
    Args:
        original_path: Original file path
        mount_targets: List of mount targets (or successfully mounted list)
        mode: File open mode (default: 'r' for text, 'rb' for binary)
        encoding: Text encoding (default: 'utf-8', ignored for binary mode)
        
    Returns:
        File content (str for text mode, bytes for binary mode)
        
    Raises:
        ValueError: If no mount targets available
        FileNotFoundError: If file does not exist
        IOError: If file cannot be read
        
    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    # Get the complete file path using hash-based routing
    complete_path = get_file_path(original_path, mount_targets)
    
    logger.debug(f"Reading file: {original_path} -> {complete_path}")
    
    # Read the file
    try:
        if 'b' in mode:
            # Binary mode
            with open(complete_path, mode) as f:
                return f.read()
        else:
            # Text mode
            with open(complete_path, mode, encoding=encoding) as f:
                return f.read()
    except Exception as e:
        logger.error(f"Failed to read file {original_path}: {str(e)}")
        raise


def write_file(original_path, content, mount_targets, mode='w', encoding='utf-8'):
    """
    Write content to file using hash-based routing
    
    Args:
        original_path: Original file path
        content: Content to write (str for text mode, bytes for binary mode)
        mount_targets: List of mount targets (or successfully mounted list)
        mode: File open mode (default: 'w' for text, 'wb' for binary)
        encoding: Text encoding (default: 'utf-8', ignored for binary mode)
        
    Returns:
        str: Complete file path where content was written
        
    Raises:
        ValueError: If no mount targets available
        IOError: If file cannot be written
        
    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    # Get the complete file path using hash-based routing
    complete_path = get_file_path(original_path, mount_targets)
    
    logger.debug(f"Writing file: {original_path} -> {complete_path}")
    
    # Ensure parent directory exists
    parent_dir = os.path.dirname(complete_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    
    # Write the file
    try:
        if 'b' in mode:
            # Binary mode
            with open(complete_path, mode) as f:
                f.write(content)
        else:
            # Text mode
            with open(complete_path, mode, encoding=encoding) as f:
                f.write(content)
        
        logger.debug(f"Successfully wrote file: {complete_path}")
        return complete_path
        
    except Exception as e:
        logger.error(f"Failed to write file {original_path}: {str(e)}")
        raise


def append_file(original_path, content, mount_targets, encoding='utf-8'):
    """
    Append content to file using hash-based routing
    
    Args:
        original_path: Original file path
        content: Content to append (str for text mode, bytes for binary mode)
        mount_targets: List of mount targets (or successfully mounted list)
        encoding: Text encoding (default: 'utf-8', ignored for binary mode)
        
    Returns:
        str: Complete file path where content was appended
        
    Raises:
        ValueError: If no mount targets available
        IOError: If file cannot be written
        
    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    # Determine mode based on content type
    if isinstance(content, bytes):
        mode = 'ab'
    else:
        mode = 'a'
    
    return write_file(original_path, content, mount_targets, mode=mode, encoding=encoding)


def file_exists(original_path, mount_targets):
    """
    Check if file exists using hash-based routing
    
    Args:
        original_path: Original file path
        mount_targets: List of mount targets (or successfully mounted list)
        
    Returns:
        bool: True if file exists, False otherwise
        
    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    try:
        complete_path = get_file_path(original_path, mount_targets)
        return os.path.exists(complete_path)
    except ValueError:
        return False


def delete_file(original_path, mount_targets):
    """
    Delete file using hash-based routing
    
    Args:
        original_path: Original file path
        mount_targets: List of mount targets (or successfully mounted list)
        
    Returns:
        bool: True if file was deleted, False if file did not exist
        
    Raises:
        ValueError: If no mount targets available
        IOError: If file cannot be deleted
        
    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    complete_path = get_file_path(original_path, mount_targets)
    
    logger.debug(f"Deleting file: {original_path} -> {complete_path}")
    
    try:
        if os.path.exists(complete_path):
            os.remove(complete_path)
            logger.debug(f"Successfully deleted file: {complete_path}")
            return True
        else:
            logger.debug(f"File does not exist: {complete_path}")
            return False
    except Exception as e:
        logger.error(f"Failed to delete file {original_path}: {str(e)}")
        raise


if __name__ == "__main__":
    initialize()
    logger.info("Fargate application started")
