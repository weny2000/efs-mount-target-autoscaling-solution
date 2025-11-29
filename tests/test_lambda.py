# Unit tests for Lambda function
import pytest
import sys
import os
import tempfile
import shutil
import importlib.util

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import from lambda directory (lambda is a reserved keyword)
spec = importlib.util.spec_from_file_location("file_monitor", os.path.join(os.path.dirname(__file__), '..', 'lambda', 'file_monitor.py'))
file_monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(file_monitor)

get_config_from_env = file_monitor.get_config_from_env
count_files_in_directory = file_monitor.count_files_in_directory
convert_mount_targets_to_json = file_monitor.convert_mount_targets_to_json
update_ssm_parameter = file_monitor.update_ssm_parameter
trigger_ecs_service_deployment = file_monitor.trigger_ecs_service_deployment


class TestGetConfigFromEnv:
    """Tests for get_config_from_env function"""
    
    def test_get_config_with_all_env_vars(self, monkeypatch):
        """Test configuration reading with all required environment variables"""
        monkeypatch.setenv('TARGET_DIRECTORY', '/mnt/efs/data')
        monkeypatch.setenv('FILE_COUNT_THRESHOLD', '50000')
        monkeypatch.setenv('EFS_FILE_SYSTEM_ID', 'fs-12345678')
        monkeypatch.setenv('VPC_ID', 'vpc-12345678')
        monkeypatch.setenv('SSM_PARAMETER_NAME', '/app/efs/mount-targets')
        monkeypatch.setenv('ECS_CLUSTER_NAME', 'my-cluster')
        monkeypatch.setenv('ECS_SERVICE_NAME', 'my-service')
        
        config = get_config_from_env()
        
        assert config['target_directory'] == '/mnt/efs/data'
        assert config['file_count_threshold'] == 50000
        assert config['efs_file_system_id'] == 'fs-12345678'
        assert config['vpc_id'] == 'vpc-12345678'
        assert config['ssm_parameter_name'] == '/app/efs/mount-targets'
        assert config['ecs_cluster_name'] == 'my-cluster'
        assert config['ecs_service_name'] == 'my-service'
    
    def test_get_config_with_default_threshold(self, monkeypatch):
        """Test configuration reading with default threshold"""
        monkeypatch.setenv('TARGET_DIRECTORY', '/mnt/efs/data')
        monkeypatch.setenv('EFS_FILE_SYSTEM_ID', 'fs-12345678')
        monkeypatch.setenv('VPC_ID', 'vpc-12345678')
        monkeypatch.setenv('SSM_PARAMETER_NAME', '/app/efs/mount-targets')
        monkeypatch.setenv('ECS_CLUSTER_NAME', 'my-cluster')
        monkeypatch.setenv('ECS_SERVICE_NAME', 'my-service')
        monkeypatch.delenv('FILE_COUNT_THRESHOLD', raising=False)
        
        config = get_config_from_env()
        
        assert config['file_count_threshold'] == 100000
    
    def test_get_config_missing_target_directory(self, monkeypatch):
        """Test configuration reading fails when TARGET_DIRECTORY is missing"""
        monkeypatch.delenv('TARGET_DIRECTORY', raising=False)
        monkeypatch.setenv('EFS_FILE_SYSTEM_ID', 'fs-12345678')
        
        with pytest.raises(ValueError, match="TARGET_DIRECTORY environment variable is required"):
            get_config_from_env()
    
    def test_get_config_missing_efs_file_system_id(self, monkeypatch):
        """Test configuration reading fails when EFS_FILE_SYSTEM_ID is missing"""
        monkeypatch.setenv('TARGET_DIRECTORY', '/mnt/efs/data')
        monkeypatch.delenv('EFS_FILE_SYSTEM_ID', raising=False)
        
        with pytest.raises(ValueError, match="EFS_FILE_SYSTEM_ID environment variable is required"):
            get_config_from_env()
    
    def test_get_config_invalid_threshold(self, monkeypatch):
        """Test configuration reading fails when threshold is not a valid integer"""
        monkeypatch.setenv('TARGET_DIRECTORY', '/mnt/efs/data')
        monkeypatch.setenv('FILE_COUNT_THRESHOLD', 'invalid')
        monkeypatch.setenv('EFS_FILE_SYSTEM_ID', 'fs-12345678')
        
        with pytest.raises(ValueError, match="FILE_COUNT_THRESHOLD must be a valid integer"):
            get_config_from_env()


