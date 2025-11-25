## Bright Data Email Extractor (Auto)

### Setup
- Ensure Python 3.13 or 3.12 is installed.
- Create and use a local virtual environment:

```zsh
python3 -m venv .venv
"./.venv/bin/python" -m pip install -r requirements.txt
```

### Run the UI
- Always run Streamlit with the venv Python to avoid system site‑packages conflicts:

```zsh
"./.venv/bin/python" -m streamlit run app.py
```

### Environment Variables
- Create a `.env` file with your Supabase credentials:

```
SUPABASE_URL=...
SUPABASE_KEY=...
```

### Notes
- If you previously ran `streamlit run app.py` directly, it may use the system Python and cause import/type errors. Use the venv command above.
