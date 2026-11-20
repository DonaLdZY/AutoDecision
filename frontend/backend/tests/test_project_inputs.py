import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from project_inputs import ProjectBinding, prepare_window


def binding(**overrides):
    source = dict(path='observations.csv', field='history', time_column='time', columns=['time','value'], window_seconds=3600)
    source.update(overrides)
    return ProjectBinding(sources=[source])


def test_latest_uses_true_maximum_and_never_future_or_lower_boundary(tmp_path):
    (tmp_path/'observations.csv').write_text('time,value\n2026-05-25 10:00:00,10\n2026-05-25 09:00:00,9\n2026-05-25 09:30:00,9.5\n', encoding='utf-8')
    result = prepare_window(tmp_path, binding(), 'latest')
    assert result['cutoff'] == '2026-05-25 10:00:00'
    assert [r['value'] for r in json.loads(result['data_json'])['history']] == [9.5,10]
    assert result['sources'][0]['rows'] == 2
    assert len(result['sources'][0]['sha256']) == 64
    earlier = prepare_window(tmp_path, binding(), '2026-05-25 09:30:00')
    assert [r['value'] for r in json.loads(earlier['data_json'])['history']] == [9,9.5]


def test_window_refuses_silent_row_truncation_and_bad_time(tmp_path):
    file = tmp_path/'observations.csv'
    file.write_text('time,value\n2026-05-25 09:20:00,1\n2026-05-25 09:30:00,2\n')
    with pytest.raises(HTTPException, match='') as exc:
        prepare_window(tmp_path, binding(max_rows=1), 'latest')
    assert exc.value.status_code == 413
    file.write_text('time,value\nbad,1\n2026-05-25 09:30:00,2\n')
    with pytest.raises(HTTPException) as exc:
        prepare_window(tmp_path, binding(), 'latest')
    assert exc.value.status_code == 422


def test_inclusive_boundary_is_explicit_and_keeps_future_excluded(tmp_path):
    (tmp_path/'observations.csv').write_text(
        'time,value\n2026-05-25 08:59:59,8\n2026-05-25 09:00:00,9\n'
        '2026-05-25 09:30:00,9.5\n2026-05-25 10:00:00,10\n2026-05-25 10:00:01,11\n',
        encoding='utf-8')
    result = prepare_window(tmp_path, binding(lower_bound='inclusive'), '2026-05-25 10:00:00')
    assert [r['value'] for r in json.loads(result['data_json'])['history']] == [9,9.5,10]
    source = result['sources'][0]
    assert source['lower_bound'] == 'inclusive'
    assert source['window_start_inclusive'] == '2026-05-25T09:00:00+08:00'
    assert 'window_start_exclusive' not in source
    assert binding().sources[0].lower_bound == 'exclusive'
    with pytest.raises(ValidationError):
        binding(lower_bound='approximate')


def test_binding_rejects_paths_and_overlapping_targets():
    for path in ['../secret.csv', '/secret.csv', 'C:\\secret.csv', 'model.pkl']:
        with pytest.raises(ValidationError):
            binding(path=path)
    with pytest.raises(ValidationError):
        binding(field='prediction_cutoff')
    with pytest.raises(ValidationError):
        binding(columns=['value'])


def test_no_rows_and_missing_columns_are_explicit(tmp_path):
    (tmp_path/'observations.csv').write_text('time,value\n2026-05-25 09:30:00,2\n')
    with pytest.raises(HTTPException) as exc:
        prepare_window(tmp_path, binding(), '2026-05-24 09:30:00')
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        prepare_window(tmp_path, binding(columns=['time','missing']), 'latest')
    assert exc.value.status_code == 422


def test_timezone_and_secondary_sources_share_cutoff(tmp_path):
    (tmp_path/'observations.csv').write_text('time,value\n2026-05-25T01:30:00Z,2\n')
    (tmp_path/'weather.csv').write_text('time,temp\n2026-05-25 09:00:00,20\n2026-05-25 10:00:00,30\n')
    b = binding()
    from project_inputs import WindowSource
    b.sources.append(WindowSource(path='weather.csv',field='weather',time_column='time',columns=['time','temp'],window_seconds=3600))
    result = prepare_window(tmp_path,b,'latest')
    data = json.loads(result['data_json'])
    assert result['cutoff'] == '2026-05-25 09:30:00'
    assert data['weather'] == [{'time':'2026-05-25 09:00:00','temp':20}]


