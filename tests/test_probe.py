import httpx
import pytest
import respx

from astro_datalake.probe import probe_one
from astro_datalake.sources.registry import SOURCES


@pytest.mark.asyncio
async def test_probe_one_marks_2xx_as_alive():
    spec = SOURCES["nssdc_planetary_factsheet"]
    with respx.mock(assert_all_called=True) as mock:
        mock.get(spec.probe_url).mock(return_value=httpx.Response(200, text="ok"))
        async with httpx.AsyncClient() as client:
            result = await probe_one(client, "nssdc_planetary_factsheet")
    assert result["alive"] is True
    assert result["http_status"] == 200


@pytest.mark.asyncio
async def test_probe_one_marks_5xx_as_dead():
    spec = SOURCES["cneos_cad"]
    with respx.mock(assert_all_called=True) as mock:
        mock.get(spec.probe_url).mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            result = await probe_one(client, "cneos_cad")
    assert result["alive"] is False
    assert result["http_status"] == 503


@pytest.mark.asyncio
async def test_probe_one_skips_sources_requiring_credentials():
    async with httpx.AsyncClient() as client:
        result = await probe_one(client, "spacetrack")
    assert result["alive"] is None
    assert "credentials" in result["error"]