class TestCountFilesInDirectory:
    """Tests for count_files_in_directory function"""
    
    def test_count_files_in_empty_directory(self):
        """Test counting files in an empty directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            count = count_files_in_directory(tmpdir)
            assert count == 0
    
    def test_count_files_with_multiple_files(self):
        """Test counting files in a directory with multiple files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            for i in range(5):
                with open(os.path.join(tmpdir, f'file{i}.txt'), 'w') as f:
                    f.write('test content')
            
            count = count_files_in_directory(tmpdir)
            assert count == 5
    
    def test_count_files_ignores_subdirectories(self):
        """Test that subdirectories are not counted as files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files
            for i in range(3):
                with open(os.path.join(tmpdir, f'file{i}.txt'), 'w') as f:
                    f.write('test content')
            
            # Create subdirectories
            os.makedirs(os.path.join(tmpdir, 'subdir1'))
            os.makedirs(os.path.join(tmpdir, 'subdir2'))
            
            count = count_files_in_directory(tmpdir)
            assert count == 3
    
    def test_count_files_nonexistent_directory(self):
        """Test counting files in a non-existent directory raises error"""
        with pytest.raises(FileNotFoundError):
            count_files_in_directory('/nonexistent/path')
    
    def test_count_files_path_is_file(self):
        """Test counting files when path is a file raises error"""
        with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
            tmpfile.write(b'test')
            tmpfile_path = tmpfile.name
        
        try:
            with pytest.raises(NotADirectoryError):
                count_files_in_directory(tmpfile_path)
        finally:
            os.unlink(tmpfile_path)


import json
from unittest.mock import Mock, patch
from botocore.exceptions import ClientError
from hypothesis import given, strategies as st, settings

check_threshold_exceeded = file_monitor.check_threshold_exceeded


class TestCountFilesPropertyBased:
    """Property-based tests for count_files_in_directory function
    
    **Feature: efs-mount-target-autoscaling, Property 1: ファイル数カウントの正確性**
    **Validates: Requirements 1.2**
    
    Property: For any EFS directory, the Lambda function's file count must match the actual number of files
    """
    
    @given(st.integers(min_value=0, max_value=200))
    @settings(max_examples=100, deadline=None)
    def test_file_count_accuracy(self, num_files):
        """
        Property test: For any number of files in a directory, count_files_in_directory 
        should return the exact count of files (not directories)
        
        This test generates random numbers of files and verifies that the counting 
        function returns the accurate count.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create the specified number of files
            for i in range(num_files):
                file_path = os.path.join(tmpdir, f'file_{i}.txt')
                with open(file_path, 'w') as f:
                    f.write('x')  # Minimal content for speed
            
            # Count files using the function under test
            counted = count_files_in_directory(tmpdir)
            
            # Property: counted files must equal actual number of files created
            assert counted == num_files, f"Expected {num_files} files, but counted {counted}"
    
    @given(
        st.integers(min_value=0, max_value=50),
        st.integers(min_value=0, max_value=30)
    )
    @settings(max_examples=100, deadline=None)
    def test_file_count_ignores_directories(self, num_files, num_dirs):
        """
        Property test: For any combination of files and directories, count_files_in_directory 
        should only count files, not directories
        
        This test verifies that subdirectories are correctly excluded from the file count.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files
            for i in range(num_files):
                file_path = os.path.join(tmpdir, f'file_{i}.txt')
                with open(file_path, 'w') as f:
                    f.write('x')  # Minimal content for speed
            
            # Create subdirectories
            for i in range(num_dirs):
                dir_path = os.path.join(tmpdir, f'subdir_{i}')
                os.makedirs(dir_path)
            
            # Count files using the function under test
            counted = count_files_in_directory(tmpdir)
            
            # Property: counted files must equal only the number of files, not directories
            assert counted == num_files, f"Expected {num_files} files (ignoring {num_dirs} dirs), but counted {counted}"
    
    @given(
        st.integers(min_value=1, max_value=50),
        st.integers(min_value=0, max_value=30)
    )
    @settings(max_examples=100, deadline=None)
    def test_file_count_with_nested_structure(self, num_files, num_nested_files):
        """
        Property test: For any directory with files and subdirectories containing files,
        count_files_in_directory should only count files in the top-level directory
        
        This test verifies that files in subdirectories are not counted.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files in the top-level directory
            for i in range(num_files):
                file_path = os.path.join(tmpdir, f'file_{i}.txt')
                with open(file_path, 'w') as f:
                    f.write('x')  # Minimal content for speed
            
            # Create a subdirectory with files
            subdir = os.path.join(tmpdir, 'nested')
            os.makedirs(subdir)
            for i in range(num_nested_files):
                nested_file_path = os.path.join(subdir, f'nested_file_{i}.txt')
                with open(nested_file_path, 'w') as f:
                    f.write('x')  # Minimal content for speed
            
            # Count files using the function under test
            counted = count_files_in_directory(tmpdir)
            
            # Property: counted files must equal only top-level files, not nested files
            assert counted == num_files, f"Expected {num_files} top-level files (ignoring {num_nested_files} nested), but counted {counted}"


