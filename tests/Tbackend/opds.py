import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from base64 import b64encode

from flask import Flask
from backend.features.opds import opds


class OPDSTestCase(unittest.TestCase):
    """Base test case for OPDS tests with common setup."""

    def setUp(self):
        """Set up test Flask app and client."""
        self.app = Flask(__name__)
        self.app.register_blueprint(opds)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # Mock settings
        self.settings_patcher = patch('backend.features.opds.Settings')
        self.mock_settings_class = self.settings_patcher.start()
        self.mock_settings = Mock()
        self.mock_settings_class.return_value.sv = self.mock_settings

        # Default settings
        self.mock_settings.opds_enabled = True
        self.mock_settings.opds_authentication = False
        self.mock_settings.opds_username = 'test'
        self.mock_settings.opds_password = 'password'
        self.mock_settings.opds_api_key = 'test_api_key'

        # Mock database
        self.db_patcher = patch('backend.features.opds.get_db')
        self.mock_get_db = self.db_patcher.start()
        self.mock_db = Mock()
        self.mock_get_db.return_value = self.mock_db

    def tearDown(self):
        """Clean up patches."""
        self.settings_patcher.stop()
        self.db_patcher.stop()

    def get_basic_auth_header(self, username='test', password='password'):
        """Generate Basic Auth header."""
        credentials = b64encode(f'{username}:{password}'.encode()).decode()
        return {'Authorization': f'Basic {credentials}'}

    def set_db_results(self, results):
        """Configure sequential database execute responses.

        Args:
            results (List[dict]): Each dict can contain `fetchone` and/or `fetchall`
                values that should be returned by that execute call.
        """
        def _make_result(fetchone=None, fetchall=None):
            result = Mock()
            if fetchone is not None:
                result.fetchone.return_value = fetchone
            if fetchall is not None:
                result.fetchall.return_value = fetchall
            return result

        self.mock_db.execute.side_effect = [
            _make_result(**res) for res in results
        ]

    def set_single_db_result(self, fetchone=None, fetchall=None):
        """Shortcut for configuring a single execute result."""
        self.set_db_results([{'fetchone': fetchone, 'fetchall': fetchall}])


class TestOPDSAuthentication(OPDSTestCase):
    """Test OPDS authentication logic."""

    def test_opds_disabled(self):
        """Test that OPDS returns 403 when disabled."""
        self.mock_settings.opds_enabled = False

        response = self.client.get('/opds/')
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'OPDS is disabled', response.data)

    def test_no_auth_when_disabled(self):
        """Test that OPDS works without auth when authentication disabled."""
        self.mock_settings.opds_authentication = False

        # Mock database response
        cursor = Mock()
        cursor.execute.return_value.fetchone.return_value = [0]
        self.mock_db.execute.return_value = cursor

        response = self.client.get('/opds/')
        self.assertEqual(response.status_code, 200)

    def test_auth_required_when_enabled(self):
        """Test that OPDS requires auth when enabled."""
        self.mock_settings.opds_authentication = True

        response = self.client.get('/opds/')
        self.assertEqual(response.status_code, 401)
        self.assertIn('WWW-Authenticate', response.headers)

    def test_successful_auth(self):
        """Test successful authentication."""
        self.mock_settings.opds_authentication = True

        # Mock database response
        cursor = Mock()
        cursor.execute.return_value.fetchone.return_value = [0]
        self.mock_db.execute.return_value = cursor

        response = self.client.get(
            '/opds/',
            headers=self.get_basic_auth_header()
        )
        self.assertEqual(response.status_code, 200)

    def test_failed_auth_wrong_password(self):
        """Test failed authentication with wrong password."""
        self.mock_settings.opds_authentication = True

        response = self.client.get(
            '/opds/',
            headers=self.get_basic_auth_header(password='wrong')
        )
        self.assertEqual(response.status_code, 401)

    def test_failed_auth_malformed(self):
        """Test failed authentication with malformed header."""
        self.mock_settings.opds_authentication = True

        response = self.client.get(
            '/opds/',
            headers={'Authorization': 'Basic invalid_base64!!!'}
        )
        self.assertEqual(response.status_code, 401)


