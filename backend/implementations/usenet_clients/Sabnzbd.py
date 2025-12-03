# -*- coding: utf-8 -*-

"""
Sabnzbd Usenet client implementation.
"""

from typing import Any, Dict, List, Union
import os
import time
from threading import Lock

from requests.exceptions import RequestException

from backend.base.custom_exceptions import (ClientNotWorking,
                                            CredentialInvalid,
                                            DownloadClientAuthenticationException,
                                            DownloadClientUnavailableException,
                                            EnqueuingDownloadFailure,
                                            InvalidNzbException)
from backend.base.definitions import (BrokenClientReason, Constants,
                                      DownloadState, DownloadType,
                                      EnqueuingDownloadFailureReason)
from backend.base.helpers import Session
from backend.base.logging import LOGGER
from backend.implementations.external_clients import BaseExternalClient
from backend.internals.settings import Settings


class Sabnzbd(BaseExternalClient):
    """Sabnzbd Usenet client implementation."""

    client_type = 'Sabnzbd'
    download_type = DownloadType.USENET

    required_tokens = ('title', 'base_url', 'api_token')

    # Rate limiting to prevent API spam
    # Cache download status for this many seconds
    _CACHE_DURATION = 2.0
    _status_cache: Dict[str, tuple] = {}  # {download_id: (timestamp, result)}
    _cache_lock = Lock()

    # State mapping from Sabnzbd status to Kapowarr DownloadState
    STATE_MAPPING = {
        # Queue states
        'Queued': DownloadState.QUEUED_STATE,
        'Paused': DownloadState.QUEUED_STATE,
        'Grabbing': DownloadState.QUEUED_STATE,
        'Downloading': DownloadState.DOWNLOADING_STATE,
        'Idle': DownloadState.DOWNLOADING_STATE,

        # Processing states (keep downloading until ready)
        'Running': DownloadState.DOWNLOADING_STATE,
        'Verifying': DownloadState.DOWNLOADING_STATE,
        'Repairing': DownloadState.DOWNLOADING_STATE,
        'QuickCheck': DownloadState.DOWNLOADING_STATE,
        'Extracting': DownloadState.DOWNLOADING_STATE,

        # Ready for import
        'Moving': DownloadState.IMPORTING_STATE,
        'Completed': DownloadState.IMPORTING_STATE,

        # Terminal states
        'Failed': DownloadState.FAILED_STATE,
    }

    # Priority mapping from settings string to Sabnzbd integer
    PRIORITY_MAPPING = {
        'Default': -100,
        'Paused': -2,
        'Low': -1,
        'Normal': 0,
        'High': 1,
        'Force': 2,
    }

    def __init__(self, client_id: int) -> None:
        """Initialize Sabnzbd client.

        Args:
            client_id (int): The ID of the client in the database.
        """
        super().__init__(client_id)
        self.ssn: Union[Session, None] = None
        self.settings = Settings()
        return

    # Minimum Sabnzbd version required for full functionality
    MIN_VERSION = '3.0.0'

    @staticmethod
    def _version_tuple(version_string: str) -> tuple:
        """Convert version string to tuple for proper semantic comparison.

        Args:
            version_string: Version string like "3.2.1"

        Returns:
            Tuple of integers like (3, 2, 1)
        """
        try:
            return tuple(int(x) for x in version_string.split('.'))
        except (ValueError, AttributeError):
            return (0, 0, 0)

    @staticmethod
    def test(
        base_url: str,
        username: Union[str, None],
        password: Union[str, None],
        api_token: Union[str, None]
    ) -> Dict[str, Any]:
        """Test connection to Sabnzbd instance with comprehensive validation.

        Performs the following tests:
        1. Connectivity and version check
        2. Authentication validation
        3. Configuration validation (checks for problematic settings)

        Args:
            base_url (str): Base URL of Sabnzbd instance.
            username (Union[str, None]): Username (optional).
            password (Union[str, None]): Password (optional).
            api_token (Union[str, None]): API token/key (required).

        Returns:
            Dict[str, Any]: Test result with keys:
                - success (bool): Whether connection succeeded
                - message (str): Status message
                - version (str): Sabnzbd version if connected
                - warnings (List[str]): Configuration warnings

        Raises:
            ClientNotWorking: Can't connect to client.
            CredentialInvalid: Credentials are invalid.
        """
        from backend.implementations.external_clients import normalise_base_url

        base_url = normalise_base_url(base_url)
        warnings: List[str] = []

        if not api_token:
            LOGGER.error("Sabnzbd API token is required")
            raise CredentialInvalid

        ssn = Session()

        # Test 1: Version check and connectivity
        params = {
            'mode': 'version',
            'output': 'json',
            'apikey': api_token,
        }

        try:
            response = ssn.get(f'{base_url}/api', params=params, timeout=30)
        except RequestException as e:
            LOGGER.exception("Can't connect to Sabnzbd instance: ")
            raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)

        if not response.ok:
            LOGGER.error(
                f"Failed to connect to Sabnzbd instance: {response.text}"
            )
            raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)

        try:
            data = response.json()
        except Exception as e:
            LOGGER.error(f"Invalid response from Sabnzbd: {e}")
            raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)

        # Check if API key is valid
        if 'error' in data or not data.get('version'):
            LOGGER.error(
                f"Sabnzbd authentication failed: {data.get('error', 'Unknown error')}"
            )
            raise CredentialInvalid

        version = data.get('version', '')

        # Check minimum version using proper semantic versioning
        if Sabnzbd._version_tuple(version) < Sabnzbd._version_tuple(Sabnzbd.MIN_VERSION):
            warnings.append(
                f"⚠️ Sabnzbd version {version} is older than recommended "
                f"({Sabnzbd.MIN_VERSION}+). Some features may not work."
            )

        # Test 2: Get config for validation
        config_params = {
            'mode': 'get_config',
            'output': 'json',
            'apikey': api_token,
        }

        try:
            config_resp = ssn.get(
                f'{base_url}/api',
                params=config_params,
                timeout=30
            )
            config_resp.raise_for_status()
            config_data = config_resp.json()
            config = config_data.get('config', {})
            misc = config.get('misc', {})

            # Check for problematic settings
            if misc.get('pre_check', False):
                warnings.append(
                    "⚠️ Pre-check is enabled in Sabnzbd. This may cause "
                    "issues with some NZBs. Consider disabling it."
                )

            if misc.get('enable_tv_sorting', False):
                warnings.append(
                    "⚠️ TV sorting is enabled in Sabnzbd. This may "
                    "conflict with Kapowarr's file organization."
                )

            if misc.get('enable_movie_sorting', False):
                warnings.append(
                    "⚠️ Movie sorting is enabled in Sabnzbd. This may "
                    "conflict with Kapowarr's file organization."
                )

            # Check history retention
            history_retention = misc.get('history_retention', '0')
            if history_retention not in ('0', '-1', 0, -1):
                warnings.append(
                    f"⚠️ History retention is set to {history_retention}. "
                    "This may cause Kapowarr to lose track of downloads."
                )

        except Exception as e:
            LOGGER.debug(f"Could not validate Sabnzbd config: {e}")
            # Non-fatal, just skip config validation

        message = f"Connected to Sabnzbd v{version}"
        if warnings:
            message += "\n" + "\n".join(warnings)

        LOGGER.info(f"Successfully connected to Sabnzbd version {version}")
        return {
            'success': True,
            'message': message,
            'version': version,
            'warnings': warnings
        }

    def add_download(
        self,
        download_link: str,
        download_folder: str,
        download_name: Union[str, None] = None,
        nzb_content: Union[bytes, None] = None
    ) -> str:
        """Add an NZB download to Sabnzbd.

        Args:
            download_link (str): The URL of the NZB file (used if nzb_content not provided).
            download_folder (str): The folder to download to (not used by Sabnzbd).
            download_name (Union[str, None], optional): Name for the download.
                Defaults to None.
            nzb_content (Union[bytes, None], optional): Raw NZB file content.
                If provided, uploads directly instead of having Sabnzbd fetch URL.

        Raises:
            ClientNotWorking: Can't connect to client.
            CredentialInvalid: Credentials are invalid.
            EnqueuingDownloadFailure: Failed to add download.

        Returns:
            str: The nzo_id of the added download.
        """
        if not self.ssn:
            self.ssn = Session()

        params = {
            'output': 'json',
            'apikey': self.api_token,
        }

        # Add optional parameters
        if self.settings.sv.sabnzbd_category:
            params['cat'] = self.settings.sv.sabnzbd_category

        if self.settings.sv.sabnzbd_priority:
            priority = self.PRIORITY_MAPPING.get(
                self.settings.sv.sabnzbd_priority,
                0  # Default to Normal
            )
            params['priority'] = priority

        if download_name:
            params['nzbname'] = download_name

        try:
            if nzb_content:
                # Upload NZB content directly (preferred - avoids double fetch)
                params['mode'] = 'addfile'
                files = {'nzbfile': (f'{download_name or "download"}.nzb', nzb_content)}
                response = self.ssn.post(f'{self.base_url}/api', data=params, files=files)
            else:
                # Fallback to URL mode
                params['mode'] = 'addurl'
                params['name'] = download_link
                response = self.ssn.post(f'{self.base_url}/api', data=params)
            data = response.json()
        except RequestException as e:
            LOGGER.exception("Failed to add download to Sabnzbd: ")
            raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)
        except Exception as e:
            LOGGER.error(f"Invalid response from Sabnzbd: {e}")
            raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)

        if not data.get('status'):
            error_msg = data.get('error', 'Unknown error')
            LOGGER.error(f"Sabnzbd failed to add download: {error_msg}")
            raise EnqueuingDownloadFailure(
                EnqueuingDownloadFailureReason.LINK_BROKEN
            )

        # Sabnzbd returns nzo_ids as a list
        nzo_ids = data.get('nzo_ids', [])
        if not nzo_ids:
            LOGGER.error("Sabnzbd did not return an nzo_id")
            raise EnqueuingDownloadFailure(
                EnqueuingDownloadFailureReason.LINK_BROKEN
            )

        nzo_id = nzo_ids[0]
        LOGGER.info(f"Successfully added download to Sabnzbd: {nzo_id}")
        return nzo_id

    def get_download(self, download_id: str) -> Union[Dict[str, Any], None]:
        """Get download status from Sabnzbd with rate limiting.

        Uses a short-lived cache (2 seconds) to prevent API spam when multiple
        threads check the same download status repeatedly.

        Args:
            download_id (str): The nzo_id of the download.

        Raises:
            ClientNotWorking: Can't connect to client.
            CredentialInvalid: Credentials are invalid.

        Returns:
            Union[Dict[str, Any], None]: Download info dict or None if not found.
                Dict contains: state, size, progress, speed, and optionally storage_path.
        """
        # Check cache first to avoid API spam
        current_time = time.time()
        with self._cache_lock:
            if download_id in self._status_cache:
                cached_time, cached_result = self._status_cache[download_id]
                if current_time - cached_time < self._CACHE_DURATION:
                    LOGGER.debug(
                        f"Using cached status for {download_id} "
                        f"(age: {current_time - cached_time:.1f}s)"
                    )
                    return cached_result

        if not self.ssn:
            self.ssn = Session()

        # First check the active queue
        queue_params = {
            'mode': 'queue',
            'output': 'json',
            'apikey': self.api_token,
        }

        try:
            queue_resp = self.ssn.get(f'{self.base_url}/api', params=queue_params)
            queue_data = queue_resp.json()
        except RequestException as e:
            LOGGER.exception("Failed to query Sabnzbd queue: ")
            raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)
        except Exception as e:
            LOGGER.error(f"Invalid queue response from Sabnzbd: {e}")
            raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)

        # Check if download is in queue
        queue_info = queue_data.get('queue', {})
        for slot in queue_info.get('slots', []):
            if slot.get('nzo_id') == download_id:
                status = slot.get('status', 'Queued')
                state = self.STATE_MAPPING.get(status, DownloadState.QUEUED_STATE)

                # Convert MB to bytes
                size_mb = float(slot.get('mb', 0))
                size_bytes = int(size_mb * 1024 * 1024)

                # Progress is inverse of percentage (100 - percentage remaining)
                percentage = float(slot.get('percentage', 100))
                progress = 100.0 - percentage

                # Convert KB/s to bytes/s
                speed_kbps = float(slot.get('kbpersec', 0))
                speed_bps = int(speed_kbps * 1024)

                # Check for encrypted download (Sabnzbd prefixes with "ENCRYPTED /")
                title = slot.get('filename', '')
                is_encrypted = title.startswith('ENCRYPTED /')
                if is_encrypted:
                    title = title[11:]  # Strip "ENCRYPTED /" prefix

                result = {
                    'state': state,
                    'size': size_bytes,
                    'progress': progress,
                    'speed': speed_bps,
                    'is_encrypted': is_encrypted,
                    'title': title,
                }

                # Update cache
                with self._cache_lock:
                    self._status_cache[download_id] = (current_time, result)

                return result

        # Not in queue, check history
        hist_params = {
            'mode': 'history',
            'output': 'json',
            'apikey': self.api_token,
        }

        # For Sabnzbd 3.2.0+, we can filter by nzo_id directly
        # For older versions, we'll search through the results
        try:
            hist_resp = self.ssn.get(f'{self.base_url}/api', params=hist_params)
            history_data = hist_resp.json()
        except RequestException as e:
            LOGGER.exception("Failed to query Sabnzbd history: ")
            raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)
        except Exception as e:
            LOGGER.error(f"Invalid history response from Sabnzbd: {e}")
            raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)

        # Search history for the download
        history_info = history_data.get('history', {})
        for entry in history_info.get('slots', []):
            if entry.get('nzo_id') == download_id:
                status = entry.get('status', 'Failed')
                fail_message = entry.get('fail_message', '')
                LOGGER.debug(
                    f"Found {download_id} in Sabnzbd history: "
                    f"status={status}, fail_message={fail_message}, "
                    f"keys={list(entry.keys())}"
                )
                state = self.STATE_MAPPING.get(status, DownloadState.FAILED_STATE)

                # Special handling for certain failure types
                # Some failures shouldn't be treated as permanent/blocklisted
                fail_message_lower = fail_message.lower()

                if status == 'Failed':
                    # Duplicate NZB - not a broken link, just already in SABnzbd
                    if 'duplicate' in fail_message_lower:
                        state = DownloadState.CANCELED_STATE
                        LOGGER.info(
                            f"Download {download_id} marked as duplicate by SABnzbd, "
                            f"treating as canceled (will not blocklist)"
                        )

                    # Insufficient disk space - temporary issue, treat as canceled
                    elif 'disk' in fail_message_lower and 'space' in fail_message_lower:
                        state = DownloadState.CANCELED_STATE
                        LOGGER.warning(
                            f"Download {download_id} failed due to disk space, "
                            f"treating as canceled (will not blocklist)"
                        )

                    # Unwanted file extension - SABnzbd's filter rejected it
                    # This is a config mismatch, not a broken link
                    elif 'unwanted' in fail_message_lower and 'extension' in fail_message_lower:
                        state = DownloadState.CANCELED_STATE
                        LOGGER.warning(
                            f"Download {download_id} rejected by SABnzbd file filter, "
                            f"treating as canceled (will not blocklist)"
                        )

                    # For other failures, log the message for debugging
                    else:
                        LOGGER.warning(
                            f"Download {download_id} permanently failed: {fail_message}"
                        )

                size_bytes = int(entry.get('bytes', 0))
                progress = 100.0 if status == 'Completed' else 0.0

                # Check for encrypted download in history
                title = entry.get('name', '')
                is_encrypted = title.startswith('ENCRYPTED /')
                if is_encrypted:
                    title = title[11:]  # Strip "ENCRYPTED /" prefix

                # Also check fail_message for encryption indicators
                if 'encrypted' in fail_message_lower or 'password' in fail_message_lower:
                    is_encrypted = True

                result = {
                    'state': state,
                    'size': size_bytes,
                    'progress': progress,
                    'speed': 0.0,
                    'is_encrypted': is_encrypted,
                    'title': title,
                }

                # CRITICAL: Include storage path when completed
                if state == DownloadState.IMPORTING_STATE:
                    storage_path = entry.get('storage', '')
                    if storage_path:
                        # Validate storage path exists
                        if not os.path.isabs(storage_path):
                            LOGGER.error(
                                f"SABnzbd returned relative path '{storage_path}' "
                                f"for download {download_id}, expected absolute path"
                            )
                        elif not os.path.exists(storage_path):
                            LOGGER.error(
                                f"SABnzbd storage path does not exist: {storage_path} "
                                f"(download {download_id})"
                            )
                        else:
                            result['storage_path'] = storage_path
                    else:
                        LOGGER.warning(
                            f"Completed download {download_id} has no storage path"
                        )

                # Update cache
                with self._cache_lock:
                    self._status_cache[download_id] = (current_time, result)

                return result

        # Download not found in queue or history
        LOGGER.debug(f"Download {download_id} not found in Sabnzbd queue or history")
        return None

    def delete_download(self, download_id: str, delete_files: bool) -> None:
        """Delete a download from Sabnzbd.

        Args:
            download_id (str): The nzo_id of the download.
            delete_files (bool): Whether to delete downloaded files.

        Raises:
            ClientNotWorking: Can't connect to client.
            CredentialInvalid: Credentials are invalid.
        """
        if not self.ssn:
            self.ssn = Session()

        # Try to delete from queue first
        queue_params = {
            'mode': 'queue',
            'name': 'delete',
            'value': download_id,
            'output': 'json',
            'apikey': self.api_token,
        }

        if delete_files:
            queue_params['del_files'] = 1

        try:
            self.ssn.get(f'{self.base_url}/api', params=queue_params)
        except RequestException as e:
            LOGGER.exception("Failed to delete from Sabnzbd queue: ")
            raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)

        # Also try to delete from history
        hist_params = {
            'mode': 'history',
            'name': 'delete',
            'value': download_id,
            'output': 'json',
            'apikey': self.api_token,
        }

        if delete_files:
            hist_params['del_files'] = 1

        try:
            self.ssn.get(f'{self.base_url}/api', params=hist_params)
        except RequestException as e:
            LOGGER.exception("Failed to delete from Sabnzbd history: ")
            raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)

        # Clear from cache
        with self._cache_lock:
            self._status_cache.pop(download_id, None)

        LOGGER.info(f"Deleted download {download_id} from Sabnzbd")
        return

    def retry_download(self, download_id: str) -> str:
        """Retry a failed download in Sabnzbd.

        This uses Sabnzbd's retry API to re-attempt a failed download
        from history. Useful for downloads that failed due to temporary
        issues like network problems or incomplete articles.

        Args:
            download_id (str): The nzo_id of the failed download.

        Returns:
            str: The new nzo_id of the retried download.

        Raises:
            ClientNotWorking: Can't connect to client.
            DownloadClientException: Retry failed.
        """
        from backend.base.custom_exceptions import DownloadClientException

        if not self.ssn:
            self.ssn = Session()

        params = {
            'mode': 'retry',
            'value': download_id,
            'output': 'json',
            'apikey': self.api_token,
        }

        try:
            response = self.ssn.get(f'{self.base_url}/api', params=params)
            response.raise_for_status()
            data = response.json()
        except RequestException as e:
            LOGGER.exception("Failed to retry download in Sabnzbd: ")
            raise ClientNotWorking(BrokenClientReason.CONNECTION_ERROR)
        except Exception as e:
            LOGGER.error(f"Invalid response from Sabnzbd retry: {e}")
            raise ClientNotWorking(BrokenClientReason.NOT_CLIENT_INSTANCE)

        # Sabnzbd returns the new nzo_id(s) in 'nzo_ids' field
        nzo_ids = data.get('nzo_ids', [])
        if not nzo_ids:
            # Check for error in response
            if data.get('error'):
                error_msg = data.get('error', 'Unknown error')
                LOGGER.error(f"Sabnzbd retry failed: {error_msg}")
                raise DownloadClientException(f"Retry failed: {error_msg}")

            LOGGER.error("Sabnzbd retry did not return a new nzo_id")
            raise DownloadClientException(
                "Retry failed: No new download ID returned"
            )

        new_nzo_id = nzo_ids[0]
        LOGGER.info(
            f"Successfully retried download {download_id} -> {new_nzo_id}"
        )
        return new_nzo_id
