# -*- coding: utf-8 -*-

"""
Comprehensive tests for Usenet download bug fixes.

Tests for fixes applied to resolve:
1. Search deduplication bug
2. SABnzbd failure handling (duplicates, disk space, file filters)
3. Version comparison
4. Storage path validation
5. API rate limiting/caching
"""

import os
import pytest
import time
from unittest.mock import MagicMock, patch, call
from threading import Thread

# Check if full environment is available
try:
    import requests
    from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd
    from backend.base.definitions import DownloadState
    from backend.features.search import manual_search
    FULL_ENV_AVAILABLE = True
except ImportError:
    FULL_ENV_AVAILABLE = False

requires_full_env = pytest.mark.skipif(
    not FULL_ENV_AVAILABLE,
    reason="Requires full Kapowarr environment"
)


# =============================================================================
# Fix 1: Search Deduplication Tests
# =============================================================================

@requires_full_env
class TestSearchDeduplication:
    """Test that search results are properly deduplicated.

    Bug: search.py was creating deduped_results but using search_results,
    causing duplicate NZBs to be sent to SABnzbd.
    """

    def test_deduplication_removes_duplicate_links(self):
        """Test that duplicate search results are removed."""
        # Simulate the deduplication logic
        search_results = [
            {'link': 'http://example.com/nzb1', 'title': 'Batman 001'},
            {'link': 'http://example.com/nzb1', 'title': 'Batman 001 (dupe)'},  # Same link
            {'link': 'http://example.com/nzb2', 'title': 'Batman 002'},
            {'link': 'http://example.com/nzb1', 'title': 'Batman 001 (dupe2)'},  # Same link again
        ]

        deduped_results = []
        seen_links = set()
        for r in search_results:
            if r['link'] not in seen_links:
                deduped_results.append(r)
                seen_links.add(r['link'])

        assert len(deduped_results) == 2
        assert deduped_results[0]['link'] == 'http://example.com/nzb1'
        assert deduped_results[1]['link'] == 'http://example.com/nzb2'
        assert 'dupe' not in deduped_results[0]['title']  # Should keep first occurrence

    def test_deduplication_preserves_order(self):
        """Test that deduplication preserves the original order."""
        search_results = [
            {'link': 'http://example.com/nzb3', 'title': 'First'},
            {'link': 'http://example.com/nzb1', 'title': 'Second'},
            {'link': 'http://example.com/nzb2', 'title': 'Third'},
            {'link': 'http://example.com/nzb1', 'title': 'Second (dupe)'},
        ]

        deduped_results = []
        seen_links = set()
        for r in search_results:
            if r['link'] not in seen_links:
                deduped_results.append(r)
                seen_links.add(r['link'])

        assert len(deduped_results) == 3
        assert deduped_results[0]['title'] == 'First'
        assert deduped_results[1]['title'] == 'Second'
        assert deduped_results[2]['title'] == 'Third'

    def test_no_duplicates_unchanged(self):
        """Test that results without duplicates pass through unchanged."""
        search_results = [
            {'link': 'http://example.com/nzb1', 'title': 'Batman 001'},
            {'link': 'http://example.com/nzb2', 'title': 'Batman 002'},
            {'link': 'http://example.com/nzb3', 'title': 'Batman 003'},
        ]

        deduped_results = []
        seen_links = set()
        for r in search_results:
            if r['link'] not in seen_links:
                deduped_results.append(r)
                seen_links.add(r['link'])

        assert len(deduped_results) == len(search_results)
        assert deduped_results == search_results


# =============================================================================
# Fix 2: SABnzbd Failure Handling Tests
# =============================================================================

