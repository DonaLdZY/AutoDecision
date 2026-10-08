"""Re-audit an actual system-generated report without rerunning search or writing."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runs/industrial-examples-20260907'
sys.path.insert(0, str(ROOT / 'core/AutoReport'))
from autoreport.collector import collect_evidence
from autoreport.config import load_config
from autoreport.events import ReportEventWriter
from autoreport.generator import revise_existing_report


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def fingerprint(source):
    return {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in ('report.md', 'report.json', 'report_trace.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slug', required=True)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--feedback-file', type=Path)
    parser.add_argument('--from-directory', type=Path)
    parser.add_argument('--section', action='append')
    parser.add_argument('--code-block', action='append', type=int)
    parser.add_argument('--reviewed-edits-file', type=Path)
    args = parser.parse_args()
    live = read(OUT / 'batch-state.json')['tasks'][args.slug]
    source = Path(live['report_dir']).resolve()
    if not source.is_relative_to(OUT.resolve()) or live['phase'] != 'report_completed':
        raise RuntimeError('A completed report inside the current batch is required')
    dest = args.directory or OUT / 'stage-repairs' / f'report-audit-{args.slug}-{time.time_ns()}'
    dest = dest.resolve()
    if not dest.is_relative_to(OUT.resolve()):
        raise RuntimeError('Repair outputs must remain inside this batch')
    if args.apply:
        result = read(dest / 'result.json')
        if not result['passed'] or result['original_fingerprints'] != fingerprint(source):
            raise RuntimeError('Repair is incomplete or original report changed')
        if result['revised_fingerprints'] != fingerprint(dest):
            raise RuntimeError('Audited report changed after verification')
        archive = OUT / 'stage-archives' / args.slug / f'report-before-audit-{time.time_ns()}'
        shutil.copytree(source, archive)
        for name in ('report.md', 'report.json', 'report_trace.json'):
            shutil.copy2(dest / name, source / name)
        save(dest / 'application.json', {'applied': True, 'source': str(source), 'archive': str(archive)})
        print(json.dumps({'applied': True, 'source': str(source), 'archive': str(archive)}))
        return
    dest.mkdir(parents=True, exist_ok=True)
    prior = fingerprint(source)
    draft_source = args.from_directory.resolve() if args.from_directory else source
    if draft_source != source:
        if not draft_source.is_relative_to((OUT / 'stage-repairs').resolve()):
            raise ValueError('The prior audited candidate must belong to this batch')
        previous = read(draft_source / 'result.json')
        if (not previous.get('passed') or previous['original_fingerprints'] != prior
                or previous['revised_fingerprints'] != fingerprint(draft_source)):
            raise RuntimeError('The prior candidate or its official source changed after audit')
    cfg = load_config(source / 'resolved_config.yaml')
    cfg.output_dir = str(dest)
    spec = importlib.util.spec_from_file_location('provider', ROOT / 'scripts/validate-industrial-prompts.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    model = helper.model_entry()
    cfg.llm.model, cfg.llm.base_url, cfg.llm.api_key = model['model'], model['baseUrl'], model['apiKey']
    cfg.llm.reasoning_effort = 'xhigh'
    cfg.llm.request_timeout_seconds = 900
    cfg.llm.max_retries = 1
    os.environ['AUTOREPORT_PROMPT_CACHE_KEY_MODE'] = 'enabled'
    events = ReportEventWriter(dest, run_id='report-audit', print_events_to_console=False)
    bundle = collect_evidence(cfg, events)
    feedback = read(args.feedback_file) if args.feedback_file else []
    if not isinstance(feedback, list) or any(not isinstance(item, str) for item in feedback):
        raise ValueError('Report feedback must be a list of concrete evidence-backed findings')
    save(dest / 'feedback.json', feedback)
    revise_existing_report(cfg, bundle, events, read(draft_source / 'report.json'), read(draft_source / 'report_trace.json'),
                           feedback=feedback, section_titles=args.section, code_block_indices=args.code_block,
                           reviewed_edits=read(args.reviewed_edits_file) if args.reviewed_edits_file else None)
    if fingerprint(source) != prior:
        raise RuntimeError('Original report changed during repair')
    audit = read(dest / 'report_trace.json')['audit']
    save(dest / 'result.json', {'passed': audit['status'] in ('pass', 'revised') and audit['complete_draft_covered'],
        'scope': 'Actual production auditor output; independent factual and API review is still required before applying.',
        'audit_parts': audit['parts'], 'original_fingerprints': prior, 'revised_fingerprints': fingerprint(dest),
        'search_or_holdout_repeated': False, 'original_source': str(source),
        'draft_source': str(draft_source), 'repaired_sections': args.section, 'repaired_code_blocks': args.code_block})
    print(json.dumps({'directory': str(dest), 'audit_status': audit['status'], 'audit_parts': audit['parts']}))


if __name__ == '__main__':
    main()
