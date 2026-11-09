"""Product series comes only from the primary requirement's original filename."""
import hashlib
import re
from pathlib import Path


def filename_series_candidates(snapshot):
    sources = [source for source in snapshot.get('sources', [])
               if source.get('role') == 'tech' and source.get('status') != 'deleted']
    selected = snapshot.get('source_selection', {}).get('tech')
    if selected is None and len(sources) == 1:
        selected = sources[0]['id']
    source = next((item for item in sources if item['id'] == selected), None)
    if not source:
        return []
    name = source.get('name', '')
    match = re.search(r'[A-Za-z]+', Path(name).stem)
    if not match:
        return []
    return [{'value': match.group().upper(), 'source_id': source['id'], 'role': 'tech',
             'kind': 'source_filename', 'sha256': source['sha256'], 'version': source.get('version'),
             'name_sha256': hashlib.sha256(name.encode('utf-8')).hexdigest(),
             'location': {'filename': name}, 'quote': name}]
