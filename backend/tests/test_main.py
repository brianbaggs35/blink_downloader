"""App factory: docs exposure per environment."""

from app.main import app as module_app
from app.main import create_app
from tests.conftest import PlainSettings


def test_module_level_app_exists() -> None:
    assert module_app.title == "Blink AI Security Platform"


def test_docs_enabled_outside_production() -> None:
    app = create_app(PlainSettings(environment="test"))
    assert app.docs_url == "/api/docs"
    assert app.openapi_url == "/api/openapi.json"
    assert app.redoc_url is None


def test_docs_disabled_in_production() -> None:
    settings = PlainSettings(
        environment="production",
        secret_key="x" * 43,
        encryption_key="iRZbYNDbXbGGoHy4JV2XChcPYDbdCTC9YXf29CQzB1I=",
    )
    app = create_app(settings)
    assert app.docs_url is None
    assert app.openapi_url is None
