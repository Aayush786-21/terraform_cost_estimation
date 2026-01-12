"""
Tests for Terraform file parsing and extraction.
"""

import pytest
import zipfile
import io
from backend.utils.fs import extract_and_scan_terraform_files


def create_test_zip(files):
    """Helper to create a test ZIP file."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for path, content in files.items():
            zip_file.writestr(path, content)
    return zip_buffer.getvalue()


def test_zip_extraction_handles_nested_repos():
    """ZIP extraction handles nested repository structures."""
    zip_data = create_test_zip({
        'repo-main/main.tf': 'resource "aws_instance" "web" {}',
        'repo-main/modules/db/main.tf': 'resource "aws_db_instance" "db" {}',
    })
    
    result = extract_and_scan_terraform_files(zip_data, 'owner', 'repo')
    
    assert len(result) == 2
    assert any(f['path'] == 'main.tf' for f in result)
    assert any('modules/db/main.tf' in f['path'] for f in result)


def test_only_tf_files_are_read():
    """Only .tf files are extracted, other files are ignored."""
    zip_data = create_test_zip({
        'main.tf': 'resource "aws_instance" "web" {}',
        'main.py': 'print("not terraform")',
        'README.md': '# Documentation',
        'config.json': '{"key": "value"}',
    })
    
    result = extract_and_scan_terraform_files(zip_data, 'owner', 'repo')
    
    assert len(result) == 1
    assert result[0]['path'] == 'main.tf'


def test_terraform_directories_are_ignored():
    """Directories like .terraform/, vendor/, .git are ignored."""
    zip_data = create_test_zip({
        'main.tf': 'resource "aws_instance" "web" {}',
        '.terraform/modules/module.tf': 'should be ignored',
        'vendor/module.tf': 'should be ignored',
        '.git/config': 'should be ignored',
    })
    
    result = extract_and_scan_terraform_files(zip_data, 'owner', 'repo')
    
    assert len(result) == 1
    assert result[0]['path'] == 'main.tf'


def test_empty_repo_raises_value_error():
    """Empty repository raises ValueError."""
    zip_data = create_test_zip({})
    
    with pytest.raises(ValueError, match='No Terraform files found'):
        extract_and_scan_terraform_files(zip_data, 'owner', 'repo')


def test_invalid_zip_raises_error():
    """Invalid ZIP data raises appropriate error."""
    invalid_zip = b'not a zip file'
    
    with pytest.raises(Exception):  # zipfile.BadZipFile or similar
        extract_and_scan_terraform_files(invalid_zip, 'owner', 'repo')


def test_tf_files_in_subdirectories_are_included():
    """Terraform files in subdirectories are included."""
    zip_data = create_test_zip({
        'main.tf': 'resource "aws_instance" "web" {}',
        'modules/compute/main.tf': 'resource "aws_instance" "app" {}',
        'environments/prod/main.tf': 'resource "aws_instance" "prod" {}',
    })
    
    result = extract_and_scan_terraform_files(zip_data, 'owner', 'repo')
    
    assert len(result) == 3
    paths = [f['path'] for f in result]
    assert 'main.tf' in paths
    assert 'modules/compute/main.tf' in paths
    assert 'environments/prod/main.tf' in paths
