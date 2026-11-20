"""Offline, read-only artifact replay. Estimates are not provider token counts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core/AutoRealize'))
from autorealize.prompt_cache import dynamic_json_block, json_block, estimate_text_tokens
from autorealize.review_prompt import decode_review_snapshot
from autorealize.report_writer import render_automl_context_markdown


def decode_dynamic(text, stable):
    envelope = decode_review_snapshot(text.split('\n', 1)[1])
    if '_stable_reference_encoding' not in envelope:
        return envelope
    def resolve(value):
        if isinstance(value, dict) and set(value) == {'$stable_ref'}:
            result = stable
            for key in value['$stable_ref'].split('/')[1:]:
                key = key.replace('~1', '/').replace('~0', '~')
                result = result[int(key)] if isinstance(result, list) else result[key]
            return result
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v) for v in value]
        return value
    return resolve(envelope['data'])


def sizes(before, after):
    return dict(before_chars=len(before), after_chars=len(after),
                before_estimated_tokens=estimate_text_tokens(before),
                after_estimated_tokens=estimate_text_tokens(after),
                chars_reduction_fraction=round(1-len(after)/len(before),6) if before else 0)


def measure(tasks):
    result = {'measurement': 'same-artifact offline representation replay; not live pipeline or fee A/B',
              'token_estimator': 'CJK chars + non-CJK chars/4; not a provider tokenizer',
              'contexts': [], 'dynamic_snapshots': []}
    for report in sorted(tasks.glob('*/autorealize/realize_report')):
        task = report.parents[1].name
        pack_path = report/'automl_context_pack.json'
        if not pack_path.is_file():
            continue
        pack = json.loads(pack_path.read_text(encoding='utf-8-sig'))
        before = render_automl_context_markdown(pack, include_audit_details=True)
        after = render_automl_context_markdown(pack)
        result['contexts'].append(dict(task=task, source_sha256=hashlib.sha256(pack_path.read_bytes()).hexdigest(),
                                       **sizes(before, after)))
        authorities = sorted((report/'context_artifacts').glob('cross_stage_stable_context_*.json'))
        if not authorities:
            continue
        # Select a deterministic same-task source, never combine different tasks.
        authority = json.loads(authorities[0].read_text(encoding='utf-8-sig'))['payload']
        for artifact in sorted((report/'context_artifacts').glob('cross_stage_prompt_payload_*.json')):
            snapshot = json.loads(artifact.read_text(encoding='utf-8-sig'))['payload']
            before = json_block('Dynamic', snapshot, sort_keys=False)
            after = dynamic_json_block('Dynamic', snapshot, authority)
            assert decode_dynamic(after, authority) == snapshot, artifact
            result['dynamic_snapshots'].append(dict(task=task, artifact=artifact.name,
                authority_artifact=authorities[0].name, round_trip=True, **sizes(before, after)))
    for key in ('contexts', 'dynamic_snapshots'):
        rows=result[key]
        before=sum(x['before_estimated_tokens'] for x in rows)
        after=sum(x['after_estimated_tokens'] for x in rows)
        result[key+'_total']=dict(count=len(rows), before_estimated_tokens=before,
            after_estimated_tokens=after, reduction_fraction=round(1-after/before,6) if before else 0)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    result=measure(args.tasks_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k.endswith('_total')},ensure_ascii=False))
