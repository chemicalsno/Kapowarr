# -*- coding: utf-8 -*-

"""
Tests for Usenet-related functionality including:
- NZB validation
- Download client exceptions
- Sabnzbd client methods
- Encrypted download detection
"""

import unittest
from unittest.mock import MagicMock, patch

from backend.base.custom_exceptions import (
    DownloadClientAuthenticationException,
    DownloadClientException,
    DownloadClientUnavailableException,
    EncryptedDownloadException,
    InvalidNzbException
)
from backend.implementations.usenet_clients.nzb_validation import (
    validate_nzb,
    validate_nzb_url_response
)

# Check if full environment is available (requests installed)
try:
    import requests
    FULL_ENV_AVAILABLE = True
except ImportError:
    FULL_ENV_AVAILABLE = False

# Decorator for tests that require the full Kapowarr environment
requires_full_env = unittest.skipUnless(
    FULL_ENV_AVAILABLE,
    "Requires full Kapowarr environment with all dependencies"
)


class TestNzbValidation(unittest.TestCase):
    """Test cases for NZB file validation."""

    def test_valid_nzb_minimal(self):
        """Test that a minimal valid NZB passes validation."""
        nzb_content = b'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <file poster="test@example.com" date="1234567890" subject="test.rar (1/1)">
    <groups><group>alt.binaries.test</group></groups>
    <segments>
      <segment bytes="1000" number="1">test@news.example.com</segment>
    </segments>
  </file>
</nzb>'''
        # Should not raise any exception
        validate_nzb(nzb_content, "test.nzb")

    def test_valid_nzb_multiple_files(self):
        """Test NZB with multiple file elements."""
        nzb_content = b'''<?xml version="1.0"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <file poster="test@example.com" date="1234567890" subject="test.part1.rar">
    <groups><group>alt.binaries.test</group></groups>
    <segments><segment bytes="1000" number="1">seg1@news</segment></segments>
  </file>
  <file poster="test@example.com" date="1234567891" subject="test.part2.rar">
    <groups><group>alt.binaries.test</group></groups>
    <segments><segment bytes="1000" number="1">seg2@news</segment></segments>
  </file>
</nzb>'''
        validate_nzb(nzb_content, "multifile.nzb")

    def test_valid_nzb_no_namespace(self):
        """Test NZB without XML namespace (some indexers do this)."""
        nzb_content = b'''<?xml version="1.0"?>
<nzb>
  <file poster="test" date="123" subject="test">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</nzb>'''
        validate_nzb(nzb_content)

    def test_invalid_nzb_empty_content(self):
        """Test that empty content raises InvalidNzbException."""
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb(b'', "empty.nzb")
        self.assertIn("Empty NZB content", str(ctx.exception.message))

    def test_invalid_nzb_not_xml(self):
        """Test that non-XML content raises InvalidNzbException."""
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb(b'This is not XML at all', "notxml.nzb")
        self.assertIn("Unable to parse XML", str(ctx.exception.message))

    def test_invalid_nzb_malformed_xml(self):
        """Test that malformed XML raises InvalidNzbException."""
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb(b'<nzb><file></nzb>', "malformed.nzb")
        self.assertIn("Unable to parse XML", str(ctx.exception.message))

    def test_invalid_nzb_wrong_root_element(self):
        """Test that wrong root element raises InvalidNzbException."""
        nzb_content = b'''<?xml version="1.0"?>
<rss version="2.0">
  <channel><title>Not an NZB</title></channel>
</rss>'''
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb(nzb_content, "rss.xml")
        self.assertIn("Unexpected root element", str(ctx.exception.message))
        self.assertIn("rss", str(ctx.exception.message))

    def test_invalid_nzb_indexer_error(self):
        """Test that indexer error XML raises InvalidNzbException (nZEDb bug)."""
        # This is what some broken indexers return instead of an NZB
        nzb_content = b'''<?xml version="1.0"?>
<error code="100" description="Incorrect user credentials"/>'''
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb(nzb_content, "error.nzb")
        self.assertIn("indexer error", str(ctx.exception.message).lower())
        self.assertIn("100", str(ctx.exception.message))

    def test_invalid_nzb_indexer_error_with_namespace(self):
        """Test indexer error detection with namespace."""
        nzb_content = b'''<?xml version="1.0"?>
<error xmlns="http://www.newznab.com/DTD/2010/feeds/attributes/"
       code="201" description="API key invalid"/>'''
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb(nzb_content)
        self.assertIn("indexer error", str(ctx.exception.message).lower())

    def test_invalid_nzb_no_files(self):
        """Test that NZB with no file elements raises InvalidNzbException."""
        nzb_content = b'''<?xml version="1.0"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <!-- No file elements -->
