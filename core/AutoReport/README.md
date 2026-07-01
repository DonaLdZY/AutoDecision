# AutoReport

AutoReport is the delivery-report generator for AutoDecision. It scans AutoRealize, MLEvolve/AutoML, and caller-provided evidence paths, compresses the evidence into a solution briefing, and uses an LLM to write a human-facing Markdown report.

The report is not meant to explain how AutoML works. It is meant to convince a user that the discovered solution is effective, reusable, and deliverable. The generated report should focus on:

- the final method design and why it solves the task;
- validation metrics, score components, output artifacts, and known limitations;
- how to reuse `solution.py`, expected input directory/file format, `predict()` or solver entrypoints, and generated outputs;
- how other searched candidates compared, including their metrics and failure reasons when available.

AutoReport is LLM-written and evidence-driven. If `llm.model`, `llm.base_url`, or an API key is missing, startup fails.

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
  --report-title "demo_task 方案交付报告" `
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
  --report-title "demo_task 方案交付报告" \
  --llm-model deepseek-chat \
  --llm-base-url https://api.deepseek.com \
  --llm-api-key "$DEEPSEEK_API_KEY" \
  --evidence autorealize=../../runs/demo_task/autorealize::autorealize \
  --evidence automl=../../runs/demo_task/automl::automl
```

## Evidence Used

AutoReport now extracts a structured solution evidence pack when the files exist:

- `best_solution/metric.txt`, `best_solution/solution.py`, `node_id.txt`, model artifact manifests;
- `top_solution/top*/metric.txt` and `top_solution/top*/solution.py`;
- `journal.json`, `filtered_journal.json`, `node_summary_compact.json` for candidate comparison;
- `submission.csv`, `assignments.csv`, `metrics.json`, `unassigned_orders.csv` for delivery artifacts;
- AutoRealize `description.md`, `data_description.md`, and context files for task/data grounding.

The LLM prompt receives compressed evidence, not full logs or full journals.

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
