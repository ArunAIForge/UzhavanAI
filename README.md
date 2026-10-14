# Uzhavan AI — Tamil Nadu Agriculture Schemes

Uzhavan AI is a Tamil-language agriculture information assistant. The Streamlit app sends questions to a FastAPI backend, which retrieves evidence from an existing FAISS index and its matching BM25 corpus before asking the configured language model to respond. The persistent index is stored in `storage/faiss_index/`.

## Features

- Tamil-language chat with quick questions about agriculture schemes and irrigation, plus a farmer-type and crop-based eligibility query.
- Source references returned by the API, including source links or filenames and PDF page numbers when available.
- An application dossier in supported answers, with scheme, subsidy, eligibility, office, and required-document fields.
- Tamil/English speech playback for answer summaries.
- In-memory chat sessions during the current Streamlit session.
- Persistent FAISS storage, hybrid dense and lexical retrieval, FlashRank reranking, relevance filtering, and a bounded API response cache.

## How it works

```text
Separate ingestion workflow
Configured government websites ─┐
PDFs in data/ or storage/pdfs/ ──┼─> extract and clean -> split -> embed -> storage/faiss_index/
Text files in storage/ ──────────┘

Interactive question
Streamlit -> FastAPI -> loaded FAISS + BM25 -> FlashRank -> relevance threshold
          -> configured LLM -> answer and sources -> Streamlit
```

Interactive questions only search already-indexed content. They do not fetch websites, read PDFs, start ingestion, or embed source documents. An uncached question may be embedded for semantic retrieval, and the configured LLM generates the response.

At FastAPI startup, the service loads the persisted FAISS index and builds the BM25 corpus from the same indexed chunks. Startup also checks coverage for predefined questions; if evidence is missing, this preparation step may refresh configured sources. Scheduled refreshes, when enabled, run separately from query requests.

## Setup

Use Python 3.10 or newer. In PowerShell, from the project directory:

1. Create and activate a virtual environment if you do not already have one:

   ```powershell
   py -3 -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

2. Install the project dependencies:

   ```powershell
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Create a local environment file and provide an OpenAI API key:

   ```powershell
   Copy-Item .env.example .env
   ```

   Edit `.env` and set `OPENAI_API_KEY`. Do not commit `.env`.

4. Install Playwright's Chromium runtime for website ingestion:

   ```powershell
   .\venv\Scripts\python.exe -m playwright install chromium
   ```

   Ingestion first tries installed Chrome or Edge channels and uses bundled Chromium as a fallback. Website extraction falls back to HTTP where Playwright cannot use asynchronous subprocesses.

5. Run the backend and UI in separate PowerShell terminals:

   ```powershell
   .\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

   ```powershell
   .\venv\Scripts\python.exe -m streamlit run app.py
   ```

   Open the local Streamlit URL printed in its terminal (typically `http://localhost:8501`). The API is available at `http://127.0.0.1:8000`; its interactive API documentation is at `/docs`.

## Configuration

Copy `.env.example` to `.env` and configure values for your environment:

| Variable | Purpose | Behavior |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI authentication | Required by the backend for embeddings and chat. `API_KEY` is accepted as a fallback by the backend. |
| `FASTAPI_BASE_URL` | FastAPI URL used by Streamlit | Defaults to `http://127.0.0.1:8000`. |
| `RAG_MIN_RERANK_SCORE` | Minimum FlashRank score for evidence | Defaults to `0.10` when unset. The example file sets `0.15`. |
| `INGESTION_REFRESH_INTERVAL_HOURS` | Optional scheduled refresh interval | Unset or a value less than or equal to zero disables scheduled refreshes; a positive value enables them. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed browser origins | Defaults to `http://localhost:8501,http://127.0.0.1:8501`. |

The embedding model (`text-embedding-3-small`), chat model (`gpt-4o-mini`), and FlashRank model (`ms-marco-TinyBERT-L-2-v2`) are configured in the application code.

