import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .contracts import PermissionDenied

ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = ('retrieve', 'cache', 'retain', 'train')


def rights_record(provider: str, path=None):
    file = Path(path or os.environ.get('WANG_PROVIDER_RIGHTS_FILE', ROOT / '.private/provider-rights.json'))
    try:
        data = json.loads(file.read_text()) if file.exists() else {}
    except (ValueError,OSError):
        data = {}
    record = data.get(provider,{}) if isinstance(data,dict) else {}
    if not isinstance(record,dict):
        record = {}
    valid = False
    try:
        expiry = datetime.fromisoformat(record['expires_at'].replace('Z', '+00:00'))
        reviewed = datetime.fromisoformat(record['reviewed_at'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        valid = bool(record.get('reviewed_by') and record.get('evidence_url', '').startswith('https://') and record.get('evidence_summary') and reviewed <= now < expiry)
    except (KeyError, ValueError, TypeError, AttributeError):
        pass
    scopes = record.get('operations', {})
    if not isinstance(scopes,dict):
        scopes = {}
        valid = False
    return {'provider': provider, 'review_status': 'reviewed' if valid else 'unverified',
            'operations': {op: valid and scopes.get(op) is True for op in OPERATIONS},
            'evidence_url': record.get('evidence_url') if valid else None,
            'reason': None if valid else 'No current reviewed evidence for automated retrieval, caching, retention or training.'}


def require_rights(provider: str, *operations: str, path=None):
    record = rights_record(provider, path)
    denied = [op for op in operations if op not in OPERATIONS or not record['operations'][op]]
    if denied:
        raise PermissionDenied(f'{provider}: disabled operations: {", ".join(denied)}. Reviewed rights evidence is required; endpoint success is not permission.')
    return record