def test_full_week_of_minute_observations_is_not_cut_at_ten_thousand(tmp_path):
    from datetime import datetime, timedelta
    start = datetime(2026, 5, 18)
    rows = [f'{start + timedelta(minutes=i)},{i}' for i in range(10081)]
    (tmp_path/'observations.csv').write_text('time,value\n'+'\n'.join(rows),encoding='utf-8')
    result = prepare_window(tmp_path,binding(window_seconds=7*86400),'latest')
    history = json.loads(result['data_json'])['history']
    assert len(history)==10080
    assert history[0]['value']==1 and history[-1]['value']==10080


def hourly_binding(**overrides):
    source = dict(path='trades.csv', field='history', time_column='time',
                  columns=['gate', 'time', 'plate'], window_seconds=86400,
                  aggregation={'entity_column': 'gate', 'distinct_column': 'plate'})
    source.update(overrides)
    return ProjectBinding(sources=[source], include_cutoff=False,
                          forecast={'source_field': 'history'})


def test_hourly_counts_deduplicate_across_chunks_and_target_next_hour(tmp_path):
    # Duplicated ID straddles pandas' 20000-row chunk boundary; no per-chunk nunique.
    rows = ['001,2025-07-28 09:01:00,same'] * 20001
    rows += ['001,2025-07-28 09:59:00,other', '002,2025-07-28 10:00:00,z',
             '001,2025-07-28 10:00:01,future']
    (tmp_path/'trades.csv').write_text('gate,time,plate\n'+'\n'.join(rows), encoding='utf-8')
    result = prepare_window(tmp_path, hourly_binding(), '2025-07-28 10:00:00')
    value = json.loads(result['data_json'])
    assert set(value) == {'history', 'target_pairs'}
    assert value['history'] == [
        {'gid': '001', 'hour': '2025-07-28 09:00:00', 'y': 2, 'txn': 20002},
        {'gid': '002', 'hour': '2025-07-28 10:00:00', 'y': 1, 'txn': 1}]
    assert value['target_pairs'] == [['001', '2025-07-28 11:00:00'], ['002', '2025-07-28 11:00:00']]
    assert result['sources'][0]['raw_rows'] == 20003
    assert result['sources'][0]['rows'] == 2
    assert result['cutoff'] == '2025-07-28 10:00:00'


def test_hourly_declared_date_format_and_latest_observation(tmp_path):
    (tmp_path/'trades.csv').write_text(
        'gate,time,plate\n001,02/11/2025 23:59:00,a\n001,01/11/2025 22:10:00,b\n', encoding='utf-8')
    result = prepare_window(tmp_path, hourly_binding(time_format='%m/%d/%Y %H:%M:%S'), 'latest')
    assert result['cutoff'] == '2025-02-11 23:59:00'
    value = json.loads(result['data_json'])
    assert value['target_pairs'] == [['001', '2025-02-12 00:00:00']]
    assert value['history'][0]['y'] == 1


def test_hourly_aggregation_refuses_missing_identifiers_and_limits(tmp_path):
    path = tmp_path/'trades.csv'
    path.write_text('gate,time,plate\n001,2025-07-28 09:00:00,\n', encoding='utf-8')
    with pytest.raises(HTTPException) as exc:
        prepare_window(tmp_path, hourly_binding(), 'latest')
    assert exc.value.status_code == 422
    path.write_text('gate,time,plate\n001,2025-07-28 09:00:00,a\n002,2025-07-28 09:00:00,b\n', encoding='utf-8')
    for limits in [{'max_source_rows': 1}, {'max_rows': 1}]:
        with pytest.raises(HTTPException) as exc:
            prepare_window(tmp_path, hourly_binding(**limits), 'latest')
        assert exc.value.status_code == 413


def test_hourly_binding_rejects_missing_columns_and_target_overwrites():
    with pytest.raises(ValidationError):
        hourly_binding(columns=['gate', 'time'])
    with pytest.raises(ValidationError):
        ProjectBinding(sources=[dict(path='trades.csv', field='history', time_column='time',
                       columns=['time'], window_seconds=3600)], forecast={'source_field': 'history'})
    with pytest.raises(ValidationError):
        ProjectBinding(**{**hourly_binding().model_dump(), 'forecast': {'source_field': 'history', 'target_field': 'history'}})