class TestThresholdJudgmentPropertyBased:
    """Property-based tests for check_threshold_exceeded function
    
    **Feature: efs-mount-target-autoscaling, Property 2: 閾値判定の一貫性**
    **Validates: Requirements 1.3**
    
    Property: For any file count and threshold combination, scaling processing should 
    only be executed when file count exceeds the threshold
    """
    
    @given(
        st.integers(min_value=0, max_value=1000000),
        st.integers(min_value=0, max_value=1000000)
    )
    @settings(max_examples=100, deadline=None)
    def test_threshold_judgment_consistency(self, file_count, threshold):
        """
        Property test: For any file count and threshold, check_threshold_exceeded 
        should return True if and only if file_count > threshold
        
        This test verifies that the threshold judgment logic is consistent across 
        all possible combinations of file counts and thresholds.
        """
        result = check_threshold_exceeded(file_count, threshold)
        
        # Property: result should be True if and only if file_count > threshold
        expected = file_count > threshold
        assert result == expected, \
            f"For file_count={file_count} and threshold={threshold}, " \
            f"expected {expected} but got {result}"
    
    @given(st.integers(min_value=0, max_value=1000000))
    @settings(max_examples=100, deadline=None)
    def test_threshold_boundary_below(self, threshold):
        """
        Property test: For any threshold, file count equal to threshold should NOT trigger scaling
        
        This test verifies the boundary condition where file_count == threshold.
        According to the requirement, scaling should only occur when file_count > threshold.
        """
        file_count = threshold
        result = check_threshold_exceeded(file_count, threshold)
        
        # Property: when file_count equals threshold, should return False
        assert result is False, \
            f"For file_count={file_count} equal to threshold={threshold}, " \
            f"expected False but got {result}"
    
    @given(st.integers(min_value=1, max_value=1000000))
    @settings(max_examples=100, deadline=None)
    def test_threshold_boundary_above(self, threshold):
        """
        Property test: For any threshold, file count one above threshold should trigger scaling
        
        This test verifies the boundary condition where file_count = threshold + 1.
        """
        file_count = threshold + 1
        result = check_threshold_exceeded(file_count, threshold)
        
        # Property: when file_count is one above threshold, should return True
        assert result is True, \
            f"For file_count={file_count} (threshold + 1), threshold={threshold}, " \
            f"expected True but got {result}"
    
    @given(st.integers(min_value=1, max_value=1000000))
    @settings(max_examples=100, deadline=None)
    def test_threshold_boundary_below_by_one(self, threshold):
        """
        Property test: For any threshold > 0, file count one below threshold should NOT trigger scaling
        
        This test verifies the boundary condition where file_count = threshold - 1.
        """
        file_count = threshold - 1
        result = check_threshold_exceeded(file_count, threshold)
        
        # Property: when file_count is one below threshold, should return False
        assert result is False, \
            f"For file_count={file_count} (threshold - 1), threshold={threshold}, " \
            f"expected False but got {result}"