## Indexed data and ingestion

The ingestion workflow accepts:

- Configured government websites listed in `ingest.py` (`TARGET_URLS`).
- PDF files in `data/` and `storage/pdfs/`.
- Cached plain-text files (`*.txt`) directly in `storage/`.

Chunks are stored in `storage/faiss_index/index.faiss` and `storage/faiss_index/index.pkl`. Website and local-file source metadata is preserved where available, including source identity, document type, scheme, department, PDF page number, and ingestion time.

Refreshes reuse indexed data:

- PDF files are fingerprinted before parsing. Unchanged PDFs are skipped.
- Cached text files are fingerprinted from their bytes before decoding and indexing. Unchanged files are skipped.
- Website refreshes check stored HTTP validators and response fingerprints. Unchanged static pages skip extraction; pages with JavaScript-rendered content are revalidated through the browser extractor to avoid losing rendered text.
- Only new or changed source chunks are embedded and added to FAISS. Extracted content is compared with indexed chunks before updating the index. An unchanged refresh does not reload the in-memory FAISS index or rebuild the runtime BM25 corpus.

When the index is missing, FastAPI startup attempts to build it from the configured sources. Ingestion can also be triggered explicitly through the API. Successful changes are persisted and reloaded by the running backend. Index backups are written under `storage/faiss_backups/` before incremental index updates.

## API

| Method and path | Purpose |
|---|---|
| `POST /api/v1/query` | Retrieve evidence and return a generated answer with sources. |
| `POST /api/v1/query/stream` | Stream source and answer-token events; used by the Streamlit chat. |
| `GET /api/v1/schemes` | Search/filter indexed scheme records and paginate results. |
| `GET /api/v1/schemes/{scheme_id}` | Return one indexed scheme record. |
| `GET /api/v1/filters` | List indexed scheme, department, and document-type filter values. |
| `POST /api/v1/ingestion/websites` | Start website ingestion for configured URLs. |
| `POST /api/v1/ingestion/pdfs` | Start PDF ingestion from the API host's supported directories. |
| `POST /api/v1/ingestion/refresh` | Start a refresh of websites, PDFs, and cached text files. |
| `GET /api/v1/ingestion/jobs/{job_id}` | Read ingestion job status and progress. |
| `GET /health` | Report API and vector-index startup status. |
| `GET /api/v1/health/dependencies` | Report vector database and LLM dependency status. |

Query requests accept `query`, `top_k` (1–10), and optional metadata `filters` (`scheme_name`, `doc_type`, or `department`). The backend applies hybrid retrieval and reranking, then uses `RAG_MIN_RERANK_SCORE` to decide whether there is sufficient evidence. If not, it returns the configured insufficient-evidence response rather than performing live search.

The API provides indexed scheme-browsing endpoints; the current Streamlit UI is focused on chat and does not present a scheme browser.

## Operational notes

- Ingestion endpoints are not protected by bearer-token authentication. Keep the API bound to a trusted local/private network, and apply deployment-appropriate access and network controls before exposing it.
- Website ingestion only accepts configured government URLs. Requests for unconfigured URLs are rejected.
- Ingestion job history is held in process memory and is cleared when the FastAPI process restarts. Only one ingestion job can run at a time.
- The API response cache is bounded to 256 entries and is cleared when indexed data changes or the service shuts down.
- A query with no, low-scoring, or insufficient indexed evidence receives an insufficient-evidence result. Generated answer citations are checked against returned source IDs when present; this check does not prove that every claim is entailed by the sources.
- The UI keeps chat state in Streamlit session state; it is not durable storage across application sessions.

## Postman

The `postman/` directory contains a local environment and a collection for checking health, query, validation, scheme/filter, and ingestion endpoints. Start FastAPI before running the collection. Ingestion requests perform real work on the API host; use them only when an index update is intended. PDF ingestion reads files on the host and does not upload a local file.

## Tests

Run the test suite from the project directory:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```
