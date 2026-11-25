"""La chaîne Alembic doit avoir une seule tête, sinon `alembic upgrade head` échoue au démarrage."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_exactly_one_head() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1, f"Plusieurs têtes Alembic : {heads}"
