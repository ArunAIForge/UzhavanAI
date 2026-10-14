import os
import sys
import io
import json
import re
import asyncio
import hashlib
import threading
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from unittest.mock import MagicMock

import httpx

sys.modules.setdefault("tiktoken", MagicMock())
sys.modules.setdefault("tiktoken._tiktoken", MagicMock())
os.environ.setdefault("OPENAI_API_KEY", "test-api-key")

import ingest
import main
from backend_client import (
    get_scheme_detail,
    get_scheme_filters,
    search_schemes,
    stream_query_events,
)
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from predefined_queries import (
    CROP_INTERESTS,
    FARMER_TYPES,
    PREDEFINED_QUERIES,
    QUICK_QUERIES,
    eligibility_query,
)
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)


class FixtureEmbeddings(main.Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 7 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 7


class LocalVectorRetriever:
    def __init__(self, vector_db):
        self.vector_db = vector_db

    def retrieve(
        self,
        query: str,
        top_k_dense: int = 5,
        top_k_sparse: int = 5,
        filters=None,
        top_k_results: int = 4,
    ):
        documents = self.vector_db.similarity_search(query, k=top_k_dense)
        return [
            Document(
                page_content=document.page_content,
                metadata={**document.metadata, "rerank_score": 0.8},
            )
            for document in documents[:top_k_results]
        ]


class MockCompletionStream:
    async def __aiter__(self):
        for content in (
            "[ADVISORY] தமிழில் சோதனை பதில் [S1].",
            "[DOSSIER_JSON]",
            '{"scheme_name":"சோதனைத் திட்டம்","subsidy":"மானியம்","eligibility":"விவசாயிகள்","office":"அலுவலகம்","documents":"ஆவணங்கள்"}',
        ):
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
            )


