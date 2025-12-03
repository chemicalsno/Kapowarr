# Kapowarr Tests

Comprehensive test suite for Kapowarr, focusing on Usenet functionality, NZB validation, and bug fixes.

## Test Structure

```
tests/
├── Tbackend/
│   ├── usenet.py                    # Core Usenet/SABnzbd tests
│   ├── test_usenet_fixes.py         # Tests for recent bug fixes
│   ├── settings_search.py           # Search format filtering tests
│   ├── file_extraction.py           # File extraction tests
│   └── opds.py                      # OPDS feed tests
└── README.md                        # This file
```

## Running Tests

### Prerequisites

```bash
# Install test dependencies
pip install pytest pytest-cov

# Ensure Kapowarr dependencies are installed
pip install -r requirements.txt
```

### Run All Tests

```bash
# From project root
pytest tests/

# With verbose output
pytest tests/ -v

# With coverage report
pytest tests/ --cov=backend --cov-report=html
```

### Run Specific Test Files

```bash
# Usenet tests
pytest tests/Tbackend/usenet.py -v

# Bug fix tests
pytest tests/Tbackend/test_usenet_fixes.py -v

# Search/format filtering tests
pytest tests/Tbackend/settings_search.py -v
```

### Run Specific Test Classes

```bash
# Version comparison tests
pytest tests/Tbackend/test_usenet_fixes.py::TestVersionComparison -v

# Failure handling tests
pytest tests/Tbackend/test_usenet_fixes.py::TestSabnzbdFailureHandling -v

# API rate limiting tests
pytest tests/Tbackend/test_usenet_fixes.py::TestApiRateLimiting -v
```

### Run Specific Tests

```bash
# Single test
pytest tests/Tbackend/usenet.py::TestSabnzbdGetDownload::test_get_download_duplicate_marked_canceled -v
```

## Test Categories

### Core Usenet Tests (`usenet.py`)

- **NZB Validation**: XML parsing, format validation, error detection
- **Exception Handling**: Client exceptions, authentication, connectivity
- **SABnzbd Integration**: Connection testing, download management
- **State Mappings**: Queue states, priorities, version checks
- **Encrypted Detection**: ENCRYPTED prefix, fail_message parsing
- **Download Operations**: Add, get, retry, delete

### Bug Fix Tests (`test_usenet_fixes.py`)

Tests for the 6 major fixes applied:

1. **Search Deduplication** - Ensures duplicate NZBs aren't sent multiple times
2. **Smart Failure Handling** - Duplicates/disk space/filters don't get blocklisted
3. **Version Comparison** - Semantic versioning works correctly
4. **Storage Path Validation** - Paths are validated before use
5. **API Rate Limiting** - Caching prevents API spam
6. **Integration Tests** - Combined scenarios

### Search/Format Tests (`settings_search.py`)

- **Format Filtering**: Extension-based filtering for direct downloads
- **Usenet Bypass**: Usenet sources bypass format filtering
- **Settings Persistence**: CommaList handling in database

## Key Test Scenarios

### Duplicate NZB Handling

```python
def test_duplicate_failure_returns_canceled_state():
    """Verifies duplicates return CANCELED_STATE (not blocklisted)"""
```

### Version Comparison

```python
def test_version_comparison_greater_than():
    """Verifies 3.10.0 > 3.2.0 (string comparison would fail)"""
```

### API Caching

```python
def test_cache_prevents_duplicate_api_calls():
    """Verifies repeated calls within 2s use cache"""
```

### Storage Validation

```python
def test_absolute_existing_path_accepted():
    """Verifies only valid absolute paths are accepted"""
```

## Test Markers

- `@requires_full_env` - Tests requiring full Kapowarr environment
- `@pytest.mark.parametrize` - Data-driven tests with multiple inputs

## Writing New Tests

### Guidelines

1. **Use descriptive names**: `test_duplicate_failure_returns_canceled_state` not `test_duplicate`
2. **Add docstrings**: Explain what the test validates
3. **Mock external dependencies**: Don't hit real APIs in tests
4. **Test edge cases**: Empty inputs, None values, boundary conditions
5. **Test the fix, not just the code**: Ensure bugs can't resurface

### Example Test Template

```python
@requires_full_env
class TestNewFeature:
    """Test description of what's being tested."""

    @pytest.fixture
    def client(self):
        """Setup code (if needed)."""
        pass

    def test_normal_case(self, client):
        """Test the happy path."""
        pass

    def test_edge_case(self, client):
        """Test boundary conditions."""
        pass

    @pytest.mark.parametrize("input,expected", [
        ("case1", True),
        ("case2", False),
    ])
    def test_multiple_cases(self, input, expected):
        """Test multiple scenarios."""
        pass
```

## Continuous Integration

Tests are designed to run in CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Run tests
  run: pytest tests/ --cov=backend --cov-report=xml
```

## Debugging Failed Tests

### Verbose Output

```bash
pytest tests/ -vv --tb=long
```

### Stop on First Failure

```bash
pytest tests/ -x
```

### Run Only Failed Tests

```bash
pytest tests/ --lf
```

### Capture Output

```bash
pytest tests/ -s  # Show print statements
```

## Coverage Goals

- **Core functionality**: >80% coverage
- **Critical paths**: 100% coverage
- **Bug fixes**: 100% test coverage

## Contributing

When adding features or fixing bugs:

1. **Write tests first** (TDD approach)
2. **Ensure all tests pass** before submitting PR
3. **Add tests for bug fixes** to prevent regressions
4. **Update this README** if adding new test files

## Known Issues

- Some tests require mocked SABnzbd responses
- Integration tests need full environment setup
- Network tests may be skipped in CI

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [unittest.mock guide](https://docs.python.org/3/library/unittest.mock.html)
- [Coverage.py](https://coverage.readthedocs.io/)
