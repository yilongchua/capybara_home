# Conversation Summarization

CapyHome uses automatic conversation summarization to compact old context before the active thread approaches the model context window. Compaction is token-pressure based: message count is recorded for diagnostics, but it does not decide when compaction runs.

## Configuration

```yaml
summarization:
  enabled: true
  model_name: null
  trigger:
    type: fraction
    value: 0.8
  keep:
    type: tokens
    value: 32000
  max_context_tokens: 128000
  trim_tokens_to_summarize: 32000
```

### `trigger`

Use `type: fraction` for the public config shape. The lead-agent factory resolves the fraction to an absolute token threshold before constructing LangChain's middleware.

Resolution order:

1. Model profile `max_input_tokens`
2. `summarization.max_context_tokens`
3. Model config `context_window` or `max_input_tokens`
4. Conservative fallback of `128000`

With `max_context_tokens: 128000`, `value: 0.8` becomes `102400` tokens.

Legacy `type: messages` triggers are accepted by config parsing for backward compatibility, but the lead-agent factory logs a deprecation warning and ignores them.

### `keep`

Use token-based retention:

```yaml
keep:
  type: tokens
  value: 32000
```

`type: fraction` is resolved against the same context-window source as `trigger`. Legacy message-count keep policies are converted to the default token keep budget.

### `summary_prompt`

The default summary prompt lives in `src/agents/middlewares/summarization_middleware.py`. `summary_prompt` remains supported as an advanced override, but normal configs should omit it.

## How It Works

1. Before each model call, the middleware estimates current context tokens and emits `context_tokens` telemetry with both token and message counts.
2. If token usage crosses the resolved threshold, older context is summarized.
3. Recent context is retained by token budget.
4. AI/tool-call groups are kept valid, and CapyHome-specific rescue logic preserves active skill blocks, operational reminders, and user anchor messages.
5. A summary message plus preserved recent messages replace the old history.

## Example Configurations

### Standard

```yaml
summarization:
  enabled: true
  trigger:
    type: fraction
    value: 0.8
  keep:
    type: tokens
    value: 32000
  max_context_tokens: 128000
  trim_tokens_to_summarize: 32000
```

### Smaller Context Model

```yaml
summarization:
  enabled: true
  trigger:
    type: fraction
    value: 0.75
  keep:
    type: tokens
    value: 12000
  max_context_tokens: 64000
  trim_tokens_to_summarize: 12000
```

### Advanced Custom Summary Prompt

```yaml
summarization:
  enabled: true
  trigger:
    type: fraction
    value: 0.8
  keep:
    type: tokens
    value: 32000
  summary_prompt: |
    Summarize the prior context with exact file paths and unresolved decisions.

    <messages>
    {messages}
    </messages>
```

## Troubleshooting

- If compaction runs too late, lower `trigger.value` or configure the model's `context_window`.
- If summaries lose useful details, increase `trim_tokens_to_summarize` or use a stronger summarization model.
- If too little recent context survives, increase `keep.value`.

## Implementation Details

- Configuration: `src/config/summarization_config.py`
- Factory normalization: `src/agents/lead_agent/agent.py`
- Middleware extensions and default prompt: `src/agents/middlewares/summarization_middleware.py`
