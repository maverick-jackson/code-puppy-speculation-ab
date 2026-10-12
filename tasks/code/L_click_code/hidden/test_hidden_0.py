import click
from click.testing import CliRunner


def test_open_bounds_clamp_inside_range():
    t = click.IntRange(0, 10, min_open=True, max_open=True, clamp=True)
    assert t.convert(15, None, None) == 9
    assert t.convert(-5, None, None) == 1
    assert t.convert(10, None, None) == 9
    assert t.convert(0, None, None) == 1
    assert t.convert(5, None, None) == 5


def test_closed_bounds_clamp_unchanged():
    t = click.IntRange(0, 10, clamp=True)
    assert t.convert(15, None, None) == 10
    assert t.convert(-1, None, None) == 0


def test_cli_open_max_clamp():
    @click.command()
    @click.option("--n", type=click.IntRange(1, 5, max_open=True, clamp=True))
    def cli(n):
        click.echo(n)

    r = CliRunner().invoke(cli, ["--n", "99"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "4"


def test_open_without_clamp_still_fails():
    @click.command()
    @click.option("--n", type=click.IntRange(1, 5, max_open=True))
    def cli(n):
        click.echo(n)

    r = CliRunner().invoke(cli, ["--n", "5"])
    assert r.exit_code == 2
