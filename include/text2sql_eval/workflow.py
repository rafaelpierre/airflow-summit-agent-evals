"""Evaluate saved Phoenix outputs. This module never executes the application."""
from .config import normalize, snapshot, digest
from .models import EvaluationParams
from .phoenix_adapter import annotation_name


def prepare_evaluation(store, params, run_identity, rubric_loader, model_loader):
    p = EvaluationParams.model_validate(params)
    source = store.manifest(p.experiment_id)
    if source.get("source_experiment_id"):
        raise ValueError("Select an output experiment, not an evaluation ledger")
    run_key = digest(run_identity)
    recovered = store.find(source["dataset_id"], run_key)
    if recovered:
        saved = store.manifest(recovered)
        if saved.get("source_experiment_id") != p.experiment_id:
            raise ValueError("Run identity already belongs to another experiment")
        return {"manifest_id": recovered, "experiment_id": p.experiment_id}
    # Fetch the exact golden version; never reselect by question or position.
    golden = normalize(store.dataset(source["dataset_id"], source["dataset_version_id"]))
    by_id = {e["example_id"]: e for e in golden}
    selected = source["selected_example_ids"]
    if not selected or len(set(selected)) != len(selected) or any(i not in by_id for i in selected):
        raise ValueError("Invalid saved example identities")
    examples = [by_id[i] for i in sorted(selected)]
    if examples != sorted(source["examples"], key=lambda e: e["example_id"]):
        raise ValueError("Saved context differs from pinned golden dataset")
    configs = store.configurations(p.experiment_id)
    if p.new_evaluation_config or (not configs and not p.evaluation_config_id):
        config = snapshot(rubric_loader(), model_loader(), examples)
    else:
        config = store.select_config(p.experiment_id, p.evaluation_config_id)
    m = {**source, "source_experiment_id": p.experiment_id, "mode": "evaluate_existing",
         "run_key": run_key, "config": config, "examples": examples,
         "selected_example_ids": [e["example_id"] for e in examples],
         "baseline_experiment_id": p.baseline_experiment_id,
         "baseline_evaluation_config_id": p.baseline_evaluation_config_id}
    ledger = store.create(m)
    return {"manifest_id": ledger, "experiment_id": p.experiment_id}


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
