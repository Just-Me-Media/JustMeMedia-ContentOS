# Provider adapter contract — design draft

Every model adapter should expose a common interface independent of provider.

Required operations:
- `health()`: availability and diagnostic summary
- `capabilities()`: text, vision, structured output, tool use, context limits where known
- `generate(request)`: normalized request to normalized response
- `cancel(run_id)`: cancel where supported

Normalized request fields:
- task_id
- system_prompt
- user_prompt
- model
- temperature / output limits when supported
- timeout
- selected context references

Normalized response fields:
- provider_id
- model_id
- output
- finish_status
- usage (if supplied)
- latency_ms
- error (if any)
- timestamp

Rules:
- Never assume all providers support the same features.
- Report unsupported capabilities explicitly.
- Do not log secrets or full sensitive context by default.
- Record provider/model identity for auditability.
- Provider failure must not corrupt the content record.
- Manual operation remains available if all providers are offline.
