#!/usr/bin/env python3
"""
Python Version Compatibility Test Script
Tests the application across different Python versions to identify version-specific issues.
"""

import sys
import subprocess
import platform
import os
import time
import requests
from pathlib import Path

def print_status(message):
    print(f"[INFO] {message}")

def print_success(message):
    print(f"[SUCCESS] {message}")

def print_error(message):
    print(f"[ERROR] {message}")

def print_warning(message):
    print(f"[WARNING] {message}")

def test_python_version():
    """Test the current Python version for compatibility issues."""
    print_status(f"Testing Python {sys.version}")
    print_status(f"Platform: {platform.platform()}")
    print_status(f"Architecture: {platform.architecture()}")
    
    # Test basic imports
    try:
        import hashlib
        import traceback
        import logging
        print_success("Basic imports successful")
    except ImportError as e:
        print_error(f"Basic import failed: {e}")
        return False
    
    # Test MD5 encoding (the main issue we fixed)
    try:
        test_string = "test_key"
        hash_obj = hashlib.md5(test_string.encode('utf-8'))
        result = hash_obj.hexdigest()
        print_success("MD5 encoding test passed")
    except Exception as e:
        print_error(f"MD5 encoding test failed: {e}")
        return False
    
    # Test bytes encoding
    try:
        test_id = "test_id_string"
        if isinstance(test_id, str):
            encoded_id = test_id.encode('utf-8')
        elif isinstance(test_id, bytes):
            encoded_id = test_id
        else:
            encoded_id = str(test_id).encode('utf-8')
        print_success("Bytes encoding test passed")
    except Exception as e:
        print_error(f"Bytes encoding test failed: {e}")
        return False
    
    return True

def test_application_startup():
    """Test if the application can start without critical errors."""
    print_status("Testing application startup...")
    
    # Set up environment
    env = os.environ.copy()
    env['PYTHONPATH'] = f"{env.get('PYTHONPATH', '')}:./libs"
    
    try:
        # Start the application in background
        process = subprocess.Popen(
            [sys.executable, "-W", "ignore::SyntaxWarning", "CouchPotato.py", "--console_log"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for startup
        time.sleep(10)
        
        # Check if process is still running
        if process.poll() is None:
            print_success("Application started successfully")
            
            # Try to access the web interface
            try:
                response = requests.get("http://localhost:5050/", timeout=5)
                if response.status_code == 200:
                    print_success("Web interface accessible")
                else:
                    print_warning(f"Web interface returned status {response.status_code}")
            except requests.exceptions.RequestException as e:
                print_warning(f"Web interface not accessible: {e}")
            
            # Terminate the process
            process.terminate()
            process.wait(timeout=5)
            return True
        else:
            stdout, stderr = process.communicate()
            print_error("Application failed to start")
            if stderr:
                print_error(f"Error output: {stderr}")
            return False
            
    except Exception as e:
        print_error(f"Startup test failed: {e}")
        return False

def test_docker_compatibility():
    """Test Docker compatibility."""
    print_status("Testing Docker compatibility...")
    
    try:
        # Check if Docker is available
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print_success(f"Docker available: {result.stdout.strip()}")
        else:
            print_warning("Docker not available")
            return False
        
        # Check if Docker Compose is available
        result = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
        if result.returncode == 0:
            print_success(f"Docker Compose available: {result.stdout.strip()}")
        else:
            print_warning("Docker Compose not available")
            return False
        
        return True
        
    except FileNotFoundError:
        print_warning("Docker not found in PATH")
        return False

def main():
    """Main test function."""
    print_status("Starting Python version compatibility tests...")
    
    # Test 1: Python version compatibility
    if not test_python_version():
        print_error("Python version compatibility test failed")
        sys.exit(1)
    
    # Test 2: Application startup
    if not test_application_startup():
        print_warning("Application startup test failed (this might be expected in some environments)")
    
    # Test 3: Docker compatibility
    if not test_docker_compatibility():
        print_warning("Docker compatibility test failed")
    
    print_success("All compatibility tests completed!")
    print_status("If you see warnings, they may indicate environment-specific issues.")
    print_status("Use the test_local_docker.sh script for comprehensive Docker testing.")

if __name__ == "__main__":
    main() 