from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Example(Strict):
    example_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    reference_sql: str = Field(min_length=1)
    schema_context: str = Field(min_length=1)
    sql_dialect: str = Field(min_length=1)
    business_rules: str = ''
    split: str = ''


class Response(Strict):
    sql: str = Field(min_length=1, max_length=100000)
    trace_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    app_revision: str | None = None


class Judgment(Strict):
    verdict: Literal['correct', 'incorrect', 'uncertain']
    failure_category: Literal['none', 'missing_filter', 'incorrect_join', 'aggregation', 'date_logic', 'null_handling', 'duplicates', 'ordering', 'other', 'insufficient_context']
    explanation: str = Field(min_length=1, max_length=4000)
    suggested_check: str = Field(max_length=2000)

    @property
    def score(self):
        return {'correct': 1, 'incorrect': 0, 'uncertain': None}[self.verdict]


class EvaluationParams(Strict):
    experiment_id: str = Field(min_length=1)
    evaluation_config_id: str | None = None
    new_evaluation_config: bool = False
    baseline_experiment_id: str | None = None
    baseline_evaluation_config_id: str | None = None

    @model_validator(mode='after')
    def config_selection(self):
        if self.new_evaluation_config and self.evaluation_config_id:
            raise ValueError('Choose a saved configuration OR a new one')
        return self


class RunParams(Strict):
    mode: Literal['new_experiment', 'evaluate_existing'] = 'new_experiment'
    dataset_version_id: str | None = None
    app_revision: str | None = None
    max_examples: int = Field(default=12, ge=1, le=100, strict=True)
    experiment_id: str | None = None
    evaluation_config_id: str | None = None
    new_evaluation_config: bool = False
    baseline_experiment_id: str | None = None
    baseline_evaluation_config_id: str | None = None

    @model_validator(mode='after')
    def identity(self):
        if self.mode == 'new_experiment' and (not self.dataset_version_id or not self.app_revision):
            raise ValueError('New experiments require dataset_version_id and app_revision')
        if self.mode == 'evaluate_existing':
            if not self.experiment_id:
                raise ValueError('experiment_id is required')
            if self.dataset_version_id or self.app_revision or self.max_examples != 12:
                raise ValueError('Re-evaluation uses saved identities, not new selection parameters')
            if self.new_evaluation_config and self.evaluation_config_id:
                raise ValueError('Choose a saved configuration OR a new one')
        return self
