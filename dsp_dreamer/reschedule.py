"""Create a v4 derivative from verified v3 facts, preserving original evidence."""
from pathlib import Path
import copy
import shutil
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

from .archive import capacity_preflight
from .contract import atomic_save, file_info, load, require, save
from .dataset import Dataset, open_dataset, table_contract
from .progress import reschedule_rows


def reschedule_dataset(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    require(source != destination and source not in destination.parents and destination not in source.parents,
            'Schedule source and destination must not overlap')
    require(not destination.exists(), 'Refusing schedule derivative overwrite')
    dataset = open_dataset(source)
    require(dataset.metadata['progress_version'] == 3, 'Rescheduling requires progress v3 source')
    before = file_info(source / 'COMPLETED')
    completed = load(source / 'COMPLETED')
    require(reschedule_rows(dataset.rows, 3) == dataset.rows, 'Legacy schedule differs from node facts')
    rows = reschedule_rows(dataset.rows, 4)
    capacity_preflight(destination, sum(info['bytes'] for info in completed['files'].values()), copies=1)
    destination.mkdir(parents=True)
    for name in completed['files']:
        if name in ('dataset.json', 'transitions.parquet'):
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        require(file_info(target) == completed['files'][name], 'Copied source changed')
    pq.write_table(pa.Table.from_pylist(rows), destination / 'transitions.parquet', compression='zstd', row_group_size=1024)
    metadata = copy.deepcopy(dataset.metadata)
    metadata.update(artifact_id=str(uuid.uuid4()), progress_version=4,
        rescheduled_from=dict(artifact_id=dataset.metadata['artifact_id'], completed=before, progress_version=3,
                              method='unchanged node facts; v4 priority; raw events retain v3 claims'))
    metadata['tables']['transitions.parquet'] = table_contract(destination / 'transitions.parquet')
    save(destination / 'dataset.json', metadata)
    files = {p.relative_to(destination).as_posix(): file_info(p) for p in destination.rglob('*') if p.is_file()}
    result = dict(schema='dsp-completed/1', files=files)
    Dataset(destination, _completed=result)
    require(file_info(source / 'COMPLETED') == before, 'Source changed during rescheduling')
    atomic_save(destination / 'COMPLETED', result)
    return destination
