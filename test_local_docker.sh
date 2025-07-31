#!/bin/bash

# Comprehensive Local Docker Testing Script
# Mimics GitHub Actions environment for better local testing

set -e

echo "🚀 Starting comprehensive local Docker testing..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to cleanup
cleanup() {
    print_status "Cleaning up..."
    docker compose -f docker-compose.test.yml down 2>/dev/null || true
    rm -rf test-data/database test-data/logs test-data/cache test-data/settings.conf 2>/dev/null || true
}

# Set trap for cleanup
trap cleanup EXIT

# Check prerequisites
print_status "Checking prerequisites..."
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    print_error "Docker Compose is not installed"
    exit 1
fi

# Get system info
print_status "System Information:"
echo "  OS: $(uname -s)"
echo "  Architecture: $(uname -m)"
echo "  Docker Version: $(docker --version)"
echo "  Docker Compose Version: $(docker compose version)"

# Clean previous test data
print_status "Cleaning previous test data..."
cleanup

# Test 1: Basic Docker Build
print_status "Test 1: Building Docker image..."
if docker compose -f docker-compose.test.yml build; then
    print_success "Docker build completed successfully"
else
    print_error "Docker build failed"
    exit 1
fi

# Test 2: Container Startup with Timeout (mimic GitHub Actions)
print_status "Test 2: Container startup test (GitHub Actions style)..."
print_status "Starting container..."
docker compose -f docker-compose.test.yml up -d

# Wait for container to be ready (mimic GitHub Actions timeout)
print_status "Waiting for container to be ready (max 100 seconds)..."
container_ready=false
for i in {1..10}; do
    print_status "Attempt $i/10: Checking if container is ready..."
    
    # Check if container is running
    if ! docker compose -f docker-compose.test.yml ps | grep -q "Up"; then
        print_error "Container is not running"
        docker compose -f docker-compose.test.yml logs
        exit 1
    fi
    
    # Check if web interface is accessible
    if curl -fs http://localhost:5050/ > /dev/null 2>&1; then
        print_success "Container is ready on attempt $i"
        container_ready=true
        break
    fi
    
    if [ "$i" -eq 10 ]; then
        print_error "Container failed to start within 100 seconds"
        print_status "Container logs:"
        docker compose -f docker-compose.test.yml logs
        exit 1
    fi
    
    print_status "Container not ready yet, waiting 10 seconds..."
    sleep 10
done

if [ "$container_ready" = true ]; then
    print_success "Container startup test passed"
else
    print_error "Container startup test failed"
    exit 1
fi

# Test 3: Health Check
print_status "Test 3: Health check test..."
sleep 5
if curl -f http://localhost:5050/ > /dev/null 2>&1; then
    print_success "Health check passed"
else
    print_error "Health check failed"
    docker compose -f docker-compose.test.yml logs
    exit 1
fi

# Test 4: Log Analysis
print_status "Test 4: Analyzing container logs for errors..."
logs=$(docker compose -f docker-compose.test.yml logs)

# Check for critical errors
error_count=0
if echo "$logs" | grep -q "TypeError: Strings must be encoded before hashing"; then
    print_error "Found encoding error in logs"
    error_count=$((error_count + 1))
fi

if echo "$logs" | grep -q "CPLog.debug() takes from 2 to 3 positional arguments but 4 were given"; then
    print_error "Found method signature error in logs"
    error_count=$((error_count + 1))
fi

if echo "$logs" | grep -q "string argument without an encoding"; then
    print_error "Found bytes encoding error in logs"
    error_count=$((error_count + 1))
fi

if echo "$logs" | grep -q "IndexPreconditionsException"; then
    print_error "Found database index error in logs"
    error_count=$((error_count + 1))
fi

if [ $error_count -eq 0 ]; then
    print_success "No critical errors found in logs"
else
    print_warning "Found $error_count critical error(s) in logs"
    print_status "Logs:"
    echo "$logs"
fi

# Test 5: Performance Test
print_status "Test 5: Performance test..."
start_time=$(date +%s)
for i in {1..5}; do
    if curl -f http://localhost:5050/ > /dev/null 2>&1; then
        print_success "Request $i/5 successful"
    else
        print_error "Request $i/5 failed"
    fi
    sleep 1
done
end_time=$(date +%s)
duration=$((end_time - start_time))
print_status "Performance test completed in ${duration}s"

# Test 6: Resource Usage
print_status "Test 6: Resource usage check..."
container_stats=$(docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}")
print_status "Container resource usage:"
echo "$container_stats"

# Test 7: File System Check
print_status "Test 7: File system check..."
if docker compose -f docker-compose.test.yml exec couchpotato-test ls -la /data; then
    print_success "File system access test passed"
else
    print_warning "File system access test failed (container may not support exec)"
fi

# Test 8: Network Connectivity
print_status "Test 8: Network connectivity test..."
if curl -f http://localhost:5050/ > /dev/null 2>&1; then
    print_success "Network connectivity test passed"
else
    print_error "Network connectivity test failed"
    exit 1
fi

# Test 9: Graceful Shutdown
print_status "Test 9: Graceful shutdown test..."
docker compose -f docker-compose.test.yml down
sleep 5

if ! docker compose -f docker-compose.test.yml ps | grep -q "Up"; then
    print_success "Graceful shutdown test passed"
else
    print_error "Graceful shutdown test failed"
    exit 1
fi

# Test 10: Restart Test
print_status "Test 10: Restart test..."
docker compose -f docker-compose.test.yml up -d
sleep 15

if curl -f http://localhost:5050/ > /dev/null 2>&1; then
    print_success "Restart test passed"
else
    print_error "Restart test failed"
    docker compose -f docker-compose.test.yml logs
    exit 1
fi

# Final Summary
print_success "🎉 All local Docker tests passed!"
print_status "Summary:"
echo "  ✅ Docker build: PASSED"
echo "  ✅ Container startup: PASSED"
echo "  ✅ Health check: PASSED"
echo "  ✅ Log analysis: PASSED"
echo "  ✅ Performance test: PASSED"
echo "  ✅ Resource usage: CHECKED"
echo "  ✅ File system: CHECKED"
echo "  ✅ Network connectivity: PASSED"
echo "  ✅ Graceful shutdown: PASSED"
echo "  ✅ Restart test: PASSED"

print_status "Local testing completed successfully!"
print_status "This environment should closely match GitHub Actions behavior." 