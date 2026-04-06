# LinkedIn Growth Agent

Knowledge-first LinkedIn assistant for:

- collecting sector context from LinkedIn via Playwright
- updating a persistent knowledge base
- building daily content briefs
- generating multiple post variants
- surfacing comment, reaction, and connection opportunities
- reviewing outputs in a Streamlit dashboard

## Main components

- `linkedin_agent/scripts/deep_bootstrap_knowledge.py`
  Deep bootstrap of the persistent sector knowledge base.
- `linkedin_agent/scripts/daily_refresh_knowledge.py`
  Daily incremental refresh using fresh LinkedIn context.
- `linkedin_agent/scripts/build_daily_brief.py`
  Builds and stores the daily content brief.
- `linkedin_agent/scripts/generate_post_variants.py`
  Generates 2-3 post variants from the latest or selected brief.
- `linkedin_agent/scripts/app.py`
  Streamlit dashboard for observability and review.
- `n8n/workflows/`
  Versioned n8n workflow exports for orchestration.

## Required environment

Configure a `.env` file with at least:

```env
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-sonnet-4-0
LINKEDIN_EMAIL=...
LINKEDIN_PASSWORD=...
```

If you use the browser session flow, keep `linkedin_agent/data/browser_session.json`
available locally, but do not commit it.

## Typical flow

1. Run `deep_bootstrap_knowledge` occasionally to enrich the sector memory.
2. Run `daily_refresh_knowledge` to collect the latest delta.
3. Run `build_daily_brief` to persist the content brief.
4. Run `generate_post_variants` to create reviewable post drafts.
5. Open Streamlit to review and approve pending items.

## Local development

Install dependencies:

```bash
pip install -r requirements.txt
```

Run tests:

```bash
pytest -q linkedin_agent/tests
```

Open the dashboard:

```bash
streamlit run linkedin_agent/scripts/app.py --server.port 8501
```
