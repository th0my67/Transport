import pytest
from sqlalchemy.orm import sessionmaker

from tl_delay_collector.db import make_engine


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    return sessionmaker(engine)
