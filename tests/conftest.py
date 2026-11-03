import pytest


@pytest.fixture
def mock_pin_factory():
    from gpiozero.pins.mock import MockFactory

    factory = MockFactory()
    yield factory
    factory.reset()
