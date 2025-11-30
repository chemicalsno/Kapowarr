# -*- coding: utf-8 -*-

"""
NZBHydra2 search integration.
"""

from typing import List
from xml.etree import ElementTree

from backend.base.definitions import DownloadType, SearchResultData, SearchSource
from backend.base.file_extraction import (extract_issue_number,
                                          extract_year_from_date,
                                          extract_volume_number)
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

        # Skip if NZBHydra2 is not configured
        if not settings.nzbhydra_base_url:
            return []

        # Skip if no Usenet download client is configured
        usenet_clients = [
            c for c in ExternalClients.get_clients()
            if c['download_type'] == DownloadType.USENET.value
        ]
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

        # Parse filename from title to extract metadata
        # This uses Kapowarr's existing filename extraction logic
        from backend.base.file_extraction import (
            extract_filename_data,
            FilenameData
        )

        # Try to extract metadata from title
        try:
            filename_data = extract_filename_data(title)
        except Exception:
            # If parsing fails, create minimal data
            filename_data: FilenameData = {
                'series': title,
                'year': None,
                'volume_number': None,
                'special_version': None,
                'issue_number': None,
                'annual': False
            }

        # Build SearchResultData
        result: SearchResultData = {
            'link': nzb_url,
            'display_title': title,
            'source': indexer_name,
            'series': filename_data['series'],
            'year': filename_data['year'],
            'volume_number': filename_data['volume_number'],
            'special_version': filename_data['special_version'],
            'issue_number': filename_data['issue_number'],
            'annual': filename_data['annual']
        }

        return result
