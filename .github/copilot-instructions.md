# GitHub Copilot Instructions

## Project objective

Build and maintain a Tamil Nadu Agriculture Schemes question-answering application. Streamlit is the user interface, FastAPI is the backend, and the existing FAISS index is the persistent vector store. Answers must be grounded in indexed agriculture sources and show source references when available. Preserve the project's current Python, Streamlit, FastAPI, FAISS, BM25, FlashRank, and configured LLM choices unless a change is explicitly requested.

## Mandatory query pipeline

Every interactive user query must follow this exact boundary:

**Streamlit → FastAPI → existing vector database retrieval → relevance-threshold validation → RAG/LLM → answer and citation validation → Streamlit.**

- Streamlit must send questions to FastAPI; it must not retrieve documents or contact agriculture websites itself.
- Query handling must retrieve only from the already-loaded FAISS index and the lexical corpus derived from the same indexed chunks.
- Apply query metadata filters where provided, hybrid semantic and keyword retrieval, reranking, and the configured relevance threshold before generating an answer.
- Give the LLM only the user's question and retrieved indexed evidence needed to answer. Validate returned citations against retrieved sources; never invent facts, sources, or citation identifiers.
- If evidence is missing, below threshold, conflicting, or insufficient, return a clear insufficient-evidence answer and available source information.
- **Never use web search as a fallback. Never fetch websites, run Playwright, read source PDFs, ingest documents, or embed source content while handling a user query.** Query embedding and LLM inference are allowed; they do not authorize source fetching or ingestion.
- Keep user-query code paths independent from ingestion jobs, including startup and scheduled ingestion mechanisms. Do not silently route a failed or low-relevance retrieval into ingestion or an external search provider.

## Separate ingestion pipeline

Ingestion is an explicit, separate workflow: configured government URLs and local PDFs/text → extraction → cleaning and chunking → source metadata → document embeddings → persisted FAISS index. Use Playwright for JavaScript-rendered pages only in this workflow; retain the existing HTTP fallback where applicable. Extract PDF text and retain page numbers when available. Support configured websites, PDFs under `data/` and `storage/pdfs/`, and supported cached text in `storage/`.

Preserve useful metadata wherever available: scheme name, department, source URL or file/document name, document type, PDF page, and ingestion timestamp. Keep incremental updates, duplicate/source replacement behavior, scheduled refreshes, and job progress consistent with existing patterns. Successful ingestion must persist and reload the index correctly. Do not add an ingestion trigger to Streamlit question submission.

Initial index creation and predefined-question coverage checks may run during backend startup as preparation for serving requests. Missing predefined coverage may cause the existing startup ingestion behavior; this is not permission to ingest during an interactive query. Scheduled refreshes must remain separate from request handling.

## FastAPI responsibilities and API

Keep FastAPI as the central boundary for query, indexed scheme browsing, ingestion, and health operations. Preserve these routes and their established request/response shapes:

- `POST /api/v1/query` — retrieve, validate evidence, generate an answer, and return sources.
- `POST /api/v1/query/stream` — streaming query route used by Streamlit.
- `GET /api/v1/schemes` — search, filter, and paginate indexed schemes.
- `GET /api/v1/schemes/{scheme_id}` — return an indexed scheme and its supported metadata.
- `GET /api/v1/filters` — return available indexed filter options.
- `POST /api/v1/ingestion/websites`, `POST /api/v1/ingestion/pdfs`, and `POST /api/v1/ingestion/refresh` — start separate ingestion jobs.
- `GET /api/v1/ingestion/jobs/{job_id}` — report job status and progress.
- `GET /health` and `GET /api/v1/health/dependencies` — report API and dependency health.

Keep long-running ingestion off the interactive query path and use the existing background-job pattern. Validate input and return clear HTTP errors rather than success-shaped fallbacks.

## Retrieval and answer quality

