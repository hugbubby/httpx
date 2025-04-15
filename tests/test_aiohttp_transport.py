import pytest

import httpx
from httpx._transports.aiohttp import AioHTTPTransport

try:
    import aiohttp
    has_aiohttp = True
except ImportError:
    has_aiohttp = False


@pytest.mark.skipif(not has_aiohttp, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_aiohttp_transport():
    """
    Test that AioHTTPTransport can be used as a transport for AsyncClient.
    """
    transport = AioHTTPTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://httpbin.org/get")
        assert response.status_code == 200
        assert response.json()["url"] == "https://httpbin.org/get"


@pytest.mark.skipif(not has_aiohttp, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_aiohttp_transport_is_default():
    """
    Test that AioHTTPTransport is the default transport when aiohttp is installed.
    """
    async with httpx.AsyncClient() as client:
        assert isinstance(client._transport, AioHTTPTransport)


@pytest.mark.skipif(not has_aiohttp, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_proxy_with_aiohttp_transport():
    """
    Test that proxies work with AioHTTPTransport.
    """
    # This test uses a mock proxy
    transport = AioHTTPTransport(proxy="http://example.org")
    async with httpx.AsyncClient(transport=transport) as client:
        # This should raise a connection error since the proxy doesn't exist
        with pytest.raises(httpx.NetworkError):
            await client.get("https://httpbin.org/get")


@pytest.mark.skipif(not has_aiohttp, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_aiohttp_transport_headers():
    """
    Test that headers are properly passed to AioHTTPTransport.
    """
    headers = {"User-Agent": "test-agent", "X-Test": "test-value"}
    transport = AioHTTPTransport()
    async with httpx.AsyncClient(transport=transport, headers=headers) as client:
        response = await client.get("https://httpbin.org/headers")
        assert response.status_code == 200
        response_headers = response.json()["headers"]
        assert response_headers["User-Agent"] == "test-agent"
        assert response_headers["X-Test"] == "test-value"


@pytest.mark.skipif(not has_aiohttp, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_aiohttp_transport_cookies():
    """
    Test that cookies are properly passed to AioHTTPTransport.
    """
    cookies = {"test-cookie": "test-value"}
    transport = AioHTTPTransport()
    async with httpx.AsyncClient(transport=transport, cookies=cookies) as client:
        response = await client.get("https://httpbin.org/cookies")
        assert response.status_code == 200
        assert response.json()["cookies"]["test-cookie"] == "test-value"