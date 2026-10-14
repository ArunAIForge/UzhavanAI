# -*- coding: utf-8 -*-
import os
import asyncio
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from bs4 import BeautifulSoup

from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY must be set in your .env file.")

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = str(PROJECT_DIR / "data")
STORAGE_DIR = str(PROJECT_DIR / "storage")
OUTPUT_INDEX_DIR = str(PROJECT_DIR / "storage" / "faiss_index")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(OUTPUT_INDEX_DIR, exist_ok=True)

# Curated Agricultural Scheme URLs
TARGET_URLS = [
    {
        "scheme": "TNAU Paddy Cultivation Practices (SRI)",
        "url": "https://agritech.tnau.ac.in/expert_system/paddy/cultivationpractices2.html"
    },
    {
        "scheme": "TNAU Schemes for Paddy Cultivation",
        "url": "https://agritech.tnau.ac.in/expert_system/paddy/Schemes.html"
    }   
]

def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def _indexed_source_metadata():
    from main import app_state

    vector_db = app_state.get("vector_db")
    if vector_db is None:
        return {}

    metadata_by_source = {}
    for doc_id in vector_db.index_to_docstore_id.values():
        document = vector_db.docstore.search(doc_id)
        metadata = getattr(document, "metadata", {})
        source = str(metadata.get("source", ""))
        if source:
            metadata_by_source[source] = metadata
    return metadata_by_source