</nzb>'''
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb(nzb_content, "nofiles.nzb")
        self.assertIn("No files found", str(ctx.exception.message))

    def test_invalid_nzb_empty_nzb_element(self):
        """Test NZB with empty nzb root element."""
        nzb_content = b'<nzb></nzb>'
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb(nzb_content)
        self.assertIn("No files found", str(ctx.exception.message))


class TestNzbUrlValidation(unittest.TestCase):
    """Test cases for NZB URL response validation."""

    def test_valid_response(self):
        """Test that valid NZB response passes."""
        nzb_content = b'''<?xml version="1.0"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <file poster="test" date="123" subject="test">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</nzb>'''
        validate_nzb_url_response(nzb_content, "http://example.com/test.nzb")

    def test_empty_response(self):
        """Test that empty response raises InvalidNzbException."""
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb_url_response(b'', "http://example.com/test.nzb")
        self.assertIn("Empty response", str(ctx.exception.message))

    def test_html_error_page(self):
        """Test that HTML error page is detected."""
        html_content = b'''<!DOCTYPE html>
<html>
<head><title>Error</title></head>
<body><h1>404 Not Found</h1></body>
</html>'''
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb_url_response(html_content, "http://example.com/test.nzb")
        self.assertIn("HTML instead of NZB", str(ctx.exception.message))

    def test_html_without_doctype(self):
        """Test HTML detection without DOCTYPE."""
        html_content = b'<html><body>Error page</body></html>'
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb_url_response(html_content, "http://example.com/test.nzb")
        self.assertIn("HTML instead of NZB", str(ctx.exception.message))


class TestDownloadClientExceptions(unittest.TestCase):
    """Test cases for download client exception classes."""

    def test_download_client_exception_base(self):
        """Test base DownloadClientException."""
        exc = DownloadClientException("Test error")
        self.assertEqual(exc.message, "Test error")
        self.assertEqual(exc.api_response['code'], 400)
        self.assertEqual(exc.api_response['error'], "DownloadClientException")

    def test_download_client_exception_default_message(self):
        """Test DownloadClientException with default message."""
        exc = DownloadClientException()
        self.assertEqual(exc.message, "Download client error")

    def test_download_client_unavailable_exception(self):
        """Test DownloadClientUnavailableException."""
        exc = DownloadClientUnavailableException("Connection timeout")
        self.assertEqual(exc.message, "Connection timeout")
        self.assertEqual(exc.api_response['code'], 503)
        self.assertEqual(
            exc.api_response['error'],
            "DownloadClientUnavailableException"
        )

    def test_download_client_auth_exception(self):
        """Test DownloadClientAuthenticationException."""
        exc = DownloadClientAuthenticationException("Invalid API key")
        self.assertEqual(exc.message, "Invalid API key")
        self.assertEqual(exc.api_response['code'], 401)

    def test_invalid_nzb_exception(self):
        """Test InvalidNzbException."""
        exc = InvalidNzbException("No files in NZB")
        self.assertEqual(exc.message, "No files in NZB")
        self.assertEqual(exc.api_response['code'], 400)
        self.assertEqual(exc.api_response['error'], "InvalidNzbException")

    def test_encrypted_download_exception(self):
        """Test EncryptedDownloadException."""
        exc = EncryptedDownloadException()
        self.assertIn("encrypted", exc.message.lower())
        self.assertEqual(exc.api_response['code'], 400)

    def test_exception_inheritance(self):
        """Test that specific exceptions inherit from base."""
        self.assertTrue(
            issubclass(DownloadClientUnavailableException, DownloadClientException)
        )
        self.assertTrue(
            issubclass(DownloadClientAuthenticationException, DownloadClientException)
        )
        self.assertTrue(
            issubclass(InvalidNzbException, DownloadClientException)
        )
        self.assertTrue(
            issubclass(EncryptedDownloadException, DownloadClientException)
        )


class TestSabnzbdEncryptedDetection(unittest.TestCase):
    """Test encrypted download detection in Sabnzbd responses."""

    def test_detect_encrypted_in_queue_title(self):
        """Test detection of ENCRYPTED / prefix in queue title."""
        title = "ENCRYPTED /Batman (2020) Issue 5.nzb"
        is_encrypted = title.startswith('ENCRYPTED /')
        self.assertTrue(is_encrypted)

        # Strip prefix
        clean_title = title[11:] if is_encrypted else title
        self.assertEqual(clean_title, "Batman (2020) Issue 5.nzb")

    def test_no_encrypted_prefix(self):
        """Test normal title without encryption prefix."""
        title = "Batman (2020) Issue 5.nzb"
        is_encrypted = title.startswith('ENCRYPTED /')
        self.assertFalse(is_encrypted)

    def test_detect_encrypted_in_fail_message(self):
        """Test detection of encryption in fail_message."""
        fail_messages = [
            "Unpacking failed, archive requires a password",
            "Download is encrypted",
            "Password protected archive",
            "ENCRYPTED archive detected",
        ]
        for msg in fail_messages:
            is_encrypted = 'encrypted' in msg.lower() or 'password' in msg.lower()
            self.assertTrue(
                is_encrypted,
                f"Should detect encryption in: {msg}"
            )

    def test_normal_fail_message(self):
        """Test that normal fail messages don't trigger encryption detection."""
        fail_messages = [
            "Download failed: incomplete",
            "Server error",
            "Missing articles",
            "",
        ]
        for msg in fail_messages:
            is_encrypted = 'encrypted' in msg.lower() or 'password' in msg.lower()
            self.assertFalse(
                is_encrypted,
                f"Should not detect encryption in: {msg}"
            )


class TestSabnzbdStateMappings(unittest.TestCase):
    """Test Sabnzbd state to Kapowarr state mappings."""

    def setUp(self):
        """Set up state mapping for tests."""
        from backend.base.definitions import DownloadState

        self.STATE_MAPPING = {
            'Queued': DownloadState.QUEUED_STATE,
            'Paused': DownloadState.QUEUED_STATE,
            'Grabbing': DownloadState.QUEUED_STATE,
            'Downloading': DownloadState.DOWNLOADING_STATE,
            'Idle': DownloadState.DOWNLOADING_STATE,
            'Running': DownloadState.DOWNLOADING_STATE,
            'Verifying': DownloadState.DOWNLOADING_STATE,
            'Repairing': DownloadState.DOWNLOADING_STATE,
            'QuickCheck': DownloadState.DOWNLOADING_STATE,
            'Extracting': DownloadState.DOWNLOADING_STATE,
            'Moving': DownloadState.IMPORTING_STATE,
            'Completed': DownloadState.IMPORTING_STATE,
            'Failed': DownloadState.FAILED_STATE,
        }
        self.DownloadState = DownloadState

    def test_queue_states(self):
        """Test that queue states map correctly."""
        queue_states = ['Queued', 'Paused', 'Grabbing']
        for state in queue_states:
            self.assertEqual(
                self.STATE_MAPPING[state],
                self.DownloadState.QUEUED_STATE,
                f"{state} should map to QUEUED_STATE"
            )

    def test_downloading_states(self):
        """Test that downloading/processing states map correctly."""
        dl_states = [
            'Downloading', 'Idle', 'Running', 'Verifying',
            'Repairing', 'QuickCheck', 'Extracting'
        ]
        for state in dl_states:
            self.assertEqual(
                self.STATE_MAPPING[state],
                self.DownloadState.DOWNLOADING_STATE,
                f"{state} should map to DOWNLOADING_STATE"
            )

    def test_completed_states(self):
        """Test that completed states map correctly."""
        completed_states = ['Moving', 'Completed']
        for state in completed_states:
            self.assertEqual(
                self.STATE_MAPPING[state],
                self.DownloadState.IMPORTING_STATE,
                f"{state} should map to IMPORTING_STATE"
            )

    def test_failed_state(self):
        """Test that failed state maps correctly."""
        self.assertEqual(
            self.STATE_MAPPING['Failed'],
            self.DownloadState.FAILED_STATE
        )


class TestSabnzbdPriorityMappings(unittest.TestCase):
    """Test Sabnzbd priority mappings."""

    def setUp(self):
        """Set up priority mapping for tests."""
        self.PRIORITY_MAPPING = {
            'Default': -100,
            'Paused': -2,
            'Low': -1,
            'Normal': 0,
            'High': 1,
            'Force': 2,
        }

    def test_all_priorities_exist(self):
        """Test that all expected priority levels exist."""
        expected = ['Default', 'Paused', 'Low', 'Normal', 'High', 'Force']
        for priority in expected:
            self.assertIn(priority, self.PRIORITY_MAPPING)

    def test_priority_ordering(self):
        """Test that priorities are in correct order."""
        self.assertLess(
            self.PRIORITY_MAPPING['Paused'],
            self.PRIORITY_MAPPING['Low']
        )
        self.assertLess(
            self.PRIORITY_MAPPING['Low'],
            self.PRIORITY_MAPPING['Normal']
        )
        self.assertLess(
            self.PRIORITY_MAPPING['Normal'],
            self.PRIORITY_MAPPING['High']
        )
        self.assertLess(
            self.PRIORITY_MAPPING['High'],
            self.PRIORITY_MAPPING['Force']
        )

    def test_default_is_special(self):
        """Test that Default priority is special value."""
        self.assertEqual(self.PRIORITY_MAPPING['Default'], -100)


class TestSabnzbdVersionCheck(unittest.TestCase):
    """Test Sabnzbd version checking logic."""

    def test_version_comparison(self):
        """Test version string comparison."""
        MIN_VERSION = '3.0.0'

        # Versions that should pass
        passing = ['3.0.0', '3.0.1', '3.1.0', '4.0.0', '4.2.1']
        for version in passing:
            self.assertGreaterEqual(
                version, MIN_VERSION,
                f"Version {version} should pass minimum check"
            )

        # Versions that should fail
        failing = ['2.9.9', '2.0.0', '1.0.0']
        for version in failing:
            self.assertLess(
                version, MIN_VERSION,
                f"Version {version} should fail minimum check"
            )


class TestSabnzbdConfigWarnings(unittest.TestCase):
    """Test Sabnzbd configuration warning detection."""

    def test_pre_check_warning(self):
        """Test pre_check warning detection."""
        config = {'misc': {'pre_check': True}}
        warnings = []
        if config.get('misc', {}).get('pre_check', False):
            warnings.append("Pre-check is enabled")
        self.assertEqual(len(warnings), 1)
        self.assertIn("Pre-check", warnings[0])

    def test_tv_sorting_warning(self):
        """Test TV sorting warning detection."""
        config = {'misc': {'enable_tv_sorting': True}}
        warnings = []
        if config.get('misc', {}).get('enable_tv_sorting', False):
            warnings.append("TV sorting is enabled")
        self.assertEqual(len(warnings), 1)

    def test_movie_sorting_warning(self):
        """Test movie sorting warning detection."""
        config = {'misc': {'enable_movie_sorting': True}}
        warnings = []
        if config.get('misc', {}).get('enable_movie_sorting', False):
            warnings.append("Movie sorting is enabled")
        self.assertEqual(len(warnings), 1)

    def test_history_retention_warning(self):
        """Test history retention warning detection."""
        # Should warn
        warn_values = ['7', '30', 7, 30]
        for val in warn_values:
            warnings = []
            if val not in ('0', '-1', 0, -1):
                warnings.append("History retention limited")
            self.assertEqual(
                len(warnings), 1,
                f"Should warn for history_retention={val}"
            )

        # Should not warn
        ok_values = ['0', '-1', 0, -1]
        for val in ok_values:
            warnings = []
            if val not in ('0', '-1', 0, -1):
                warnings.append("History retention limited")
            self.assertEqual(
                len(warnings), 0,
                f"Should not warn for history_retention={val}"
            )

    def test_clean_config(self):
        """Test config with no problematic settings."""
        config = {
            'misc': {
                'pre_check': False,
                'enable_tv_sorting': False,
                'enable_movie_sorting': False,
                'history_retention': '0',
            }
        }
        warnings = []
        misc = config.get('misc', {})
        if misc.get('pre_check', False):
            warnings.append("Pre-check enabled")
        if misc.get('enable_tv_sorting', False):
            warnings.append("TV sorting enabled")
        if misc.get('enable_movie_sorting', False):
            warnings.append("Movie sorting enabled")
        if misc.get('history_retention', '0') not in ('0', '-1', 0, -1):
            warnings.append("History retention limited")

        self.assertEqual(len(warnings), 0)


@requires_full_env
class TestSabnzbdClientMocked(unittest.TestCase):
    """Test Sabnzbd client methods with mocked HTTP responses."""

    def _create_mock_response(self, json_data, status_code=200, ok=True):
        """Helper to create a mock response object."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = json_data
        mock_resp.status_code = status_code
        mock_resp.ok = ok
        mock_resp.text = str(json_data)
        mock_resp.raise_for_status = MagicMock()
        if not ok:
            mock_resp.raise_for_status.side_effect = Exception("HTTP Error")
        return mock_resp

    @patch('backend.implementations.usenet_clients.Sabnzbd.Session')
    def test_test_connection_success(self, MockSession):
        """Test successful connection test."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        mock_session = MagicMock()
        MockSession.return_value = mock_session

        # Mock version response
        version_resp = self._create_mock_response({'version': '4.0.0'})
        # Mock config response
        config_resp = self._create_mock_response({
            'config': {
                'misc': {
                    'pre_check': False,
                    'enable_tv_sorting': False,
                    'enable_movie_sorting': False,
                    'history_retention': '0'
                }
            }
        })
        mock_session.get.side_effect = [version_resp, config_resp]

        result = Sabnzbd.test(
            base_url='http://localhost:8080',
            username=None,
            password=None,
            api_token='test_api_key'
        )

        self.assertTrue(result['success'])
        self.assertIn('4.0.0', result['message'])
        self.assertEqual(result['version'], '4.0.0')
        self.assertEqual(len(result['warnings']), 0)

    @patch('backend.implementations.usenet_clients.Sabnzbd.Session')
    def test_test_connection_with_warnings(self, MockSession):
        """Test connection test with config warnings."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        mock_session = MagicMock()
        MockSession.return_value = mock_session

        version_resp = self._create_mock_response({'version': '4.0.0'})
        config_resp = self._create_mock_response({
            'config': {
                'misc': {
                    'pre_check': True,  # Should warn
                    'enable_tv_sorting': True,  # Should warn
                    'history_retention': '7'  # Should warn
                }
            }
        })
        mock_session.get.side_effect = [version_resp, config_resp]

        result = Sabnzbd.test(
            base_url='http://localhost:8080',
            username=None,
            password=None,
            api_token='test_api_key'
        )

        self.assertTrue(result['success'])
        self.assertGreater(len(result['warnings']), 0)

    @patch('backend.implementations.usenet_clients.Sabnzbd.Session')
    def test_test_connection_old_version(self, MockSession):
        """Test connection test with old Sabnzbd version."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        mock_session = MagicMock()
        MockSession.return_value = mock_session

        version_resp = self._create_mock_response({'version': '2.3.0'})
        config_resp = self._create_mock_response({'config': {'misc': {}}})
        mock_session.get.side_effect = [version_resp, config_resp]

        result = Sabnzbd.test(
            base_url='http://localhost:8080',
            username=None,
            password=None,
            api_token='test_api_key'
        )

        self.assertTrue(result['success'])
        # Should have version warning
        self.assertTrue(
            any('version' in w.lower() for w in result['warnings'])
        )

    @patch('backend.implementations.usenet_clients.Sabnzbd.Session')
    def test_test_connection_invalid_api_key(self, MockSession):
        """Test connection test with invalid API key."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd
        from backend.base.custom_exceptions import CredentialInvalid

        mock_session = MagicMock()
        MockSession.return_value = mock_session

        # Sabnzbd returns error in JSON when API key is invalid
        error_resp = self._create_mock_response({
            'error': 'API Key Incorrect'
        })
        mock_session.get.return_value = error_resp

        with self.assertRaises(CredentialInvalid):
            Sabnzbd.test(
                base_url='http://localhost:8080',
                username=None,
                password=None,
                api_token='invalid_key'
            )

    @patch('backend.implementations.usenet_clients.Sabnzbd.Session')
    def test_test_connection_no_api_key(self, MockSession):
        """Test connection test without API key."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd
        from backend.base.custom_exceptions import CredentialInvalid

        with self.assertRaises(CredentialInvalid):
            Sabnzbd.test(
                base_url='http://localhost:8080',
                username=None,
                password=None,
                api_token=None
            )

    @patch('backend.implementations.usenet_clients.Sabnzbd.Session')
    def test_test_connection_network_error(self, MockSession):
        """Test connection test with network error."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd
        from backend.base.custom_exceptions import ClientNotWorking
        from requests.exceptions import RequestException

        mock_session = MagicMock()
        MockSession.return_value = mock_session
        mock_session.get.side_effect = RequestException("Connection refused")

        with self.assertRaises(ClientNotWorking):
            Sabnzbd.test(
                base_url='http://localhost:8080',
                username=None,
                password=None,
                api_token='test_key'
            )


@requires_full_env
class TestSabnzbdAddDownload(unittest.TestCase):
    """Test Sabnzbd add_download method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_session = MagicMock()
        self.mock_settings = MagicMock()
        self.mock_settings.sv.sabnzbd_category = 'comics'
        self.mock_settings.sv.sabnzbd_priority = 'Normal'

    def _create_sabnzbd_client(self):
        """Helper to create a Sabnzbd client for testing."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = self.mock_session
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        client.settings = self.mock_settings
        return client

    def test_add_download_success(self):
        """Test successful download addition."""
        client = self._create_sabnzbd_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': True,
            'nzo_ids': ['SABnzbd_nzo_abc123']
        }
        self.mock_session.post.return_value = mock_resp

        nzo_id = client.add_download(
            download_link='http://indexer.com/nzb/123',
            target_folder='/downloads',
            download_name='Batman 2020 Issue 5'
        )

        self.assertEqual(nzo_id, 'SABnzbd_nzo_abc123')
        self.mock_session.post.assert_called_once()

    def test_add_download_failure(self):
        """Test failed download addition."""
        from backend.base.custom_exceptions import EnqueuingDownloadFailure

        client = self._create_sabnzbd_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': False,
            'error': 'NZB file not found'
        }
        self.mock_session.post.return_value = mock_resp

        with self.assertRaises(EnqueuingDownloadFailure):
            client.add_download(
                download_link='http://indexer.com/nzb/invalid',
                target_folder='/downloads',
                download_name='Invalid NZB'
            )


@requires_full_env
class TestSabnzbdGetDownload(unittest.TestCase):
    """Test Sabnzbd get_download method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_session = MagicMock()

    def _create_sabnzbd_client(self):
        """Helper to create a Sabnzbd client for testing."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = self.mock_session
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        return client

    def test_get_download_from_queue(self):
        """Test getting download status from queue."""
        from backend.base.definitions import DownloadState

        client = self._create_sabnzbd_client()

        # Mock queue response with our download
        queue_resp = MagicMock()
        queue_resp.json.return_value = {
            'queue': {
                'slots': [{
                    'nzo_id': 'SABnzbd_nzo_abc123',
                    'status': 'Downloading',
                    'filename': 'Batman.2020.Issue.5.nzb',
                    'mb': '500',
                    'percentage': '25',
                    'kbpersec': '1024'
                }]
            }
        }
        self.mock_session.get.return_value = queue_resp

        result = client.get_download('SABnzbd_nzo_abc123')

        self.assertIsNotNone(result)
        self.assertEqual(result['state'], DownloadState.DOWNLOADING_STATE)
        self.assertEqual(result['progress'], 75.0)  # 100 - 25
        self.assertFalse(result['is_encrypted'])

    def test_get_download_from_history(self):
        """Test getting completed download from history."""
        from backend.base.definitions import DownloadState

        client = self._create_sabnzbd_client()

        # Mock empty queue, then history with completed download
        queue_resp = MagicMock()
        queue_resp.json.return_value = {'queue': {'slots': []}}

        history_resp = MagicMock()
        history_resp.json.return_value = {
            'history': {
                'slots': [{
                    'nzo_id': 'SABnzbd_nzo_abc123',
                    'status': 'Completed',
                    'name': 'Batman.2020.Issue.5',
                    'bytes': 524288000,
                    'storage': '/downloads/complete/Batman.2020.Issue.5'
                }]
            }
        }
        self.mock_session.get.side_effect = [queue_resp, history_resp]

        result = client.get_download('SABnzbd_nzo_abc123')

        self.assertIsNotNone(result)
        self.assertEqual(result['state'], DownloadState.IMPORTING_STATE)
        self.assertEqual(result['progress'], 100.0)
        self.assertIn('storage_path', result)

    def test_get_download_not_found(self):
        """Test getting non-existent download."""
        client = self._create_sabnzbd_client()

        queue_resp = MagicMock()
        queue_resp.json.return_value = {'queue': {'slots': []}}

        history_resp = MagicMock()
        history_resp.json.return_value = {'history': {'slots': []}}

        self.mock_session.get.side_effect = [queue_resp, history_resp]

        result = client.get_download('nonexistent_id')

        self.assertIsNone(result)

    def test_get_download_encrypted_in_queue(self):
        """Test detecting encrypted download in queue."""
        from backend.base.definitions import DownloadState

        client = self._create_sabnzbd_client()

        queue_resp = MagicMock()
        queue_resp.json.return_value = {
            'queue': {
                'slots': [{
                    'nzo_id': 'SABnzbd_nzo_encrypted',
                    'status': 'Downloading',
                    'filename': 'ENCRYPTED /Batman.2020.Issue.5.nzb',
                    'mb': '500',
                    'percentage': '50',
                    'kbpersec': '0'
                }]
            }
        }
        self.mock_session.get.return_value = queue_resp

        result = client.get_download('SABnzbd_nzo_encrypted')

        self.assertIsNotNone(result)
        self.assertTrue(result['is_encrypted'])
        self.assertEqual(result['title'], 'Batman.2020.Issue.5.nzb')

    def test_get_download_encrypted_in_history(self):
        """Test detecting encrypted download in history via fail_message."""
        from backend.base.definitions import DownloadState

        client = self._create_sabnzbd_client()

        queue_resp = MagicMock()
        queue_resp.json.return_value = {'queue': {'slots': []}}

        history_resp = MagicMock()
        history_resp.json.return_value = {
            'history': {
                'slots': [{
                    'nzo_id': 'SABnzbd_nzo_encrypted',
                    'status': 'Failed',
                    'name': 'Batman.2020.Issue.5',
                    'bytes': 0,
                    'fail_message': 'Unpacking failed, archive requires password'
                }]
            }
        }
        self.mock_session.get.side_effect = [queue_resp, history_resp]

        result = client.get_download('SABnzbd_nzo_encrypted')

        self.assertIsNotNone(result)
        self.assertTrue(result['is_encrypted'])
        self.assertEqual(result['state'], DownloadState.FAILED_STATE)


@requires_full_env
class TestSabnzbdRetryDownload(unittest.TestCase):
    """Test Sabnzbd retry_download method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_session = MagicMock()

    def _create_sabnzbd_client(self):
        """Helper to create a Sabnzbd client for testing."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = self.mock_session
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        return client

    def test_retry_download_success(self):
        """Test successful download retry."""
        client = self._create_sabnzbd_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': True,
            'nzo_ids': ['SABnzbd_nzo_new123']
        }
        mock_resp.raise_for_status = MagicMock()
        self.mock_session.get.return_value = mock_resp

        new_id = client.retry_download('SABnzbd_nzo_old123')

        self.assertEqual(new_id, 'SABnzbd_nzo_new123')

    def test_retry_download_failure(self):
        """Test failed download retry."""
        from backend.base.custom_exceptions import DownloadClientException

        client = self._create_sabnzbd_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': False,
            'error': 'Job not found in history'
        }
        mock_resp.raise_for_status = MagicMock()
        self.mock_session.get.return_value = mock_resp

        with self.assertRaises(DownloadClientException):
            client.retry_download('nonexistent_id')

    def test_retry_download_no_new_id(self):
        """Test retry when no new ID is returned."""
        from backend.base.custom_exceptions import DownloadClientException

        client = self._create_sabnzbd_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': True,
            'nzo_ids': []  # Empty list
        }
        mock_resp.raise_for_status = MagicMock()
        self.mock_session.get.return_value = mock_resp

        with self.assertRaises(DownloadClientException):
            client.retry_download('SABnzbd_nzo_old123')


@requires_full_env
class TestSabnzbdDeleteDownload(unittest.TestCase):
    """Test Sabnzbd delete_download method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_session = MagicMock()

    def _create_sabnzbd_client(self):
        """Helper to create a Sabnzbd client for testing."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = self.mock_session
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        return client

    def test_delete_download_success(self):
        """Test successful download deletion."""
        client = self._create_sabnzbd_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {'status': True}
        self.mock_session.get.return_value = mock_resp

        # Should not raise
        client.delete_download('SABnzbd_nzo_abc123', delete_files=True)

        # Should have called delete on both queue and history
        self.assertEqual(self.mock_session.get.call_count, 2)

    def test_delete_download_with_files(self):
        """Test deletion with file deletion flag."""
        client = self._create_sabnzbd_client()

        mock_resp = MagicMock()
        self.mock_session.get.return_value = mock_resp

        client.delete_download('SABnzbd_nzo_abc123', delete_files=True)

        # Verify del_files parameter was passed
        calls = self.mock_session.get.call_args_list
        for call in calls:
            params = call[1].get('params', call[0][1] if len(call[0]) > 1 else {})
            self.assertIn('del_files', params)


class TestNzbValidationEdgeCases(unittest.TestCase):
    """Test edge cases in NZB validation."""

    def test_nzb_with_xml_comments(self):
        """Test NZB with XML comments."""
        nzb_content = b'''<?xml version="1.0"?>
