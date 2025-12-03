# -*- coding: utf-8 -*-

"""
OPDS (Open Publication Distribution System) server implementation.
Allows comic reader apps like Panels, Chunky, etc. to browse and download comics.

Based on Mylar3's OPDS implementation (GPL-3.0 compatible).
"""

from base64 import b64decode
from datetime import datetime
from io import BytesIO
from os.path import basename, exists, splitext
from typing import Any, Dict, List, Union
from urllib.parse import quote_plus

import requests
from flask import Blueprint, Response, render_template, request, send_file

# PIL is optional - only needed for thumbnail generation
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from backend.base.logging import LOGGER
from backend.implementations.volumes import Library, Volume, Issue
from backend.internals.db import get_db
from backend.internals.db_models import FilesDB
from backend.internals.settings import Settings

opds = Blueprint('opds', __name__, url_prefix='/opds')

PAGE_SIZE = 50

# MIME type mapping for comic file extensions
COMIC_MIMETYPES = {
    '.cbz': 'application/x-cbz',
    '.cbr': 'application/x-cbr',
    '.pdf': 'application/pdf',
    '.epub': 'application/epub+zip',
}


def _check_opds_access() -> Union[Response, None]:
    """Check if OPDS is enabled and user is authenticated.

    Authentication fallback behavior:
        If opds_password is not set but authentication is enabled, the API key
        is used as the password (similar to Mylar3's behavior). This allows OPDS
        to work with existing API credentials but could be a security concern if
        the API key is used elsewhere. It's recommended to set an explicit OPDS
        password in Settings > General > OPDS Authentication if security is a concern.
    """
    settings = Settings().sv

    # Check if OPDS is enabled
    if not settings.opds_enabled:
        return Response(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<error>OPDS is disabled. Enable it in Settings &gt; General.</error>',
            status=403,
            mimetype='application/xml'
        )

    # Check authentication if enabled
    if settings.opds_authentication:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Basic '):
            return Response(
                'Authentication required',
                status=401,
                headers={'WWW-Authenticate': 'Basic realm="Kapowarr OPDS"'}
            )
        
        try:
            encoded_credentials = auth_header[6:]  # Remove 'Basic '
            decoded = b64decode(encoded_credentials).decode('utf-8')
            username, password = decoded.split(':', 1)
        except Exception:
            return Response(
                'Invalid credentials',
                status=401,
                headers={'WWW-Authenticate': 'Basic realm="Kapowarr OPDS"'}
            )
        
        # Get expected credentials
        expected_username = settings.opds_username or ''  # Default empty string
        # If opds_password is not set, use API key as password (like Mylar3 does)
        expected_password = settings.opds_password or settings.api_key or ''

        if username != expected_username or password != expected_password:
            LOGGER.warning(f'OPDS authentication failed for user: {username}')
            return Response(
                'Invalid credentials',
                status=401,
                headers={'WWW-Authenticate': 'Basic realm="Kapowarr OPDS"'}
            )
    
    return None


def _now() -> str:
    """Get current timestamp in ISO format."""
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _make_link(href: str, type: str, rel: str, title: str = None) -> Dict[str, str]:
    """Create a link dictionary for OPDS feed."""
    link = {'href': href, 'type': type, 'rel': rel}
    if title:
        link['title'] = title
    return link


def _get_mimetype(filename: str) -> str:
    """Get MIME type for a comic file based on extension.

    Args:
        filename: The filename to check

    Returns:
        MIME type string, defaults to 'application/octet-stream' if unknown
    """
    ext = splitext(filename)[1].lower()
    return COMIC_MIMETYPES.get(ext, 'application/octet-stream')


def _format_issue_number(issue_num: Any, calc_num: Any) -> str:
    """Format issue number for display, handling None/missing values.

    Args:
        issue_num: The issue number (can be None, 0, or string)
        calc_num: The calculated issue number (can be None or float)

    Returns:
        Formatted issue string like "#1" or "Issue 1.5" or "Issue (Unknown)"
    """
    if issue_num:
        return f"#{issue_num}"
    elif calc_num is not None:
        return f"Issue {calc_num}"
    else:
        return "Issue (Unknown)"


def _render_feed(title: str, feed_id: str, links: List[Dict], entries: List[Dict]) -> Response:
    """Render an OPDS Atom feed."""
    xml = render_template(
        'opds.xml',
        title=title,
        id=feed_id,
        updated=_now(),
        links=links,
        entries=entries
    )
    return Response(xml, mimetype='application/atom+xml; charset=utf-8')


