#!/usr/bin/env python3
"""Import user-supplied normalized JSON examples. Never manufacture golden answers."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from include.text2sql_eval.models import Example
from include.text2sql_eval.phoenix_adapter import PhoenixStore


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--name', required=True)
    p.add_argument('--file', required=True, help='JSON array of normalized Example records')
    p.add_argument('--record', default='outputs/dataset-import.json')
    a = p.parse_args()
    examples = [Example.model_validate(e) for e in json.loads(Path(a.file).read_text())]
    if not examples or len({e.example_id for e in examples}) != len(examples):
        raise ValueError('Examples must be nonempty and uniquely identified')
    client = PhoenixStore().client
    matches = [d for d in client.datasets.list() if d['name'] == a.name]
    if len(matches) > 1:
        raise ValueError('Ambiguous dataset name')
    if matches:
        dataset = client.datasets.get_dataset(dataset=matches[0]['id'])
    else:
        dataset = client.datasets.create_dataset(name=a.name,
            inputs=[{'question': e.question} for e in examples],
            outputs=[{'sql': e.reference_sql} for e in examples],
            metadata=[{**e.model_dump(exclude={'question', 'reference_sql', 'example_id'}), 'source_example_id': e.example_id} for e in examples])
    record = {'dataset_id': dataset.id, 'dataset_version_id': dataset.version_id,
              'example_ids': [e['id'] for e in dataset.examples], 'reused_existing': bool(matches)}
    path = Path(a.record); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
