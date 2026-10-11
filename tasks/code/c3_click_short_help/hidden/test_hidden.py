import click
from click.testing import CliRunner
from click.utils import make_default_short_help


def test_stops_at_first_sentence():
    text = "Initialize the repo. Creates files and directories as needed."
    assert make_default_short_help(text) == "Initialize the repo."


def test_long_text_without_period_is_truncated():
    text = "Fetch every remote branch and prune deleted ones and then report"
    out = make_default_short_help(text)
    assert out.endswith("...") and len(out) <= 45


def test_short_text_untouched():
    assert make_default_short_help("Show status") == "Show status"
    assert make_default_short_help("Show status.") == "Show status."


def test_group_listing_uses_first_sentence():
    @click.group()
    def cli():
        pass

    @cli.command()
    def init():
        """Initialize the repo. Creates files and directories as needed."""

    r = CliRunner().invoke(cli, ["--help"])
    assert r.exit_code == 0
    line = [ln for ln in r.output.splitlines() if ln.strip().startswith("init")][0]
    assert line.split(None, 1)[1].strip() == "Initialize the repo."
