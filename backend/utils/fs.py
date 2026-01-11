"""
Filesystem utilities for extracting archives and scanning Terraform files.
"""
import os
import zipfile
import tempfile
from pathlib import Path
from typing import List, Dict, Any


# Directories and files to ignore when scanning for Terraform files
IGNORED_PATTERNS = {".git", ".terraform", "vendor", "__pycache__", ".venv", "venv"}


def should_ignore_path(path: Path) -> bool:
    """
    Check if a path should be ignored when scanning for Terraform files.
    
    Args:
        path: Path object to check
    
    Returns:
        True if path should be ignored, False otherwise
    """
    parts = path.parts
    for part in parts:
        if part in IGNORED_PATTERNS:
            return True
    return False


def extract_zip_archive(zip_data: bytes, extract_to: Path) -> None:
    """
    Extract ZIP archive data to a directory.
    
    Args:
        zip_data: Raw bytes of the ZIP archive
        extract_to: Directory path where archive should be extracted
    
    Raises:
        zipfile.BadZipFile: If zip_data is not a valid ZIP file
        OSError: If extraction fails
    """
    extract_to.mkdir(parents=True, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_zip:
        try:
            temp_zip.write(zip_data)
            temp_zip.flush()
            
            with zipfile.ZipFile(temp_zip.name, "r") as zip_ref:
                zip_ref.extractall(extract_to)
        finally:
            # Clean up temporary ZIP file
            if os.path.exists(temp_zip.name):
                os.unlink(temp_zip.name)


def find_terraform_files(directory: Path) -> List[Path]:
    """
    Recursively find all .tf files in a directory.
    Ignores .git/, .terraform/, vendor/ and other common directories.
    
    Args:
        directory: Root directory to search
    
    Returns:
        Sorted list of Path objects for all .tf files found
    """
    terraform_files = []
    
    for root, dirs, files in os.walk(directory):
        # Filter out ignored directories to avoid traversing them
        dirs[:] = [d for d in dirs if d not in IGNORED_PATTERNS]
        
        root_path = Path(root)
        if should_ignore_path(root_path):
            continue
        
        for file in files:
            if file.endswith(".tf"):
                file_path = root_path / file
                if not should_ignore_path(file_path):
                    terraform_files.append(file_path)
    
    # Sort for deterministic output
    return sorted(terraform_files)


def read_terraform_file(file_path: Path) -> str:
    """
    Read Terraform file contents as UTF-8.
    
    Args:
        file_path: Path to the Terraform file
    
    Returns:
        File contents as string
    
    Raises:
        UnicodeDecodeError: If file cannot be decoded as UTF-8
        OSError: If file cannot be read
    """
    return file_path.read_text(encoding="utf-8")


def extract_and_scan_terraform_files(
    zip_data: bytes,
    owner: str,
    repo: str
) -> List[Dict[str, str]]:
    """
    Extract ZIP archive and scan for Terraform files.
    Creates a temporary directory, extracts archive, scans for .tf files,
    and returns their paths and contents. Ensures cleanup even on failure.
    
    Args:
        zip_data: Raw bytes of the ZIP archive from GitHub
        owner: Repository owner name (for error messages)
        repo: Repository name (for error messages)
    
    Returns:
        List of dictionaries with 'path' and 'content' keys
    
    Raises:
        ValueError: If no Terraform files are found
        zipfile.BadZipFile: If zip_data is not a valid ZIP file
        OSError: If extraction or file reading fails
    """
    temp_dir = None
    try:
        # Create temporary directory for extraction
        temp_dir = Path(tempfile.mkdtemp(prefix=f"terraform_{owner}_{repo}_"))
        
        # Extract archive
        extract_zip_archive(zip_data, temp_dir)
        
        # Find the actual repository root (GitHub zipballs have a root directory)
        # Typically: owner-repo-<hash>/...
        contents = list(temp_dir.iterdir())
        if len(contents) == 1 and contents[0].is_dir():
            repo_root = contents[0]
        else:
            repo_root = temp_dir
        
        # Find all Terraform files
        terraform_files = find_terraform_files(repo_root)
        
        if not terraform_files:
            raise ValueError(f"No Terraform files found in {owner}/{repo}")
        
        # Read file contents and build response
        result = []
        for tf_file in terraform_files:
            # Calculate relative path from repo root for cleaner output
            try:
                relative_path = tf_file.relative_to(repo_root)
                content = read_terraform_file(tf_file)
                result.append({
                    "path": str(relative_path),
                    "content": content,
                })
            except (UnicodeDecodeError, OSError) as error:
                # Skip files that can't be read, but continue processing others
                # In production, you might want to log this
                continue
        
        return result
    
    finally:
        # Cleanup: remove temporary directory and all contents
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