class TestOPDSRootCatalog(OPDSTestCase):
    """Test OPDS root catalog endpoint."""

    def test_root_catalog_structure(self):
        """Test that root catalog has correct structure."""
        # Mock volume count
        self.set_single_db_result(fetchone=[42])

        response = self.client.get('/opds/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/atom+xml; charset=utf-8')

        # Check content
        data = response.data.decode('utf-8')
        self.assertIn('<?xml version="1.0"', data)
        self.assertIn('Kapowarr OPDS', data)
        self.assertIn('Recent Additions', data)
        self.assertIn('All Volumes (42)', data)

        # Cache headers present
        self.assertIn('ETag', response.headers)
        self.assertIn('Last-Modified', response.headers)
        self.assertIn('Cache-Control', response.headers)

        # Conditional GET should return 304
        response_304 = self.client.get(
            '/opds/',
            headers={'If-None-Match': response.headers['ETag']}
        )
        self.assertEqual(response_304.status_code, 304)
        self.assertEqual(response_304.data, b'')

    def test_root_catalog_links(self):
        """Test that root catalog has required OPDS links."""
        self.set_single_db_result(fetchone=[0])

        response = self.client.get('/opds/')
        data = response.data.decode('utf-8')

        self.assertIn('rel="start"', data)
        self.assertIn('rel="self"', data)
        self.assertIn('rel="search"', data)
        self.assertIn('opensearch.xml', data)


class TestOPDSVolumes(OPDSTestCase):
    """Test OPDS volumes listing endpoint."""

    def test_volumes_empty(self):
        """Test volumes endpoint with no volumes."""
        self.set_db_results([
            {'fetchone': [0]},
            {'fetchall': []}
        ])

        response = self.client.get('/opds/volumes')
        self.assertEqual(response.status_code, 200)

        data = response.data.decode('utf-8')
        self.assertIn('All Volumes', data)

    def test_volumes_list(self):
        """Test volumes endpoint with volumes."""
        volumes = [
            (1, 'Batman', 1940, 25),
            (2, 'Spider-Man', 1963, 50),
            (3, 'X-Men', None, 10)
        ]
        self.set_db_results([
            {'fetchone': [len(volumes)]},
            {'fetchall': volumes}
        ])

        response = self.client.get('/opds/volumes')
        self.assertEqual(response.status_code, 200)

        data = response.data.decode('utf-8')
        self.assertIn('Batman (1940)', data)
        self.assertIn('Spider-Man (1963)', data)
        self.assertIn('X-Men', data)
        self.assertIn('25 issues', data)
        self.assertIn('50 issues', data)

    def test_volumes_pagination(self):
        """Test volumes pagination."""
        # Create 60 volumes (more than PAGE_SIZE of 50)
        volumes = [(i, f'Volume {i}', 2020, 10) for i in range(60)]
        first_page = volumes[:50]
        second_page = volumes[50:]

        # First page request
        self.set_db_results([
            {'fetchone': [len(volumes)]},
            {'fetchall': first_page}
        ])

        response = self.client.get('/opds/volumes')
        data = response.data.decode('utf-8')

        # Should have next link but not previous on first page
        self.assertIn('rel="next"', data)
        self.assertNotIn('rel="previous"', data)

        # Second page
        self.set_db_results([
            {'fetchone': [len(volumes)]},
            {'fetchall': second_page}
        ])

        response = self.client.get('/opds/volumes?index=50')
        data = response.data.decode('utf-8')
        self.assertIn('rel="previous"', data)


