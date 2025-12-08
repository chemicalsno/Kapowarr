# -*- coding: utf-8 -*-

"""
NZBHydra2 search integration.
"""

import re
from typing import List
from xml.etree import ElementTree

from backend.base.definitions import DownloadType, SearchResultData, SearchSource
from backend.base.file_extraction import extract_filename_data
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

        # Extract key search terms from query for relevance filtering
        # Remove common words and special characters
        query_words = set(re.sub(r'[^\w\s]', ' ', self.query.lower()).split())
        # Remove common filler words
        query_words -= {'vol', 'no', 'the', 'of', 'a', 'an', 'and', 'tpb', 'hc'}
        # Remove pure numbers as they're too generic
        query_words = {w for w in query_words if not w.isdigit()}

        LOGGER.debug(f"Hydra filter - Query: '{self.query}' → Keywords: {query_words}")

        for item in channel.findall('item'):
            try:
                result = self._parse_item(item)
                if not result:
                    continue

                # Filter out obviously irrelevant results
                # Check if series name has at least some overlap with query
                series_words = set(result['series'].lower().split())
                matching_words = query_words & series_words

                # For multi-word queries, require at least 2 words to match
                # For single-word queries, require the word to match
                min_matches = min(2, len(query_words))
                LOGGER.debug(
                    f"Hydra filter - Series: '{result['series']}' → "
                    f"Matching: {matching_words} ({len(matching_words)}/{min_matches})"
                )
                if len(matching_words) < min_matches:
                    LOGGER.debug(
                        f"Filtering irrelevant result: '{result['display_title']}' "
                        f"(only {len(matching_words)} words match, need {min_matches})"
                    )
                    continue

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

        # Extract pubDate and calculate age in days
        from datetime import datetime
        from email.utils import parsedate_to_datetime
        age = None
        pub_date_elem = item.find('pubDate')
        if pub_date_elem is not None and pub_date_elem.text:
            try:
                pub_date = parsedate_to_datetime(pub_date_elem.text)
                age = (datetime.now(pub_date.tzinfo) - pub_date).days
            except Exception:
                pass

        # Get indexer name from Newznab attributes
        # NZBHydra2 adds custom attributes with indexer info
        indexer_name = 'Usenet'
        for attr in item.findall('.//{http://www.newznab.com/DTD/2010/feeds/attributes/}attr'):
            attr_name = attr.get('name', '')
            if attr_name == 'indexer':
                indexer_name = attr.get('value', 'Usenet')
                break

        # Preprocess title for Usenet naming conventions:
        # - Replace dots/underscores with spaces
        # - Replace hyphens with spaces EXCEPT when between numbers (preserve "70-75")
        # - Remove common publisher prefixes

        # First replace dots and underscores with spaces
        clean_title = re.sub(r'[\.\_]+', ' ', title)

        # Replace hyphens with spaces, but NOT when between digits (preserve issue ranges)
        # This regex matches hyphens that are NOT between two digits
        clean_title = re.sub(r'(?<!\d)-|-(?!\d)', ' ', clean_title)

        # Remove common publisher prefixes like "DC Comics" at the start
        clean_title = re.sub(
            r'^(DC|Marvel|Image|Dark Horse|IDW|Vertigo|Boom|Dynamite|Valiant)\s*(Comics?)?\s*',
            '', clean_title, flags=re.IGNORECASE
        )
        clean_title = clean_title.strip()

        # Use extract_filename_data to properly parse the cleaned title
        # This handles issue numbers, volume numbers, years, etc.
        # Use assume_volume_number=False so releases without explicit volume
        # numbers return None, allowing conservative matching to pass
        parsed = extract_filename_data(
            clean_title,
            assume_volume_number=False,
            fix_year=True
        )

        # Build SearchResultData using properly extracted data
        # Allow volume_number to be None for conservative matching
        result: SearchResultData = {
            'link': nzb_url,
            'display_title': title,
            'source': indexer_name,
            'series': parsed['series'] or title,
            'year': parsed['year'],
            'volume_number': parsed['volume_number'],
            'special_version': parsed['special_version'],
            'issue_number': parsed['issue_number'],
            'annual': parsed['annual'],
            'age': age
        }

        return result