def clean_html_content(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    meaningful_lines = [l for l in lines if len(l) > 30]
    return "\n\n".join(meaningful_lines)

def load_pdf_documents(pdf_directories=None):
    documents = []
    timestamp = datetime.now(timezone.utc).isoformat()
    indexed_sources = _indexed_source_metadata()
    if pdf_directories is None:
        pdf_directories = (Path(DATA_DIR), Path(STORAGE_DIR) / "pdfs")
    pdf_files = sorted({
        path.resolve()
        for directory in pdf_directories
        if directory.is_dir()
        for path in directory.glob("*.pdf")
    })
    for pdf_path in pdf_files:
        source = str(pdf_path)
        try:
            fingerprint = _sha256_file(pdf_path)
        except OSError as exc:
            print(f"  ✖ Error reading {pdf_path}: {exc}")
            continue
        indexed = indexed_sources.get(source, {})
        if indexed.get("source_fingerprint") == fingerprint:
            continue
        pages = PyPDFLoader(str(pdf_path)).load()
        for page in pages:
            page_number = int(page.metadata.get("page", 0)) + 1
            page.metadata.update({
                "source": source,
                "scheme_name": pdf_path.stem,
                "doc_type": "pdf",
                "page_number": page_number,
                "ingested_at": timestamp,
                "source_fingerprint": fingerprint,
            })
        documents.extend(pages)
    return documents

def load_cached_text_documents(text_directory=None):
    directory = Path(text_directory) if text_directory is not None else Path(STORAGE_DIR)
    documents = []
    timestamp = datetime.now(timezone.utc).isoformat()
    indexed_sources = _indexed_source_metadata()
    for txt_path in sorted(directory.glob("*.txt")) if directory.is_dir() else []:
        try:
            raw_content = txt_path.read_bytes()
            fingerprint = _sha256(raw_content)
            source = f"./storage{os.sep}{txt_path.name}"
            if indexed_sources.get(source, {}).get("source_fingerprint") == fingerprint:
                continue
            content = raw_content.decode("utf-8", errors="ignore").strip()
            if len(content) <= 100:
                continue
            documents.append(Document(
                page_content=content,
                metadata={
                    "source": source,
                    "scheme_name": txt_path.stem,
                    "doc_type": "cached_text",
                    "ingested_at": timestamp,
                    "source_fingerprint": fingerprint,
                },
            ))
        except OSError as exc:
            print(f"  ✖ Error reading {txt_path}: {exc}")
    return documents

async def _load_website_documents_with_playwright(target_urls=None, progress_callback=None):
    from playwright.async_api import async_playwright

    targets = TARGET_URLS if target_urls is None else target_urls
    documents = []
    failures = []
    timestamp = datetime.now(timezone.utc).isoformat()

    async with async_playwright() as playwright:
        browser = None
        launch_errors = []
        for channel in ("chrome", "msedge", None):
            try:
                launch_options = {
                    "headless": True,
                    "args": ["--no-sandbox", "--disable-gpu"],
                }
                if channel:
                    launch_options["channel"] = channel
                browser = await playwright.chromium.launch(**launch_options)
                break
            except Exception as exc:
                launch_errors.append(f"{channel or 'bundled Chromium'}: {exc}")
        if browser is None:
            raise RuntimeError(
                "Could not launch Chrome or Edge for Playwright ingestion. "
                + " | ".join(launch_errors)
            )

        try:
            page = await browser.new_page(ignore_https_errors=False)
            total = len(targets)
            for position, item in enumerate(targets, start=1):
                try:
                    response = await page.goto(
                        item["url"], wait_until="domcontentloaded", timeout=30000
                    )
                    if response is None or response.status >= 400:
                        raise RuntimeError(
                            f"Website returned HTTP {response.status if response else 'no response'}."
                        )
                    await page.wait_for_timeout(1000)
                    rendered_html = await page.content()
                    content = clean_html_content(rendered_html)
                    if len(content) < 150:
                        raise RuntimeError("Website contained insufficient extractable text.")
                    cache_safe = True
                    try:
                        response_body = await response.body()
                        raw_content = clean_html_content(
                            response_body.decode("utf-8", errors="ignore")
                        )
                    except Exception as exc:
                        print(
                            f"Could not fingerprint the raw response for {item['url']}; "
                            f"the rendered page will be revalidated on refresh: {exc}"
                        )
                        response_body = rendered_html.encode("utf-8")
                        cache_safe = False
                    documents.append(Document(
                        page_content=content,
                        metadata={
                            "source": item["url"],
                            "scheme_name": item["scheme"],
                            "doc_type": "url",
                            "department": item.get("department", "Agriculture"),
                            "ingested_at": timestamp,
                            "source_fingerprint": _sha256(response_body),
                            "source_etag": response.headers.get("etag"),
                            "source_last_modified": response.headers.get("last-modified"),
                            "source_cache_safe": cache_safe and raw_content == content,
                        },
                    ))
                except Exception as exc:
                    failures.append(f"{item['url']}: {exc}")
                if progress_callback:
                    progress_callback(position, total)
        finally:
            await browser.close()

    if not documents:
        detail = "; ".join(failures) or "No websites were configured."
        raise RuntimeError(f"Website ingestion produced no documents: {detail}")
    return documents, failures


async def _load_website_documents_with_httpx(target_urls=None, progress_callback=None):
    import httpx

    targets = TARGET_URLS if target_urls is None else target_urls
    documents = []
    failures = []
    timestamp = datetime.now(timezone.utc).isoformat()

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for position, item in enumerate(targets, start=1):
            try:
                response = await client.get(item["url"])
                response.raise_for_status()
                content = clean_html_content(response.text)
                if len(content) < 150:
                    raise RuntimeError("Website contained insufficient extractable text.")
                documents.append(Document(
                    page_content=content,
                    metadata={
                        "source": item["url"],
                        "scheme_name": item["scheme"],
                        "doc_type": "url",
                        "department": item.get("department", "Agriculture"),
                        "ingested_at": timestamp,
                        "source_fingerprint": _sha256(response.content),
                        "source_etag": response.headers.get("etag"),
                        "source_last_modified": response.headers.get("last-modified"),
                        "source_cache_safe": True,
                    },
                ))
            except Exception as exc:
                failures.append(f"{item['url']}: {exc}")
            if progress_callback:
                progress_callback(position, len(targets))

    if not documents:
        detail = "; ".join(failures) or "No websites were configured."
        raise RuntimeError(f"Website ingestion produced no documents: {detail}")
    return documents, failures


async def load_website_documents(target_urls=None, progress_callback=None):
    import httpx

    targets = TARGET_URLS if target_urls is None else target_urls
    indexed_sources = _indexed_source_metadata()
    changed_targets = []
    snapshots = {}

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for item in targets:
            source = item["url"]
            indexed = indexed_sources.get(source, {})
            headers = {}
            if indexed.get("source_etag"):
                headers["If-None-Match"] = indexed["source_etag"]
            if indexed.get("source_last_modified"):
                headers["If-Modified-Since"] = indexed["source_last_modified"]

            try:
                response = await client.get(source, headers=headers)
                if (
                    response.status_code == 304
                    and indexed.get("source_fingerprint")
                    and indexed.get("source_cache_safe")
                ):
                    continue
                response.raise_for_status()
                fingerprint = _sha256(response.content)
                if (
                    indexed.get("source_fingerprint") == fingerprint
                    and indexed.get("source_cache_safe")
                ):
                    continue
                snapshots[source] = {
                    "source_fingerprint": fingerprint,
                    "source_etag": response.headers.get("etag"),
                    "source_last_modified": response.headers.get("last-modified"),
                }
            except Exception as exc:
                print(
                    f"Website cache validation failed for {source}; "
                    f"retrying with the configured extractor: {exc}"
                )
            changed_targets.append(item)

    if not changed_targets:
        return [], []

    if (
        sys.platform == "win32"
        and not isinstance(
            asyncio.get_running_loop(), asyncio.ProactorEventLoop
        )
    ):
        print(
            "The active Windows event loop does not support subprocesses; "
            "loading configured websites with HTTP."
        )
        documents, failures = await _load_website_documents_with_httpx(
            changed_targets, progress_callback
        )
    else:
        try:
            documents, failures = await _load_website_documents_with_playwright(
                changed_targets, progress_callback
            )
        except NotImplementedError:
            print(
                "Playwright requires asyncio subprocess support; "
                "retrying configured websites with HTTP."
            )
            documents, failures = await _load_website_documents_with_httpx(
                changed_targets, progress_callback
            )

    for document in documents:
        source = str(document.metadata.get("source", ""))
        document.metadata.update(snapshots.get(source, {}))
    return documents, failures


def load_all_sources():
    print("\n--- 1. Loading configured scheme URLs with Playwright ---")
    documents, website_failures = asyncio.run(load_website_documents())
    for failure in website_failures:
        print(f"  ⚠️ Website ingestion warning: {failure}")

    print("\n--- 2. Loading PDFs from ./data/ and ./storage/pdfs/ ---")
    pdf_documents = load_pdf_documents()
    documents.extend(pdf_documents)
    print(f"Loaded {len(pdf_documents)} PDF page(s) from new or changed files.")

    # 3. Load Cached Text Files from ./storage/*.txt
    print("\n--- 3. Loading Cached Files from ./storage/ ---")
    cached_text_documents = load_cached_text_documents()
    documents.extend(cached_text_documents)
    for document in cached_text_documents:
        print(f"  ✔ Loaded: {Path(document.metadata['source']).name}")

    return documents

def create_embeddings():
    from main import DirectOpenAIEmbeddings

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set in your .env file.")
    return DirectOpenAIEmbeddings(api_key=api_key, model="text-embedding-3-small")

def run_ingestion():
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set in your .env file.")
    raw_docs = load_all_sources()
    if not raw_docs:
        index_dir = Path(OUTPUT_INDEX_DIR)
        if (index_dir / "index.faiss").is_file() and (index_dir / "index.pkl").is_file():
            print("No new or changed source documents were indexed.")
        else:
            print("❌ No data found across URLs, PDFs, or storage. Exiting.")
        return

    print(f"\nTotal source documents/pages collected: {len(raw_docs)}")
    print("Chunking documents...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", " "]
    )
    chunks = text_splitter.split_documents(raw_docs)
    if not chunks:
        raise RuntimeError("Collected source documents produced no indexable chunks.")
    print(f"✔ Generated {len(chunks)} chunks.")

    print("\nGenerating embeddings (OpenAI text-embedding-3-small)...")
    embeddings = create_embeddings()

    index_dir = Path(OUTPUT_INDEX_DIR)
    if (index_dir / "index.faiss").is_file() and (index_dir / "index.pkl").is_file():
        from main import app_state, _persist_incremental_documents

        app_state["embeddings"] = embeddings
        result = _persist_incremental_documents(raw_docs, refresh_runtime=False)
        print(
            f"\n🎉 Incremental update complete: {result['chunks_added']} chunks added; "
            f"{result['vectors_total']} vectors in {OUTPUT_INDEX_DIR}"
        )
    else:
        print("Building initial FAISS vector index...")
        vector_db = FAISS.from_documents(chunks, embeddings)
        vector_db.save_local(OUTPUT_INDEX_DIR)
        print(f"\n🎉 Step 1 Complete! Vector store saved to: {OUTPUT_INDEX_DIR}")

if __name__ == "__main__":
    run_ingestion()