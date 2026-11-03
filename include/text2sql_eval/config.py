import hashlib
import json
from pydantic import Field
from .models import Strict, Example


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Rubric(Strict):
    rubric_version: str = Field(min_length=1)
    rubric: str = Field(min_length=1)
    temperature: float = Field(default=0, ge=0, le=2)


def snapshot(rubric, model, examples):
    if not model or ':' in model:
        raise ValueError('text2sql_judge_model must be an explicit OpenAI model identifier, not a provider prefix')
    return dict(rubric=Rubric.model_validate(rubric).model_dump(), model=model,
                evaluator_version='2', output_schema_version='1', model_api='openai-chat',
                context=[{k: e[k] for k in ('example_id', 'schema_context', 'sql_dialect', 'business_rules')} for e in examples])


DEFAULT_FIELDS = {'question': 'input.question', 'reference_sql': 'output.sql',
                  'schema_context': 'metadata.schema_context', 'sql_dialect': 'metadata.sql_dialect',
                  'business_rules': 'metadata.business_rules', 'split': 'metadata.split'}


def normalize(raw, fields=None, shared=None):
    fields = {**DEFAULT_FIELDS, **(fields or {})}
    shared = shared or {}
    records = []
    for item in raw:
        data = {'example_id': item['id']}
        for key, path in fields.items():
            value = item
            for part in path.split('.'):
                value = value.get(part) if isinstance(value, dict) else None
            if value is not None:
                data[key] = value
            elif key in shared:
                data[key] = shared[key]
        records.append(Example.model_validate(data).model_dump())
    if not records or len({e['example_id'] for e in records}) != len(records):
        raise ValueError('Dataset must be nonempty with unique example IDs')
    return sorted(records, key=lambda e: e['example_id'])
