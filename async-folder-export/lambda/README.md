# Async export Lambda handlers (reference)

These are **reference implementations** aligned with [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md). Deploy with SAM ([../sam/template.yaml](../sam/template.yaml)) or repackage into your language of choice (Java) as long as behavior matches.

| Function                 | Trigger        | Role |
|--------------------------|----------------|------|
| `export_update_handler`  | DynamoDB stream| Terminal `status` → publish versioned JSON + attributes to SNS |
| `export_revision_logger` | SQS            | Parse SNS-wrapped body → `POST` Monolith revision endpoint |

## Environment variables

See module docstrings in each `handler.py`.

## Local sanity check

```bash
cd export_update_handler && python -c "import handler; print('ok')"
```

Monolith URL and auth must be wired per environment; do not commit secrets.
