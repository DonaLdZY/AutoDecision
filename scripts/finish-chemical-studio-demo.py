"""Publish the real demo's selected package through the existing product APIs.

Run only after the search and final evaluation finish. A reviewed publication
spec must be supplied; this helper never synthesizes or edits candidate code.
Credentials remain in the application's settings. All receipts are resumable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/chemical-studio-demo-20261019'
BASE = 'http://127.0.0.1:18080'


def request(path, payload=None, timeout=180):
    req = urllib.request.Request(BASE + path,
        data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def save(name, value):
    path = RUN / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def publish(spec_path):
    receipt = json.loads((RUN/'receipt.json').read_text(encoding='utf-8'))
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    task = next(t for t in request('/api/tasks') if t['id'] == receipt['task_id'])
    if task['status'] == 'running':
        raise RuntimeError('Research still running; do not freeze a moving result')
    if task['status'] != 'completed':
        raise RuntimeError(f"Research requires inspection: {task['status']} / {task['phase']}")
    if (RUN/'published-package.json').is_file():
        package = json.loads((RUN/'published-package.json').read_text(encoding='utf-8'))
        current = request('/api/studio/packages/'+package['id'])
        if current['fingerprint'] != package['fingerprint']:
            raise RuntimeError('Published package receipt fingerprint changed')
    else:
        delivery_path = f"/api/studio/tasks/{task['id']}/delivery"
        delivery = request(delivery_path, {'confirm':True})
        save('delivery-prepared.json', delivery)
        if not delivery['structure_ready']:
            raise RuntimeError('Delivery not ready; inspect delivery-prepared.json')
        # Prepare the model's reviewed window using the same product helper used
        # by /prepare-input. This is input assembly only, not model inference.
        sys.path.insert(0, str(ROOT/'frontend/backend'))
        from project_inputs import ProjectBinding, prepare_window
        binding = ProjectBinding.model_validate(spec['input_binding'])
        prepared = prepare_window(task['input_root'], binding, 'latest')
        save('delivery-input-provenance.json', {k:v for k,v in prepared.items() if k!='data_json'})
        verification = request(delivery_path+'/verify', {
            'delivery_id':delivery['delivery_id'], 'input_mode':'json',
            'data_json':prepared['data_json'], 'timeout_seconds':120, 'confirm':True})
        save('delivery-verification.json', verification)
        if verification['status'] != 'passed':
            raise RuntimeError('Actual inference failed; inspect delivery-verification.json')
        package = request('/api/studio/packages', {
            **spec, 'task_id':task['id'], 'project_id':receipt['project_id'],
            'delivery_id':delivery['delivery_id']})
        save('published-package.json', package)
    archive_path = RUN/'硫酸铝下一小时AlN与蒸汽参考_算法包.zip'
    with urllib.request.urlopen(BASE+f"/api/studio/packages/{package['id']}/bundle", timeout=180) as response:
        raw = response.read()
    archive_path.write_bytes(raw)
    save('package-export.json', {'package_id':package['id'],'fingerprint':package['fingerprint'],
        'zip_path':str(archive_path),'zip_bytes':len(raw),'zip_sha256':hashlib.sha256(raw).hexdigest()})
    print(json.dumps({'package_id':package['id'],'name':package['name'],'zip':str(archive_path)},ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('publication_spec', type=Path)
    args = parser.parse_args()
    publish(args.publication_spec)
