#!/bin/bash
# Test runner script for Kapowarr
# Usage: ./run_tests.sh [options]

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================="
echo "  Kapowarr Test Runner"
echo "=================================="
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest is not installed${NC}"
    echo "Install with: pip install pytest pytest-cov"
    exit 1
fi

# Parse command line arguments
COVERAGE=false
VERBOSE=false
SPECIFIC_TEST=""
MARKERS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--coverage)
            COVERAGE=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -m|--marker)
            MARKERS="-m $2"
            shift 2
            ;;
        -t|--test)
            SPECIFIC_TEST="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./run_tests.sh [options]"
            echo ""
            echo "Options:"
            echo "  -c, --coverage        Run with coverage report"
            echo "  -v, --verbose         Run with extra verbosity"
            echo "  -m, --marker MARKER   Run tests with specific marker"
            echo "  -t, --test PATH       Run specific test file or class"
            echo "  -h, --help            Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./run_tests.sh                                    # Run all tests"
            echo "  ./run_tests.sh -c                                 # Run with coverage"
            echo "  ./run_tests.sh -t tests/Tbackend/usenet.py       # Run specific file"
            echo "  ./run_tests.sh -m usenet                         # Run usenet tests"
            echo "  ./run_tests.sh -v -c                             # Verbose with coverage"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Build pytest command
CMD="pytest"

if [ -n "$SPECIFIC_TEST" ]; then
    CMD="$CMD $SPECIFIC_TEST"
else
    CMD="$CMD tests/"
fi

if [ "$VERBOSE" = true ]; then
    CMD="$CMD -vv"
fi

if [ -n "$MARKERS" ]; then
    CMD="$CMD $MARKERS"
fi

if [ "$COVERAGE" = true ]; then
    CMD="$CMD --cov=backend --cov-report=term --cov-report=html"
fi

# Run tests
echo -e "${YELLOW}Running: $CMD${NC}"
echo ""

if $CMD; then
    echo ""
    echo -e "${GREEN}✓ All tests passed!${NC}"

    if [ "$COVERAGE" = true ]; then
        echo ""
        echo -e "${GREEN}Coverage report generated in htmlcov/index.html${NC}"
        echo "Open with: open htmlcov/index.html"
    fi

    exit 0
else
    echo ""
    echo -e "${RED}✗ Some tests failed${NC}"
    exit 1
fi
