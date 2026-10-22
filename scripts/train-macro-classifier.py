import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.macro_classifier import trained_classifier
if __name__=='__main__':
 _,report=trained_classifier();out=Path('.private/shared-intelligence');out.mkdir(parents=True,exist_ok=True);(out/'classifier-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report))
