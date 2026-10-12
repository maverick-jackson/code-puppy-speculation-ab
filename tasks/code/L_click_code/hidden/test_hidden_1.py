import click
from click.testing import CliRunner


@click.command()
@click.option("--name")
@click.option("--flag/--no-flag", default=False)
def cli(name, flag):
    click.echo(f"{name}|{flag}")


def run(args):
    r = CliRunner().invoke(cli, args)
    assert r.exit_code == 0, r.output
    return r.output.strip()


def test_value_containing_equals():
    assert run(["--name=a=b=c"]) == "a=b=c|False"
    assert run(["--name=key=value", "--flag"]) == "key=value|True"


def test_plain_forms_still_work():
    assert run(["--name=x"]) == "x|False"
    assert run(["--name", "p=q"]) == "p=q|False"
    assert run(["--name="]) == "|False"


def test_unknown_option_with_equals_still_errors():
    r = CliRunner().invoke(cli, ["--nope=1=2"])
    assert r.exit_code == 2
    assert "--nope" in r.output
