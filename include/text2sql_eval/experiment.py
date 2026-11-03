"""Generate durable Phoenix experiment outputs through the separately hosted API."""
from datetime import datetime, timezone
from .config import digest, normalize, snapshot
from .models import EvaluationParams
from pydantic import Field, model_validator


class ExperimentParams(EvaluationParams):
    experiment_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    max_examples: int | None = Field(default=None, ge=1, le=1024, strict=True)

    @model_validator(mode='after')
    def selection(self):
        if self.experiment_id:
            if self.dataset_id or self.dataset_version_id or self.max_examples is not None:
                raise ValueError('Saved-output evaluation cannot select a new dataset or sample')
        elif not self.dataset_id or not self.dataset_version_id:
            raise ValueError('New experiments require dataset_id and dataset_version_id')
        elif self.evaluation_config_id:
            raise ValueError('New experiments snapshot the configured judge settings')
        return self


def prepare_experiment(store, params, identity, rubric_loader, model_loader):
    from .workflow import prepare_evaluation
    p = ExperimentParams.model_validate(params)
    if p.experiment_id:
        return prepare_evaluation(store, {k: getattr(p, k) for k in EvaluationParams.model_fields},
                                  identity, rubric_loader, model_loader)
    key = digest(identity)
    recovered = store.find(p.dataset_id, key)
    if recovered:
        m = store.manifest(recovered)
        if m['dataset_version_id'] != p.dataset_version_id or m.get('max_examples') != p.max_examples:
            raise ValueError('Run identity already belongs to a different dataset selection')
        return {'manifest_id': recovered, 'experiment_id': recovered}
    examples = normalize(store.dataset(p.dataset_id, p.dataset_version_id))
    if p.max_examples is not None:
        examples = examples[:p.max_examples]
    if len(examples) > 1024:
        raise ValueError('Dataset exceeds the 1024 mapped-task limit; set max_examples')
    manifest = dict(dataset_id=p.dataset_id, dataset_version_id=p.dataset_version_id,
                    examples=examples, selected_example_ids=[e['example_id'] for e in examples],
                    config=snapshot(rubric_loader(), model_loader(), examples),
                    mode='new_experiment', run_key=key, repetition=1, app_revision=None,
                    max_examples=p.max_examples, baseline_experiment_id=p.baseline_experiment_id,
                    baseline_evaluation_config_id=p.baseline_evaluation_config_id)
    eid = store.create(manifest)
    return {'manifest_id': eid, 'experiment_id': eid}


def experiment_refs(store, ref):
    m = store.manifest(ref['manifest_id'])
    if m.get('mode') != 'new_experiment':
        return []
    return [{**ref, 'example_id': eid} for eid in m['selected_example_ids']]


def run_example(store, ref, caller):
    m = store.manifest(ref['manifest_id'])
    if m.get('mode') != 'new_experiment':
        raise ValueError('Cannot generate outputs during re-evaluation')
    example = next(e for e in m['examples'] if e['example_id'] == ref['example_id'])
    runs, _ = store.records(ref['experiment_id'])
    # Persisted failures remain failures; clearing tasks must not silently rerun the app.
    if any(r['dataset_example_id'] == ref['example_id'] for r in runs):
        return
    start = datetime.now(timezone.utc)
    output = caller(ref['experiment_id'], {'example_id': example['example_id'], 'question': example['question']})
    store.save_run(ref['experiment_id'], example['example_id'], output, start, datetime.now(timezone.utc))
