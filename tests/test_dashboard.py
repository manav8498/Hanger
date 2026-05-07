from __future__ import annotations

from httpx import AsyncClient


async def test_dashboard_html_served(client: AsyncClient) -> None:
    response = await client.get("/dashboard/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Hangar</title>" in response.text
    assert "dashboard.js" in response.text
    assert "dashboard.css" in response.text


async def test_dashboard_js_served(client: AsyncClient) -> None:
    response = await client.get("/dashboard/dashboard.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


async def test_dashboard_css_served(client: AsyncClient) -> None:
    response = await client.get("/dashboard/dashboard.css")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


async def test_dashboard_redirect_without_trailing_slash(client: AsyncClient) -> None:
    response = await client.get("/dashboard")

    assert response.status_code in {307, 308}
    assert response.headers["location"] == "/dashboard/"
