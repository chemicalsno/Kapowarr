# -*- coding: utf-8 -*-

"""
NZB file validation module.

Validates NZB files before submission to download clients to catch
invalid files, indexer errors, and malformed XML early.

Based on Sonarr's NzbValidationService implementation.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

from backend.base.custom_exceptions import InvalidNzbException
from backend.base.logging import LOGGER


def validate_nzb(nzb_content: bytes, filename: Optional[str] = None) -> None:
    """Validate an NZB file before submission to download client.

    Performs the following checks:
    1. Valid XML structure
    2. Detects indexer error responses (nZEDb bug workaround)
    3. Verifies root element is 'nzb'
    4. Ensures at least one file element exists

    Args:
        nzb_content (bytes): The raw NZB file content.
        filename (Optional[str]): Filename for error messages.

    Raises:
        InvalidNzbException: If validation fails for any reason.
    """
    file_ref = f" [{filename}]" if filename else ""

    if not nzb_content:
        raise InvalidNzbException(f"Empty NZB content{file_ref}")

    try:
        # Parse the XML
        root = ET.fromstring(nzb_content)
    except ET.ParseError as e:
        raise InvalidNzbException(
            f"Unable to parse XML{file_ref}: {e}"
        )

    # Get the local name (without namespace)
    local_name = root.tag.split('}')[-1] if '}' in root.tag else root.tag

    # Check 1: Detect indexer error responses (nZEDb bug workaround)
    # Some indexers return error XML wrapped as NZB when there's an issue
    if local_name == 'error':
        code = root.get('code', 'unknown')
        description = root.get('description', 'No description')
        raise InvalidNzbException(
            f"Contains indexer error{file_ref}: {code} - {description}"
        )

    # Check 2: Verify root element is 'nzb'
    if local_name != 'nzb':
        raise InvalidNzbException(
            f"Unexpected root element '{local_name}', expected 'nzb'{file_ref}"
        )

    # Check 3: Ensure at least one file element exists
    # Handle namespace (e.g., {http://www.newzbin.com/DTD/2003/nzb}file)
    namespace = ''
    if '}' in root.tag:
        namespace = root.tag.split('}')[0] + '}'

    files = root.findall(f'{namespace}file')

    if not files:
        # Also try without namespace as fallback
        files = root.findall('file')

    if not files:
        raise InvalidNzbException(f"No files found in NZB{file_ref}")

    LOGGER.debug(
        f"NZB validation passed{file_ref}: {len(files)} file(s) found"
    )
    return


def validate_nzb_url_response(
    response_content: bytes,
    url: str,
    expected_content_type: Optional[str] = None
) -> None:
    """Validate an HTTP response that should contain an NZB file.

    Args:
        response_content (bytes): The response body.
        url (str): The URL (for error messages).
        expected_content_type (Optional[str]): Expected Content-Type header value.

    Raises:
        InvalidNzbException: If the response doesn't contain a valid NZB.
    """
    if not response_content:
        raise InvalidNzbException(f"Empty response from {url}")

    # Check if response looks like HTML (common error page)
    content_start = response_content[:100].lower()
    if b'<!doctype html' in content_start or b'<html' in content_start:
        raise InvalidNzbException(
            f"Received HTML instead of NZB from {url} - "
            "possible error page or authentication issue"
        )

    # Validate the NZB content
    validate_nzb(response_content, filename=url)
    return