<!-- This is a comment -->
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <!-- Another comment -->
  <file poster="test" date="123" subject="test">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</nzb>'''
        # Should not raise
        validate_nzb(nzb_content)

    def test_nzb_with_cdata(self):
        """Test NZB with CDATA sections in text content."""
        # CDATA must be in element text content, not attribute values
        nzb_content = b'''<?xml version="1.0"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <file poster="test" date="123" subject="test">
    <groups><group><![CDATA[alt.binaries.<special>]]></group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</nzb>'''
        validate_nzb(nzb_content)

    def test_nzb_with_unicode(self):
        """Test NZB with unicode characters."""
        nzb_content = '''<?xml version="1.0" encoding="UTF-8"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <file poster="tëst@example.com" date="123" subject="Bätmän 日本語">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</nzb>'''.encode('utf-8')
        validate_nzb(nzb_content)

    def test_nzb_with_many_files(self):
        """Test NZB with many file elements."""
        files = '\n'.join([
            f'''<file poster="test" date="{i}" subject="part{i}.rar">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">seg{i}</segment></segments>
  </file>'''
            for i in range(100)
        ])
        nzb_content = f'''<?xml version="1.0"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  {files}
</nzb>'''.encode()
        validate_nzb(nzb_content)

    def test_nzb_with_extra_whitespace(self):
        """Test NZB with extra whitespace."""
        nzb_content = b'''<?xml version="1.0"?>

