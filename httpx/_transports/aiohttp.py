from __future__ import annotations

import typing
from types import TracebackType
import ssl
import asyncio

import aiohttp

from .._config import DEFAULT_LIMITS, Limits, Proxy, create_ssl_context
from .._exceptions import (
    ConnectError,
    ConnectTimeout,
    LocalProtocolError,
    NetworkError,
    PoolTimeout,
    ProtocolError,
    ProxyError,
    ReadError,
    ReadTimeout,
    RemoteProtocolError,
    TimeoutException,
    UnsupportedProtocol,
    WriteError,
    WriteTimeout,
)
from .._models import Request, Response
from .._types import AsyncByteStream
from .._urls import URL
from .base import AsyncBaseTransport

A = typing.TypeVar("A", bound="AioHTTPTransport")

__all__ = ["AioHTTPTransport"]


class AsyncResponseStream(AsyncByteStream):
    def __init__(self, content: aiohttp.StreamReader) -> None:
        self._content = content

    async def __aiter__(self) -> typing.AsyncIterator[bytes]:
        try:
            while True:
                chunk = await self._content.read(65536)
                if not chunk:
                    break
                yield chunk
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise NetworkError(str(exc)) from exc

    async def aclose(self) -> None:
        pass


class AioHTTPTransport(AsyncBaseTransport):
    def __init__(
        self,
        verify: ssl.SSLContext | str | bool = True,
        cert: typing.Any | None = None,
        trust_env: bool = True,
        http1: bool = True,
        http2: bool = False,
        limits: Limits = DEFAULT_LIMITS,
        proxy: str | URL | Proxy | None = None,
        socket_options: typing.Any | None = None,
        **kwargs: typing.Any,
    ) -> None:
        proxy = Proxy(url=proxy) if isinstance(proxy, (str, URL)) else proxy
        ssl_context = create_ssl_context(verify=verify, cert=cert, trust_env=trust_env)

        # Configure aiohttp-specific options
        self._timeout = aiohttp.ClientTimeout(
            total=None,  # httpx handles timeouts at a higher level
            connect=None,
            sock_connect=None,
            sock_read=None,
        )

        connector_kwargs = {
            "ssl": ssl_context,
            "limit": limits.max_connections,
            "enable_cleanup_closed": True,
            "force_close": False,
            "limit_per_host": limits.max_keepalive_connections,
            "ttl_dns_cache": limits.keepalive_expiry
        }

        # Handle proxy configuration
        if proxy is not None:
            if proxy.url.scheme in ("http", "https"):
                connector_kwargs["proxy"] = str(proxy.url)
                if proxy.headers:
                    connector_kwargs["proxy_headers"] = dict(proxy.headers.items())
            else:
                raise ValueError(
                    "AioHTTPTransport only supports HTTP proxies, not "
                    f"{proxy.url.scheme!r}."
                )

        # Create connector
        if http2:
            try:
                import aiohttp_http2
                self._connector = aiohttp_http2.HTTP2ClientConnector(**connector_kwargs)
            except ImportError:
                raise ImportError(
                    "Using HTTP/2 with aiohttp requires aiohttp_http2 to be installed. "
                    "Install it with `pip install aiohttp_http2`."
                ) from None
        else:
            self._connector = aiohttp.TCPConnector(**connector_kwargs)

        self._session = None
        self._session_kwargs = {
            "connector": self._connector,
            "timeout": self._timeout,
            "auto_decompress": False,  # HTTPX handles content-encoding
            "trust_env": trust_env,
        }

    async def __aenter__(self: A) -> A:
        if self._session is None:
            self._session = aiohttp.ClientSession(**self._session_kwargs)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self.aclose()

    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        if self._session is None:
            self._session = aiohttp.ClientSession(**self._session_kwargs)

        # Convert HTTPX request to aiohttp request
        url = str(request.url)
        headers = dict(request.headers.items())
        method = request.method.decode("ascii") if isinstance(request.method, bytes) else request.method
        
        # Handle request content
        data = None
        if hasattr(request.stream, "__aiter__"):
            data = aiohttp.StreamReader()
            async for chunk in request.stream:
                data.feed_data(chunk)
            data.feed_eof()

        try:
            # Send request
            async with self._session.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                allow_redirects=False,  # HTTPX handles redirects
            ) as aiohttp_response:
                # Convert aiohttp response to HTTPX response
                status_code = aiohttp_response.status
                headers = [(k.encode("ascii"), v.encode("ascii")) for k, v in aiohttp_response.headers.items()]
                
                # Handle response body
                return Response(
                    status_code=status_code,
                    headers=headers,
                    stream=AsyncResponseStream(aiohttp_response.content),
                    extensions={},
                )
                
        except aiohttp.ClientError as exc:
            # Map aiohttp exceptions to HTTPX exceptions
            if isinstance(exc, aiohttp.ClientConnectorError):
                raise ConnectError(str(exc)) from exc
            elif isinstance(exc, aiohttp.ClientOSError):
                raise NetworkError(str(exc)) from exc
            elif isinstance(exc, aiohttp.ServerDisconnectedError):
                raise RemoteProtocolError(str(exc)) from exc
            elif isinstance(exc, aiohttp.ClientResponseError):
                raise ProtocolError(str(exc)) from exc
            elif isinstance(exc, aiohttp.ClientPayloadError):
                raise ReadError(str(exc)) from exc
            else:
                raise NetworkError(str(exc)) from exc
        except asyncio.TimeoutError as exc:
            raise TimeoutException(str(exc)) from exc

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        
        if hasattr(self._connector, "close"):
            await self._connector.close()