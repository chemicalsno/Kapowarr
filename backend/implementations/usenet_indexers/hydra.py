# -*- coding: utf-8 -*-

"""
NZBHydra2 search integration.
"""

from typing import List
from xml.etree import ElementTree

from backend.base.definitions import DownloadType, SearchResultData, SearchSource
from backend.base.helpers import AsyncSession
from backend.base.logging import LOGGER
from backend.implementations.external_clients import ExternalClients
from backend.internals.settings import Settings


class HydraSearchSource(SearchSource):
    """Search source for NZBHydra2 indexer."""

    source_name = 'NZBHydra2'

    async def search(self, session: AsyncSession) -> List[SearchResultData]:
        """Search NZBHydra2 for the query.

        Args:
            session (AsyncSession): The aiohttp session to use.

        Returns:
            List[SearchResultData]: The search results.
        """
        settings = Settings().sv
        LOGGER.debug(f"HydraSearchSource.search() called for query: '{self.query}'")

        # Skip if NZBHydra2 is not configured
        if not settings.nzbhydra_base_url:
            LOGGER.debug("NZBHydra2 base URL not configured, skipping search")
            return []

        # Skip if no Usenet download client is configured
        usenet_clients = [
            c for c in ExternalClients.get_clients()
            if c['download_type'] == DownloadType.USENET.value
        ]
        LOGGER.debug(f"Found {len(usenet_clients)} Usenet client(s)")
        if not usenet_clients:
            LOGGER.debug("No Usenet client configured, skipping NZBHydra2 search")
            return []

        # Build Newznab API request
        params = {
            'apikey': settings.nzbhydra_api_key,
            't': 'search',
            'q': self.query,
            'o': 'xml',  # Newznab uses XML format
        }

        # Add categories if configured
        if settings.nzbhydra_categories:
            params['cat'] = settings.nzbhydra_categories

        url = f"{settings.nzbhydra_base_url.rstrip('/')}/api"
        LOGGER.debug(f"Searching NZBHydra2 at {url}")

        try:
            async with session.get(url, params=params) as response:
                if not response.ok:
                    LOGGER.error(
                        f"NZBHydra2 search failed with status {response.status}"
                    )
                    return []

                xml_content = await response.text()

        except Exception as e:
            LOGGER.error(f"Error searching NZBHydra2: {e}")
            return []

        # Parse Newznab XML response
        try:
            root = ElementTree.fromstring(xml_content)
        except ElementTree.ParseError as e:
            LOGGER.error(f"Failed to parse NZBHydra2 XML response: {e}")
            return []

        # Check for errors
        if root.tag == 'error':
            error_code = root.get('code', 'unknown')
            error_desc = root.get('description', 'Unknown error')
            LOGGER.error(f"NZBHydra2 error {error_code}: {error_desc}")
            return []

        # Parse search results
        results = []
        channel = root.find('channel')
        if channel is None:
            LOGGER.warning("No channel found in NZBHydra2 response")
            return []

        for item in channel.findall('item'):
            try:
                result = self._parse_item(item)
                if result:
                    results.append(result)
            except Exception as e:
                LOGGER.warning(f"Failed to parse NZBHydra2 item: {e}")
                continue

        LOGGER.info(f"NZBHydra2 search for '{self.query}' returned {len(results)} results")
        return results

    def _parse_item(self, item: ElementTree.Element) -> SearchResultData:
        """Parse a single Newznab item into SearchResultData.

        Args:
            item (ElementTree.Element): The XML item element.

        Returns:
            SearchResultData: The parsed search result.
        """
        # Extract basic fields
        title_elem = item.find('title')
        title = title_elem.text if title_elem is not None else 'Unknown'

        link_elem = item.find('link')
        nzb_url = link_elem.text if link_elem is not None else ''

        # Try to get enclosure URL if link is empty
        if not nzb_url:
            enclosure = item.find('enclosure')
            if enclosure is not None:
                nzb_url = enclosure.get('url', '')

        # Get indexer name from Newznab attributes
        # NZBHydra2 adds custom attributes with indexer info
        indexer_name = 'Usenet'
        for attr in item.findall('.//{http://www.newznab.com/DTD/2010/feeds/attributes/}attr'):
            attr_name = attr.get('name', '')
            if attr_name == 'indexer':
                indexer_name = attr.get('value', 'Usenet')
                break

        # Extract year from title if present (e.g., "(2024)" or "2024")
        import re
        year_match = re.search(r'\((\d{4})\)|\.(\d{4})\.', title)
        year = None
        if year_match:
            year = int(year_match.group(1) or year_match.group(2))

        # For Usenet results, use title as series name
        # Clean up common separators for better matching
        series = re.sub(r'[\.\-_]+', ' ', title)
        series = re.sub(r'\s*\(\d{4}\)\s*', ' ', series)  # Remove year
        series = re.sub(r'\s*(digital|hybrid|comic|ebook|sd|hd).*$', '', series, flags=re.IGNORECASE)
        series = series.strip()

        # Build SearchResultData
        # For Usenet, we don't try to extract issue numbers - these are typically full volumes
        result: SearchResultData = {
            'link': nzb_url,
            'display_title': title,
            'source': indexer_name,
            'series': series,
            'year': year,
            'volume_number': 1,  # Default to volume 1 for TPBs
            'special_version': None,
            'issue_number': None,  # Don't guess issue numbers from release titles
            'annual': False
        }

        return result
