# AutoReport

AutoReport is the report-generation core for AutoDecision. It scans AutoRealize, AutoML, MLEvolve, or other caller-provided evidence paths, compresses the evidence into a briefing, and **uses an LLM to write a human-facing Markdown article** that explains the whole solution.

AutoReport is not a deterministic paste-together report. LLM configuration is required. If `llm.model`, `llm.base_url`, or an API key is missing, startup fails.

## CLI

From `core/AutoReport`:

```powershell
python -m autoreport.cli --config .\config.example.json
```

Or pass evidence and LLM settings directly:

```powershell
python -m autoreport.cli `
  --task-name demo_task `
  --output-dir ..\..\runs\demo_task\report `
  --report-title "demo_task AutoDecision 方案报告" `
  --llm-model deepseek-chat `
  --llm-base-url https://api.deepseek.com `
  --llm-api-key $env:DEEPSEEK_API_KEY `
  --evidence autorealize=..\..\runs\demo_task\autorealize::autorealize `
  --evidence automl=..\..\runs\demo_task\automl::automl
```

On Linux/macOS:

```bash
python -m autoreport.cli \
  --task-name demo_task \
  --output-dir ../../runs/demo_task/report \
  --report-title "demo_task AutoDecision 方案报告" \
  --llm-model deepseek-chat \
  --llm-base-url https://api.deepseek.com \
  --llm-api-key "$DEEPSEEK_API_KEY" \
  --evidence autorealize=../../runs/demo_task/autorealize::autorealize \
  --evidence automl=../../runs/demo_task/automl::automl
```

## API

From `core/AutoReport`:

```powershell
python -m uvicorn service_api:app --host 127.0.0.1 --port 18104
```

Useful endpoints:

- `GET /health`
- `GET /usage`
- `GET /config/schema`
- `POST /jobs/start`
- `GET /jobs/{job_id}`
- `POST /jobs/stop`
- `POST /snapshot`

`POST /jobs/start` expects either `config_path` or a generated config in `config`. The generated config must include:

```json
{
  "use_llm": true,
  "llm": {
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "api_key": "..."
  }
}
```

When the model name starts with `deepseek`, `https://api.deepseek.com` and `https://api.deepseek.com/v1` are automatically redirected to `https://api.deepseek.com/beta`.