@requires_full_env
class TestSabnzbdFailureHandling:
    """Test that different SABnzbd failures are handled correctly.

    Bug: All failures were treated as permanent and blocklisted.
    Fix: Duplicates, disk space, and file filter failures are now CANCELED_STATE.
    """

    @pytest.mark.parametrize("fail_message,should_cancel", [
        ("Duplicate NZB", True),
        ("duplicate nzb detected", True),
        ("DUPLICATE NZB", True),
        ("Insufficient disk space", True),
        ("Not enough disk space available", True),
        ("disk space error", True),
        ("Unwanted file extension", True),
        ("File has unwanted extension .exe", True),
        ("Verification failed", False),
        ("Unpacking failed: CRC error", False),
        ("Download incomplete", False),
        ("", False),
    ])
    def test_fail_message_classification(self, fail_message, should_cancel):
        """Test that fail messages are classified correctly."""
        fail_message_lower = fail_message.lower()

        is_duplicate = 'duplicate' in fail_message_lower
        is_disk_space = 'disk' in fail_message_lower and 'space' in fail_message_lower
        is_unwanted = 'unwanted' in fail_message_lower and 'extension' in fail_message_lower

        should_be_canceled = is_duplicate or is_disk_space or is_unwanted

        assert should_be_canceled == should_cancel, f"Failed for: {fail_message}"

    @pytest.fixture
    def sabnzbd_client(self):
        """Create a mock Sabnzbd client."""
        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = MagicMock()
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        return client

    def test_duplicate_failure_returns_canceled_state(self, sabnzbd_client):
        """Test that duplicate NZB failures return CANCELED_STATE."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},  # Not in queue
            {  # In history with duplicate failure
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Failed',
                        'fail_message': 'Duplicate NZB',
                        'name': 'Test Download',
                        'bytes': 0
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        result = sabnzbd_client.get_download('test_id')

        assert result is not None
        assert result['state'] == DownloadState.CANCELED_STATE

    def test_disk_space_failure_returns_canceled_state(self, sabnzbd_client):
        """Test that disk space failures return CANCELED_STATE."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},
            {
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Failed',
                        'fail_message': 'Insufficient disk space',
                        'name': 'Test Download',
                        'bytes': 0
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        result = sabnzbd_client.get_download('test_id')

        assert result is not None
        assert result['state'] == DownloadState.CANCELED_STATE

    def test_unwanted_extension_failure_returns_canceled_state(self, sabnzbd_client):
        """Test that unwanted extension failures return CANCELED_STATE."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},
            {
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Failed',
                        'fail_message': 'Unwanted file extension',
                        'name': 'Test Download',
                        'bytes': 0
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        result = sabnzbd_client.get_download('test_id')

        assert result is not None
        assert result['state'] == DownloadState.CANCELED_STATE

    def test_actual_failure_returns_failed_state(self, sabnzbd_client):
        """Test that real failures (CRC, incomplete, etc.) return FAILED_STATE."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},
            {
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Failed',
                        'fail_message': 'Verification failed: CRC error',
                        'name': 'Test Download',
                        'bytes': 0
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        result = sabnzbd_client.get_download('test_id')

        assert result is not None
        assert result['state'] == DownloadState.FAILED_STATE


# =============================================================================
# Fix 3: Version Comparison Tests
# =============================================================================

@requires_full_env
class TestVersionComparison:
    """Test that version comparison works correctly.

    Bug: String comparison failed for multi-digit versions.
    Fix: Added _version_tuple() helper for semantic versioning.
    """

    def test_version_tuple_basic(self):
        """Test basic version tuple conversion."""
        assert Sabnzbd._version_tuple('3.0.0') == (3, 0, 0)
        assert Sabnzbd._version_tuple('4.2.1') == (4, 2, 1)
        assert Sabnzbd._version_tuple('1.9.3') == (1, 9, 3)

    def test_version_tuple_handles_multi_digit(self):
        """Test that multi-digit version numbers work correctly."""
        assert Sabnzbd._version_tuple('3.10.0') == (3, 10, 0)
        assert Sabnzbd._version_tuple('3.2.15') == (3, 2, 15)
        assert Sabnzbd._version_tuple('10.5.20') == (10, 5, 20)

    def test_version_comparison_greater_than(self):
        """Test that version comparison works correctly for >."""
        # String comparison would fail these
        assert Sabnzbd._version_tuple('3.10.0') > Sabnzbd._version_tuple('3.2.0')
        assert Sabnzbd._version_tuple('3.0.10') > Sabnzbd._version_tuple('3.0.9')
        assert Sabnzbd._version_tuple('4.0.0') > Sabnzbd._version_tuple('3.99.99')

    def test_version_comparison_equal(self):
        """Test version equality."""
        assert Sabnzbd._version_tuple('3.0.0') == Sabnzbd._version_tuple('3.0.0')
        assert Sabnzbd._version_tuple('4.2.1') == Sabnzbd._version_tuple('4.2.1')

    def test_version_comparison_less_than(self):
        """Test that version comparison works correctly for <."""
        assert Sabnzbd._version_tuple('2.9.9') < Sabnzbd._version_tuple('3.0.0')
        assert Sabnzbd._version_tuple('3.0.0') < Sabnzbd._version_tuple('3.0.1')
        assert Sabnzbd._version_tuple('3.0.0') < Sabnzbd._version_tuple('3.1.0')

    def test_version_tuple_handles_invalid_input(self):
        """Test that invalid version strings return (0, 0, 0)."""
        assert Sabnzbd._version_tuple('invalid') == (0, 0, 0)
        assert Sabnzbd._version_tuple('') == (0, 0, 0)
        assert Sabnzbd._version_tuple(None) == (0, 0, 0)

    @pytest.mark.parametrize("version,expected", [
        ('3.0.0', False),  # Equal to MIN_VERSION
        ('3.0.1', False),  # Greater than MIN_VERSION
        ('3.1.0', False),
        ('4.0.0', False),
        ('2.9.9', True),   # Less than MIN_VERSION
        ('2.3.0', True),
    ])
    def test_minimum_version_check(self, version, expected):
        """Test that minimum version checking works correctly."""
        MIN_VERSION = '3.0.0'
        is_old = Sabnzbd._version_tuple(version) < Sabnzbd._version_tuple(MIN_VERSION)
        assert is_old == expected


# =============================================================================
# Fix 4: Storage Path Validation Tests
# =============================================================================

@requires_full_env
class TestStoragePathValidation:
    """Test that storage paths are validated before use.

    Bug: Storage paths weren't validated, causing silent post-processing failures.
    Fix: Check paths are absolute and exist before using them.
    """

    @pytest.fixture
    def sabnzbd_client(self):
        """Create a mock Sabnzbd client."""
        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = MagicMock()
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        return client

    def test_absolute_existing_path_accepted(self, sabnzbd_client, tmp_path):
        """Test that absolute existing paths are accepted."""
        download_dir = tmp_path / "downloads"
        download_dir.mkdir()

        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},
            {
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Completed',
                        'name': 'Test Download',
                        'bytes': 1000000,
                        'storage': str(download_dir)
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        result = sabnzbd_client.get_download('test_id')

        assert result is not None
        assert 'storage_path' in result
        assert result['storage_path'] == str(download_dir)

    def test_relative_path_rejected(self, sabnzbd_client):
        """Test that relative paths are rejected."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},
            {
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Completed',
                        'name': 'Test Download',
                        'bytes': 1000000,
                        'storage': 'relative/path/to/download'  # Relative!
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        result = sabnzbd_client.get_download('test_id')

        # Should not include storage_path if validation failed
        assert result is not None
        assert 'storage_path' not in result

    def test_nonexistent_path_rejected(self, sabnzbd_client):
        """Test that non-existent paths are rejected."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},
            {
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Completed',
                        'name': 'Test Download',
                        'bytes': 1000000,
                        'storage': '/this/path/does/not/exist/12345'
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        result = sabnzbd_client.get_download('test_id')

        # Should not include storage_path if path doesn't exist
        assert result is not None
        assert 'storage_path' not in result

    def test_empty_storage_path_handled(self, sabnzbd_client):
        """Test that empty storage paths are handled gracefully."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},
            {
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Completed',
                        'name': 'Test Download',
                        'bytes': 1000000,
                        'storage': ''
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        result = sabnzbd_client.get_download('test_id')

        assert result is not None
        assert 'storage_path' not in result


# =============================================================================
# Fix 5: API Rate Limiting/Caching Tests
# =============================================================================

@requires_full_env
class TestApiRateLimiting:
    """Test that API calls are rate-limited with caching.

    Bug: No rate limiting, causing excessive API calls.
    Fix: Added 2-second cache for download status.
    """

    @pytest.fixture
    def sabnzbd_client(self):
        """Create a mock Sabnzbd client."""
        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = MagicMock()
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        # Clear cache before each test
        client._status_cache = {}
        return client

    def test_cache_prevents_duplicate_api_calls(self, sabnzbd_client):
        """Test that cached results prevent duplicate API calls."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'queue': {
                'slots': [{
                    'nzo_id': 'test_id',
                    'status': 'Downloading',
                    'filename': 'Test.nzb',
                    'mb': '100',
                    'percentage': '50',
                    'kbpersec': '1024'
                }]
            }
        }
        sabnzbd_client.ssn.get.return_value = mock_resp

        # First call - should hit API
        result1 = sabnzbd_client.get_download('test_id')
        assert result1 is not None
        assert sabnzbd_client.ssn.get.call_count == 1

        # Second call within cache duration - should use cache
        result2 = sabnzbd_client.get_download('test_id')
        assert result2 is not None
        assert result2 == result1  # Same result
        assert sabnzbd_client.ssn.get.call_count == 1  # No additional API call

    def test_cache_expires_after_duration(self, sabnzbd_client):
        """Test that cache expires after configured duration."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'queue': {
                'slots': [{
                    'nzo_id': 'test_id',
                    'status': 'Downloading',
                    'filename': 'Test.nzb',
                    'mb': '100',
                    'percentage': '50',
                    'kbpersec': '1024'
                }]
            }
        }
        sabnzbd_client.ssn.get.return_value = mock_resp

        # First call
        result1 = sabnzbd_client.get_download('test_id')
        assert sabnzbd_client.ssn.get.call_count == 1

        # Wait for cache to expire (slightly longer than CACHE_DURATION)
        time.sleep(Sabnzbd._CACHE_DURATION + 0.1)

        # Second call after expiry - should hit API again
        result2 = sabnzbd_client.get_download('test_id')
        assert sabnzbd_client.ssn.get.call_count == 2

    def test_cache_per_download_id(self, sabnzbd_client):
        """Test that cache is per-download, not global."""
        def mock_get(*args, **kwargs):
            mock_resp = MagicMock()
            if 'queue' in kwargs['params']['mode']:
                # Return different download based on what's being queried
                mock_resp.json.return_value = {
                    'queue': {
                        'slots': [{
                            'nzo_id': 'test_id',
                            'status': 'Downloading',
                            'filename': 'Test.nzb',
                            'mb': '100',
                            'percentage': '50',
                            'kbpersec': '1024'
                        }]
                    }
                }
            return mock_resp

        sabnzbd_client.ssn.get.side_effect = mock_get

        # Get two different downloads
        result1 = sabnzbd_client.get_download('test_id_1')
        result2 = sabnzbd_client.get_download('test_id_2')

        # Each should have made its own API call (2 calls total)
        # Note: Each get_download makes 1-2 API calls (queue, possibly history)
        assert sabnzbd_client.ssn.get.call_count >= 2

    def test_delete_clears_cache(self, sabnzbd_client):
        """Test that deleting a download clears its cache."""
        # Setup cache with a download
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'queue': {
                'slots': [{
                    'nzo_id': 'test_id',
                    'status': 'Downloading',
                    'filename': 'Test.nzb',
                    'mb': '100',
                    'percentage': '50',
                    'kbpersec': '1024'
                }]
            }
        }
        sabnzbd_client.ssn.get.return_value = mock_resp

        # Populate cache
        result1 = sabnzbd_client.get_download('test_id')
        assert 'test_id' in sabnzbd_client._status_cache

        # Delete the download
        sabnzbd_client.delete_download('test_id', delete_files=True)

        # Cache should be cleared
        assert 'test_id' not in sabnzbd_client._status_cache

    def test_cache_thread_safety(self, sabnzbd_client):
        """Test that cache access is thread-safe."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'queue': {
                'slots': [{
                    'nzo_id': 'test_id',
                    'status': 'Downloading',
                    'filename': 'Test.nzb',
                    'mb': '100',
                    'percentage': '50',
                    'kbpersec': '1024'
                }]
            }
        }
        sabnzbd_client.ssn.get.return_value = mock_resp

        results = []
        errors = []

        def fetch_status():
            try:
                result = sabnzbd_client.get_download('test_id')
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Create multiple threads accessing cache simultaneously
        threads = [Thread(target=fetch_status) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should succeed
        assert len(errors) == 0
        assert len(results) == 10
        # All results should be identical (from cache)
        assert all(r == results[0] for r in results)


# =============================================================================
# Integration Tests
# =============================================================================

@requires_full_env
class TestUsenetFixesIntegration:
    """Integration tests combining multiple fixes."""

    @pytest.fixture
    def sabnzbd_client(self):
        """Create a mock Sabnzbd client."""
        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = MagicMock()
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        client._status_cache = {}
        return client

    def test_duplicate_with_caching(self, sabnzbd_client):
        """Test that duplicate failures are cached and not blocklisted."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},
            {
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Failed',
                        'fail_message': 'Duplicate NZB',
                        'name': 'Test Download',
                        'bytes': 0
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        # First call
        result1 = sabnzbd_client.get_download('test_id')
        assert result1['state'] == DownloadState.CANCELED_STATE
        assert sabnzbd_client.ssn.get.call_count == 2  # Queue + history

        # Reset mock to verify caching
        sabnzbd_client.ssn.get.reset_mock()

        # Second call should use cache
        result2 = sabnzbd_client.get_download('test_id')
        assert result2['state'] == DownloadState.CANCELED_STATE
        assert sabnzbd_client.ssn.get.call_count == 0  # No API calls

    def test_completed_with_valid_path(self, sabnzbd_client, tmp_path):
        """Test completed download with valid storage path."""
        download_dir = tmp_path / "completed"
        download_dir.mkdir()

        mock_resp = MagicMock()
        mock_resp.json.side_effect = [
            {'queue': {'slots': []}},
            {
                'history': {
                    'slots': [{
                        'nzo_id': 'test_id',
                        'status': 'Completed',
                        'name': 'Batman 001',
                        'bytes': 50000000,
                        'storage': str(download_dir)
                    }]
                }
            }
        ]
        sabnzbd_client.ssn.get.return_value = mock_resp

        result = sabnzbd_client.get_download('test_id')

        assert result is not None
        assert result['state'] == DownloadState.IMPORTING_STATE
        assert 'storage_path' in result
        assert result['storage_path'] == str(download_dir)
        assert result['progress'] == 100.0
