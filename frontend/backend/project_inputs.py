"""Bounded, declared project data bindings for frozen inference packages.

No generated code or inference runs during input preparation. The persisted
snapshot, not a later reread of a changing source, is passed to the model.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from local_product import safe_file, MAX_TRIAL_INPUT_BYTES

MAX_INPUT_BYTES = MAX_TRIAL_INPUT_BYTES


class HourlyCounts(BaseModel):
    """Declared entity/hour aggregation, without running package or generated code."""
    model_config = ConfigDict(extra='forbid')
    entity_column: str = Field(min_length=1, max_length=300)
    distinct_column: str = Field(min_length=1, max_length=300)
    entity_field: str = 'gid'
    time_field: str = 'hour'
    count_field: str = 'y'
    rows_field: str = 'txn'

    @model_validator(mode='after')
    def check(self):
        fields = [self.entity_field, self.time_field, self.count_field, self.rows_field]
        if any(not name or len(name) > 120 for name in fields) or len(set(fields)) != len(fields):
            raise ValueError('聚合输出字段须非空且唯一')
        return self


class ForecastTargets(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_field: str = Field(min_length=1, max_length=120)
    target_field: str = Field(default='target_pairs', min_length=1, max_length=120)


class WindowSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=1000)
    field: str = Field(min_length=1, max_length=120)
    time_column: str = Field(min_length=1, max_length=300)
    columns: list[str] = Field(min_length=1, max_length=512)
    window_seconds: int = Field(ge=60, le=7 * 86400)
    lower_bound: Literal['exclusive', 'inclusive'] = 'exclusive'
    # Seven days of minute-level observations contain 10080 rows.
    max_rows: int = Field(default=20000, ge=1, le=20000)
    encoding: Literal['utf-8-sig', 'utf-8', 'gb18030'] = 'utf-8-sig'
    time_format: str | None = Field(default=None, max_length=100)
    aggregation: HourlyCounts | None = None
    max_source_rows: int = Field(default=500000, ge=1, le=1000000)

    @model_validator(mode='after')
    def check(self):
        path = Path(self.path)
        if path.is_absolute() or path.root or path.drive or '..' in path.parts or path.suffix.lower() != '.csv':
            raise ValueError('数据源须为项目内的相对 CSV 路径')
        if self.time_column not in self.columns or len(set(self.columns)) != len(self.columns):
            raise ValueError('输入列须唯一，且包含时间列')
        if self.aggregation and not {self.aggregation.entity_column, self.aggregation.distinct_column}.issubset(self.columns):
            raise ValueError('聚合须声明实体列和去重列')
        return self


class ProjectBinding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['time_window'] = 'time_window'
    cutoff_field: str = Field(default='prediction_cutoff', min_length=1, max_length=120)
    timezone: str = 'Asia/Shanghai'
    sources: list[WindowSource] = Field(min_length=1, max_length=4)
    include_cutoff: bool = True
    forecast: ForecastTargets | None = None

    @model_validator(mode='after')
    def check(self):
        fields = [self.cutoff_field, *(s.field for s in self.sources)]
        if len(set(fields)) != len(fields):
            raise ValueError('数据源目标字段不可重复或覆盖截止时间')
        if self.forecast:
            source = next((s for s in self.sources if s.field == self.forecast.source_field), None)
            if not source or not source.aggregation or self.forecast.target_field in fields:
                raise ValueError('下一小时目标须引用已声明的小时聚合，且不得覆盖其他字段')
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('无效的数据时区')
        return self


class PrepareInput(BaseModel):
    cutoff: str = Field(default='latest', min_length=1, max_length=100)


def _signature(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def prepare_window(root, binding: ProjectBinding, cutoff: str):
    import pandas as pd

    root = Path(root).resolve()
    value, provenance = {}, []
    selected_time = None

    def times(series, time_format=None):
        result = pd.to_datetime(series, errors='coerce', format=time_format or 'mixed')
        if result.isna().any():
            raise HTTPException(422, '数据源含无法解析的时间，不能静默丢弃记录')
        try:
            return result.dt.tz_localize(binding.timezone) if result.dt.tz is None else result.dt.tz_convert(binding.timezone)
        except (AttributeError, TypeError, ValueError):
            raise HTTPException(422, '数据源时间格式或时区不一致')

    try:
        if cutoff != 'latest':
            selected_time = pd.Timestamp(cutoff)
            if pd.isna(selected_time):
                raise ValueError('empty cutoff')
            selected_time = selected_time.tz_localize(binding.timezone) if selected_time.tzinfo is None else selected_time.tz_convert(binding.timezone)
        for source in binding.sources:
            path = safe_file(root, root / source.path)
            before = _signature(path)
            if before[0] > 512 * 1024**2:
                raise HTTPException(413, '时间窗数据源超过512MiB，请先生成较小的数据包')
            with path.open('rb') as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            if selected_time is None:
                for chunk in pd.read_csv(path, encoding=source.encoding, usecols=[source.time_column], chunksize=20000):
                    maximum = times(chunk[source.time_column], source.time_format).max()
                    if not pd.isna(maximum):
                        selected_time = maximum if selected_time is None else max(selected_time, maximum)
                if selected_time is None:
                    raise HTTPException(422, '数据源没有有效观测时间')
            start = selected_time - pd.Timedelta(seconds=source.window_seconds)
            frames, count, total_rows = [], 0, 0
            string_columns = ({source.aggregation.entity_column: 'string', source.aggregation.distinct_column: 'string'}
                              if source.aggregation else None)
            for chunk in pd.read_csv(path, encoding=source.encoding, usecols=source.columns, dtype=string_columns, chunksize=20000):
                time_values = times(chunk[source.time_column], source.time_format)
                total_rows += len(chunk)
                if total_rows > 3_000_000:
                    raise HTTPException(413, '数据源超过300万行，请先缩小数据包')
                after_start = time_values >= start if source.lower_bound == 'inclusive' else time_values > start
                selected = chunk.loc[after_start & (time_values <= selected_time), source.columns].copy()
                count += len(selected)
                if count > (source.max_source_rows if source.aggregation else source.max_rows):
                    raise HTTPException(413, '时间窗行数超过合同上限，未截断数据；请缩小窗口或重新发布合同')
                if len(selected):
                    selected[source.time_column] = time_values.loc[selected.index].dt.tz_localize(None).map(lambda x: x.isoformat(sep=' '))
                    frames.append(selected)
            if _signature(path) != before:
                raise HTTPException(409, '数据源在读取过程中发生变化，请重新准备输入')
            if not frames:
                raise HTTPException(422, f'数据源 {source.path} 在截止时间前的指定窗口内没有记录')
            frame = pd.concat(frames, ignore_index=True).sort_values(source.time_column, kind='stable')
            first_observation, last_observation = str(frame.iloc[0][source.time_column]), str(frame.iloc[-1][source.time_column])
            if source.aggregation:
                agg = source.aggregation
                if frame[[agg.entity_column, agg.distinct_column]].isna().any().any() or (
                        frame[[agg.entity_column, agg.distinct_column]] == '').any().any():
                    raise HTTPException(422, '聚合实体或去重标识缺失，不能静默忽略记录')
                # Aggregate after concatenating chunks, so repeated identifiers
                # across a chunk boundary count only once per entity/hour.
                frame[source.time_column] = pd.to_datetime(frame[source.time_column]).dt.floor('h')
                frame = (frame.groupby([agg.entity_column, source.time_column], sort=True)[agg.distinct_column]
                         .agg(['nunique', 'size']).reset_index()
                         .rename(columns={agg.entity_column: agg.entity_field, source.time_column: agg.time_field,
                                          'nunique': agg.count_field, 'size': agg.rows_field}))
                frame[agg.time_field] = frame[agg.time_field].map(lambda value: value.isoformat(sep=' '))
                if len(frame) > source.max_rows:
                    raise HTTPException(413, '聚合后行数超过合同上限，未截断数据')
            value[source.field] = json.loads(frame.to_json(orient='records', force_ascii=False))
            provenance.append({'path': source.path, 'sha256': checksum, 'source_bytes': before[0],
                'field': source.field, 'rows': len(frame), 'raw_rows': count, 'columns': source.columns, 'source_rows_scanned': total_rows,
                **({'aggregation': source.aggregation.model_dump()} if source.aggregation else {}),
                ('window_start_inclusive' if source.lower_bound == 'inclusive' else 'window_start_exclusive'): start.isoformat(),
                'lower_bound': source.lower_bound, 'window_end_inclusive': selected_time.isoformat(),
                'first_observation': first_observation, 'last_observation': last_observation})
            if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_INPUT_BYTES:
                raise HTTPException(413, '准备的输入超过16MiB，未截断数据；请核对模型所需窗口及输入列')
        cutoff_text = selected_time.tz_localize(None).isoformat(sep=' ')
        if binding.include_cutoff:
            value[binding.cutoff_field] = cutoff_text
        if binding.forecast:
            source = next(s for s in binding.sources if s.field == binding.forecast.source_field)
            entities = sorted({row[source.aggregation.entity_field] for row in value[source.field]})
            target_hour = (selected_time.floor('h') + pd.Timedelta(hours=1)).tz_localize(None).isoformat(sep=' ')
            value[binding.forecast.target_field] = [[entity, target_hour] for entity in entities]
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(raw.encode()) > MAX_INPUT_BYTES:
            raise HTTPException(413, '准备的输入超过16MiB，未截断数据')
        return {'data_json': raw, 'input_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'cutoff': cutoff_text, 'timezone': binding.timezone,
            'cutoff_mode': 'latest_observation' if cutoff == 'latest' else 'specified', 'sources': provenance}
    except HTTPException:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, '项目输入准备失败，请核对文件、完整列名、时间格式与编码') from exc