class TestOPDSVolumeIssues(OPDSTestCase):
    """Test OPDS volume issues endpoint."""

    def test_volume_not_found(self):
        """Test 404 when volume doesn't exist."""
        self.set_single_db_result(fetchone=None)

        response = self.client.get('/opds/volume/999')
        self.assertEqual(response.status_code, 404)

    def test_volume_issues_list(self):
        """Test listing issues for a volume."""
        files = [
            (1, '/path/to/batman-001.cbz', 1024, '1', 1.0, '2020-01-01'),
            (2, '/path/to/batman-002.cbr', 2048, '2', 2.0, '2020-01-02'),
        ]
        self.set_db_results([
            {'fetchone': ('Batman', 1940)},
            {'fetchone': [len(files)]},
            {'fetchall': files}
        ])

        response = self.client.get('/opds/volume/1')
        self.assertEqual(response.status_code, 200)

        data = response.data.decode('utf-8')
        self.assertIn('Batman (1940)', data)
        self.assertIn('batman-001.cbz', data)
        self.assertIn('batman-002.cbr', data)
        self.assertIn('application/x-cbz', data)
        self.assertIn('application/x-cbr', data)

    def test_volume_issues_acquisition_links(self):
        """Test that issues have proper acquisition links."""
        files = [
            (1, '/path/to/issue.cbz', 4096, '1', 1.0, None),
        ]
        self.set_db_results([
            {'fetchone': ('Test Volume', 2020)},
            {'fetchone': [len(files)]},
            {'fetchall': files}
        ])

        response = self.client.get('/opds/volume/1')
        data = response.data.decode('utf-8')

        self.assertIn('rel="http://opds-spec.org/acquisition"', data)
        self.assertIn('/opds/download/1', data)


class TestOPDSSearch(OPDSTestCase):
    """Test OPDS search functionality."""

    def test_search_empty_query(self):
        """Test search with empty query."""
        response = self.client.get('/opds/search')
        self.assertEqual(response.status_code, 200)

        data = response.data.decode('utf-8')
        self.assertIn('Search', data)

    def test_search_results(self):
        """Test search with results."""
        files = [
            (1, '/path/batman-1.cbz', 1000, 1, 'Batman', 1940, '1', 1.0),
            (2, '/path/batman-2.cbz', 1100, 1, 'Batman', 1940, '2', 2.0),
        ]
        self.set_db_results([
            {'fetchone': [len(files)]},
            {'fetchall': files}
        ])

        response = self.client.get('/opds/search?query=Batman')
        self.assertEqual(response.status_code, 200)

        data = response.data.decode('utf-8')
        self.assertIn('Batman', data)
        self.assertIn('batman-1.cbz', data)

    def test_opensearch_descriptor(self):
        """Test OpenSearch descriptor XML."""
        response = self.client.get('/opds/opensearch.xml')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/opensearchdescription+xml')

        data = response.data.decode('utf-8')
        self.assertIn('OpenSearchDescription', data)
        self.assertIn('Kapowarr', data)
        self.assertIn('{searchTerms}', data)


class TestOPDSCover(OPDSTestCase):
    """Test OPDS cover image endpoint."""

    @patch('backend.features.opds.HAS_PIL', True)
    @patch('backend.features.opds.Image')
    def test_cover_with_pil(self, mock_image):
        """Test cover serving with PIL available."""
        # Mock database cover data
        cursor = Mock()
        fake_image_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        cursor.execute.return_value.fetchone.return_value = [fake_image_data]
        self.mock_db.execute.return_value = cursor

        # Mock PIL Image
        mock_img = Mock()
        mock_img.mode = 'RGB'
        mock_image.open.return_value = mock_img

        response = self.client.get('/opds/cover/1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/jpeg')
        self.assertIn('ETag', response.headers)
        self.assertIn('Last-Modified', response.headers)
        self.assertIn('Cache-Control', response.headers)

        response_304 = self.client.get(
            '/opds/cover/1',
            headers={'If-None-Match': response.headers['ETag']}
        )
        self.assertEqual(response_304.status_code, 304)

    @patch('backend.features.opds.HAS_PIL', False)
    def test_cover_without_pil(self):
        """Test cover serving without PIL."""
        cursor = Mock()
        cursor.execute.return_value.fetchone.return_value = [b'fake_image_data']
        self.mock_db.execute.return_value = cursor

        response = self.client.get('/opds/cover/1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/jpeg')

    def test_cover_not_found(self):
        """Test 404 when cover doesn't exist."""
        cursor = Mock()
        cursor.execute.return_value.fetchone.return_value = None
        self.mock_db.execute.return_value = cursor

        response = self.client.get('/opds/cover/999')
        self.assertEqual(response.status_code, 404)