class RagApiFlowTests(unittest.TestCase):
    def test_pdf_loader_skips_unchanged_indexed_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "indexed.pdf"
            self._write_pdf(pdf_path)
            source = str(pdf_path.resolve())
            fingerprint = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            with (
                patch.object(ingest, "_indexed_source_metadata", return_value={
                    source: {"source_fingerprint": fingerprint},
                }),
                patch.object(ingest, "PyPDFLoader") as pdf_loader,
            ):
                self.assertEqual(
                    ingest.load_pdf_documents((Path(temp_dir),)),
                    [],
                )

        pdf_loader.assert_not_called()

    def test_website_loader_skips_extraction_when_response_is_unchanged(self):
        source = "https://example.test/agriculture"

        class NotModifiedClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url, headers=None):
                self.headers = headers
                return httpx.Response(
                    304,
                    request=httpx.Request("GET", source),
                )

        target = {"scheme": "Test scheme", "url": source}
        with (
            patch.object(
                ingest,
                "_indexed_source_metadata",
                return_value={
                    source: {
                        "source_fingerprint": "indexed-content",
                        "source_etag": '"version-1"',
                        "source_cache_safe": True,
                    },
                },
            ),
            patch("httpx.AsyncClient", NotModifiedClient),
            patch.object(ingest, "_load_website_documents_with_playwright", new=AsyncMock()) as extractor,
            patch.object(ingest, "_load_website_documents_with_httpx", new=AsyncMock()) as fallback,
        ):
            documents, failures = asyncio.run(ingest.load_website_documents([target]))

        self.assertEqual(documents, [])
        self.assertEqual(failures, [])
        extractor.assert_not_awaited()
        fallback.assert_not_awaited()

    def test_incremental_ingestion_does_not_reload_unchanged_index(self):
        source = "https://example.test/scheme"
        fingerprint = "source-content-v1"
        document = Document(
            page_content="Indexed source passage remains unchanged.",
            metadata={"source": source, "source_fingerprint": fingerprint},
        )
        vector_db = main.FAISS.from_documents([document], FixtureEmbeddings())
        previous_state = dict(main.app_state)
        main.app_state.clear()
        main.app_state.update(
            vector_db=vector_db,
            embeddings=FixtureEmbeddings(),
        )
        try:
            with patch.object(main.FAISS, "load_local") as load_index:
                result = main._persist_incremental_documents([document])
            load_index.assert_not_called()
            self.assertEqual(result["chunks_added"], 0)
            self.assertEqual(result["vectors_total"], 1)
        finally:
            main.app_state.clear()
            main.app_state.update(previous_state)

    def test_query_cache_is_bounded(self):
        previous_cache = main.QUERY_CACHE.copy()
        main.QUERY_CACHE.clear()
        try:
            for index in range(main.QUERY_CACHE_MAX_ENTRIES + 1):
                main._cache_query(str(index), {"tokens": []})

            self.assertEqual(len(main.QUERY_CACHE), main.QUERY_CACHE_MAX_ENTRIES)
            self.assertNotIn("0", main.QUERY_CACHE)
            self.assertIn(str(main.QUERY_CACHE_MAX_ENTRIES), main.QUERY_CACHE)
        finally:
            main.QUERY_CACHE.clear()
            main.QUERY_CACHE.update(previous_cache)

    def test_query_retrieval_runs_outside_asyncio_event_loop(self):
        caller_thread = threading.get_ident()
        retrieval_threads = []

        class RecordingRetriever:
            def retrieve(self, *_args, **_kwargs):
                retrieval_threads.append(threading.get_ident())
                return []

        previous_state = dict(main.app_state)
        main.app_state["rag_engine"] = RecordingRetriever()
        try:
            status, sources, tokens = asyncio.run(main.execute_rag("test"))
        finally:
            main.app_state.clear()
            main.app_state.update(previous_state)

        self.assertEqual(status, "REFUSE")
        self.assertEqual(sources, [])
        self.assertTrue(tokens)
        self.assertEqual(len(retrieval_threads), 1)
        self.assertNotEqual(retrieval_threads[0], caller_thread)

    def test_query_rejects_missing_or_invalid_reranker_scores(self):
        class ScoreRetriever:
            def __init__(self, score):
                self.score = score

            def retrieve(self, *_args, **_kwargs):
                metadata = {}
                if self.score is not ...:
                    metadata["rerank_score"] = self.score
                return [
                    Document(
                        page_content="Relevant indexed agriculture evidence.",
                        metadata=metadata,
                    )
                ]

        previous_state = dict(main.app_state)
        previous_threshold = main.MIN_RELEVANCE_SCORE
        completion = AsyncMock()
        main.MIN_RELEVANCE_SCORE = 0.05
        try:
            for invalid_score in (..., None, "0.9", float("nan"), float("inf"), True, 0.01):
                with self.subTest(score=invalid_score):
                    main.app_state.clear()
                    main.app_state.update(
                        rag_engine=ScoreRetriever(invalid_score),
                        async_client=SimpleNamespace(
                            chat=SimpleNamespace(
                                completions=SimpleNamespace(create=completion)
                            )
                        ),
                    )
                    status, sources, tokens = asyncio.run(main.execute_rag("test"))
                    self.assertEqual(status, "REFUSE")
                    self.assertEqual(sources, [])
                    self.assertEqual(tokens, [main.INSUFFICIENT_EVIDENCE_ANSWER])
            completion.assert_not_awaited()
        finally:
            main.MIN_RELEVANCE_SCORE = previous_threshold
            main.app_state.clear()
            main.app_state.update(previous_state)

    def test_answer_grounding_validation_rejects_unsupported_claims(self):
        valid_answer = (
            "மானியம் வழங்கப்படுகிறது [S1]. [DOSSIER_JSON]"
            '{"scheme_name":"திட்டம்","subsidy":"மானியம்",'
            '"eligibility":"விவசாயிகள்","office":"அலுவலகம்","documents":"ஆவணங்கள்"}'
        )

        async def validator_response(content):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(content))
                    )
                ]
            )

        async def run_validation(answer, judgment):
            client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(
                        create=AsyncMock(return_value=await validator_response(judgment))
                    )
                )
            )
            return await main._validate_grounded_answer(
                answer, "[S1] Indexed evidence.", {"S1"}, cast(Any, client)
            )

        judgment = {
            "grounded": True,
            "claims": [
                {
                    "claim": "The subsidy claim is supported.",
                    "source_ids": ["S1"],
                    "supported": True,
                }
            ],
        }
        self.assertTrue(asyncio.run(run_validation(valid_answer, judgment)))

        unsupported_judgment = {
            "grounded": False,
            "claims": [
                {
                    "claim": "The claim is unsupported.",
                    "source_ids": ["S1"],
                    "supported": False,
                }
            ],
        }
        self.assertFalse(
            asyncio.run(run_validation(valid_answer, unsupported_judgment))
        )
        self.assertFalse(
            asyncio.run(
                run_validation(valid_answer.replace("[S1]", "[S99]"), judgment)
            )
        )

    def test_retrieval_filters_bm25_before_top_k_and_returns_requested_top_k(self):
        from rag_engine import AgriRAGEngine

        eligible = [
            Document(
                page_content=f"Eligible scheme evidence number {index}.",
                metadata={"department": "Agriculture", "source": f"eligible-{index}"},
            )
            for index in range(6)
        ]
        excluded = Document(
            page_content="Higher lexical score but wrong department.",
            metadata={"department": "Revenue", "source": "excluded"},
        )

        class FakeVectorDatabase:
            def similarity_search(self, *_args, **_kwargs):
                return []

        class FakeBM25:
            def get_scores(self, _tokens):
                return [100.0] + [10.0 - index for index in range(6)]

        class FakeReranker:
            def rerank(self, request):
                return [
                    {"text": item["text"], "meta": item["meta"], "score": 0.8}
                    for item in request.passages
                ]

        engine = cast(Any, object.__new__(AgriRAGEngine))
        engine.vector_db = FakeVectorDatabase()
        engine.documents = [excluded, *eligible]
        engine.bm25 = FakeBM25()
        engine.reranker = FakeReranker()

        results = engine.retrieve(
            "scheme",
            top_k_dense=6,
            top_k_sparse=6,
            filters={"department": "Agriculture"},
            top_k_results=6,
        )

        self.assertEqual(len(results), 6)
        self.assertTrue(
            all(result.metadata["department"] == "Agriculture" for result in results)
        )
        self.assertEqual(
            {result.metadata["source"] for result in results},
            {f"eligible-{index}" for index in range(6)},
        )

    def test_streaming_query_rejects_unsupported_metadata_filters(self):
        previous_state = dict(main.app_state)
        main.app_state.update(rag_engine=object(), async_client=object())
        client = TestClient(main.app)
        try:
            response = client.post(
                "/api/v1/query/stream",
                json={"query": "scheme", "filters": {"unknown": "value"}},
            )
            self.assertEqual(response.status_code, 422)
        finally:
            client.close()
            main.app_state.clear()
            main.app_state.update(previous_state)

    def test_streaming_backend_client_sends_filters_to_fastapi_query(self):
        previous_state = dict(main.app_state)
        previous_cache = main.QUERY_CACHE.copy()
        main.app_state.update(rag_engine=object(), async_client=object())
        main.QUERY_CACHE.clear()
        sources = [
            {
                "id": "S1",
                "source": "Micro Irrigation",
                "document_name": "irrigation.pdf",
                "url_or_file": "https://example.gov/irrigation.pdf",
                "page_number": 4,
                "content": "Irrigation subsidy evidence.",
            }
        ]
        filters = {"department": "Agriculture", "scheme_name": "Micro Irrigation"}
        client = TestClient(main.app)
        try:
            with patch(
                "main.execute_rag",
                new=AsyncMock(return_value=("PASS", sources, ["Grounded answer [S1]"])),
            ) as execute_rag:
                events = list(
                    stream_query_events(
                        "irrigation subsidy",
                        "http://testserver",
                        top_k=3,
                        client=cast(httpx.Client, client),
                        filters=filters,
                    )
                )

            execute_rag.assert_awaited_once_with(
                "irrigation subsidy", top_k=3, filters=filters
            )
            source_events = [event for event in events if event.get("type") == "sources"]
            self.assertEqual(source_events, [{"type": "sources", "data": sources}])
            self.assertEqual(source_events[0]["data"][0]["id"], "S1")
            self.assertEqual(
                source_events[0]["data"][0]["url_or_file"],
                "https://example.gov/irrigation.pdf",
            )
            self.assertEqual(source_events[0]["data"][0]["page_number"], 4)
        finally:
            client.close()
            main.app_state.clear()
            main.app_state.update(previous_state)
            main.QUERY_CACHE.clear()
            main.QUERY_CACHE.update(previous_cache)

    def test_query_with_no_indexed_evidence_never_uses_web_or_ingestion(self):
        class EmptyRetriever:
            def retrieve(self, *_args, **_kwargs):
                return []

        previous_state = dict(main.app_state)
        previous_cache = main.QUERY_CACHE.copy()
        completion = AsyncMock()
        main.app_state.clear()
        main.app_state.update(
            rag_engine=EmptyRetriever(),
            async_client=SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=completion)
                )
            ),
        )
        main.QUERY_CACHE.clear()
        client = TestClient(main.app)
        query = "unique query with no indexed evidence"
        try:
            with (
                patch.object(
                    ingest,
                    "load_website_documents",
                    side_effect=AssertionError("A user query must not search the web."),
                ) as search_web,
                patch.object(
                    ingest,
                    "load_pdf_documents",
                    side_effect=AssertionError("A user query must not ingest PDFs."),
                ) as ingest_pdfs,
                patch.object(
                    ingest,
                    "load_cached_text_documents",
                    side_effect=AssertionError("A user query must not reload source files."),
                ) as load_cached,
                patch.object(
                    ingest,
                    "run_ingestion",
                    side_effect=AssertionError("A user query must not run ingestion."),
                ) as run_ingestion,
                patch.object(
                    main,
                    "_run_ingestion_job",
                    side_effect=AssertionError("A user query must not start ingestion."),
                ) as start_ingestion,
            ):
                response = client.post(
                    "/api/v1/query",
                    json={"query": query},
                )
                stream_events = list(
                    stream_query_events(
                        query,
                        "http://testserver",
                        client=cast(httpx.Client, client),
                    )
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "refuse")
            self.assertEqual(response.json()["sources"], [])
            self.assertIn("எங்கள் ஆவணங்களில்", response.json()["answer"])
            self.assertEqual(
                "".join(
                    event["content"]
                    for event in stream_events
                    if event.get("type") == "token"
                ),
                "எங்கள் ஆவணங்களில் இந்த தகவல் இல்லை.",
            )
            self.assertEqual(completion.await_count, 0)
            search_web.assert_not_called()
            ingest_pdfs.assert_not_called()
            load_cached.assert_not_called()
            run_ingestion.assert_not_called()
            start_ingestion.assert_not_called()
        finally:
            client.close()
            main.app_state.clear()
            main.app_state.update(previous_state)
            main.QUERY_CACHE.clear()
            main.QUERY_CACHE.update(previous_cache)

    def test_scheme_browser_client_reads_filters_and_details_from_fastapi(self):
        responses = {
            "/api/v1/filters": {
                "departments": ["Agriculture"],
                "doc_types": ["pdf", "url"],
                "scheme_names": ["Micro Irrigation"],
            },
            "/api/v1/schemes/scheme-123": {
                "scheme_id": "scheme-123",
                "scheme_name": "Micro Irrigation",
                "description": "Indexed scheme details.",
            },
        }

        def handler(request):
            return httpx.Response(200, json=responses[request.url.path])

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            filters = get_scheme_filters("http://test", client)
            detail = get_scheme_detail("http://test", "scheme-123", client)

        self.assertEqual(filters["departments"], ["Agriculture"])
        self.assertEqual(detail["scheme_name"], "Micro Irrigation")

    def _write_pdf(self, file_path: Path) -> None:
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources = DictionaryObject()
        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = writer._add_object(font)
        resources[NameObject("/Font")] = fonts
        page[NameObject("/Resources")] = resources

        content = DecodedStreamObject()
        content.set_data(
            b"BT /F1 12 Tf 40 200 Td "
            b"(PDF agriculture fixture content for irrigation subsidies in Tamil Nadu.) Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(content)
        with file_path.open("wb") as pdf_file:
            writer.write(pdf_file)

    def test_predefined_query_catalog_includes_every_streamlit_combination(self):
        expected_sidebar_questions = {
            eligibility_query(farmer_type, crop_interest)
            for farmer_type in FARMER_TYPES
            for crop_interest in CROP_INTERESTS
        }
        self.assertEqual(len(expected_sidebar_questions), 9)
        self.assertTrue(expected_sidebar_questions.issubset(PREDEFINED_QUERIES))
        self.assertTrue(set(QUICK_QUERIES.values()).issubset(PREDEFINED_QUERIES))
        self.assertEqual(len(PREDEFINED_QUERIES), len(set(PREDEFINED_QUERIES)))

    def test_predefined_coverage_rejects_low_relevance_retrievals(self):
        class CoverageRetriever:
            def retrieve(self, query, top_k_dense=5, top_k_sparse=5):
                if query == "missing":
                    return []
                if query == "unscored":
                    return [
                        Document(
                            page_content="Relevant indexed agriculture evidence.",
                            metadata={},
                        )
                    ]
                if query == "invalid-score":
                    score = float("nan")
                else:
                    score = 0.01 if query == "low-score" else 0.5
                return [Document(page_content="Relevant indexed agriculture evidence.", metadata={"rerank_score": score})]

        with patch.object(
            main,
            "PREDEFINED_QUERIES",
            ("covered", "low-score", "missing", "unscored", "invalid-score"),
        ):
            self.assertEqual(
                main._missing_predefined_queries(cast(Any, CoverageRetriever())),
                ["low-score", "missing", "unscored", "invalid-score"],
            )

    def test_missing_predefined_coverage_is_ingested_before_startup_continues(self):
        previous_state = dict(main.app_state)
        main.app_state["rag_engine"] = object()

        async def fetch_official_sources():
            return [Document(page_content="Official agriculture evidence.")], []

        try:
            with (
                patch.object(
                    main,
                    "_missing_predefined_queries",
                    side_effect=[["uncovered question"], []],
                ),
                patch.object(ingest, "load_website_documents", side_effect=fetch_official_sources) as fetch,
                patch.object(ingest, "load_pdf_documents", return_value=[]) as load_pdfs,
                patch.object(ingest, "load_cached_text_documents", return_value=[]) as load_cached,
                patch.object(main, "_persist_incremental_documents", return_value={"chunks_added": 1}) as persist,
            ):
                self.assertEqual(asyncio.run(main._ensure_predefined_query_coverage()), [])
                fetch.assert_awaited_once_with()
                load_pdfs.assert_called_once_with()
                load_cached.assert_called_once_with()
                persist.assert_called_once()
                self.assertEqual(persist.call_args.args[0][0].page_content, "Official agriculture evidence.")
        finally:
            main.app_state.clear()
            main.app_state.update(previous_state)

    def test_website_ingestion_falls_back_to_http_when_async_subprocesses_are_unavailable(self):
        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url, headers=None):
                return httpx.Response(
                    200,
                    text=(
                        "<html><body><p>"
                        "Official agriculture guidance for farmers in Tamil Nadu "
                        "includes information about irrigation, crop management, "
                        "available government schemes, farmer eligibility, and "
                        "application procedures through the local agriculture office."
                        "</p></body></html>"
                    ),
                    request=httpx.Request("GET", url),
                )

        target = {"scheme": "Test scheme", "url": "https://example.test/agriculture"}
        with (
            patch(
                "playwright.async_api.async_playwright",
                side_effect=NotImplementedError("async subprocesses are unavailable"),
            ),
            patch("httpx.AsyncClient", return_value=FakeAsyncClient()),
        ):
            documents, failures = asyncio.run(ingest.load_website_documents([target]))

        self.assertFalse(failures)
        self.assertEqual(len(documents), 1)
        self.assertIn("Official agriculture guidance", documents[0].page_content)
        self.assertEqual(documents[0].metadata["source"], target["url"])

    def test_ingestion_index_is_retrieved_through_fastapi_client(self):
        self.assertEqual(Path(ingest.OUTPUT_INDEX_DIR), main.INDEX_DIR)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            storage_dir = root / "storage"
            pdfs_dir = storage_dir / "pdfs"
            index_dir = storage_dir / "faiss_index"
            data_dir.mkdir()
            storage_dir.mkdir()
            pdfs_dir.mkdir()
            self._write_pdf(data_dir / "irrigation.pdf")
            self._write_pdf(pdfs_dir / "new-inputs.pdf")

            url_content = (
                "This official agriculture page describes irrigation subsidies, "
                "eligibility rules, application steps, and assistance available "
                "to farmers in Tamil Nadu through the local agriculture office."
            )

            async def fake_load_website_documents(target_urls=None, progress_callback=None):
                return [
                    Document(
                        page_content=url_content,
                        metadata={
                            "source": "https://example.test/agriculture",
                            "scheme_name": "Fixture scheme",
                            "doc_type": "url",
                        },
                    )
                ], []

            with (
                patch.object(ingest, "DATA_DIR", str(data_dir)),
                patch.object(ingest, "STORAGE_DIR", str(storage_dir)),
                patch.object(ingest, "OUTPUT_INDEX_DIR", str(index_dir)),
                patch.object(
                    ingest,
                    "load_website_documents",
                    side_effect=fake_load_website_documents,
                ) as website_scraper,
                patch.object(ingest, "create_embeddings", return_value=FixtureEmbeddings()),
            ):
                with redirect_stdout(io.StringIO()):
                    ingest.run_ingestion()
                website_scraper.assert_called_once_with()

            self.assertTrue((index_dir / "index.faiss").is_file())
            self.assertTrue((index_dir / "index.pkl").is_file())

            vector_db = main.FAISS.load_local(
                str(index_dir),
                FixtureEmbeddings(),
                allow_dangerous_deserialization=True,
            )
            stored_text = [
                document.page_content
                for document in vector_db.similarity_search("irrigation subsidies", k=10)
            ]
            self.assertTrue(any("PDF agriculture fixture" in text for text in stored_text))
            self.assertTrue(
                any("official agriculture page" in text for text in stored_text),
                stored_text,
            )

            previous_index_dir = main.INDEX_DIR
            previous_storage_dir = main.STORAGE_DIR

            async def verify_fastapi_startup():
                async with main.lifespan(main.app):
                    self.assertIn("vector_db", main.app_state)
                    self.assertIn("rag_engine", main.app_state)
                    loaded_docs = main.app_state["vector_db"].similarity_search(
                        "irrigation subsidies",
                        k=10,
                    )
                    self.assertTrue(loaded_docs)
                    self.assertTrue(
                        any("PDF agriculture fixture" in doc.page_content for doc in loaded_docs)
                    )

            def discard_background_task(coroutine):
                coroutine.close()
                return None

            with (
                patch.object(main, "INDEX_DIR", index_dir),
                patch.object(main, "STORAGE_DIR", storage_dir),
                patch.object(main, "DirectOpenAIEmbeddings", return_value=FixtureEmbeddings()),
                patch.object(
                    main,
                    "AgriRAGEngine",
                    side_effect=lambda vector_db, storage_dir: LocalVectorRetriever(vector_db),
                ),
                patch.object(main, "AsyncOpenAI", return_value=object()),
                patch.object(main.asyncio, "create_task", side_effect=discard_background_task),
            ):
                asyncio.run(verify_fastapi_startup())

            self.assertEqual(main.INDEX_DIR, previous_index_dir)
            self.assertEqual(main.STORAGE_DIR, previous_storage_dir)

            previous_state = dict(main.app_state)
            previous_cache = dict(main.QUERY_CACHE)
            main.app_state.clear()
            main.app_state.update(
                vector_db=vector_db,
                rag_engine=LocalVectorRetriever(vector_db),
                async_client=SimpleNamespace(
                    chat=SimpleNamespace(
                        completions=SimpleNamespace(
                            create=self._create_completion_stream
                        )
                    )
                ),
            )
            main.QUERY_CACHE.clear()
            client = TestClient(main.app)
            try:
                with (
                    patch.object(
                        ingest,
                        "load_website_documents",
                        side_effect=AssertionError("A query must not scrape websites."),
                    ),
                    patch.object(
                        ingest,
                        "load_pdf_documents",
                        side_effect=AssertionError("A query must not ingest PDFs."),
                    ),
                ):
                    events = list(
                        stream_query_events(
                            "irrigation subsidies",
                            "http://testserver",
                            client=cast(httpx.Client, client),
                        )
                    )
                    query_response = client.post(
                        "/api/v1/query",
                        json={"query": "irrigation subsidies", "top_k": 5},
                    )
            finally:
                client.close()
                main.app_state.clear()
                main.app_state.update(previous_state)
                main.QUERY_CACHE.clear()
                main.QUERY_CACHE.update(previous_cache)

            source_events = [event for event in events if event.get("type") == "sources"]
            token_events = [event for event in events if event.get("type") == "token"]
            self.assertEqual(len(source_events), 1)
            returned_sources = source_events[0]["data"]
            self.assertTrue(returned_sources)
            self.assertIn("content", returned_sources[0])
            self.assertTrue(token_events)
            streamed_answer = "".join(event["content"] for event in token_events)
            self.assertIn("தமிழில் சோதனை பதில்", streamed_answer)
            self.assertIn("[S1]", streamed_answer)
            returned_source_ids = {f"[{source['id']}]" for source in returned_sources}
            cited_source_ids = set(re.findall(r"\[S\d+\]", streamed_answer))
            self.assertTrue(cited_source_ids)
            self.assertLessEqual(cited_source_ids, returned_source_ids)
            self.assertTrue(
                any(
                    source["url_or_file"] == "https://example.test/agriculture"
                    and source["document_name"]
                    for source in returned_sources
                )
            )

            self.assertEqual(query_response.status_code, 200)
            self.assertEqual(query_response.json()["status"], "pass")
            self.assertIn("[S1]", query_response.json()["answer"])
            self.assertLessEqual(
                set(re.findall(r"\[S\d+\]", query_response.json()["answer"])),
                {
                    f"[{source['id']}]"
                    for source in query_response.json()["sources"]
                },
            )
            self.assertEqual(self.completion_call_count, 2)
            user_prompt = self.generation_completion_request["messages"][1]["content"]
            self.assertIn("ஒவ்வொரு உண்மைத் தகவலின் முடிவிலும்", user_prompt)
            self.assertIn("[S1]", user_prompt)
            self.assertIn("Retrieved evidence:", self.last_completion_request["messages"][1]["content"])
            self.assertTrue(
                any(
                    document.metadata.get("scheme_name") == "new-inputs"
                    and document.metadata.get("page_number") == 1
                    for doc_id in vector_db.index_to_docstore_id.values()
                    for document in [vector_db.docstore.search(doc_id)]
                    if isinstance(document, Document)
                )
            )

    async def _create_completion_stream(self, **_kwargs):
        self.completion_call_count = getattr(self, "completion_call_count", 0) + 1
        self.last_completion_request = _kwargs
        if _kwargs.get("stream"):
            self.generation_completion_request = _kwargs
        if not _kwargs.get("stream"):
            content = json.dumps(
                {
                    "grounded": True,
                    "claims": [
                        {
                            "claim": "The advisory and dossier are supported.",
                            "source_ids": ["S1"],
                            "supported": True,
                        }
                    ],
                }
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content)
                    )
                ]
            )
        return MockCompletionStream()

    def test_predefined_queries_never_trigger_source_ingestion(self):
        vector_db = main.FAISS.from_documents(
            [
                Document(
                    page_content="Tamil Nadu agriculture source indexed for query testing.",
                    metadata={"source": "fixture.txt", "scheme_name": "Fixture"},
                )
            ],
            FixtureEmbeddings(),
        )
        previous_state = dict(main.app_state)
        previous_cache = dict(main.QUERY_CACHE)
        main.app_state.clear()
        main.app_state.update(
            vector_db=vector_db,
            rag_engine=LocalVectorRetriever(vector_db),
            async_client=SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(
                        create=self._create_completion_stream
                    )
                )
            ),
        )
        main.QUERY_CACHE.clear()
        client = TestClient(main.app)
        try:
            with (
                patch.object(
                    ingest,
                    "load_website_documents",
                    side_effect=AssertionError("Chat queries must not scrape websites."),
                ) as scrape_websites,
                patch.object(
                    ingest,
                    "load_pdf_documents",
                    side_effect=AssertionError("Chat queries must not ingest PDFs."),
                ) as ingest_pdfs,
                patch.object(
                    ingest,
                    "load_cached_text_documents",
                    side_effect=AssertionError("Chat queries must not reload source files."),
                ) as load_cached_text,
                patch.object(
                    main,
                    "_run_ingestion_job",
                    side_effect=AssertionError("Chat queries must not start ingestion jobs."),
                ) as start_ingestion,
            ):
                for query in main.PREDEFINED_QUERIES:
                    events = list(
                        stream_query_events(
                            query,
                            "http://testserver",
                            client=cast(httpx.Client, client),
                        )
                    )
                    self.assertTrue(
                        any(event.get("type") == "sources" for event in events),
                        query,
                    )
                    response = client.post(
                        "/api/v1/query",
                        json={"query": query, "top_k": 5},
                    )
                    self.assertEqual(response.status_code, 200, query)
                    self.assertEqual(response.json()["status"], "pass", query)

            scrape_websites.assert_not_called()
            ingest_pdfs.assert_not_called()
            load_cached_text.assert_not_called()
            start_ingestion.assert_not_called()
        finally:
            client.close()
            main.app_state.clear()
            main.app_state.update(previous_state)
            main.QUERY_CACHE.clear()
            main.QUERY_CACHE.update(previous_cache)

    def test_refresh_ingestion_includes_cached_text_sources(self):
        website_document = Document(
            page_content="Official website source text.",
            metadata={"source": "https://example.test", "scheme_name": "Website"},
        )
        pdf_document = Document(
            page_content="PDF source text.",
            metadata={"source": "example.pdf", "scheme_name": "PDF"},
        )
        text_document = Document(
            page_content="Cached source text.",
            metadata={"source": "./storage\\cached.txt", "scheme_name": "cached"},
        )

        async def load_websites(*_args, **_kwargs):
            return [website_document], []

        job_id = "refresh-text-test"
        main.INGESTION_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
        }
        try:
            with (
                patch.object(ingest, "load_website_documents", side_effect=load_websites),
                patch.object(ingest, "load_pdf_documents", return_value=[pdf_document]),
                patch.object(
                    ingest,
                    "load_cached_text_documents",
                    return_value=[text_document],
                ) as load_text,
                patch.object(
                    main,
                    "_persist_incremental_documents",
                    return_value={"documents": 3, "chunks_added": 3, "vectors_total": 3},
                ) as persist,
            ):
                main._run_ingestion_job(job_id, "refresh")

            load_text.assert_called_once_with()
            ingested_documents = persist.call_args.args[0]
            self.assertEqual(
                {document.page_content for document in ingested_documents},
                {
                    "Official website source text.",
                    "PDF source text.",
                    "Cached source text.",
                },
            )
            self.assertEqual(main.INGESTION_JOBS[job_id]["status"], "completed")
        finally:
            main.INGESTION_JOBS.pop(job_id, None)

    def test_cached_text_loader_preserves_incremental_source_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "scheme.txt").write_text(
                "Agriculture scheme details. " * 10,
                encoding="utf-8",
            )
            with patch.object(ingest, "STORAGE_DIR", str(root)):
                documents = ingest.load_cached_text_documents()

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].metadata["source"], f"./storage{os.sep}scheme.txt")
        self.assertEqual(documents[0].metadata["scheme_name"], "scheme")
        self.assertEqual(documents[0].metadata["doc_type"], "cached_text")

    def test_scheme_search_filters_and_detail_use_index_metadata(self):
        documents = [
            Document(
                page_content="Official irrigation subsidy for farmers.",
                metadata={
                    "scheme_name": "Micro Irrigation",
                    "source": "https://example.gov/irrigation",
                    "doc_type": "url",
                    "department": "Agriculture",
                    "ingested_at": "2026-10-14T10:00:00+00:00",
                },
            ),
            Document(
                page_content="PDF page about crop support.",
                metadata={
                    "scheme_name": "Crop Support",
                    "source": "crop-support.pdf",
                    "doc_type": "pdf",
                    "page_number": 2,
                },
            ),
        ]
        vector_db = main.FAISS.from_documents(documents, FixtureEmbeddings())
        previous_state = dict(main.app_state)
        main.app_state["vector_db"] = vector_db
        client = TestClient(main.app)
        try:
            filters = get_scheme_filters(
                "http://testserver", client=cast(httpx.Client, client)
            )
            self.assertEqual(set(filters["doc_types"]), {"pdf", "url"})
            self.assertIn("Micro Irrigation", filters["scheme_names"])
            filters_response = client.get("/api/v1/filters")
            self.assertEqual(filters_response.status_code, 200)
            search_result = search_schemes(
                "http://testserver",
                query="irrigation",
                department="Agriculture",
                client=cast(httpx.Client, client),
            )
            self.assertEqual(search_result["total"], 1)
            item = search_result["items"][0]
            detail = get_scheme_detail(
                "http://testserver",
                item["scheme_id"],
                client=cast(httpx.Client, client),
            )
            self.assertEqual(detail["scheme_name"], "Micro Irrigation")
            self.assertEqual(
                detail["ingested_at"], "2026-10-14T10:00:00+00:00"
            )
            self.assertEqual(client.get("/api/v1/schemes/unknown").status_code, 404)
            first_page = client.get("/api/v1/schemes", params={"page": 1, "page_size": 1})
            second_page = client.get("/api/v1/schemes", params={"page": 2, "page_size": 1})
            self.assertEqual(first_page.json()["total"], 2)
            self.assertEqual(len(first_page.json()["items"]), 1)
            self.assertEqual(len(second_page.json()["items"]), 1)
            self.assertNotEqual(
                first_page.json()["items"][0]["scheme_id"],
                second_page.json()["items"][0]["scheme_id"],
            )
        finally:
            client.close()
            main.app_state.clear()
            main.app_state.update(previous_state)

    def test_ingestion_endpoints_start_jobs(self):
        client = TestClient(main.app)
        try:
            with patch.object(
                main, "_start_ingestion_job", return_value={"job_id": "test-job"}
            ):
                for route in (
                    "/api/v1/ingestion/websites",
                    "/api/v1/ingestion/pdfs",
                    "/api/v1/ingestion/refresh",
                ):
                    with self.subTest(route=route):
                        self.assertEqual(client.post(route).status_code, 202)
        finally:
            client.close()

    def test_ingestion_jobs_report_progress_and_reject_duplicates(self):
        client = TestClient(main.app)

        def keep_job_running(job_id, kind, website_targets=None):
            main._set_job(job_id, status="running", progress=35, message="Test running.")

        try:
            with patch.object(main, "_run_ingestion_job", keep_job_running):
                response = client.post("/api/v1/ingestion/pdfs")
                self.assertEqual(response.status_code, 202)
                job_id = response.json()["job_id"]
                status = client.get(f"/api/v1/ingestion/jobs/{job_id}")
                self.assertEqual(status.status_code, 200)
                self.assertEqual(status.json()["status"], "running")
                self.assertEqual(status.json()["progress"], 35)
                duplicate = client.post("/api/v1/ingestion/refresh")
                self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(client.get("/api/v1/ingestion/jobs/missing").status_code, 404)
        finally:
            client.close()
            main.INGESTION_JOBS.clear()

    def test_incremental_ingestion_replaces_source_and_persists_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_dir = root / "storage"
            index_dir = storage_dir / "faiss_index"
            index_dir.mkdir(parents=True)
            original = Document(
                page_content="Old indexed version of the same source.",
                metadata={"source": "https://example.test/scheme", "scheme_name": "Scheme"},
            )
            unrelated = Document(
                page_content="Unrelated source which must remain in the index.",
                metadata={"source": "https://example.test/other", "scheme_name": "Other"},
            )
            original_db = main.FAISS.from_documents(
                [original, unrelated], FixtureEmbeddings()
            )
            original_db.save_local(str(index_dir))

            previous_state = dict(main.app_state)
            main.app_state.clear()
            main.app_state["embeddings"] = FixtureEmbeddings()
            replacement = Document(
                page_content="Updated indexed version with new eligibility information.",
                metadata={
                    "source": "https://example.test/scheme",
                    "scheme_name": "Scheme",
                    "doc_type": "url",
                },
            )
            try:
                with (
                    patch.object(main, "INDEX_DIR", index_dir),
                    patch.object(main, "STORAGE_DIR", storage_dir),
                    patch.object(main, "AgriRAGEngine", return_value=object()),
                ):
                    result = main._persist_incremental_documents([replacement])
                updated_db = main.FAISS.load_local(
                    str(index_dir),
                    FixtureEmbeddings(),
                    allow_dangerous_deserialization=True,
                )
                stored = [
                    document
                    for doc_id in updated_db.index_to_docstore_id.values()
                    for document in [updated_db.docstore.search(doc_id)]
                    if isinstance(document, Document)
                ]
                self.assertEqual(result["replaced_chunks"], 1)
                self.assertEqual(len(stored), 2)
                self.assertTrue(
                    any("Updated indexed version" in doc.page_content for doc in stored)
                )
                self.assertTrue(
                    any("Unrelated source" in doc.page_content for doc in stored)
                )
                self.assertEqual(len(list(Path(result["backup"]).glob("index.*"))), 2)
            finally:
                main.app_state.clear()
                main.app_state.update(previous_state)


if __name__ == "__main__":
    unittest.main()