def _get_opds_root() -> str:
    """Get the OPDS root URL as an absolute URL.

    Returns absolute URL like: http://localhost:5656/opds
    """
    # Get the base URL from the request (includes scheme and host)
    base_url = request.url_root.rstrip('/')
    return f'{base_url}/opds'


def _handle_opds_error(f):
    """Decorator to handle errors in OPDS endpoints gracefully."""
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            LOGGER.exception(f"OPDS error in {f.__name__}: ")
            return Response(
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<error>Server error. Please check server logs.</error>',
                status=500,
                mimetype='application/xml'
            )
    return wrapper


@opds.route('/')
@_handle_opds_error
def root():
    """Root OPDS catalog - navigation feed."""
    if (error := _check_opds_access()):
        return error
    root_url = _get_opds_root()

    links = [
        _make_link(
            href=root_url,
            type='application/atom+xml; profile=opds-catalog; kind=navigation',
            rel='start',
            title='Home'
        ),
        _make_link(
            href=root_url,
            type='application/atom+xml; profile=opds-catalog; kind=navigation',
            rel='self'
        ),
        _make_link(
            href=f'{root_url}/opensearch.xml',
            type='application/opensearchdescription+xml',
            rel='search',
            title='Search'
        ),
    ]
    
    # Count volumes with files
    cursor = get_db()
    volume_count = cursor.execute("""
        SELECT COUNT(DISTINCT i.volume_id)
        FROM files f
        JOIN issues_files if ON f.id = if.file_id
        JOIN issues i ON if.issue_id = i.id
    """).fetchone()[0]
    
    entries = [
        {
            'title': 'Recent Additions',
            'id': 'recent',
            'updated': _now(),
            'content': 'Recently added issues',
            'href': f'{root_url}/recent',
            'kind': 'navigation',  # Links to a feed, not a file
        },
        {
            'title': f'All Volumes ({volume_count})',
            'id': 'volumes',
            'updated': _now(),
            'content': 'Browse all comic volumes',
            'href': f'{root_url}/volumes',
            'kind': 'navigation',
        },
    ]
    
    return _render_feed(
        title='Kapowarr OPDS',
        feed_id='kapowarr:root',
        links=links,
        entries=entries
    )


@opds.route('/volumes')
@_handle_opds_error
def all_volumes():
    """List all volumes with downloaded files."""
    if (error := _check_opds_access()):
        return error
    root_url = _get_opds_root()
    index = int(request.args.get('index', 0))
    
    links = [
        _make_link(
            href=root_url,
            type='application/atom+xml; profile=opds-catalog; kind=navigation',
            rel='start',
            title='Home'
        ),
        _make_link(
            href=f'{root_url}/volumes',
            type='application/atom+xml; profile=opds-catalog; kind=navigation',
            rel='self'
        ),
    ]
    
    # Get volumes that have files - use LIMIT/OFFSET for efficient pagination
    cursor = get_db()

    # Get total count for pagination
    total = cursor.execute("""
        SELECT COUNT(DISTINCT v.id)
        FROM volumes v
        JOIN issues i ON i.volume_id = v.id
        JOIN issues_files if ON if.issue_id = i.id
        JOIN files f ON f.id = if.file_id
    """).fetchone()[0]

    # Get paginated volumes
    volumes = cursor.execute("""
        SELECT DISTINCT v.id, v.title, v.year,
               COUNT(DISTINCT f.id) as file_count
        FROM volumes v
        JOIN issues i ON i.volume_id = v.id
        JOIN issues_files if ON if.issue_id = i.id
        JOIN files f ON f.id = if.file_id
        GROUP BY v.id
        ORDER BY v.title
        LIMIT ? OFFSET ?
    """, (PAGE_SIZE, index)).fetchall()

    entries = []
    for vol in volumes:
        vol_id, title, year, file_count = vol
        display_title = f"{title} ({year})" if year else title

        entry = {
            'title': display_title,
            'id': f'volume:{vol_id}',
            'updated': _now(),
            'content': f'{file_count} issues',
            'href': f'{root_url}/volume/{vol_id}',
            'kind': 'navigation',
            'cover': f'{root_url}/cover/{vol_id}',
        }
        entries.append(entry)

    # Pagination links
    if total > index + PAGE_SIZE:
        links.append(_make_link(
            href=f'{root_url}/volumes?index={index + PAGE_SIZE}',
            type='application/atom+xml; profile=opds-catalog; kind=navigation',
            rel='next'
        ))
    if index >= PAGE_SIZE:
        links.append(_make_link(
            href=f'{root_url}/volumes?index={index - PAGE_SIZE}',
            type='application/atom+xml; profile=opds-catalog; kind=navigation',
            rel='previous'
        ))
    
    return _render_feed(
        title='Kapowarr OPDS - All Volumes',
        feed_id='kapowarr:volumes',
        links=links,
        entries=entries  # Already paginated by SQL
    )