class TestConvertMountTargetsToJson:
    """Tests for convert_mount_targets_to_json function"""
    
    def test_convert_empty_list(self):
        """Test converting an empty mount target list"""
        mount_targets = []
        result = convert_mount_targets_to_json(mount_targets)
        
        data = json.loads(result)
        assert 'mount_targets' in data
        assert data['mount_targets'] == []
    
    def test_convert_single_mount_target(self):
        """Test converting a single mount target"""
        mount_targets = [
            {
                'mount_target_id': 'fsmt-12345678',
                'ip_address': '10.0.1.100',
                'availability_zone': 'ap-northeast-1a',
                'subnet_id': 'subnet-12345678',
                'lifecycle_state': 'available'
            }
        ]
        
        result = convert_mount_targets_to_json(mount_targets)
        data = json.loads(result)
        
        assert 'mount_targets' in data
        assert len(data['mount_targets']) == 1
        
        mt = data['mount_targets'][0]
        assert mt['mount_target_id'] == 'fsmt-12345678'
        assert mt['ip_address'] == '10.0.1.100'
        assert mt['availability_zone'] == 'ap-northeast-1a'
        assert mt['subnet_id'] == 'subnet-12345678'
        assert 'lifecycle_state' not in mt  # Should be filtered out
    
    def test_convert_multiple_mount_targets(self):
        """Test converting multiple mount targets"""
        mount_targets = [
            {
                'mount_target_id': 'fsmt-12345678',
                'ip_address': '10.0.1.100',
                'availability_zone': 'ap-northeast-1a',
                'subnet_id': 'subnet-12345678',
                'lifecycle_state': 'available'
            },
            {
                'mount_target_id': 'fsmt-87654321',
                'ip_address': '10.0.2.100',
                'availability_zone': 'ap-northeast-1c',
                'subnet_id': 'subnet-87654321',
                'lifecycle_state': 'available'
            }
        ]
        
        result = convert_mount_targets_to_json(mount_targets)
        data = json.loads(result)
        
        assert 'mount_targets' in data
        assert len(data['mount_targets']) == 2
        
        # Verify first mount target
        mt1 = data['mount_targets'][0]
        assert mt1['mount_target_id'] == 'fsmt-12345678'
        assert mt1['ip_address'] == '10.0.1.100'
        
        # Verify second mount target
        mt2 = data['mount_targets'][1]
        assert mt2['mount_target_id'] == 'fsmt-87654321'
        assert mt2['ip_address'] == '10.0.2.100'
    
    def test_convert_filters_lifecycle_state(self):
        """Test that lifecycle_state is filtered out from the output"""
        mount_targets = [
            {
                'mount_target_id': 'fsmt-12345678',
                'ip_address': '10.0.1.100',
                'availability_zone': 'ap-northeast-1a',
                'subnet_id': 'subnet-12345678',
                'lifecycle_state': 'creating'
            }
        ]
        
        result = convert_mount_targets_to_json(mount_targets)
        data = json.loads(result)
        
        mt = data['mount_targets'][0]
        assert 'lifecycle_state' not in mt


class TestUpdateSsmParameter:
    """Tests for update_ssm_parameter function"""
    
    def test_update_ssm_parameter_success(self):
        """Test successful SSM parameter update"""
        with patch.object(file_monitor.ssm_client, 'put_parameter') as mock_put:
            mock_put.return_value = {}
            
            mount_targets_json = json.dumps({
                'mount_targets': [
                    {
                        'mount_target_id': 'fsmt-12345678',
                        'ip_address': '10.0.1.100',
                        'availability_zone': 'ap-northeast-1a',
                        'subnet_id': 'subnet-12345678'
                    }
                ]
            })
            
            result = update_ssm_parameter('/app/efs/mount-targets', mount_targets_json)
            
            assert result is True
            mock_put.assert_called_once_with(
                Name='/app/efs/mount-targets',
                Value=mount_targets_json,
                Type='String',
                Overwrite=True,
                Description='EFS Mount Target list for Fargate service'
            )
    
    def test_update_ssm_parameter_failure(self):
        """Test SSM parameter update failure"""
        with patch.object(file_monitor.ssm_client, 'put_parameter') as mock_put:
            # Simulate AWS API error
            error_response = {
                'Error': {
                    'Code': 'AccessDeniedException',
                    'Message': 'User is not authorized to perform: ssm:PutParameter'
                }
            }
            mock_put.side_effect = ClientError(error_response, 'PutParameter')
            
            mount_targets_json = json.dumps({'mount_targets': []})
            
            result = update_ssm_parameter('/app/efs/mount-targets', mount_targets_json)
            
            # Should return False but not raise exception (as per requirement 6.3)
            assert result is False
    
    def test_update_ssm_parameter_with_empty_list(self):
        """Test updating SSM parameter with empty mount target list"""
        with patch.object(file_monitor.ssm_client, 'put_parameter') as mock_put:
            mock_put.return_value = {}
            
            mount_targets_json = json.dumps({'mount_targets': []})
            
            result = update_ssm_parameter('/app/efs/mount-targets', mount_targets_json)
            
            assert result is True
            mock_put.assert_called_once()


