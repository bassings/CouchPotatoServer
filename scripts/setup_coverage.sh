#!/bin/bash
# Setup script for coverage reporting

echo "Setting up coverage reporting for CouchPotato..."

# Install coverage dependencies
echo "Installing coverage dependencies..."
pip install pytest-cov coveralls

# Run tests with coverage
echo "Running tests with coverage..."
pytest --cov=couchpotato --cov-report=html --cov-report=term-missing

echo ""
echo "Coverage setup complete!"
echo "HTML coverage report generated in htmlcov/index.html"
echo ""
echo "To enable Coveralls integration:"
echo "1. Go to https://coveralls.io and add this repository"
echo "2. Add COVERALLS_REPO_TOKEN to your GitHub repository secrets"
echo "3. Push changes to trigger CI with coverage reporting"
