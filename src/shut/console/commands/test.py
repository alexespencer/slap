
import typing as t

from shut.console.command import Command, IO, argument, option
from shut.console.application import Application
from shut.plugins.application_plugin import ApplicationPlugin


class TestRunner:

  def __init__(self, name: str, config: t.Any, io: IO) -> None:
    assert isinstance(config, str), type(config)
    self.name = name
    self.config = config
    self.io = io

  def run(self) -> int:
    import subprocess as sp

    self.io.write_line(f'<comment>running test <b>{self.name}</b></comment>:')
    return sp.call(self.config, shell=True)


class TestCommand(Command):
  """
  Execute the tests configured in <info>tool.shut.test</info>.

  <b>Example</b>

    <fg=cyan>[tool.shut.test]</fg>
    <fg=green>pytest</fg> = <fg=yellow>"pytest --cov=my_package tests/"</fg>
    <fg=green>mypy</fg> = <fg=yellow>"mypy src"</fg>
  """

  name = "test"
  description = "Execute all tests configured in <info>tool.shut.test</info>"
  arguments = [
    argument("test", "One or more tests to run (runs all if none are specified)", optional=True, multiple=True),
  ]

  def __init__(self, app: Application) -> None:
    super().__init__()
    self.app = app

  def handle(self) -> int:
    test_config = self.app.load_pyproject().get('tool', {}).get('shut', {}).get('test', {})
    if not test_config:
      self.line_error('error: no tests configured in <info>tool.shut.test</info>', 'error')
      return 1

    tests = tests if (tests := self.argument("test")) else sorted(test_config.keys())
    if (unknown_tests := set(tests) - test_config.keys()):
      self.line_error(
        f'error: unknown test{"" if len(unknown_tests) == 1 else "s"} <b>{", ".join(unknown_tests)}</b>',
        'error'
      )
      return 1

    results = {}
    for test_name in tests:
      results[test_name] = TestRunner(test_name, test_config[test_name], self.io).run()

    if len(tests) > 1:
      self.line('\n<comment>test summary:</comment>')
      for test_name, exit_code in results.items():
        color = 'green' if exit_code == 0 else 'red'
        self.line(f'  <fg={color}>•</fg> {test_name} (exit code: {exit_code})')

    return 0 if set(results.values()) == {0} else 1


class TestPlugin(ApplicationPlugin):

  def activate(self, app: 'Application') -> None:
    app.cleo.add(TestCommand(app))