class TestSsmParameterStoreRoundTripPropertyBased:
    """Property-based tests for SSM Parameter Store update consistency
    
    **Feature: efs-mount-target-autoscaling, Property 4: SSM Parameter Storeの更新整合性**
    **Validates: Requirements 1.5, 2.1**
    
    Property: For any mount target list, data saved to SSM Parameter Store and then 
    retrieved should return the same content (round-trip consistency)
    """
    
    @given(
        st.lists(
            st.fixed_dictionaries({
                'mount_target_id': st.text(
                    alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-'),
                    min_size=10,
                    max_size=20
                ).map(lambda s: f"fsmt-{s[:12]}"),
                'ip_address': st.tuples(
                    st.integers(min_value=10, max_value=10),
                    st.integers(min_value=0, max_value=255),
                    st.integers(min_value=0, max_value=255),
                    st.integers(min_value=1, max_value=254)
                ).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}"),
                'availability_zone': st.sampled_from([
                    'ap-northeast-1a', 'ap-northeast-1c', 'ap-northeast-1d',
                    'us-east-1a', 'us-east-1b', 'us-east-1c',
                    'eu-west-1a', 'eu-west-1b', 'eu-west-1c'
                ]),
                'subnet_id': st.text(
                    alphabet=st.characters(whitelist_categories=('Ll', 'Nd')),
                    min_size=8,
                    max_size=12
                ).map(lambda s: f"subnet-{s[:8]}")
            }),
            min_size=0,
            max_size=10
        )
    )
    @settings(max_examples=100, deadline=None)
    def test_ssm_parameter_round_trip_consistency(self, mount_targets):
        """
        Property test: For any mount target list, converting to JSON, storing in SSM,
        and retrieving should return the same data structure
        
        This test verifies the round-trip property: serialize -> store -> retrieve -> deserialize
        should produce equivalent data to the original input.
        """
        # Step 1: Convert mount targets to JSON format (as would be stored in SSM)
        mount_targets_json = convert_mount_targets_to_json(mount_targets)
        
        # Step 2: Parse the JSON to verify it's valid and can be deserialized
        parsed_data = json.loads(mount_targets_json)
        
        # Step 3: Mock SSM Parameter Store operations to simulate round-trip
        with patch.object(file_monitor.ssm_client, 'put_parameter') as mock_put, \
             patch.object(file_monitor.ssm_client, 'get_parameter') as mock_get:
            
            # Configure mock to return the same value that was stored
            mock_put.return_value = {}
            mock_get.return_value = {
                'Parameter': {
                    'Name': '/test/mount-targets',
                    'Value': mount_targets_json,
                    'Type': 'String'
                }
            }
            
            # Store the data
            parameter_name = '/test/mount-targets'
            store_result = update_ssm_parameter(parameter_name, mount_targets_json)
            
            # Verify storage succeeded
            assert store_result is True, "Failed to store mount targets in SSM"
            
            # Retrieve the data
            retrieve_response = file_monitor.ssm_client.get_parameter(Name=parameter_name)
            retrieved_json = retrieve_response['Parameter']['Value']
            
            # Parse retrieved data
            retrieved_data = json.loads(retrieved_json)
        
        # Step 4: Verify round-trip consistency
        # The retrieved data should match the original parsed data
        assert 'mount_targets' in retrieved_data, "Retrieved data missing 'mount_targets' key"
        assert len(retrieved_data['mount_targets']) == len(mount_targets), \
            f"Mount target count mismatch: expected {len(mount_targets)}, got {len(retrieved_data['mount_targets'])}"
        
        # Verify each mount target in detail
        for i, (original, retrieved) in enumerate(zip(mount_targets, retrieved_data['mount_targets'])):
            assert retrieved['mount_target_id'] == original['mount_target_id'], \
                f"Mount target {i}: ID mismatch"
            assert retrieved['ip_address'] == original['ip_address'], \
                f"Mount target {i}: IP address mismatch"
            assert retrieved['availability_zone'] == original['availability_zone'], \
                f"Mount target {i}: Availability zone mismatch"
            assert retrieved['subnet_id'] == original['subnet_id'], \
                f"Mount target {i}: Subnet ID mismatch"
            
            # Verify that lifecycle_state is NOT in the retrieved data (it should be filtered out)
            assert 'lifecycle_state' not in retrieved, \
                f"Mount target {i}: lifecycle_state should be filtered out"
    
    @given(st.integers(min_value=0, max_value=20))
    @settings(max_examples=100, deadline=None)
    def test_ssm_parameter_round_trip_with_varying_sizes(self, num_mount_targets):
        """
        Property test: For any number of mount targets (0 to 20), the round-trip 
        property should hold
        
        This test specifically focuses on varying list sizes to ensure the property
        holds for empty lists, single items, and larger collections.
        """
        # Generate mount targets with predictable data
        mount_targets = []
        for i in range(num_mount_targets):
            mount_targets.append({
                'mount_target_id': f'fsmt-{i:08d}',
                'ip_address': f'10.0.{i // 256}.{i % 256}',
                'availability_zone': f'az-{i % 3}',
                'subnet_id': f'subnet-{i:08d}',
                'lifecycle_state': 'available'  # This should be filtered out
            })
        
        # Convert to JSON
        mount_targets_json = convert_mount_targets_to_json(mount_targets)
        
        # Parse and verify
        parsed_data = json.loads(mount_targets_json)
        
        # Mock SSM operations
        with patch.object(file_monitor.ssm_client, 'put_parameter') as mock_put, \
             patch.object(file_monitor.ssm_client, 'get_parameter') as mock_get:
            
            mock_put.return_value = {}
            mock_get.return_value = {
                'Parameter': {
                    'Value': mount_targets_json
                }
            }
            
            # Store and retrieve
            parameter_name = '/test/mount-targets'
            update_ssm_parameter(parameter_name, mount_targets_json)
            retrieved_json = file_monitor.ssm_client.get_parameter(Name=parameter_name)['Parameter']['Value']
            retrieved_data = json.loads(retrieved_json)
        
        # Verify round-trip consistency
        assert len(retrieved_data['mount_targets']) == num_mount_targets, \
            f"Expected {num_mount_targets} mount targets, got {len(retrieved_data['mount_targets'])}"
        
        # Verify structure is preserved
        for i, mt in enumerate(retrieved_data['mount_targets']):
            assert mt['mount_target_id'] == f'fsmt-{i:08d}'
            assert mt['ip_address'] == f'10.0.{i // 256}.{i % 256}'
            assert 'lifecycle_state' not in mt



