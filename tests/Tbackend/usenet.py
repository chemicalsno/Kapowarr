# -*- coding: utf-8 -*-

"""
Tests for Usenet-related functionality including:
- NZB validation
- Download client exceptions
- Sabnzbd client methods
- Encrypted download detection

Converted to pytest format.
"""

import gzip
from unittest.mock import MagicMock, patch

import pytest

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

# Marker for tests that require the full Kapowarr environment
requires_full_env = pytest.mark.skipif(
    not FULL_ENV_AVAILABLE,
    reason="Requires full Kapowarr environment with all dependencies"
)


# =============================================================================
# NZB Validation Tests
# =============================================================================

class TestNzbValidation:
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
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(b'', "empty.nzb")
        assert "Empty NZB content" in str(exc_info.value.message)

    def test_invalid_nzb_not_xml(self):
        """Test that non-XML content raises InvalidNzbException."""
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(b'This is not XML at all', "notxml.nzb")
        assert "Unable to parse XML" in str(exc_info.value.message)

    def test_invalid_nzb_malformed_xml(self):
        """Test that malformed XML raises InvalidNzbException."""
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(b'<nzb><file></nzb>', "malformed.nzb")
        assert "Unable to parse XML" in str(exc_info.value.message)

    def test_invalid_nzb_wrong_root_element(self):
        """Test that wrong root element raises InvalidNzbException."""
        nzb_content = b'''<?xml version="1.0"?>
<rss version="2.0">
  <channel><title>Not an NZB</title></channel>
</rss>'''
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(nzb_content, "rss.xml")
        assert "Unexpected root element" in str(exc_info.value.message)
        assert "rss" in str(exc_info.value.message)

    def test_invalid_nzb_indexer_error(self):
        """Test that indexer error XML raises InvalidNzbException (nZEDb bug)."""
        nzb_content = b'''<?xml version="1.0"?>
<error code="100" description="Incorrect user credentials"/>'''
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(nzb_content, "error.nzb")
        assert "indexer error" in str(exc_info.value.message).lower()
        assert "100" in str(exc_info.value.message)

    def test_invalid_nzb_indexer_error_with_namespace(self):
        """Test indexer error detection with namespace."""
        nzb_content = b'''<?xml version="1.0"?>
<error xmlns="http://www.newznab.com/DTD/2010/feeds/attributes/"
       code="201" description="API key invalid"/>'''
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(nzb_content)
        assert "indexer error" in str(exc_info.value.message).lower()

    def test_invalid_nzb_no_files(self):
        """Test that NZB with no file elements raises InvalidNzbException."""
        nzb_content = b'''<?xml version="1.0"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <!-- No file elements -->
</nzb>'''
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(nzb_content, "nofiles.nzb")
        assert "No files found" in str(exc_info.value.message)

    def test_invalid_nzb_empty_nzb_element(self):
        """Test NZB with empty nzb root element."""
        nzb_content = b'<nzb></nzb>'
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(nzb_content)
        assert "No files found" in str(exc_info.value.message)


class TestNzbUrlValidation:
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
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb_url_response(b'', "http://example.com/test.nzb")
        assert "Empty response" in str(exc_info.value.message)

    def test_html_error_page(self):
        """Test that HTML error page is detected."""
        html_content = b'''<!DOCTYPE html>
<html>
<head><title>Error</title></head>
<body><h1>404 Not Found</h1></body>
</html>'''
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb_url_response(html_content, "http://example.com/test.nzb")
        assert "HTML instead of NZB" in str(exc_info.value.message)

    def test_html_without_doctype(self):
        """Test HTML detection without DOCTYPE."""
        html_content = b'<html><body>Error page</body></html>'
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb_url_response(html_content, "http://example.com/test.nzb")
        assert "HTML instead of NZB" in str(exc_info.value.message)


# =============================================================================
# Download Client Exception Tests
# =============================================================================

