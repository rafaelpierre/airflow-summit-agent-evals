import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .config import digest
from .phoenix_adapter import annotation_name


def build_report(store, experiment_id, config_id=None, baseline_id=None, baseline_config_id=None):
    m = store.manifest(experiment_id)
    config = store.select_config(experiment_id, config_id)
    config_id = digest(config)
    runs, evaluations = store.records(experiment_id)
    by_example = {}
    for run in runs:
        key = (run['dataset_example_id'], run['repetition_number'])
        if key in by_example:
            raise ValueError('Duplicate experiment run identity')
        by_example[key] = run
    annotations = {e['experiment_run_id']: e for e in evaluations if e['name'] == annotation_name(config_id)}
    rows = []
    for example in m['examples']:
        run = by_example.get((example['example_id'], 1))
        evaluation = annotations.get(run['id']) if run else None
        status = 'missing_run'
        if run:
            status = 'api_error' if run.get('error') or run['output'].get('status') != 'ok' else 'missing_evaluation'
        if status == 'missing_evaluation' and evaluation:
            status = 'evaluator_error' if evaluation.get('error') else evaluation['result']['label']
        rows.append({**example, 'run_id': run['id'] if run else None, 'repetition': 1,
                     'status': status, 'output': run.get('output') or {} if run else {},
                     'evaluation': evaluation.get('metadata', {}).get('judgment') or {} if evaluation else {}})
    counts = {s: sum(r['status'] == s for r in rows) for s in
              ['correct', 'incorrect', 'uncertain', 'api_error', 'evaluator_error', 'missing_run', 'missing_evaluation']}
    judged = sum(counts[s] for s in ['correct', 'incorrect', 'uncertain'])
    denominator = counts['correct'] + counts['incorrect']
    summary = dict(experiment_id=experiment_id, dataset_id=m['dataset_id'], dataset_version_id=m['dataset_version_id'],
        app_revision=m['app_revision'], evaluation_config_id=config_id, config=config,
        selected_example_ids=m['selected_example_ids'], expected=len(rows), judged=judged,
        completed_application_runs=len(rows) - counts['missing_run'] - counts['api_error'],
        coverage=judged / len(rows) if rows else 0,
        pass_rate=counts['correct'] / denominator if denominator else None, pass_rate_denominator=denominator,
        counts=counts, complete=bool(rows) and judged == len(rows))
    if baseline_id:
        baseline = build_report(store, baseline_id, baseline_config_id)
        keys = ['dataset_id', 'dataset_version_id', 'evaluation_config_id', 'selected_example_ids']
        compatible = all(summary[k] == baseline['summary'][k] for k in keys)
        comparison = {'compatible': compatible, 'reason': None if compatible else 'Dataset, context, judge, or selected identities differ'}
        if compatible:
            old = {(r['example_id'], r['repetition']): r for r in baseline['rows']}
            pairs = []
            for row in rows:
                prior = old[(row['example_id'], row['repetition'])]['status']
                current = row['status']
                change = 'not_comparable'
                if prior in ('correct', 'incorrect') and current in ('correct', 'incorrect'):
                    change = 'unchanged' if prior == current else ('improved' if current == 'correct' else 'regressed')
                pairs.append({'example_id': row['example_id'], 'baseline': prior, 'candidate': current, 'change': change})
            comparison['examples'] = pairs
        summary['comparison'] = comparison
    failures = {'experiment_id': experiment_id, 'dataset_id': m['dataset_id'], 'dataset_version_id': m['dataset_version_id'],
                'evaluation_config_id': config_id, 'app_revision': m['app_revision'],
                'examples': [r for r in rows if r['status'] != 'correct' and r['split'] != 'holdout']}
    return {'summary': summary, 'rows': rows, 'failures': failures}


def render(report):
    env = Environment(loader=FileSystemLoader(Path(__file__).parent.parent / 'templates'),
                      autoescape=select_autoescape(default=True))
    return env.get_template('evaluation_report.html.j2').render(**report)


def export(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'report.html').write_text(render(report))
    for name in ['summary', 'failures']:
        (directory / f'{name}.json').write_text(json.dumps(report[name], sort_keys=True, indent=2, ensure_ascii=False) + '\n')