get_existing_mount_targets = file_monitor.get_existing_mount_targets
find_available_subnet = file_monitor.find_available_subnet
create_mount_target = file_monitor.create_mount_target


class TestTriggerEcsServiceDeployment:
    """Tests for trigger_ecs_service_deployment function"""
    
    def test_trigger_deployment_success(self):
        """Test successful ECS service deployment trigger"""
        with patch.object(file_monitor.ecs_client, 'update_service') as mock_update:
            mock_update.return_value = {
                'service': {
                    'serviceName': 'my-service',
                    'deployments': [
                        {'id': 'ecs-svc/1234567890'},
                        {'id': 'ecs-svc/0987654321'}
                    ]
                }
            }
            
            result = trigger_ecs_service_deployment('my-cluster', 'my-service')
            
            assert result is True
            mock_update.assert_called_once_with(
                cluster='my-cluster',
                service='my-service',
                forceNewDeployment=True
            )
    
    def test_trigger_deployment_service_not_found(self):
        """Test ECS service deployment when service doesn't exist"""
        with patch.object(file_monitor.ecs_client, 'update_service') as mock_update:
            # Simulate ServiceNotFoundException
            error_response = {
                'Error': {
                    'Code': 'ServiceNotFoundException',
                    'Message': 'Service not found'
                }
            }
            mock_update.side_effect = ClientError(error_response, 'UpdateService')
            
            result = trigger_ecs_service_deployment('my-cluster', 'nonexistent-service')
            
            # Should return False but not raise exception
            assert result is False
    
    def test_trigger_deployment_cluster_not_found(self):
        """Test ECS service deployment when cluster doesn't exist"""
        with patch.object(file_monitor.ecs_client, 'update_service') as mock_update:
            # Simulate ClusterNotFoundException
            error_response = {
                'Error': {
                    'Code': 'ClusterNotFoundException',
                    'Message': 'Cluster not found'
                }
            }
            mock_update.side_effect = ClientError(error_response, 'UpdateService')
            
            result = trigger_ecs_service_deployment('nonexistent-cluster', 'my-service')
            
            # Should return False but not raise exception
            assert result is False
    
    def test_trigger_deployment_access_denied(self):
        """Test ECS service deployment with insufficient permissions"""
        with patch.object(file_monitor.ecs_client, 'update_service') as mock_update:
            # Simulate AccessDeniedException
            error_response = {
                'Error': {
                    'Code': 'AccessDeniedException',
                    'Message': 'User is not authorized to perform: ecs:UpdateService'
                }
            }
            mock_update.side_effect = ClientError(error_response, 'UpdateService')
            
            result = trigger_ecs_service_deployment('my-cluster', 'my-service')
            
            # Should return False but not raise exception
            assert result is False
    
    def test_trigger_deployment_with_empty_deployments(self):
        """Test ECS service deployment with no active deployments"""
        with patch.object(file_monitor.ecs_client, 'update_service') as mock_update:
            mock_update.return_value = {
                'service': {
                    'serviceName': 'my-service',
                    'deployments': []
                }
            }
            
            result = trigger_ecs_service_deployment('my-cluster', 'my-service')
            
            assert result is True
            mock_update.assert_called_once()



