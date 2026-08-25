# AI Engineering

## Setup

1. Create and activate a virtual environment, then install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy the env template and add your API key:

   ```bash
   cp .env.template .env
   ```

   Then edit `.env` and set your key from https://console.anthropic.com/settings/keys:

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

   `.env` is gitignored — never commit it.

3. Verify it works:

   ```bash
   python anthropic-api-basics/hello_claude.py
   ```

   On success the script writes the full API response to
   `anthropic-api-basics/output/api.json`:

   ```bash
   cat anthropic-api-basics/output/api.json
   ```

   If the key is missing or invalid you'll get an
   `anthropic.AuthenticationError` instead.