- Reuse the existing FAISS vector index and indexed-document corpus; do not create a parallel source of truth.
- Preserve hybrid retrieval (semantic vector search plus BM25 keyword search), metadata filtering, deduplication, and FlashRank reranking where appropriate.
- Apply a configurable relevance threshold (currently `RAG_MIN_RERANK_SCORE`) before answer generation. An empty result or below-threshold result must produce the insufficient-evidence response, not a web search or unsupported answer.
- Keep chunking context-aware and preserve source/page metadata through extraction, chunking, indexing, retrieval, streaming, and UI rendering.
- Generate concise responses supported by the retrieved evidence. Validate citation IDs against the retrieved set, and be transparent about incomplete or conflicting indexed information. Citation-ID validation is not proof that all claims are factually entailed.
- Consider query rewriting, parent-child retrieval, or other RAG changes only when evaluation demonstrates a measurable benefit; avoid adding complexity without evidence.

## Streamlit responsibilities

- Keep Streamlit focused on chat, query submission, result/source display, and indexed-scheme browsing.
- Route every chat query to FastAPI. Display streaming answers, source URLs, PDF page references, and retrieval/error/fallback states when available.
- Source scheme search, filters, pagination, and detail views from FastAPI's indexed scheme endpoints, not from live websites.
- Handle empty results, insufficient evidence, backend unavailability, malformed responses, and timeouts clearly. Do not disguise errors as valid answers.
- Keep any query or browsing cache bounded and short-lived where existing behavior requires it; do not cache a result in a way that bypasses current filters or evidence validation.

## Configuration and security

- Read credentials, backend URLs, thresholds, and refresh settings from environment configuration; never hard-code secrets or commit `.env`.
- Preserve existing settings such as `OPENAI_API_KEY`, `FASTAPI_BASE_URL`, `RAG_MIN_RERANK_SCORE`, and `INGESTION_REFRESH_INTERVAL_HOURS`; document new settings in `.env.example` and the README.
- Treat ingestion routes as privileged operations. Restrict them using deployment-appropriate authorization and network controls before exposing the API beyond a trusted local environment. The current ingestion routes do not enforce bearer-token authentication; do not describe them as authenticated or reintroduce a token setting without an explicit requirement.
- Restrict website ingestion to configured, trusted government URLs; validate paths and inputs, use safe file handling, and avoid exposing secrets or sensitive document contents in logs or errors.
- Apply timeouts, bounded caches, clear dependency health reporting, and explicit failure handling. Do not silently swallow ingestion, retrieval, citation-validation, or LLM errors.

## Tests and development workflow

- Inspect existing implementation, tests, and README before changing behavior. Keep changes focused and preserve the repository's current technology and conventions.
- Add or update regression tests for query/ingestion separation, including that empty or low-relevance retrieval never calls web-fetch, Playwright, PDF extraction, ingestion, or source-embedding code.
- Test retrieval thresholds, metadata filters, hybrid retrieval/reranking, fallback behavior, citation validation, source metadata, ingestion job status, and Streamlit-to-FastAPI request behavior when affected.
- Run the focused tests first, then the full suite when changes warrant it. The documented suite is:

  ```powershell
  .\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
  ```

- Update the README when routes, configuration, operational workflows, or user-visible behavior change. Do not modify unrelated application code when a request is limited to documentation or agent instructions.

## Acceptance criteria

A change is acceptable only when all applicable criteria hold:

1. Every Streamlit user query travels through FastAPI and reads agriculture evidence only from the existing vector index and its indexed lexical corpus.
2. No user query can initiate web search, website fetching, Playwright, PDF reading, ingestion, or source-document embedding, including as an error or low-relevance fallback.
3. Relevance threshold and evidence checks run before generation; insufficient evidence yields a clear fallback.
4. Generated answers use retrieved context, and citations point only to sources returned by retrieval.
5. Ingestion remains separately operable, persists/reloads the vector index, retains available source metadata, and reports job progress.
6. Streamlit scheme browsing and filters use indexed FastAPI endpoints and handle errors and empty results clearly.
7. Relevant tests pass, configuration contains no committed secrets, and documentation matches actual endpoint and security behavior.