@opds.route('/volume/<int:volume_id>')
@_handle_opds_error
def volume_issues(volume_id: int):
    """List issues in a volume - acquisition feed."""
    if (error := _check_opds_access()):
        return error
    root_url = _get_opds_root()
    index = int(request.args.get('index', 0))
    
    # Get volume info
    cursor = get_db()
    vol_info = cursor.execute(
        "SELECT title, year FROM volumes WHERE id = ?",
        (volume_id,)
    ).fetchone()

    if not vol_info:
        return Response("Volume not found", status=404)

    vol_title, vol_year = vol_info
    display_title = f"{vol_title} ({vol_year})" if vol_year else vol_title
    
    links = [
        _make_link(
            href=root_url,
            type='application/atom+xml; profile=opds-catalog; kind=navigation',
            rel='start',
            title='Home'
        ),
        _make_link(
            href=f'{root_url}/volume/{volume_id}',
            type='application/atom+xml; profile=opds-catalog; kind=acquisition',
            rel='self'
        ),
    ]
    
    # Get files for this volume
    files = cursor.execute("""
        SELECT f.id, f.filepath, f.size, i.issue_number, i.calculated_issue_number, i.date
        FROM files f
        JOIN issues_files if ON f.id = if.file_id
        JOIN issues i ON if.issue_id = i.id
        WHERE i.volume_id = ?
        ORDER BY i.calculated_issue_number
    """, (volume_id,)).fetchall()

    entries = []
    LOGGER.debug(f'OPDS: Found {len(files)} files for volume {volume_id}')
    for file_row in files:
        file_id, filepath, file_size, issue_num, calc_num, issue_date = file_row
        LOGGER.debug(f'OPDS: Processing file_id={file_id}, issue_num={issue_num!r}, calc_num={calc_num}')
        filename = basename(filepath)

        # Determine mimetype from extension
        mimetype = _get_mimetype(filename)

        # Format issue number
        issue_title = _format_issue_number(issue_num, calc_num)

        entry = {
            'title': f"{vol_title} {issue_title}",
            'id': f'file:{file_id}',
            'updated': issue_date or _now(),
            'content': filename,
            'href': f'{root_url}/download/{file_id}',
            'kind': 'acquisition',
            'cover': f'{root_url}/cover/{volume_id}',
            'mimetype': mimetype,
            'size': file_size or 0,  # File size in bytes
        }
        LOGGER.debug(f'OPDS: Entry created - title={entry["title"]!r}, href={entry["href"]}')
        entries.append(entry)
    
    # Pagination
    total = len(entries)
    if total > index + PAGE_SIZE:
        links.append(_make_link(
            href=f'{root_url}/volume/{volume_id}?index={index + PAGE_SIZE}',
            type='application/atom+xml; profile=opds-catalog; kind=acquisition',
            rel='next'
        ))
    if index >= PAGE_SIZE:
        links.append(_make_link(
            href=f'{root_url}/volume/{volume_id}?index={index - PAGE_SIZE}',
            type='application/atom+xml; profile=opds-catalog; kind=acquisition',
            rel='previous'
        ))
    
    return _render_feed(
        title=f'Kapowarr OPDS - {display_title}',
        feed_id=f'kapowarr:volume:{volume_id}',
        links=links,
        entries=entries[index:index + PAGE_SIZE]
    )


