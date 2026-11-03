import os
from datetime import datetime, timezone
from .config import normalize, snapshot, digest
from .models import RunParams
from .agent_api import call_agent
from .phoenix_adapter import annotation_name


def prepare(store, params, run_identity, rubric_loader, model, dataset_id=None, fields=None, shared=None):
    p = RunParams.model_validate(params)
    source = store.manifest(p.experiment_id) if p.mode == 'evaluate_existing' else None
    dataset_id = source['dataset_id'] if source else dataset_id
    if not dataset_id:
        raise ValueError('PHOENIX_DATASET_ID is required')
    run_key = digest(run_identity)
    recovered = store.find(dataset_id, run_key)
    if recovered:
        m = store.manifest(recovered)
        return {'manifest_id': recovered, 'experiment_id': m.get('source_experiment_id') or recovered}
    if source:
        examples = source['examples']
        config = (snapshot(rubric_loader(), model, examples) if p.new_evaluation_config
                  else store.select_config(p.experiment_id, p.evaluation_config_id))
        m = {**source, 'source_experiment_id': p.experiment_id, 'config': config}
    else:
        examples = normalize(store.dataset(dataset_id, p.dataset_version_id), fields, shared)[:p.max_examples]
        m = {'dataset_id': dataset_id, 'dataset_version_id': p.dataset_version_id, 'examples': examples,
             'app_revision': p.app_revision, 'config': snapshot(rubric_loader(), model, examples)}
    m.update(run_key=run_key, mode=p.mode, baseline_experiment_id=p.baseline_experiment_id,
             baseline_evaluation_config_id=p.baseline_evaluation_config_id,
             selected_example_ids=[e['example_id'] for e in examples], repetition=1)
    ledger = store.create(m)
    return {'manifest_id': ledger, 'experiment_id': p.experiment_id or ledger}


def execute_application(store, ref, caller=call_agent):
    m = store.manifest(ref['manifest_id'])
    if m['mode'] == 'evaluate_existing':
        return ref
    runs, _ = store.records(ref['experiment_id'])
    complete = {r['dataset_example_id'] for r in runs if not r.get('error') and r['output'].get('status') == 'ok'}
    for example in m['examples']:
        if example['example_id'] in complete:
            continue
        start = datetime.now(timezone.utc)
        output = caller(ref['experiment_id'], example, m['app_revision'])
        store.save_run(ref['experiment_id'], example['example_id'], output, start, datetime.now(timezone.utc))
    return ref


def judge_refs(store, ref):
    m = store.manifest(ref['manifest_id'])
    runs, evaluations = store.records(ref['experiment_id'])
    name = annotation_name(digest(m['config']))
    done = {e['experiment_run_id'] for e in evaluations if e['name'] == name and not e.get('error')}
    selected = set(m['selected_example_ids'])
    return [{**ref, 'run_id': r['id']} for r in runs if r['dataset_example_id'] in selected
            and r['repetition_number'] == 1 and not r.get('error') and r['output'].get('status') == 'ok'
            and r['id'] not in done]


def judge_input(store, ref):
    m = store.manifest(ref['manifest_id'])
    runs, _ = store.records(ref['experiment_id'])
    run = next(r for r in runs if r['id'] == ref['run_id'])
    example = next(e for e in m['examples'] if e['example_id'] == run['dataset_example_id'])
    if run.get('error') or run['output'].get('status') != 'ok':
        raise ValueError('Cannot judge an API failure')
    return m['config'], {**example, 'candidate_sql': run['output']['sql']}


def persist(store, envelope):
    ref = envelope['ref']
    config, _ = judge_input(store, ref)  # Verify run belongs to the selected experiment/example set.
    store.save_evaluation(ref['run_id'], digest(config), config, envelope)
    return ref['run_id']