class TestOPDSDownload(OPDSTestCase):
    """Test OPDS file download endpoint."""

    @patch('backend.features.opds.exists')
    def test_download_success(self, mock_exists):
        """Test successful file download."""
        mock_exists.return_value = True

        cursor = Mock()
        cursor.execute.return_value.fetchone.return_value = ['/path/to/comic.cbz']
        self.mock_db.execute.return_value = cursor

        with patch('backend.features.opds.send_file') as mock_send:
            mock_send.return_value = Mock(status_code=200)

            response = self.client.get('/opds/download/1')
            self.assertEqual(response.status_code, 200)

            # Verify send_file was called with correct parameters
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            self.assertEqual(args[0], '/path/to/comic.cbz')
            self.assertEqual(kwargs['mimetype'], 'application/x-cbz')
            self.assertTrue(kwargs['as_attachment'])

    def test_download_file_not_in_db(self):
        """Test 404 when file not in database."""
        cursor = Mock()
        cursor.execute.return_value.fetchone.return_value = None
        self.mock_db.execute.return_value = cursor

        response = self.client.get('/opds/download/999')
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'File not found', response.data)

    @patch('backend.features.opds.exists')
    def test_download_file_not_on_disk(self, mock_exists):
        """Test 404 when file exists in DB but not on disk."""
        mock_exists.return_value = False

        cursor = Mock()
        cursor.execute.return_value.fetchone.return_value = ['/path/to/missing.cbz']
        self.mock_db.execute.return_value = cursor

        response = self.client.get('/opds/download/1')
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'File not found on disk', response.data)

    @patch('backend.features.opds.exists')
    def test_download_mimetype_detection(self, mock_exists):
        """Test that correct MIME types are used for different file types."""
        mock_exists.return_value = True

        test_cases = [
            ('/path/file.cbz', 'application/x-cbz'),
            ('/path/file.cbr', 'application/x-cbr'),
            ('/path/file.pdf', 'application/pdf'),
            ('/path/file.epub', 'application/epub+zip'),
            ('/path/file.unknown', 'application/octet-stream'),
        ]

        for filepath, expected_mimetype in test_cases:
            cursor = Mock()
            cursor.execute.return_value.fetchone.return_value = [filepath]
            self.mock_db.execute.return_value = cursor

            with patch('backend.features.opds.send_file') as mock_send:
                mock_send.return_value = Mock(status_code=200)
                self.client.get('/opds/download/1')

                args, kwargs = mock_send.call_args
                self.assertEqual(kwargs['mimetype'], expected_mimetype,
                               f'Wrong mimetype for {filepath}')


class TestOPDSHelpers(OPDSTestCase):
    """Test OPDS helper functions."""

    def test_absolute_urls(self):
        """Test that OPDS generates absolute URLs."""
        self.set_single_db_result(fetchone=[0])

        response = self.client.get('/opds/')
        data = response.data.decode('utf-8')

        # Check for absolute URLs (should include http://)
        self.assertIn('http://localhost/opds', data)

    def test_xml_escaping(self):
        """Test that special characters are properly escaped in XML."""
        rows = [
            (1, 'Batman & Robin', 2020, 10),
            (2, 'X-Men: <New>', 2021, 5),
        ]
        self.set_db_results([
            {'fetchone': [len(rows)]},
            {'fetchall': rows}
        ])

        response = self.client.get('/opds/volumes')
        data = response.data.decode('utf-8')

        # & should be escaped as &amp;
        self.assertIn('Batman &amp; Robin', data)
        # < and > should be escaped
        self.assertIn('&lt;New&gt;', data)


if __name__ == '__main__':
    unittest.main()
