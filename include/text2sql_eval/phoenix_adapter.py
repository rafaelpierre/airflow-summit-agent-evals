"""Public Phoenix client API boundary. No shared worker files or direct SQLite access."""
import os
from dataclasses import asdict
from phoenix.client import Client
from .config import digest


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
        return self.client.experiments.get(experiment_id=experiment_id)['metadata']['text2sql']

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
        return exp['task_runs'], [asdict(e) for e in exp['evaluation_runs']]

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
            label=judgment.verdict if judgment else None,
            explanation=judgment.explanation if judgment else None,
            error=result.get('error'), metadata={'config_id': config_id, 'config': config,
                'actual_model': result.get('actual_model'), 'judgment': judgment.model_dump() if judgment else None})

    def configurations(self, experiment_id):
        manifest = self.manifest(experiment_id)
        configs = {digest(manifest['config']): manifest['config']}
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
