# -*- coding: utf-8 -*-
from heapq import nlargest
import math
from numbers import Real
from typing import List
from rank_bm25 import BM25Okapi
from flashrank import Ranker, RerankRequest
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

class AgriRAGEngine:
    def __init__(self, vector_db: FAISS, storage_dir: str = "./storage"):
        self.vector_db = vector_db
        self.storage_dir = storage_dir
        self.documents = self._load_index_corpus()
        self.tokenized_corpus = [
            doc.page_content.lower().split() for doc in self.documents
        ]
        self.bm25 = BM25Okapi(self.tokenized_corpus) if self.tokenized_corpus else None
        self.reranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2")

    def _load_index_corpus(self) -> List[Document]:
        """Use the indexed chunks for both dense and lexical retrieval."""
        documents: List[Document] = []
        for doc_id in self.vector_db.index_to_docstore_id.values():
            document = self.vector_db.docstore.search(doc_id)
            if isinstance(document, Document):
                documents.append(document)
        return documents

    @staticmethod
    def _matches_filters(document: Document, filters: dict[str, str] | None) -> bool:
        if not filters:
            return True
        metadata = document.metadata
        return all(
            str(metadata.get(key, "")).casefold() == value.casefold()
            for key, value in filters.items()
            if value
        )

    def retrieve(
        self,
        query: str,
        top_k_dense: int = 5,
        top_k_sparse: int = 5,
        filters: dict[str, str] | None = None,
        top_k_results: int = 4,
    ) -> List[Document]:
        """Runs metadata-filtered dense and sparse search, then reranks candidates."""
        if top_k_dense < 1 or top_k_sparse < 1 or top_k_results < 1:
            raise ValueError("Retrieval top-K values must be positive integers.")

        dense_docs = self.vector_db.similarity_search(
            query,
            k=top_k_dense,
            filter=filters or None,
        )
        dense_docs = [
            document for document in dense_docs
            if self._matches_filters(document, filters)
        ]

        sparse_docs = []
        if self.bm25 and self.documents:
            query_tokens = query.lower().split()
            bm25_scores = self.bm25.get_scores(query_tokens)
            matching_indices = [
                index
                for index, document in enumerate(self.documents)
                if self._matches_filters(document, filters)
            ]
            top_indices = nlargest(
                top_k_sparse,
                matching_indices,
                key=bm25_scores.__getitem__,
            )
            sparse_docs = [
                self.documents[index]
                for index in top_indices
                if bm25_scores[index] > 0
            ][:top_k_sparse]

        candidate_map = {}
        for d in dense_docs + sparse_docs:
            fingerprint = (
                str(d.metadata.get("source", "")),
                d.page_content[:90].strip().lower(),
            )
            if fingerprint not in candidate_map and len(d.page_content.strip()) > 20:
                candidate_map[fingerprint] = d

        candidates = list(candidate_map.values())
        if not candidates:
            return []

        passages = [
            {"id": idx, "text": d.page_content, "meta": d.metadata}
            for idx, d in enumerate(candidates)
        ]
        rerank_request = RerankRequest(query=query, passages=passages)
        ranked_results = self.reranker.rerank(rerank_request)

        final_docs = []
        for item in ranked_results[:top_k_results]:
            score = item.get("score")
            if isinstance(score, bool) or not isinstance(score, Real):
                continue
            score = float(score)
            if not math.isfinite(score):
                continue
            final_docs.append(
                Document(
                    page_content=item["text"],
                    metadata={
                        **item.get("meta", {}),
                        "rerank_score": round(score, 4)
                    }
                )
            )
        return final_docs