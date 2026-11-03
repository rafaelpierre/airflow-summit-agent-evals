"""Public Phoenix client API boundary. No shared worker files or direct SQLite access."""
import os
from dataclasses import asdict
from phoenix.client import Client
from .config import digest, normalize
from .models import Response


def annotation_name(config_id):
    return 'sql_semantic_correctness_v1_' + config_id


class PhoenixStore:
    def __init__(self, client=None):
        self.client = client or Client(base_url=os.environ['PHOENIX_BASE_URL'], api_key=os.getenv('PHOENIX_API_KEY') or None)

    def dataset(self, dataset_id, version_id):
        dataset = self.client.datasets.get_dataset(dataset=dataset_id, version_id=version_id, timeout=30)
        if dataset.version_id != version_id:
            raise ValueError('Phoenix returned an unexpected dataset version')
        return dataset.examples

    def manifest(self, experiment_id):
        exp = self.client.experiments.get(experiment_id=experiment_id)
        metadata = exp.get('metadata') or {}
        if exp.get('repetitions', 1) != 1:
            raise ValueError('The workshop supports one repetition per example')
        if 'text2sql' in metadata:
            return metadata['text2sql']
        # Native Phoenix experiments are also accepted. A subset must declare its
        # expected IDs so absent application runs cannot disappear from reports.
        examples = normalize(self.dataset(exp['dataset_id'], exp['dataset_version_id']))
        selected = metadata.get('selected_example_ids')
        if selected is None:
            if exp['example_count'] != len(examples):
                raise ValueError('Subset experiments require selected_example_ids metadata')
            selected = [e['example_id'] for e in examples]
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= {e['example_id'] for e in examples}:
            raise ValueError('Invalid selected example IDs')
        return {'dataset_id': exp['dataset_id'], 'dataset_version_id': exp['dataset_version_id'],
                'app_revision': metadata.get('app_revision'), 'selected_example_ids': sorted(selected),
                'examples': [e for e in examples if e['example_id'] in selected], 'repetition': 1}

    def find(self, dataset_id, run_key):
        matches = [e for e in self.client.experiments.list(dataset_id=dataset_id)
                   if e.get('metadata', {}).get('text2sql', {}).get('run_key') == run_key]
        if len(matches) > 1:
            raise ValueError('Ambiguous recovery: multiple manifests for run identity')
        return matches[0]['id'] if matches else None

    def create(self, manifest):
        exp = self.client.experiments.create(dataset_id=manifest['dataset_id'],
            dataset_version_id=manifest['dataset_version_id'], experiment_name='text2sql-' + manifest['run_key'][:16],
            experiment_metadata={'text2sql': manifest}, repetitions=1)
        return exp['id']

    def records(self, experiment_id):
        exp = self.client.experiments.get_experiment(experiment_id=experiment_id)
        runs = []
        identities = set()
        for run in exp['task_runs']:
            identity = (run['dataset_example_id'], run['repetition_number'])
            if identity in identities or run['repetition_number'] != 1:
                raise ValueError('Expected unique example identities with one repetition')
            identities.add(identity)
            output = run.get('output')
            if run.get('error') or (isinstance(output, dict) and output.get('status', 'ok') != 'ok'):
                output = {'status': 'api_error', 'error': 'application_failure'}
            else:
                try:
                    data = {'sql': output} if isinstance(output, str) else output
                    if not isinstance(data, dict):
                        raise ValueError('Missing SQL')
                    result = Response.model_validate({k: data[k] for k in Response.model_fields if k in data}).model_dump()
                    output = {**result, 'status': 'ok', 'latency_origin': data.get('latency_origin')}
                except ValueError:
                    output = {'status': 'api_error', 'error': 'malformed_response'}
            runs.append({**run, 'output': output, 'error': 'application_failure' if run.get('error') else None})
        return runs, [asdict(e) for e in exp['evaluation_runs']]

    def save_run(self, experiment_id, example_id, output, start, end):
        return self.client.experiments.log_run(experiment_id=experiment_id, dataset_example_id=example_id,
            output=output, start_time=start, end_time=end, repetition_number=1,
            trace_id=output.get('trace_id'), error=output.get('error') if output['status'] != 'ok' else None)

    def save_evaluation(self, run_id, config_id, config, result):
        from .models import Judgment
        judgment = Judgment.model_validate(result['judgment']) if result.get('judgment') else None
        return self.client.experiments.log_evaluation(experiment_run_id=run_id,
            name=annotation_name(config_id), annotator_kind='LLM',
            score=judgment.score if judgment else None,
            # Client 3.6.0 drops error-only annotations when all result fields are
            # null. A label preserves the failure on round-trip without a score.
            label=judgment.verdict if judgment else 'evaluator_error',
            explanation=judgment.explanation if judgment else None,
            error=result.get('error'), metadata={'config_id': config_id, 'config': config,
                'actual_model': result.get('actual_model'), 'judgment': judgment.model_dump() if judgment else None})

    def configurations(self, experiment_id):
        manifest = self.manifest(experiment_id)
        configs = {digest(manifest['config']): manifest['config']} if manifest.get('config') else {}
        for exp in self.client.experiments.list(dataset_id=manifest['dataset_id']):
            m = exp.get('metadata', {}).get('text2sql', {})
            if m.get('source_experiment_id') == experiment_id:
                configs[digest(m['config'])] = m['config']
        return configs

    def select_config(self, experiment_id, config_id=None):
        configs = self.configurations(experiment_id)
        if config_id is None:
            if len(configs) != 1:
                raise ValueError('Multiple configurations exist; supply evaluation_config_id')
            config_id = next(iter(configs))
        if config_id not in configs:
            raise ValueError('Unknown evaluation configuration')
        return configs[config_id]