@opds.route('/recent')
@_handle_opds_error
def recent():
    """Recently added issues - acquisition feed."""
    if (error := _check_opds_access()):
        return error
    root_url = _get_opds_root()
    index = int(request.args.get('index', 0))
    
    links = [
        _make_link(
            href=root_url,
            type='application/atom+xml; profile=opds-catalog; kind=navigation',
            rel='start',
            title='Home'
        ),
        _make_link(
            href=f'{root_url}/recent',
            type='application/atom+xml; profile=opds-catalog; kind=acquisition',
            rel='self'
        ),
    ]
    
    # Get recent files - use LIMIT/OFFSET for efficient pagination
    cursor = get_db()

    # Get total count for pagination
    total = cursor.execute("""
        SELECT COUNT(DISTINCT f.id)
        FROM files f
        JOIN issues_files if ON f.id = if.file_id
        JOIN issues i ON if.issue_id = i.id
        JOIN volumes v ON i.volume_id = v.id
    """).fetchone()[0]

    # Get paginated files
    files = cursor.execute("""
        SELECT f.id, f.filepath, f.size, v.id, v.title, v.year,
               i.issue_number, i.calculated_issue_number
        FROM files f
        JOIN issues_files if ON f.id = if.file_id
        JOIN issues i ON if.issue_id = i.id
        JOIN volumes v ON i.volume_id = v.id
        ORDER BY f.id DESC
        LIMIT ? OFFSET ?
    """, (PAGE_SIZE, index)).fetchall()

    entries = []
    for file_row in files:
        file_id, filepath, file_size, vol_id, vol_title, vol_year, issue_num, calc_num = file_row
        filename = basename(filepath)

        # Determine mimetype from extension
        mimetype = _get_mimetype(filename)

        display_title = f"{vol_title} ({vol_year})" if vol_year else vol_title
        issue_title = _format_issue_number(issue_num, calc_num)

        entry = {
            'title': f"{display_title} {issue_title}",
            'id': f'file:{file_id}',
            'updated': _now(),
            'content': filename,
            'href': f'{root_url}/download/{file_id}',
            'kind': 'acquisition',
            'cover': f'{root_url}/cover/{vol_id}',
            'mimetype': mimetype,
            'size': file_size or 0,  # File size in bytes
        }
        entries.append(entry)

    # Pagination links (was missing before - Issue #1)
    if total > index + PAGE_SIZE:
        links.append(_make_link(
            href=f'{root_url}/recent?index={index + PAGE_SIZE}',
            type='application/atom+xml; profile=opds-catalog; kind=acquisition',
            rel='next'
        ))
    if index >= PAGE_SIZE:
        links.append(_make_link(
            href=f'{root_url}/recent?index={index - PAGE_SIZE}',
            type='application/atom+xml; profile=opds-catalog; kind=acquisition',
            rel='previous'
        ))

    return _render_feed(
        title='Kapowarr OPDS - Recent Additions',
        feed_id='kapowarr:recent',
        links=links,
        entries=entries  # Already paginated by SQL
    )


@opds.route('/opensearch.xml')
@_handle_opds_error
def opensearch_descriptor():
    """OpenSearch descriptor for OPDS search."""
    if (error := _check_opds_access()):
        return error
    root_url = _get_opds_root()
    base_url = request.url_root.rstrip('/')

    xml = render_template(
        'opensearch.xml',
        icon_url=f'{base_url}/static/img/favicon.svg',
        search_url=f'{root_url}/search'
    )
    return Response(xml, mimetype='application/opensearchdescription+xml')


@opds.route('/search')
@_handle_opds_error
def search():
    """Search for comics - acquisition feed."""
    if (error := _check_opds_access()):
        return error
    root_url = _get_opds_root()

    query = request.args.get('query', '').strip()
    index = int(request.args.get('index', 0))

    if not query:
        return _render_feed(
            title='Kapowarr OPDS - Search',
            feed_id='kapowarr:search:empty',
            links=[
                _make_link(
                    href=root_url,
                    type='application/atom+xml; profile=opds-catalog; kind=navigation',
                    rel='start',
                    title='Home'
                ),
            ],
            entries=[]
        )

    links = [
        _make_link(
            href=root_url,
            type='application/atom+xml; profile=opds-catalog; kind=navigation',
            rel='start',
            title='Home'
        ),
        _make_link(
            href=f'{root_url}/search?query={quote_plus(query)}',
            type='application/atom+xml; profile=opds-catalog; kind=acquisition',
            rel='self'
        ),
    ]

    # Search volumes and issues - use LIMIT/OFFSET for efficient pagination
    cursor = get_db()
    search_pattern = f'%{query}%'

    # Get total count for pagination
    total = cursor.execute("""
        SELECT COUNT(DISTINCT f.id)
        FROM files f
        JOIN issues_files if ON f.id = if.file_id
        JOIN issues i ON if.issue_id = i.id
        JOIN volumes v ON i.volume_id = v.id
        WHERE v.title LIKE ? OR i.issue_number LIKE ?
    """, (search_pattern, search_pattern)).fetchone()[0]

    # Search by volume title or issue number with pagination
    files = cursor.execute("""
        SELECT DISTINCT f.id, f.filepath, f.size, v.id, v.title, v.year,
               i.issue_number, i.calculated_issue_number
        FROM files f
        JOIN issues_files if ON f.id = if.file_id
        JOIN issues i ON if.issue_id = i.id
        JOIN volumes v ON i.volume_id = v.id
        WHERE v.title LIKE ? OR i.issue_number LIKE ?
        ORDER BY v.title, i.calculated_issue_number
        LIMIT ? OFFSET ?
    """, (search_pattern, search_pattern, PAGE_SIZE, index)).fetchall()

    entries = []
    for file_row in files:
        file_id, filepath, file_size, vol_id, vol_title, vol_year, issue_num, calc_num = file_row
        filename = basename(filepath)

        # Determine mimetype from extension
        mimetype = _get_mimetype(filename)

        display_title = f"{vol_title} ({vol_year})" if vol_year else vol_title
        issue_title = _format_issue_number(issue_num, calc_num)

        entry = {
            'title': f"{display_title} {issue_title}",
            'id': f'file:{file_id}',
            'updated': _now(),
            'content': filename,
            'href': f'{root_url}/download/{file_id}',
            'kind': 'acquisition',
            'cover': f'{root_url}/cover/{vol_id}',
            'mimetype': mimetype,
            'size': file_size or 0,  # File size in bytes
        }
        entries.append(entry)

    # Pagination links
    if total > index + PAGE_SIZE:
        links.append(_make_link(
            href=f'{root_url}/search?query={quote_plus(query)}&index={index + PAGE_SIZE}',
            type='application/atom+xml; profile=opds-catalog; kind=acquisition',
            rel='next'
        ))
    if index >= PAGE_SIZE:
        links.append(_make_link(
            href=f'{root_url}/search?query={quote_plus(query)}&index={index - PAGE_SIZE}',
            type='application/atom+xml; profile=opds-catalog; kind=acquisition',
            rel='previous'
        ))

    return _render_feed(
        title=f'Kapowarr OPDS - Search: {query}',
        feed_id=f'kapowarr:search:{query}',
        links=links,
        entries=entries  # Already paginated by SQL
    )