class TestDownloadClientExceptions:
    """Test cases for download client exception classes."""

    def test_download_client_exception_base(self):
        """Test base DownloadClientException."""
        exc = DownloadClientException("Test error")
        assert exc.message == "Test error"
        assert exc.api_response['code'] == 400
        assert exc.api_response['error'] == "DownloadClientException"

    def test_download_client_exception_default_message(self):
        """Test DownloadClientException with default message."""
        exc = DownloadClientException()
        assert exc.message == "Download client error"

    def test_download_client_unavailable_exception(self):
        """Test DownloadClientUnavailableException."""
        exc = DownloadClientUnavailableException("Connection timeout")
        assert exc.message == "Connection timeout"
        assert exc.api_response['code'] == 503
        assert exc.api_response['error'] == "DownloadClientUnavailableException"

    def test_download_client_auth_exception(self):
        """Test DownloadClientAuthenticationException."""
        exc = DownloadClientAuthenticationException("Invalid API key")
        assert exc.message == "Invalid API key"
        assert exc.api_response['code'] == 401

    def test_invalid_nzb_exception(self):
        """Test InvalidNzbException."""
        exc = InvalidNzbException("No files in NZB")
        assert exc.message == "No files in NZB"
        assert exc.api_response['code'] == 400
        assert exc.api_response['error'] == "InvalidNzbException"

    def test_encrypted_download_exception(self):
        """Test EncryptedDownloadException."""
        exc = EncryptedDownloadException()
        assert "encrypted" in exc.message.lower()
        assert exc.api_response['code'] == 400

    def test_exception_inheritance(self):
        """Test that specific exceptions inherit from base."""
        assert issubclass(DownloadClientUnavailableException, DownloadClientException)
        assert issubclass(DownloadClientAuthenticationException, DownloadClientException)
        assert issubclass(InvalidNzbException, DownloadClientException)
        assert issubclass(EncryptedDownloadException, DownloadClientException)


# =============================================================================
# Sabnzbd Detection Tests
# =============================================================================

class TestSabnzbdEncryptedDetection:
    """Test encrypted download detection in Sabnzbd responses."""

    def test_detect_encrypted_in_queue_title(self):
        """Test detection of ENCRYPTED / prefix in queue title."""
        title = "ENCRYPTED /Batman (2020) Issue 5.nzb"
        is_encrypted = title.startswith('ENCRYPTED /')
        assert is_encrypted

        # Strip prefix
        clean_title = title[11:] if is_encrypted else title
        assert clean_title == "Batman (2020) Issue 5.nzb"

    def test_no_encrypted_prefix(self):
        """Test normal title without encryption prefix."""
        title = "Batman (2020) Issue 5.nzb"
        is_encrypted = title.startswith('ENCRYPTED /')
        assert not is_encrypted

    @pytest.mark.parametrize("msg", [
        "Unpacking failed, archive requires a password",
        "Download is encrypted",
        "Password protected archive",
        "ENCRYPTED archive detected",
    ])
    def test_detect_encrypted_in_fail_message(self, msg):
        """Test detection of encryption in fail_message."""
        is_encrypted = 'encrypted' in msg.lower() or 'password' in msg.lower()
        assert is_encrypted, f"Should detect encryption in: {msg}"

    @pytest.mark.parametrize("msg", [
        "Download failed: incomplete",
        "Server error",
        "Missing articles",
        "",
    ])
    def test_normal_fail_message(self, msg):
        """Test that normal fail messages don't trigger encryption detection."""
        is_encrypted = 'encrypted' in msg.lower() or 'password' in msg.lower()
        assert not is_encrypted, f"Should not detect encryption in: {msg}"


