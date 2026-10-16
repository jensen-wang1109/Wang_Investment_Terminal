"""Load only recognized server settings, preserving explicit process environment."""
import os
from .rights import ROOT

SERVER_NAMES={'SUPABASE_URL','SUPABASE_SECRET_KEY','SUPABASE_SERVICE_ROLE_KEY','WANG_SUPABASE_OWNER_ID','WANG_LOCAL_API_TOKEN','WANG_STORAGE_BUDGET_BYTES','WANG_PROVIDER_RIGHTS_FILE','WANG_RESEARCH_DB'}


def load_server_environment(root=ROOT,environ=None):
    target=os.environ if environ is None else environ
    # .env.local takes precedence over .env; process environment wins over both.
    for name in ('.env.local','.env'):
        file=root/name
        if not file.exists():continue
        for line in file.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip() or line.lstrip().startswith('#') or '=' not in line:continue
            key,value=line.split('=',1);key=key.strip();value=value.strip()
            if key not in SERVER_NAMES or key in target:continue
            if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
            target[key]=value
    return target
