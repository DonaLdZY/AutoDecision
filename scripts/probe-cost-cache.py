"""Opt-in six-request DeepSeek transport probe using synthetic data only.

Set DEEPSEEK_API_KEY in the process environment; never pass keys as arguments.
This is not an end-to-end optimization-quality or production-cost benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'core/AlgoEvolve'), str(ROOT/'core/AutoRealize')]
from openai import OpenAI
from agents.prompt_cache import candidate_review_section, task_section
from llm.openai import _build_messages, _build_json_mode_messages
from llm import FunctionSpec
from autorealize.prompt_cache import stable_dynamic_prompt, json_block, estimate_text_tokens


def requests():
    requirements = {
        'metric': 'MAE; minimize', 'capacity_kg': 500, 'stop_count_cap': None,
        'missing_dates': 'reject business scoring; never assume dates',
        'population': 'Only development rows are used for candidate comparison; final holdout is excluded.',
        'contract': [
            'Train on the chronological first 60 percent, search on the next 20 percent; reserve the last 20 percent for a single independent final evaluation.',
            'A reported finite score is an untrusted candidate claim. Verify its population and evaluation implementation before accepting it.',
            'The target at decision time is strictly future. No field computed from the future interval can be a feature.',
            'Fit scalers and encoders only on training rows. Transform development rows using the same fitted objects.',
            'Generate out-of-fold training predictions for a learned ensemble; do not fit an ensemble on the development target.',
            'Preserve source identifiers, timestamp timezone, measurement units, and sorting rules. Reject duplicate input keys explicitly.',
            'Missing delivery dates make operational scoring unavailable. Software contract checks may still run, but are not operational results.',
            'Weight capacity is 500 kilograms per vehicle. There is no stop-count limit. Do not invent one to simplify the solver.',
            'Save the exact selected recipe and trained artifacts. Independent prediction must load them without redoing model selection.',
            'Return predictions in original input order, with exactly one finite numeric result per requested row. Reject unknown required fields.',
            'If a rule is unresolved, state its source and consequence. Do not silently promote assumptions into authoritative constraints.',
        ],
    }
    task = json.dumps(requirements, ensure_ascii=False, indent=2)
    code = '''import numpy as np
def predict(model, frame):
    features = frame.loc[:, model["features"]]
    if features.isna().any().any():
        raise ValueError("missing required input")
    return model["estimator"].predict(features)
def score(y_true, y_pred):
    actual = np.asarray(y_true, dtype=float)
    predicted = np.asarray(y_pred, dtype=float)
    if actual.shape != predicted.shape or not np.isfinite(predicted).all():
        raise ValueError("invalid prediction population")
    return float(np.abs(actual - predicted).mean())
'''
    schema = {'type':'object','properties':{'capacity_kg':{'type':'integer'},
              'stop_count_cap':{'type':'null'},'missing_dates_allow_business_score':{'type':'boolean'},
              'holdout_allowed_for_search':{'type':'boolean'}},
              'required':['capacity_kg','stop_count_cap','missing_dates_allow_business_score','holdout_allowed_for_search'],
              'additionalProperties':False}
    instruction = 'Read the authoritative task. Return its capacity, stop cap, missing-date scoring permission and search holdout permission using the required JSON schema.'
    rows=[]
    for role in ('code', 'result'):
        spec=FunctionSpec(name=role+'_review', description=role+' reviewer', json_schema=schema)
        old_user=task_section(task)+'\n# Implementation\n'+code
        rows.append((f'old_tools_{role}', {'messages':_build_messages(role+' review. '+instruction,old_user),
                      'tools':[spec.to_openai_tool_dict(strict=False)]}))
    for role in ('code', 'result'):
        spec=FunctionSpec(name=role+'_review', description=role+' reviewer', json_schema=schema)
        new_user=candidate_review_section(task,'',code)+'# Latest evidence\n'+role
        rows.append((f'new_json_{role}', {'messages':_build_json_mode_messages(role+' review. '+instruction,new_user,spec),
                      'response_format':{'type':'json_object'}}))
    dynamic={'repeat_authority':requirements,'instruction':instruction,'schema':schema}
    stable, compact=stable_dynamic_prompt(stable={'requirements':requirements},dynamic=dynamic)
    for name, tail in [('literal',json_block('Dynamic request',dynamic)),('references',compact)]:
        rows.append(('autorealize_'+name, {'messages':[{'role':'system','content':'Read all task evidence; return only the requested JSON object.'},
            {'role':'user','content':stable},{'role':'user','content':tail}], 'response_format':{'type':'json_object'}}))
    return rows, {'capacity_kg':500,'stop_count_cap':None,'missing_dates_allow_business_score':False,'holdout_allowed_for_search':False}


def run(output):
    key=os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise SystemExit('DEEPSEEK_API_KEY is required; no request sent')
    rows, expected=requests()
    estimated=sum(estimate_text_tokens(json.dumps(params,ensure_ascii=False)) for _,params in rows)
    if len(rows)>6 or estimated>12000:
        raise SystemExit('Probe input budget exceeded; no request sent')
    result={'model':'deepseek-flash','base_url':'https://api.deepseek.com',
            'synthetic_only':True,'max_requests':6,'max_output_tokens_per_call':768,
            'thinking':'disabled only for this transport probe; production settings unchanged',
            'estimated_total_input_tokens':estimated,'calls':[]}
    output.parent.mkdir(parents=True,exist_ok=True)
    with OpenAI(api_key=key,base_url=result['base_url'],max_retries=0,timeout=45) as client:
        for name,params in rows:
            started=time.monotonic()
            try:
                response=client.chat.completions.create(model=result['model'],max_tokens=768,
                    extra_body={'thinking':{'type':'disabled'}},**params)
                choice=response.choices[0]
                message=choice.message
                content=message.tool_calls[0].function.arguments if message.tool_calls else message.content
                record={'name':name,'seconds':round(time.monotonic()-started,3),
                        'usage':response.usage.model_dump() if response.usage else None,
                        'finish_reason':choice.finish_reason,'expected_answer_match':json.loads(content or '{}')==expected}
            except Exception as exc:
                # Do not serialize exceptions/HTTP requests, which may contain secrets.
                record={'name':name,'error_type':type(exc).__name__,
                        'status_code':getattr(exc,'status_code',None)}
            result['calls'].append(record)
            output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(record,ensure_ascii=False),flush=True)
            if 'error_type' in record:
                break
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',help='Explicitly authorize this bounded paid probe')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if not args.run:
        parser.error('--run is required to send paid requests')
    run(args.output)