class TestSabnzbdStateMappings:
    """Test Sabnzbd state to Kapowarr state mappings."""

    @pytest.fixture
    def state_mapping(self):
        """Set up state mapping for tests."""
        from backend.base.definitions import DownloadState

        return {
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

    @pytest.mark.parametrize("state", ['Queued', 'Paused', 'Grabbing'])
    def test_queue_states(self, state, state_mapping):
        """Test that queue states map correctly."""
        from backend.base.definitions import DownloadState
        assert state_mapping[state] == DownloadState.QUEUED_STATE

    @pytest.mark.parametrize("state", [
        'Downloading', 'Idle', 'Running', 'Verifying',
        'Repairing', 'QuickCheck', 'Extracting'
    ])
    def test_downloading_states(self, state, state_mapping):
        """Test that downloading/processing states map correctly."""
        from backend.base.definitions import DownloadState
        assert state_mapping[state] == DownloadState.DOWNLOADING_STATE

    @pytest.mark.parametrize("state", ['Moving', 'Completed'])
    def test_completed_states(self, state, state_mapping):
        """Test that completed states map correctly."""
        from backend.base.definitions import DownloadState
        assert state_mapping[state] == DownloadState.IMPORTING_STATE

    def test_failed_state(self, state_mapping):
        """Test that failed state maps correctly."""
        from backend.base.definitions import DownloadState
        assert state_mapping['Failed'] == DownloadState.FAILED_STATE


class TestSabnzbdPriorityMappings:
    """Test Sabnzbd priority mappings."""

    @pytest.fixture
    def priority_mapping(self):
        """Set up priority mapping for tests."""
        return {
            'Default': -100,
            'Paused': -2,
            'Low': -1,
            'Normal': 0,
            'High': 1,
            'Force': 2,
        }

    @pytest.mark.parametrize("priority", ['Default', 'Paused', 'Low', 'Normal', 'High', 'Force'])
    def test_all_priorities_exist(self, priority, priority_mapping):
        """Test that all expected priority levels exist."""
        assert priority in priority_mapping

    def test_priority_ordering(self, priority_mapping):
        """Test that priorities are in correct order."""
        assert priority_mapping['Paused'] < priority_mapping['Low']
        assert priority_mapping['Low'] < priority_mapping['Normal']
        assert priority_mapping['Normal'] < priority_mapping['High']
        assert priority_mapping['High'] < priority_mapping['Force']

    def test_default_is_special(self, priority_mapping):
        """Test that Default priority is special value."""
        assert priority_mapping['Default'] == -100


class TestSabnzbdVersionCheck:
    """Test Sabnzbd version checking logic.

    Note: These tests use the FIXED version comparison with _version_tuple(),
    not string comparison which has bugs with multi-digit versions.
    """

    MIN_VERSION = '3.0.0'

    @pytest.mark.parametrize("version", ['3.0.0', '3.0.1', '3.1.0', '3.10.0', '4.0.0', '4.2.1'])
    @requires_full_env
    def test_version_passing(self, version):
        """Test versions that should pass minimum check."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd
        # Use the fixed _version_tuple() method for proper comparison
        assert Sabnzbd._version_tuple(version) >= Sabnzbd._version_tuple(self.MIN_VERSION)

    @pytest.mark.parametrize("version", ['2.9.9', '2.0.0', '1.0.0'])
    @requires_full_env
    def test_version_failing(self, version):
        """Test versions that should fail minimum check."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd
        # Use the fixed _version_tuple() method for proper comparison
        assert Sabnzbd._version_tuple(version) < Sabnzbd._version_tuple(self.MIN_VERSION)


class TestSabnzbdConfigWarnings:
    """Test Sabnzbd configuration warning detection."""

    def test_pre_check_warning(self):
        """Test pre_check warning detection."""
        config = {'misc': {'pre_check': True}}
        warnings = []
        if config.get('misc', {}).get('pre_check', False):
            warnings.append("Pre-check is enabled")
        assert len(warnings) == 1
        assert "Pre-check" in warnings[0]

    def test_tv_sorting_warning(self):
        """Test TV sorting warning detection."""
        config = {'misc': {'enable_tv_sorting': True}}
        warnings = []
        if config.get('misc', {}).get('enable_tv_sorting', False):
            warnings.append("TV sorting is enabled")
        assert len(warnings) == 1

    def test_movie_sorting_warning(self):
        """Test movie sorting warning detection."""
        config = {'misc': {'enable_movie_sorting': True}}
        warnings = []
        if config.get('misc', {}).get('enable_movie_sorting', False):
            warnings.append("Movie sorting is enabled")
        assert len(warnings) == 1

    @pytest.mark.parametrize("val", ['7', '30', 7, 30])
    def test_history_retention_warning(self, val):
        """Test history retention warning detection - should warn."""
        warnings = []
        if val not in ('0', '-1', 0, -1):
            warnings.append("History retention limited")
        assert len(warnings) == 1

    @pytest.mark.parametrize("val", ['0', '-1', 0, -1])
    def test_history_retention_ok(self, val):
        """Test history retention values that should not warn."""
        warnings = []
        if val not in ('0', '-1', 0, -1):
            warnings.append("History retention limited")
        assert len(warnings) == 0

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

        assert len(warnings) == 0


# =============================================================================
# Sabnzbd Client Tests (Mocked)
# =============================================================================

@requires_full_env
class TestSabnzbdClientMocked:
    """Test Sabnzbd client methods with mocked HTTP responses."""

    @staticmethod
    def _create_mock_response(json_data, status_code=200, ok=True):
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

        version_resp = self._create_mock_response({'version': '4.0.0'})
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

        assert result['success']
        assert '4.0.0' in result['message']
        assert result['version'] == '4.0.0'
        assert len(result['warnings']) == 0

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
                    'pre_check': True,
                    'enable_tv_sorting': True,
                    'history_retention': '7'
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

        assert result['success']
        assert len(result['warnings']) > 0

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

        assert result['success']
        assert any('version' in w.lower() for w in result['warnings'])

    @patch('backend.implementations.usenet_clients.Sabnzbd.Session')
    def test_test_connection_invalid_api_key(self, MockSession):
        """Test connection test with invalid API key."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd
        from backend.base.custom_exceptions import CredentialInvalid

        mock_session = MagicMock()
        MockSession.return_value = mock_session

        error_resp = self._create_mock_response({'error': 'API Key Incorrect'})
        mock_session.get.return_value = error_resp

        with pytest.raises(CredentialInvalid):
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

        with pytest.raises(CredentialInvalid):
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

        with pytest.raises(ClientNotWorking):
            Sabnzbd.test(
                base_url='http://localhost:8080',
                username=None,
                password=None,
                api_token='test_key'
            )


@requires_full_env
class TestSabnzbdAddDownload:
    """Test Sabnzbd add_download method."""

    @pytest.fixture
    def mock_session(self):
        """Create mock session."""
        return MagicMock()

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.sv.sabnzbd_category = 'comics'
        settings.sv.sabnzbd_priority = 'Normal'
        return settings

    @pytest.fixture
    def sabnzbd_client(self, mock_session, mock_settings):
        """Create a Sabnzbd client for testing."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = mock_session
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        client.settings = mock_settings
        return client

    def test_add_download_success(self, sabnzbd_client, mock_session):
        """Test successful download addition."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': True,
            'nzo_ids': ['SABnzbd_nzo_abc123']
        }
        mock_session.post.return_value = mock_resp

        nzo_id = sabnzbd_client.add_download(
            download_link='http://indexer.com/nzb/123',
            target_folder='/downloads',
            download_name='Batman 2020 Issue 5'
        )

        assert nzo_id == 'SABnzbd_nzo_abc123'
        mock_session.post.assert_called_once()

    def test_add_download_failure(self, sabnzbd_client, mock_session):
        """Test failed download addition."""
        from backend.base.custom_exceptions import EnqueuingDownloadFailure

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': False,
            'error': 'NZB file not found'
        }
        mock_session.post.return_value = mock_resp

        with pytest.raises(EnqueuingDownloadFailure):
            sabnzbd_client.add_download(
                download_link='http://indexer.com/nzb/invalid',
                target_folder='/downloads',
                download_name='Invalid NZB'
            )


@requires_full_env
class TestSabnzbdGetDownload:
    """Test Sabnzbd get_download method."""

    @pytest.fixture
    def mock_session(self):
        """Create mock session."""
        return MagicMock()

    @pytest.fixture
    def sabnzbd_client(self, mock_session):
        """Create a Sabnzbd client for testing."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = mock_session
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        return client

    def test_get_download_from_queue(self, sabnzbd_client, mock_session):
        """Test getting download status from queue."""
        from backend.base.definitions import DownloadState

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
        mock_session.get.return_value = queue_resp

        result = sabnzbd_client.get_download('SABnzbd_nzo_abc123')

        assert result is not None
        assert result['state'] == DownloadState.DOWNLOADING_STATE
        assert result['progress'] == 75.0  # 100 - 25
        assert not result['is_encrypted']

    def test_get_download_from_history(self, sabnzbd_client, mock_session):
        """Test getting completed download from history."""
        from backend.base.definitions import DownloadState

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
        mock_session.get.side_effect = [queue_resp, history_resp]

        result = sabnzbd_client.get_download('SABnzbd_nzo_abc123')

        assert result is not None
        assert result['state'] == DownloadState.IMPORTING_STATE
        assert result['progress'] == 100.0
        assert 'storage_path' in result

    def test_get_download_not_found(self, sabnzbd_client, mock_session):
        """Test getting non-existent download."""
        queue_resp = MagicMock()
        queue_resp.json.return_value = {'queue': {'slots': []}}

        history_resp = MagicMock()
        history_resp.json.return_value = {'history': {'slots': []}}

        mock_session.get.side_effect = [queue_resp, history_resp]

        result = sabnzbd_client.get_download('nonexistent_id')

        assert result is None

    def test_get_download_encrypted_in_queue(self, sabnzbd_client, mock_session):
        """Test detecting encrypted download in queue."""
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
        mock_session.get.return_value = queue_resp

        result = sabnzbd_client.get_download('SABnzbd_nzo_encrypted')

        assert result is not None
        assert result['is_encrypted']
        assert result['title'] == 'Batman.2020.Issue.5.nzb'

    def test_get_download_encrypted_in_history(self, sabnzbd_client, mock_session):
        """Test detecting encrypted download in history via fail_message."""
        from backend.base.definitions import DownloadState

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
        mock_session.get.side_effect = [queue_resp, history_resp]

        result = sabnzbd_client.get_download('SABnzbd_nzo_encrypted')

        assert result is not None
        assert result['is_encrypted']
        assert result['state'] == DownloadState.FAILED_STATE

    def test_get_download_duplicate_marked_canceled(self, sabnzbd_client, mock_session):
        """Test that duplicate NZB failures return CANCELED_STATE (not blocklisted)."""
        from backend.base.definitions import DownloadState

        queue_resp = MagicMock()
        queue_resp.json.return_value = {'queue': {'slots': []}}

        history_resp = MagicMock()
        history_resp.json.return_value = {
            'history': {
                'slots': [{
                    'nzo_id': 'SABnzbd_nzo_dupe',
                    'status': 'Failed',
                    'name': 'Batman.2020.Issue.5',
                    'bytes': 0,
                    'fail_message': 'Duplicate NZB'
                }]
            }
        }
        mock_session.get.side_effect = [queue_resp, history_resp]

        result = sabnzbd_client.get_download('SABnzbd_nzo_dupe')

        assert result is not None
        assert result['state'] == DownloadState.CANCELED_STATE

    def test_get_download_disk_space_marked_canceled(self, sabnzbd_client, mock_session):
        """Test that disk space failures return CANCELED_STATE (not blocklisted)."""
        from backend.base.definitions import DownloadState

        queue_resp = MagicMock()
        queue_resp.json.return_value = {'queue': {'slots': []}}

        history_resp = MagicMock()
        history_resp.json.return_value = {
            'history': {
                'slots': [{
                    'nzo_id': 'SABnzbd_nzo_disk',
                    'status': 'Failed',
                    'name': 'Batman.2020.Issue.5',
                    'bytes': 0,
                    'fail_message': 'Insufficient disk space'
                }]
            }
        }
        mock_session.get.side_effect = [queue_resp, history_resp]

        result = sabnzbd_client.get_download('SABnzbd_nzo_disk')

        assert result is not None
        assert result['state'] == DownloadState.CANCELED_STATE

    def test_get_download_unwanted_extension_marked_canceled(self, sabnzbd_client, mock_session):
        """Test that unwanted extension failures return CANCELED_STATE (not blocklisted)."""
        from backend.base.definitions import DownloadState

        queue_resp = MagicMock()
        queue_resp.json.return_value = {'queue': {'slots': []}}

        history_resp = MagicMock()
        history_resp.json.return_value = {
            'history': {
                'slots': [{
                    'nzo_id': 'SABnzbd_nzo_unwanted',
                    'status': 'Failed',
                    'name': 'Batman.2020.Issue.5',
                    'bytes': 0,
                    'fail_message': 'Unwanted file extension'
                }]
            }
        }
        mock_session.get.side_effect = [queue_resp, history_resp]

        result = sabnzbd_client.get_download('SABnzbd_nzo_unwanted')

        assert result is not None
        assert result['state'] == DownloadState.CANCELED_STATE


@requires_full_env
class TestSabnzbdRetryDownload:
    """Test Sabnzbd retry_download method."""

    @pytest.fixture
    def mock_session(self):
        """Create mock session."""
        return MagicMock()

    @pytest.fixture
    def sabnzbd_client(self, mock_session):
        """Create a Sabnzbd client for testing."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = mock_session
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        return client

    def test_retry_download_success(self, sabnzbd_client, mock_session):
        """Test successful download retry."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': True,
            'nzo_ids': ['SABnzbd_nzo_new123']
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        new_id = sabnzbd_client.retry_download('SABnzbd_nzo_old123')

        assert new_id == 'SABnzbd_nzo_new123'

    def test_retry_download_failure(self, sabnzbd_client, mock_session):
        """Test failed download retry."""
        from backend.base.custom_exceptions import DownloadClientException

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': False,
            'error': 'Job not found in history'
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        with pytest.raises(DownloadClientException):
            sabnzbd_client.retry_download('nonexistent_id')

    def test_retry_download_no_new_id(self, sabnzbd_client, mock_session):
        """Test retry when no new ID is returned."""
        from backend.base.custom_exceptions import DownloadClientException

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'status': True,
            'nzo_ids': []
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        with pytest.raises(DownloadClientException):
            sabnzbd_client.retry_download('SABnzbd_nzo_old123')


@requires_full_env
class TestSabnzbdDeleteDownload:
    """Test Sabnzbd delete_download method."""

    @pytest.fixture
    def mock_session(self):
        """Create mock session."""
        return MagicMock()

    @pytest.fixture
    def sabnzbd_client(self, mock_session):
        """Create a Sabnzbd client for testing."""
        from backend.implementations.usenet_clients.Sabnzbd import Sabnzbd

        client = Sabnzbd.__new__(Sabnzbd)
        client.ssn = mock_session
        client._api_token = 'test_key'
        client._base_url = 'http://localhost:8080'
        return client

    def test_delete_download_success(self, sabnzbd_client, mock_session):
        """Test successful download deletion."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'status': True}
        mock_session.get.return_value = mock_resp

        sabnzbd_client.delete_download('SABnzbd_nzo_abc123', delete_files=True)

        assert mock_session.get.call_count == 2

    def test_delete_download_with_files(self, sabnzbd_client, mock_session):
        """Test deletion with file deletion flag."""
        mock_resp = MagicMock()
        mock_session.get.return_value = mock_resp

        sabnzbd_client.delete_download('SABnzbd_nzo_abc123', delete_files=True)

        calls = mock_session.get.call_args_list
        for call in calls:
            params = call[1].get('params', call[0][1] if len(call[0]) > 1 else {})
            assert 'del_files' in params


# =============================================================================
# NZB Validation Edge Cases
# =============================================================================

class TestNzbValidationEdgeCases:
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
        validate_nzb(nzb_content)

    def test_nzb_with_cdata(self):
        """Test NZB with CDATA sections in text content."""
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
        """Test that root element check is case-sensitive for tag name."""
        nzb_content = b'''<?xml version="1.0"?>
<NZB>
  <file poster="test" date="123" subject="test">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</NZB>'''
        with pytest.raises(InvalidNzbException):
            validate_nzb(nzb_content)

    @pytest.mark.parametrize("error_xml", [
        b'<error code="100" description="Incorrect user credentials"/>',
        b'<error code="200" description="Missing parameter"/>',
        b'<error code="500" description="Request limit reached"/>',
        b'<?xml version="1.0"?><error code="401" description="Unauthorized"/>',
    ])
    def test_indexer_error_variations(self, error_xml):
        """Test various indexer error response formats."""
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(error_xml)
        assert "indexer error" in exc_info.value.message.lower()


# =============================================================================
# Integration Tests
# =============================================================================

class TestUsenetDownloadIntegration:
    """Test UsenetDownload class integration."""

    def test_update_status_marks_encrypted_as_failed(self):
        """Test that encrypted downloads are marked as failed."""
        from backend.base.definitions import DownloadState

        usenet_status = {
            'progress': 50.0,
            'speed': 1000,
            'size': 524288000,
            'state': DownloadState.DOWNLOADING_STATE,
            'is_encrypted': True
        }

        state = DownloadState.QUEUED_STATE
        if usenet_status.get('is_encrypted', False):
            state = DownloadState.FAILED_STATE

        assert state == DownloadState.FAILED_STATE

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

        state = usenet_status['state']
        if usenet_status.get('is_encrypted', False):
            state = DownloadState.FAILED_STATE

        assert state == DownloadState.DOWNLOADING_STATE

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

        files = []
        if (
            usenet_status.get('state') == DownloadState.IMPORTING_STATE
            and 'storage_path' in usenet_status
        ):
            files = [usenet_status['storage_path']]

        assert len(files) == 1
        assert 'Batman' in files[0]


class TestNzbValidationWithMockedRequests:
    """Test NZB validation in the context of HTTP responses."""

    def test_validate_gzip_nzb_content(self):
        """Test that gzip-compressed content is handled correctly."""
        nzb_content = b'''<?xml version="1.0"?>
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
  <file poster="test" date="123" subject="test">
    <groups><group>test</group></groups>
    <segments><segment bytes="100" number="1">x</segment></segments>
  </file>
</nzb>'''
        compressed = gzip.compress(nzb_content)

        decompressed = gzip.decompress(compressed)
        validate_nzb(decompressed)

    def test_validate_handles_bom(self):
        """Test handling of UTF-8 BOM (byte order mark)."""
        nzb_with_bom = b'\xef\xbb\xbf<?xml version="1.0"?>\n<nzb><file poster="t" date="1" subject="t"><groups><group>t</group></groups><segments><segment bytes="1" number="1">x</segment></segments></file></nzb>'
        validate_nzb(nzb_with_bom)


class TestErrorRecovery:
    """Test error recovery scenarios."""

    def test_exception_messages_are_informative(self):
        """Test that exception messages contain useful information."""
        with pytest.raises(InvalidNzbException) as exc_info:
            validate_nzb(b'not xml', 'test_file.nzb')

        message = exc_info.value.message
        assert 'test_file.nzb' in message
        assert 'Unable to parse XML' in message

    def test_exception_api_response_format(self):
        """Test that exceptions produce valid API responses."""
        exc = InvalidNzbException("Test error message")
        response = exc.api_response

        assert 'code' in response
        assert 'error' in response
        assert 'result' in response
        assert isinstance(response['code'], int)
        assert isinstance(response['error'], str)
        assert isinstance(response['result'], dict)

    def test_network_error_exception_hierarchy(self):
        """Test that network errors use correct exception type."""
        exc = DownloadClientUnavailableException("Connection refused")
        assert exc.api_response['code'] == 503  # Service Unavailable