@opds.route('/cover/<int:volume_id>')
@_handle_opds_error
def cover_image(volume_id: int):
    """Serve cover image for a volume from the database.

    Args:
        volume_id: The volume ID
    """
    if (error := _check_opds_access()):
        return error

    LOGGER.debug(f'OPDS: Serving cover for volume {volume_id}')

    # Get volume cover from database
    cursor = get_db()
    result = cursor.execute(
        "SELECT cover FROM volumes_covers WHERE volume_id = ? LIMIT 1",
        (volume_id,)
    ).fetchone()

    if not result or not result[0]:
        # No cover in database - return 404
        LOGGER.warning(f'OPDS: No cover found for volume {volume_id}')
        return Response("Cover not found", status=404)

    cover_data = result[0]

    try:
        # Serve the cover image directly from database
        cover_io = BytesIO(cover_data)

        # If PIL is available, we can optimize/convert the image
        if HAS_PIL:
            img = Image.open(cover_io)

            # Convert to RGB if needed (for PNG with transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background

            # Save as JPEG for consistent format
            output = BytesIO()
            img.save(output, format='JPEG', quality=90, optimize=True)
            output.seek(0)

            return send_file(
                output,
                mimetype='image/jpeg',
                as_attachment=False,
                download_name=f'cover_{volume_id}.jpg'
            )
        else:
            # Serve directly without conversion
            cover_io.seek(0)
            return send_file(
                cover_io,
                mimetype='image/jpeg',  # Assume JPEG
                as_attachment=False,
                download_name=f'cover_{volume_id}.jpg'
            )

    except Exception as e:
        LOGGER.error(f'Error serving cover for volume {volume_id}: {e}')
        return Response("Error loading cover", status=500)


@opds.route('/download/<int:file_id>')
@_handle_opds_error
def download_file(file_id: int):
    """Download a comic file."""
    if (error := _check_opds_access()):
        return error

    LOGGER.info(f'OPDS: Download request for file_id={file_id}')

    cursor = get_db()
    result = cursor.execute(
        "SELECT filepath FROM files WHERE id = ?",
        (file_id,)
    ).fetchone()

    if not result:
        LOGGER.error(f'OPDS: File {file_id} not found in database')
        return Response("File not found", status=404)

    filepath = result[0]
    LOGGER.info(f'OPDS: Attempting to serve file: {filepath}')

    if not exists(filepath):
        LOGGER.error(f'OPDS: File does not exist on disk: {filepath}')
        return Response("File not found on disk", status=404)

    filename = basename(filepath)

    # Determine mimetype
    mimetype = _get_mimetype(filename)

    LOGGER.info(f'OPDS: Serving {filename} ({mimetype}) from {filepath}')

    return send_file(
        filepath,
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename
    )