class TestLambdaHandler:
    """Integration tests for lambda_handler function"""
    
    def test_lambda_handler_threshold_not_exceeded(self, monkeypatch):
        """Test lambda handler when file count is below threshold"""
        # Set up environment variables
        monkeypatch.setenv('TARGET_DIRECTORY', '/tmp/test_dir')
        monkeypatch.setenv('FILE_COUNT_THRESHOLD', '100')
        monkeypatch.setenv('EFS_FILE_SYSTEM_ID', 'fs-12345678')
        monkeypatch.setenv('VPC_ID', 'vpc-12345678')
        monkeypatch.setenv('SSM_PARAMETER_NAME', '/app/efs/mount-targets')
        monkeypatch.setenv('ECS_CLUSTER_NAME', 'my-cluster')
        monkeypatch.setenv('ECS_SERVICE_NAME', 'my-service')
        
        # Create temporary directory with few files
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv('TARGET_DIRECTORY', tmpdir)
            
            # Create 5 files (below threshold of 100)
            for i in range(5):
                with open(os.path.join(tmpdir, f'file{i}.txt'), 'w') as f:
                    f.write('test')
            
            # Mock context
            mock_context = Mock()
            mock_context.request_id = 'test-request-123'
            
            # Call lambda handler
            response = file_monitor.lambda_handler({}, mock_context)
            
            # Verify response
            assert response['statusCode'] == 200
            body = json.loads(response['body'])
            assert body['file_count'] == 5
            assert body['threshold'] == 100
            assert body['threshold_exceeded'] is False
            assert body['new_mount_target_created'] is False
            assert body['deployment_triggered'] is False
    
    def test_lambda_handler_missing_env_var(self, monkeypatch):
        """Test lambda handler with missing environment variable"""
        # Clear all environment variables
        for key in ['TARGET_DIRECTORY', 'FILE_COUNT_THRESHOLD', 'EFS_FILE_SYSTEM_ID', 
                    'VPC_ID', 'SSM_PARAMETER_NAME', 'ECS_CLUSTER_NAME', 'ECS_SERVICE_NAME']:
            monkeypatch.delenv(key, raising=False)
        
        # Mock context
        mock_context = Mock()
        mock_context.request_id = 'test-request-123'
        
        # Call lambda handler
        response = file_monitor.lambda_handler({}, mock_context)
        
        # Verify error response
        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert 'error' in body
        assert 'Configuration error' in body['error']
    
    def test_lambda_handler_directory_not_found(self, monkeypatch):
        """Test lambda handler when target directory doesn't exist"""
        # Set up environment variables
        monkeypatch.setenv('TARGET_DIRECTORY', '/nonexistent/directory')
        monkeypatch.setenv('FILE_COUNT_THRESHOLD', '100')
        monkeypatch.setenv('EFS_FILE_SYSTEM_ID', 'fs-12345678')
        monkeypatch.setenv('VPC_ID', 'vpc-12345678')
        monkeypatch.setenv('SSM_PARAMETER_NAME', '/app/efs/mount-targets')
        monkeypatch.setenv('ECS_CLUSTER_NAME', 'my-cluster')
        monkeypatch.setenv('ECS_SERVICE_NAME', 'my-service')
        
        # Mock context
        mock_context = Mock()
        mock_context.request_id = 'test-request-123'
        
        # Call lambda handler
        response = file_monitor.lambda_handler({}, mock_context)
        
        # Verify error response
        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'error' in body
        assert 'Failed to access EFS directory' in body['error']
    
    def test_lambda_handler_threshold_exceeded_with_mocks(self, monkeypatch):
        """Test lambda handler when threshold is exceeded (with mocked AWS calls)"""
        # Set up environment variables
        monkeypatch.setenv('FILE_COUNT_THRESHOLD', '10')
        monkeypatch.setenv('EFS_FILE_SYSTEM_ID', 'fs-12345678')
        monkeypatch.setenv('VPC_ID', 'vpc-12345678')
        monkeypatch.setenv('SSM_PARAMETER_NAME', '/app/efs/mount-targets')
        monkeypatch.setenv('ECS_CLUSTER_NAME', 'my-cluster')
        monkeypatch.setenv('ECS_SERVICE_NAME', 'my-service')
        
        # Create temporary directory with many files
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv('TARGET_DIRECTORY', tmpdir)
            
            # Create 20 files (above threshold of 10)
            for i in range(20):
                with open(os.path.join(tmpdir, f'file{i}.txt'), 'w') as f:
                    f.write('test')
            
            # Mock AWS API calls
            with patch.object(file_monitor.efs_client, 'describe_mount_targets') as mock_describe_mt, \
                 patch.object(file_monitor.ec2_client, 'describe_subnets') as mock_describe_subnets, \
                 patch.object(file_monitor.efs_client, 'create_mount_target') as mock_create_mt, \
                 patch.object(file_monitor.ssm_client, 'put_parameter') as mock_put_param, \
                 patch.object(file_monitor.ecs_client, 'update_service') as mock_update_service:
                
                # Mock existing mount targets - first call returns one, subsequent calls return both
                mock_describe_mt.side_effect = [
                    # First call: get existing mount targets
                    {
                        'MountTargets': [
                            {
                                'MountTargetId': 'fsmt-existing',
                                'IpAddress': '10.0.1.100',
                                'AvailabilityZoneName': 'ap-northeast-1a',
                                'SubnetId': 'subnet-existing',
                                'LifeCycleState': 'available'
                            }
                        ]
                    },
                    # Second call: check mount target status during creation
                    {
                        'MountTargets': [
                            {
                                'MountTargetId': 'fsmt-new',
                                'IpAddress': '10.0.2.100',
                                'AvailabilityZoneName': 'ap-northeast-1c',
                                'SubnetId': 'subnet-new',
                                'LifeCycleState': 'available'
                            }
                        ]
                    },
                    # Third call: get all mount targets after creation
                    {
                        'MountTargets': [
                            {
                                'MountTargetId': 'fsmt-existing',
                                'IpAddress': '10.0.1.100',
                                'AvailabilityZoneName': 'ap-northeast-1a',
                                'SubnetId': 'subnet-existing',
                                'LifeCycleState': 'available'
                            },
                            {
                                'MountTargetId': 'fsmt-new',
                                'IpAddress': '10.0.2.100',
                                'AvailabilityZoneName': 'ap-northeast-1c',
                                'SubnetId': 'subnet-new',
                                'LifeCycleState': 'available'
                            }
                        ]
                    }
                ]
                
                # Mock available subnets
                mock_describe_subnets.return_value = {
                    'Subnets': [
                        {
                            'SubnetId': 'subnet-existing',
                            'AvailabilityZone': 'ap-northeast-1a'
                        },
                        {
                            'SubnetId': 'subnet-new',
                            'AvailabilityZone': 'ap-northeast-1c'
                        }
                    ]
                }
                
                # Mock mount target creation
                mock_create_mt.return_value = {
                    'MountTargetId': 'fsmt-new',
                    'IpAddress': '10.0.2.100',
                    'AvailabilityZoneName': 'ap-northeast-1c',
                    'SubnetId': 'subnet-new',
                    'LifeCycleState': 'available'
                }
                
                # Mock SSM parameter update
                mock_put_param.return_value = {}
                
                # Mock ECS service update
                mock_update_service.return_value = {
                    'service': {
                        'serviceName': 'my-service',
                        'deployments': [{'id': 'ecs-svc/123'}]
                    }
                }
                
                # Mock context
                mock_context = Mock()
                mock_context.request_id = 'test-request-123'
                
                # Call lambda handler
                response = file_monitor.lambda_handler({}, mock_context)
                
                # Verify response
                assert response['statusCode'] == 200
                body = json.loads(response['body'])
                assert body['file_count'] == 20
                assert body['threshold'] == 10
                assert body['threshold_exceeded'] is True
                assert body['new_mount_target_created'] is True
                assert body['new_mount_target_id'] == 'fsmt-new'
                assert body['deployment_triggered'] is True
                
                # Verify AWS API calls were made
                assert mock_describe_mt.call_count >= 1
                assert mock_describe_subnets.call_count == 1
                assert mock_create_mt.call_count == 1
                assert mock_put_param.call_count == 1
                assert mock_update_service.call_count == 1
