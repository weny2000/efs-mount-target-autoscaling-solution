# Unit tests for Fargate application
import pytest
import sys
import os
import json
import subprocess
from unittest.mock import patch, MagicMock, call, mock_open
from botocore.exceptions import ClientError

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fargate.app import (
    get_mount_targets_from_ssm, 
    get_default_mount_targets, 
    mount_nfs_targets,
    initialize,
    read_file,
    write_file,
    append_file,
    file_exists,
    delete_file,
    get_file_path
)


class TestSSMParameterStoreRetrieval:
    """Test SSM Parameter Store retrieval functionality"""
    
    def test_get_mount_targets_success(self):
        """Test successful retrieval of mount targets from SSM"""
        # Arrange
        mock_mount_targets = [
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
        
        mock_response = {
            'Parameter': {
                'Value': json.dumps({'mount_targets': mock_mount_targets})
            }
        }
        
        with patch.dict(os.environ, {'SSM_PARAMETER_NAME': '/app/efs/mount-targets'}):
            with patch('boto3.client') as mock_boto_client:
                mock_ssm = MagicMock()
                mock_ssm.get_parameter.return_value = mock_response
                mock_boto_client.return_value = mock_ssm
                
                # Act
                result = get_mount_targets_from_ssm()
                
                # Assert
                assert len(result) == 2
                assert result[0]['mount_target_id'] == 'fsmt-12345678'
                assert result[1]['mount_target_id'] == 'fsmt-87654321'
                mock_ssm.get_parameter.assert_called_once_with(
                    Name='/app/efs/mount-targets',
                    WithDecryption=False
                )
    
    def test_get_mount_targets_missing_env_var(self):
        """Test behavior when SSM_PARAMETER_NAME environment variable is not set"""
        # Arrange
        with patch.dict(os.environ, {}, clear=True):
            # Act
            result = get_mount_targets_from_ssm()
            
            # Assert
            assert result == []
    
    def test_get_mount_targets_parameter_not_found(self):
        """Test behavior when SSM parameter does not exist"""
        # Arrange
        error_response = {'Error': {'Code': 'ParameterNotFound'}}
        
        with patch.dict(os.environ, {'SSM_PARAMETER_NAME': '/app/efs/mount-targets'}):
            with patch('boto3.client') as mock_boto_client:
                mock_ssm = MagicMock()
                mock_ssm.get_parameter.side_effect = ClientError(error_response, 'GetParameter')
                mock_boto_client.return_value = mock_ssm
                
                # Act
                result = get_mount_targets_from_ssm()
                
                # Assert
                assert result == []
    
    def test_get_mount_targets_invalid_json(self):
        """Test behavior when SSM parameter contains invalid JSON"""
        # Arrange
        mock_response = {
            'Parameter': {
                'Value': 'invalid json {'
            }
        }
        
        with patch.dict(os.environ, {'SSM_PARAMETER_NAME': '/app/efs/mount-targets'}):
            with patch('boto3.client') as mock_boto_client:
                mock_ssm = MagicMock()
                mock_ssm.get_parameter.return_value = mock_response
                mock_boto_client.return_value = mock_ssm
                
                # Act
                result = get_mount_targets_from_ssm()
                
                # Assert
                assert result == []
    
    def test_get_mount_targets_empty_list(self):
        """Test behavior when SSM parameter contains empty mount targets list"""
        # Arrange
        mock_response = {
            'Parameter': {
                'Value': json.dumps({'mount_targets': []})
            }
        }
        
        with patch.dict(os.environ, {'SSM_PARAMETER_NAME': '/app/efs/mount-targets'}):
            with patch('boto3.client') as mock_boto_client:
                mock_ssm = MagicMock()
                mock_ssm.get_parameter.return_value = mock_response
                mock_boto_client.return_value = mock_ssm
                
                # Act
                result = get_mount_targets_from_ssm()
                
                # Assert
                assert result == []
    
    def test_get_mount_targets_access_denied(self):
        """Test behavior when access to SSM parameter is denied"""
        # Arrange
        error_response = {'Error': {'Code': 'AccessDeniedException'}}
        
        with patch.dict(os.environ, {'SSM_PARAMETER_NAME': '/app/efs/mount-targets'}):
            with patch('boto3.client') as mock_boto_client:
                mock_ssm = MagicMock()
                mock_ssm.get_parameter.side_effect = ClientError(error_response, 'GetParameter')
                mock_boto_client.return_value = mock_ssm
                
                # Act
                result = get_mount_targets_from_ssm()
                
                # Assert
                assert result == []
    
    def test_get_default_mount_targets(self):
        """Test default mount targets function"""
        # Act
        result = get_default_mount_targets()
        
        # Assert
        assert isinstance(result, list)
        assert result == []



class TestNFSMountFunctionality:
    """Test NFS mount functionality"""
    
    def test_mount_nfs_targets_success(self):
        """Test successful mounting of all mount targets"""
        # Arrange
        mount_targets = [
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
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        
        with patch('os.makedirs') as mock_makedirs:
            with patch('subprocess.run', return_value=mock_result) as mock_subprocess:
                # Act
                result = mount_nfs_targets(mount_targets)
                
                # Assert
                assert len(result) == 2
                assert result[0]['mount_point'] == '/mnt/efs-0'
                assert result[0]['mount_target_id'] == 'fsmt-12345678'
                assert result[1]['mount_point'] == '/mnt/efs-1'
                assert result[1]['mount_target_id'] == 'fsmt-87654321'
                
                # Verify mount commands were called correctly
                assert mock_subprocess.call_count == 2
                assert mock_makedirs.call_count == 2
    
    def test_mount_nfs_targets_partial_failure(self):
        """Test mounting when some mount targets fail"""
        # Arrange
        mount_targets = [
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
        
        # First mount succeeds, second fails
        mock_result_success = MagicMock()
        mock_result_success.returncode = 0
        mock_result_success.stderr = ""
        
        mock_result_failure = MagicMock()
        mock_result_failure.returncode = 1
        mock_result_failure.stderr = "mount.nfs4: Connection timed out"
        
        with patch('os.makedirs'):
            with patch('subprocess.run', side_effect=[mock_result_success, mock_result_failure]):
                # Act
                result = mount_nfs_targets(mount_targets)
                
                # Assert
                assert len(result) == 1
                assert result[0]['mount_target_id'] == 'fsmt-12345678'
    
    def test_mount_nfs_targets_missing_ip_address(self):
        """Test mounting when mount target is missing ip_address"""
        # Arrange
        mount_targets = [
            {
                "mount_target_id": "fsmt-12345678",
                "availability_zone": "ap-northeast-1a",
                "subnet_id": "subnet-12345678"
                # Missing ip_address
            }
        ]
        
        # Act
        result = mount_nfs_targets(mount_targets)
        
        # Assert
        assert len(result) == 0
    
    def test_mount_nfs_targets_timeout(self):
        """Test mounting when mount command times out"""
        # Arrange
        mount_targets = [
            {
                "mount_target_id": "fsmt-12345678",
                "ip_address": "10.0.1.100",
                "availability_zone": "ap-northeast-1a",
                "subnet_id": "subnet-12345678"
            }
        ]
        
        with patch('os.makedirs'):
            with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('mount', 30)):
                # Act
                result = mount_nfs_targets(mount_targets)
                
                # Assert
                assert len(result) == 0
    
    def test_mount_nfs_targets_directory_creation_failure(self):
        """Test mounting when directory creation fails"""
        # Arrange
        mount_targets = [
            {
                "mount_target_id": "fsmt-12345678",
                "ip_address": "10.0.1.100",
                "availability_zone": "ap-northeast-1a",
                "subnet_id": "subnet-12345678"
            }
        ]
        
        with patch('os.makedirs', side_effect=OSError("Permission denied")):
            # Act
            result = mount_nfs_targets(mount_targets)
            
            # Assert
            assert len(result) == 0
    
    def test_mount_nfs_targets_empty_list(self):
        """Test mounting with empty mount targets list"""
        # Arrange
        mount_targets = []
        
        # Act
        result = mount_nfs_targets(mount_targets)
        
        # Assert
        assert len(result) == 0
    
    def test_mount_nfs_targets_all_failures(self):
        """Test mounting when all mount targets fail"""
        # Arrange
        mount_targets = [
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
        
        mock_result_failure = MagicMock()
        mock_result_failure.returncode = 1
        mock_result_failure.stderr = "mount.nfs4: Connection refused"
        
        with patch('os.makedirs'):
            with patch('subprocess.run', return_value=mock_result_failure):
                # Act
                result = mount_nfs_targets(mount_targets)
                
                # Assert
                assert len(result) == 0



class TestInitialization:
    """Test application initialization"""
    
    def test_initialize_success(self):
        """Test successful initialization with mount targets"""
        # Arrange
        mock_mount_targets = [
            {
                "mount_target_id": "fsmt-12345678",
                "ip_address": "10.0.1.100",
                "availability_zone": "ap-northeast-1a",
                "subnet_id": "subnet-12345678"
            }
        ]
        
        mock_response = {
            'Parameter': {
                'Value': json.dumps({'mount_targets': mock_mount_targets})
            }
        }
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        
        with patch.dict(os.environ, {'SSM_PARAMETER_NAME': '/app/efs/mount-targets'}):
            with patch('boto3.client') as mock_boto_client:
                mock_ssm = MagicMock()
                mock_ssm.get_parameter.return_value = mock_response
                mock_boto_client.return_value = mock_ssm
                
                with patch('os.makedirs'):
                    with patch('subprocess.run', return_value=mock_result):
                        # Act
                        mount_targets, successfully_mounted = initialize()
                        
                        # Assert
                        assert len(mount_targets) == 1
                        assert len(successfully_mounted) == 1
                        assert successfully_mounted[0]['mount_target_id'] == 'fsmt-12345678'
    
    def test_initialize_with_mount_failure(self):
        """Test initialization when mount fails"""
        # Arrange
        mock_mount_targets = [
            {
                "mount_target_id": "fsmt-12345678",
                "ip_address": "10.0.1.100",
                "availability_zone": "ap-northeast-1a",
                "subnet_id": "subnet-12345678"
            }
        ]
        
        mock_response = {
            'Parameter': {
                'Value': json.dumps({'mount_targets': mock_mount_targets})
            }
        }
        
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "mount failed"
        
        with patch.dict(os.environ, {'SSM_PARAMETER_NAME': '/app/efs/mount-targets'}):
            with patch('boto3.client') as mock_boto_client:
                mock_ssm = MagicMock()
                mock_ssm.get_parameter.return_value = mock_response
                mock_boto_client.return_value = mock_ssm
                
                with patch('os.makedirs'):
                    with patch('subprocess.run', return_value=mock_result):
                        # Act
                        mount_targets, successfully_mounted = initialize()
                        
                        # Assert
                        assert len(mount_targets) == 1
                        assert len(successfully_mounted) == 0


class TestFileAccessOperations:
    """Test file access operations with hash-based routing"""
    
    def test_read_file_text_mode(self):
        """Test reading file in text mode"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        file_content = "Hello, World!"
        
        with patch('builtins.open', mock_open(read_data=file_content)):
            # Act
            result = read_file('test.txt', mount_targets)
            
            # Assert
            assert result == file_content
    
    def test_read_file_binary_mode(self):
        """Test reading file in binary mode"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        file_content = b"Binary content"
        
        with patch('builtins.open', mock_open(read_data=file_content)):
            # Act
            result = read_file('test.bin', mount_targets, mode='rb')
            
            # Assert
            assert result == file_content
    
    def test_read_file_not_found(self):
        """Test reading non-existent file"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        
        with patch('builtins.open', side_effect=FileNotFoundError("File not found")):
            # Act & Assert
            with pytest.raises(FileNotFoundError):
                read_file('nonexistent.txt', mount_targets)
    
    def test_read_file_no_mount_targets(self):
        """Test reading file with no mount targets"""
        # Arrange
        mount_targets = []
        
        # Act & Assert
        with pytest.raises(ValueError, match="No mount targets available"):
            read_file('test.txt', mount_targets)
    
    def test_write_file_text_mode(self):
        """Test writing file in text mode"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        content = "Hello, World!"
        
        m = mock_open()
        with patch('builtins.open', m):
            with patch('os.makedirs'):
                with patch('os.path.dirname', return_value='/mnt/efs-0'):
                    # Act
                    result = write_file('test.txt', content, mount_targets)
                    
                    # Assert
                    assert '/mnt/efs-0' in result
                    m.assert_called_once()
    
    def test_write_file_binary_mode(self):
        """Test writing file in binary mode"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        content = b"Binary content"
        
        m = mock_open()
        with patch('builtins.open', m):
            with patch('os.makedirs'):
                with patch('os.path.dirname', return_value='/mnt/efs-0'):
                    # Act
                    result = write_file('test.bin', content, mount_targets, mode='wb')
                    
                    # Assert
                    assert '/mnt/efs-0' in result
                    m.assert_called_once()
    
    def test_write_file_creates_parent_directory(self):
        """Test that write_file creates parent directory if needed"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        content = "Hello, World!"
        
        m = mock_open()
        with patch('builtins.open', m):
            with patch('os.makedirs') as mock_makedirs:
                with patch('os.path.dirname', return_value='/mnt/efs-0/subdir'):
                    # Act
                    write_file('subdir/test.txt', content, mount_targets)
                    
                    # Assert
                    mock_makedirs.assert_called_once()
    
    def test_write_file_no_mount_targets(self):
        """Test writing file with no mount targets"""
        # Arrange
        mount_targets = []
        content = "Hello, World!"
        
        # Act & Assert
        with pytest.raises(ValueError, match="No mount targets available"):
            write_file('test.txt', content, mount_targets)
    
    def test_append_file_text(self):
        """Test appending text to file"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        content = "Appended text"
        
        m = mock_open()
        with patch('builtins.open', m):
            with patch('os.makedirs'):
                with patch('os.path.dirname', return_value='/mnt/efs-0'):
                    # Act
                    result = append_file('test.txt', content, mount_targets)
                    
                    # Assert
                    assert '/mnt/efs-0' in result
                    # Verify file was opened in append mode
                    m.assert_called_once()
    
    def test_append_file_binary(self):
        """Test appending binary content to file"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        content = b"Binary content"
        
        m = mock_open()
        with patch('builtins.open', m):
            with patch('os.makedirs'):
                with patch('os.path.dirname', return_value='/mnt/efs-0'):
                    # Act
                    result = append_file('test.bin', content, mount_targets)
                    
                    # Assert
                    assert '/mnt/efs-0' in result
                    m.assert_called_once()
    
    def test_file_exists_true(self):
        """Test checking if file exists (file exists)"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        
        with patch('os.path.exists', return_value=True):
            # Act
            result = file_exists('test.txt', mount_targets)
            
            # Assert
            assert result is True
    
    def test_file_exists_false(self):
        """Test checking if file exists (file does not exist)"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        
        with patch('os.path.exists', return_value=False):
            # Act
            result = file_exists('test.txt', mount_targets)
            
            # Assert
            assert result is False
    
    def test_file_exists_no_mount_targets(self):
        """Test checking if file exists with no mount targets"""
        # Arrange
        mount_targets = []
        
        # Act
        result = file_exists('test.txt', mount_targets)
        
        # Assert
        assert result is False
    
    def test_delete_file_success(self):
        """Test deleting existing file"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        
        with patch('os.path.exists', return_value=True):
            with patch('os.remove') as mock_remove:
                # Act
                result = delete_file('test.txt', mount_targets)
                
                # Assert
                assert result is True
                mock_remove.assert_called_once()
    
    def test_delete_file_not_exists(self):
        """Test deleting non-existent file"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0}
        ]
        
        with patch('os.path.exists', return_value=False):
            # Act
            result = delete_file('test.txt', mount_targets)
            
            # Assert
            assert result is False
    
    def test_delete_file_no_mount_targets(self):
        """Test deleting file with no mount targets"""
        # Arrange
        mount_targets = []
        
        # Act & Assert
        with pytest.raises(ValueError, match="No mount targets available"):
            delete_file('test.txt', mount_targets)
    
    def test_file_operations_use_same_mount_target(self):
        """Test that multiple operations on same file use same mount target"""
        # Arrange
        mount_targets = [
            {'mount_target_id': 'fsmt-1', 'ip_address': '10.0.1.100', 'index': 0},
            {'mount_target_id': 'fsmt-2', 'ip_address': '10.0.2.100', 'index': 1}
        ]
        file_path = 'test.txt'
        
        # Act - Get file path multiple times
        path1 = get_file_path(file_path, mount_targets)
        path2 = get_file_path(file_path, mount_targets)
        path3 = get_file_path(file_path, mount_targets)
        
        # Assert - All paths should be identical
        assert path1 == path2 == path3
