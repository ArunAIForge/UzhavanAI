import json
from collections.abc import Iterator

import httpx


class BackendStreamError(RuntimeError):
    pass


def stream_query_events(
    query: str,
    base_url: str,
    top_k: int = 5,
    client: httpx.Client | None = None,
    filters: dict[str, str] | None = None,
) -> Iterator[dict]:
    if client is not None:
        yield from _read_query_events(client, query, base_url, top_k, filters)
        return

    timeout = httpx.Timeout(180.0, connect=5.0)
    with httpx.Client(timeout=timeout) as backend_client:
        yield from _read_query_events(
            backend_client, query, base_url, top_k, filters
        )


def _read_query_events(
    client: httpx.Client,
    query: str,
    base_url: str,
    top_k: int,
    filters: dict[str, str] | None,
) -> Iterator[dict]:
    url = f"{base_url.rstrip('/')}/api/v1/query/stream"
    with client.stream(
        "POST",
        url,
        json={"query": query, "top_k": top_k, "filters": filters or {}},
        headers={"Accept": "text/event-stream"},
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue

            payload = line[5:].strip()
            if payload == "[DONE]":
                return

            try:
                event = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise BackendStreamError("FastAPI returned an invalid stream event.") from exc

            if not isinstance(event, dict):
                raise BackendStreamError("FastAPI returned an invalid stream event.")
            if event.get("type") == "error":
                raise BackendStreamError(str(event.get("content", "Backend query failed.")))

            yield event


def get_scheme_filters(base_url: str, client: httpx.Client | None = None) -> dict:
    if client is not None:
        response = client.get(f"{base_url.rstrip('/')}/api/v1/filters")
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise BackendStreamError("FastAPI returned invalid scheme filters.")
        if any(
            not isinstance(result.get(key), list)
            for key in ("departments", "doc_types", "scheme_names")
        ):
            raise BackendStreamError("FastAPI returned invalid scheme filters.")
        if any(
            not all(isinstance(option, str) for option in result[key])
            for key in ("departments", "doc_types", "scheme_names")
        ):
            raise BackendStreamError("FastAPI returned invalid scheme filters.")
        return result
    with httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0)) as backend_client:
        return get_scheme_filters(base_url, backend_client)


def get_scheme_detail(
    base_url: str,
    scheme_id: str,
    client: httpx.Client | None = None,
) -> dict:
    if client is not None:
        response = client.get(
            f"{base_url.rstrip('/')}/api/v1/schemes/{scheme_id}"
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not isinstance(
            result.get("scheme_id"), str
        ):
            raise BackendStreamError("FastAPI returned invalid scheme details.")
        return result
    with httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0)) as backend_client:
        return get_scheme_detail(base_url, scheme_id, backend_client)


def search_schemes(
    base_url: str,
    query: str = "",
    department: str = "",
    doc_type: str = "",
    page: int = 1,
    page_size: int = 10,
    client: httpx.Client | None = None,
) -> dict:
    params = {
        "query": query,
        "page": page,
        "page_size": page_size,
    }
    if department:
        params["department"] = department
    if doc_type:
        params["doc_type"] = doc_type
    if client is not None:
        response = client.get(
            f"{base_url.rstrip('/')}/api/v1/schemes", params=params
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise BackendStreamError("FastAPI returned invalid scheme search results.")
        return result
    with httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0)) as backend_client:
        return search_schemes(
            base_url, query, department, doc_type, page, page_size, backend_client
        )
