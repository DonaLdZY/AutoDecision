import sys
from pathlib import Path
sys.path.insert(0, r'core/MLEvolve-Alter')
from utils import data_preview
base = Path('runs/城市配送/automl/workspaces/20260615_130418_城市配送')
if base.exists():
    text = data_preview.generate(base, submission_required=False)
    print('data_preview chars=', len(text), 'approx_tokens=', round(len(text)/2.2))
    print(text[:2000])
