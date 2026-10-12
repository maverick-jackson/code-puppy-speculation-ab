import click
import pytest
from click.testing import CliRunner


@click.command()
@click.option("--debug", type=bool)
def cli(debug):
    click.echo(repr(debug))


@pytest.mark.parametrize("raw,want", [
    ("True", True), ("YES", True), ("On", True), ("Y", True), ("T", True),
    ("False", False), ("NO", False), ("Off", False), ("N", False), ("F", False),
    ("true", True), ("off", False), ("1", True), ("0", False), (" Yes ", True),
])
def test_bool_spellings(raw, want):
    assert click.BOOL.convert(raw, None, None) is want


def test_cli_capitalized_value():
    r = CliRunner().invoke(cli, ["--debug", "TRUE"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "True"


def test_invalid_still_rejected():
    r = CliRunner().invoke(cli, ["--debug", "maybe"])
    assert r.exit_code == 2
    assert "is not a valid boolean" in r.output