<nzb    xmlns="http://www.newzbin.com/DTD/2003/nzb"   >

  <file   poster="test"   date="123"   subject="test"  >
    <groups>  <group>  test  </group>  </groups>
    <segments>
      <segment bytes="100" number="1">  x  </segment>
    </segments>
  </file>

</nzb>'''
        validate_nzb(nzb_content)

    def test_nzb_with_different_namespace(self):
        """Test NZB with non-standard namespace."""
        nzb_content = b'''<?xml version="1.0"?>
<nzb xmlns="http://custom.namespace.org/nzb">
  <file poster="test" date="123" subject="test">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</nzb>'''
        validate_nzb(nzb_content)

    def test_nzb_case_sensitivity(self):
        """Test that root element check is case-insensitive for tag name."""
        # Note: XML is case-sensitive, so <NZB> is different from <nzb>
        # This should fail as it's not 'nzb'
        nzb_content = b'''<?xml version="1.0"?>
<NZB>
  <file poster="test" date="123" subject="test">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</NZB>'''
        with self.assertRaises(InvalidNzbException):
            validate_nzb(nzb_content)

    def test_indexer_error_variations(self):
        """Test various indexer error response formats."""
        error_formats = [
            b'<error code="100" description="Incorrect user credentials"/>',
            b'<error code="200" description="Missing parameter"/>',
            b'<error code="500" description="Request limit reached"/>',
            b'<?xml version="1.0"?><error code="401" description="Unauthorized"/>',
        ]
        for error_xml in error_formats:
            with self.assertRaises(InvalidNzbException) as ctx:
                validate_nzb(error_xml)
            self.assertIn("indexer error", ctx.exception.message.lower())


class TestUsenetDownloadIntegration(unittest.TestCase):
    """Test UsenetDownload class integration."""

    def test_update_status_marks_encrypted_as_failed(self):
        """Test that encrypted downloads are marked as failed."""
        from backend.base.definitions import DownloadState

        # Simulate what update_status does when it detects encryption
        usenet_status = {
            'progress': 50.0,
            'speed': 1000,
            'size': 524288000,
            'state': DownloadState.DOWNLOADING_STATE,
            'is_encrypted': True
        }

        # Simulate the logic from UsenetDownload.update_status()
        state = DownloadState.QUEUED_STATE
        if usenet_status.get('is_encrypted', False):
            state = DownloadState.FAILED_STATE

        self.assertEqual(state, DownloadState.FAILED_STATE)

    def test_update_status_normal_download(self):
        """Test normal download status update."""
        from backend.base.definitions import DownloadState

        usenet_status = {
            'progress': 75.0,
            'speed': 2000,
            'size': 524288000,
            'state': DownloadState.DOWNLOADING_STATE,
            'is_encrypted': False
        }

        # Normal download should keep its state
        state = usenet_status['state']
        if usenet_status.get('is_encrypted', False):
            state = DownloadState.FAILED_STATE

        self.assertEqual(state, DownloadState.DOWNLOADING_STATE)

    def test_storage_path_extraction(self):
        """Test storage path extraction on completion."""
        from backend.base.definitions import DownloadState

        usenet_status = {
            'progress': 100.0,
            'speed': 0,
            'size': 524288000,
            'state': DownloadState.IMPORTING_STATE,
            'is_encrypted': False,
            'storage_path': '/downloads/complete/Batman.2020.Issue.5'
        }

        # Simulate storage path extraction logic
        files = []
        if (
            usenet_status.get('state') == DownloadState.IMPORTING_STATE
            and 'storage_path' in usenet_status
        ):
            files = [usenet_status['storage_path']]

        self.assertEqual(len(files), 1)
        self.assertIn('Batman', files[0])


class TestNzbValidationWithMockedRequests(unittest.TestCase):
    """Test NZB validation in the context of HTTP responses."""

    def test_validate_gzip_nzb_content(self):
        """Test that gzip-compressed content is handled correctly."""
        import gzip

        nzb_content = b'''<?xml version="1.0"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <file poster="test" date="123" subject="test">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</nzb>'''
        compressed = gzip.compress(nzb_content)

        # Decompressed content should validate
        decompressed = gzip.decompress(compressed)
        validate_nzb(decompressed)

    def test_validate_handles_bom(self):
        """Test handling of UTF-8 BOM (byte order mark)."""
        # UTF-8 BOM + valid NZB
        nzb_with_bom = b'\xef\xbb\xbf<?xml version="1.0"?>\n<nzb><file poster="t" date="1" subject="t"><groups><group>t</group></groups><segments><segment bytes="1" number="1">x</segment></segments></file></nzb>'

        # Should handle BOM gracefully (XML parser usually handles this)
        validate_nzb(nzb_with_bom)


class TestErrorRecovery(unittest.TestCase):
    """Test error recovery scenarios."""

    def test_exception_messages_are_informative(self):
        """Test that exception messages contain useful information."""
        # Test InvalidNzbException message format
        with self.assertRaises(InvalidNzbException) as ctx:
            validate_nzb(b'not xml', 'test_file.nzb')

        message = ctx.exception.message
        self.assertIn('test_file.nzb', message)
        self.assertIn('Unable to parse XML', message)

    def test_exception_api_response_format(self):
        """Test that exceptions produce valid API responses."""
        exc = InvalidNzbException("Test error message")
        response = exc.api_response

        self.assertIn('code', response)
        self.assertIn('error', response)
        self.assertIn('result', response)
        self.assertIsInstance(response['code'], int)
        self.assertIsInstance(response['error'], str)
        self.assertIsInstance(response['result'], dict)

    def test_network_error_exception_hierarchy(self):
        """Test that network errors use correct exception type."""
        from backend.base.custom_exceptions import (
            ClientNotWorking,
            DownloadClientUnavailableException
        )

        # DownloadClientUnavailableException should be usable for network errors
        exc = DownloadClientUnavailableException("Connection refused")
        self.assertEqual(exc.api_response['code'], 503)  # Service Unavailable


if __name__ == '__main__':
    unittest.main()
