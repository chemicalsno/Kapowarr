# -*- coding: utf-8 -*-

"""
OPDS (Open Publication Distribution System) server implementation.
Allows comic reader apps like Panels, Chunky, etc. to browse and download comics.

Based on Mylar3's OPDS implementation (GPL-3.0 compatible).
"""

from datetime import datetime
from os.path import basename, exists, splitext
from typing import Any, Dict, List, Union
from urllib.parse import quote_plus

from flask import Blueprint, Response, render_template, request, send_file

from backend.base.logging import LOGGER
from backend.implementations.volumes import Library, Volume, Issue
from backend.internals.db import get_db
from backend.internals.db_models import FilesDB
from backend.internals.settings import Settings

opds = Blueprint('opds', __name__, url_prefix='/opds')

PAGE_SIZE = 50


def _check_opds_enabled() -> Union[Response, None]:
    """Check if OPDS is enabled, return error response if not."""
    if not Settings().get('opds_enabled'):
        return Response(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<error>OPDS is disabled. Enable it in Settings > General.</error>',
            status=403,
            mimetype='application/xml'
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
    """Get the OPDS root URL."""
    return '/opds'


@opds.route('/')
def root():
    """Root OPDS catalog - navigation feed."""
    if (error := _check_opds_enabled()):
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
            'kind': 'acquisition',
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
def all_volumes():
    """List all volumes with downloaded files."""
    if (error := _check_opds_enabled()):
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
    
    # Get volumes that have files
    cursor = get_db()
    volumes = cursor.execute("""
        SELECT DISTINCT v.id, v.title, v.year, v.cover,
               COUNT(DISTINCT f.id) as file_count
        FROM volumes v
        JOIN issues i ON i.volume_id = v.id
        JOIN issues_files if ON if.issue_id = i.id
        JOIN files f ON f.id = if.file_id
        GROUP BY v.id
        ORDER BY v.title
    """).fetchall()
    
    entries = []
    for vol in volumes:
        vol_id, title, year, cover, file_count = vol
        display_title = f"{title} ({year})" if year else title
        
        entry = {
            'title': display_title,
            'id': f'volume:{vol_id}',
            'updated': _now(),
            'content': f'{file_count} issues',
            'href': f'{root_url}/volume/{vol_id}',
            'kind': 'navigation',
            'cover': cover,
        }
        entries.append(entry)
    
    # Pagination
    total = len(entries)
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
        entries=entries[index:index + PAGE_SIZE]
    )


@opds.route('/volume/<int:volume_id>')
def volume_issues(volume_id: int):
    """List issues in a volume - acquisition feed."""
    if (error := _check_opds_enabled()):
        return error
    root_url = _get_opds_root()
    index = int(request.args.get('index', 0))
    
    # Get volume info
    cursor = get_db()
    vol_info = cursor.execute(
        "SELECT title, year, cover FROM volumes WHERE id = ?",
        (volume_id,)
    ).fetchone()
    
    if not vol_info:
        return Response("Volume not found", status=404)
    
    vol_title, vol_year, vol_cover = vol_info
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
        SELECT f.id, f.filepath, i.issue_number, i.calculated_issue_number, i.date
        FROM files f
        JOIN issues_files if ON f.id = if.file_id
        JOIN issues i ON if.issue_id = i.id
        WHERE i.volume_id = ?
        ORDER BY i.calculated_issue_number
    """, (volume_id,)).fetchall()
    
    entries = []
    for file_row in files:
        file_id, filepath, issue_num, calc_num, issue_date = file_row
        filename = basename(filepath)
        
        issue_title = f"#{issue_num}" if issue_num else f"Issue {calc_num}"
        
        entry = {
            'title': f"{vol_title} {issue_title}",
            'id': f'file:{file_id}',
            'updated': issue_date or _now(),
            'content': filename,
            'href': f'{root_url}/download/{file_id}',
            'kind': 'acquisition',
            'cover': vol_cover,
        }
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
def recent():
    """Recently added issues - acquisition feed."""
    if (error := _check_opds_enabled()):
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
    
    # Get recent files
    cursor = get_db()
    files = cursor.execute("""
        SELECT f.id, f.filepath, v.title, v.year, v.cover,
               i.issue_number, i.calculated_issue_number
        FROM files f
        JOIN issues_files if ON f.id = if.file_id
        JOIN issues i ON if.issue_id = i.id
        JOIN volumes v ON i.volume_id = v.id
        ORDER BY f.id DESC
        LIMIT 100
    """).fetchall()
    
    entries = []
    for file_row in files:
        file_id, filepath, vol_title, vol_year, vol_cover, issue_num, calc_num = file_row
        filename = basename(filepath)
        
        display_title = f"{vol_title} ({vol_year})" if vol_year else vol_title
        issue_title = f"#{issue_num}" if issue_num else f"Issue {calc_num}"
        
        entry = {
            'title': f"{display_title} {issue_title}",
            'id': f'file:{file_id}',
            'updated': _now(),
            'content': filename,
            'href': f'{root_url}/download/{file_id}',
            'kind': 'acquisition',
            'cover': vol_cover,
        }
        entries.append(entry)
    
    return _render_feed(
        title='Kapowarr OPDS - Recent Additions',
        feed_id='kapowarr:recent',
        links=links,
        entries=entries[index:index + PAGE_SIZE]
    )


@opds.route('/download/<int:file_id>')
def download_file(file_id: int):
    """Download a comic file."""
    if (error := _check_opds_enabled()):
        return error
    cursor = get_db()
    result = cursor.execute(
        "SELECT filepath FROM files WHERE id = ?",
        (file_id,)
    ).fetchone()
    
    if not result:
        return Response("File not found", status=404)
    
    filepath = result[0]
    
    if not exists(filepath):
        return Response("File not found on disk", status=404)
    
    filename = basename(filepath)
    
    # Determine mimetype
    ext = splitext(filename)[1].lower()
    mimetypes = {
        '.cbz': 'application/x-cbz',
        '.cbr': 'application/x-cbr',
        '.pdf': 'application/pdf',
        '.epub': 'application/epub+zip',
    }
    mimetype = mimetypes.get(ext, 'application/octet-stream')
    
    return send_file(
        filepath,
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename
    )
