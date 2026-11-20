"""Rebuild recorded provider token use, retaining unknown/unrecorded usage."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'runs/chemical-studio-demo-20261019'
sys.path.insert(0,str(ROOT/'core/AlgoEvolve'))
from llm.usage import _summary_for, _write_summary


def main():
    logs = next(RUN.glob('tasks/*/automl/logs/*'))
    summary_path = logs/'llm_usage_summary.json'
    old = RUN/'llm_usage_summary.before-rebuild.json'
    if not old.exists(): old.write_bytes(summary_path.read_bytes())
    _write_summary(summary_path,_summary_for(summary_path))
    core = json.loads(summary_path.read_text(encoding='utf-8'))
    seen, rows, sources = set(), [], []
    for path in RUN.glob('tasks/**/realize_report/event_stream.jsonl'):
        # Input directory aliases/copies must not add the same paid requests twice.
        count, added = 0, 0
        for line in path.read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            if event.get('event') != 'USAGE_RECORDED': continue
            count += 1
            key = hashlib.sha256(json.dumps(event,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            if key in seen: continue
            seen.add(key); rows.append(event); added += 1
        sources.append({'file':str(path.relative_to(RUN)),'usage_events':count,'new_unique_events':added})
    ar = {'calls':len(rows)}
    for key in ['prompt_tokens','cached_tokens','miss_tokens','reasoning_tokens','completion_tokens','total_tokens']:
        ar[key] = sum(int(e['fields'].get(key) or 0) for e in rows)
    ar['usage_missing_events'] = sum(not e['fields'].get('usage_available',False) for e in rows)
    ar['cache_hit_ratio_of_recorded_input'] = ar['cached_tokens']/ar['prompt_tokens'] if ar['prompt_tokens'] else None
    # Report token receipts live in llm_usage.jsonl, not the event stream.
    # A report rerun archives the old directory and keeps its original events;
    # count each provider receipt once across both locations.
    report_rows, report_events, report_sources = {}, {}, []
    for path in RUN.glob('tasks/**/llm_usage.jsonl'):
        count, added = 0, 0
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            event = json.loads(line)
            if not str(event.get('component', '')).startswith('autoreport.'): continue
            count += 1
            key = event.get('request_id') or hashlib.sha256(
                json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if key in report_rows: continue
            report_rows[key] = event; added += 1
        if count:
            report_sources.append({'file':str(path.relative_to(RUN)),
                                   'usage_events':count,'new_unique_events':added})
    for path in RUN.glob('tasks/**/event_stream.jsonl'):
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            event = json.loads(line)
            if event.get('schema_version') != 'autoreport.event.v1': continue
            key = (event.get('run_id'), event.get('seq'))
            report_events[key] = event
    def token_totals(records):
        result = {'calls':len(records)}
        for key in ['prompt_tokens','completion_tokens','total_tokens']:
            result[key] = sum(int(row.get(key) or 0) for row in records)
        result['cached_tokens'] = sum(int(row.get('prompt_cache_hit_tokens')
            or row.get('prompt_tokens_details', {}).get('cached_tokens') or 0) for row in records)
        result['reasoning_tokens'] = sum(int(row.get('completion_tokens_details', {}).get('reasoning_tokens') or 0)
            for row in records)
        result['cache_hit_ratio_of_recorded_input'] = (
            result['cached_tokens']/result['prompt_tokens'] if result['prompt_tokens'] else None)
        return result
    report = token_totals(list(report_rows.values()))
    report['completed_events'] = sum(e.get('event') == 'LLM_COMPLETED' for e in report_events.values())
    report['retry_events_without_complete_usage'] = sum(
        e.get('event') == 'LLM_RECONNECTING' for e in report_events.values())
    conversation_path = RUN/'real-conversation.json'
    chat_rows = []
    if conversation_path.is_file():
        conversation = json.loads(conversation_path.read_text(encoding='utf-8'))
        chat_rows = [m['usage'] for m in conversation['messages'] if isinstance(m.get('usage'),dict)]
    chat = token_totals(chat_rows)
    summary = {'scope':'Recorded provider tokens only. Interrupted streams can incur unreported usage; this is not the provider bill.',
        'algoevolve':{k:core.get(k) for k in ['calls','prompt_tokens','completion_tokens','reasoning_tokens','total_tokens',
            'prompt_cache_hit_tokens','prompt_cache_miss_tokens','provider_cache_hit_ratio','provider_usage_missing_calls','usage_replay_skipped_rows']},
        'autorealize_all_attempts_deduplicated':ar, 'autorealize_sources':sources,
        'autoreport_all_attempts_deduplicated':report, 'autoreport_sources':report_sources,
        'studio_real_conversation':chat,
        'price_estimate':None,'price_reason':'Exact deepseek-flash pricing was not in the local legacy pricing table; no older alias price substituted.',
        'minimum_recorded_input_tokens':core['prompt_tokens']+ar['prompt_tokens']+report['prompt_tokens']+chat['prompt_tokens'],
        'minimum_recorded_output_tokens':core['completion_tokens']+ar['completion_tokens']+report['completion_tokens']+chat['completion_tokens']}
    previous = RUN/'usage-audit.before-report-and-chat.json'
    if not previous.exists() and (RUN/'usage-audit.json').is_file():
        previous.write_bytes((RUN/'usage-audit.json').read_bytes())
    (RUN/'usage-audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='autorealize_sources'},ensure_ascii=False))


if __name__=='__main__':main()
