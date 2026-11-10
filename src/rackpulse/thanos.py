import asyncio
import httpx


class QueryError(Exception):
    """Safe error: never includes URLs, headers or remote response bodies."""


class ThanosClient:
    def __init__(self, url, client=None, token=None, timeout=30, attempts=3, backoff=1):
        self.url = url.rstrip('/')
        self.client = client
        self.token = token
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff

    async def query_range(self, query, start, end, step=60):
        if self.client is None:
            async with httpx.AsyncClient() as client:
                return await self._query(client, query, start, end, step)
        return await self._query(self.client, query, start, end, step)

    async def _query(self, client, query, start, end, step):
        def stamp(v):
            return v.timestamp() if hasattr(v, 'timestamp') else v
        for attempt in range(self.attempts):
            try:
                response = await client.get(self.url + '/api/v1/query_range', params={'query': query, 'start': stamp(start), 'end': stamp(end), 'step': step, 'dedup': 'true', 'partial_response': 'false', 'max_source_resolution': '0s'}, headers={'Authorization': f'Bearer {self.token}'} if self.token else {}, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.ConnectError('transient')
                if response.status_code != 200:
                    raise QueryError(f'query_http_{response.status_code}')
                body = response.json()
                if body.get('status') != 'success' or body.get('warnings'):
                    raise QueryError('query_partial_or_failed')
                if body['data']['resultType'] != 'matrix':
                    raise QueryError('query_not_matrix')
                return body['data']['result']
            except (httpx.TransportError, ValueError, KeyError, TypeError):
                if attempt + 1 == self.attempts:
                    raise QueryError('query_unavailable_or_invalid') from None
                await asyncio.sleep(self.backoff * 2**attempt)
        raise QueryError('query_attempts_exhausted')
