
""" With the application object we manage the CLI commands and other types of plugins as well as access to the Slam
user and project configuration. """

from __future__ import annotations

import dataclasses
import logging
import textwrap
import typing as t
from pathlib import Path

from cleo.application import Application as BaseCleoApplication  # type: ignore[import]
from cleo.commands.command import Command as _BaseCommand  # type: ignore[import]
from cleo.helpers import argument, option  # type: ignore[import]
from cleo.io.inputs.argument import Argument  # type: ignore[import]
from cleo.io.inputs.option import Option  # type: ignore[import]
from cleo.io.io import IO  # type: ignore[import]
from databind.core.annotations import alias

from slam import __version__

if t.TYPE_CHECKING:
  from nr.util.functional import Once
  from slam.project import Project
  from slam.repository import Repository
  from slam.util.vcs import Vcs

__all__ = ['Command', 'argument', 'option', 'IO', 'Application', 'ApplicationPlugin']
logger = logging.getLogger(__name__)


class Command(_BaseCommand):

  def __init_subclass__(cls) -> None:
    if not cls.help:
      first_line, remainder = (cls.__doc__ or '').partition('\n')[::2]
      cls.help = (first_line.strip() + '\n' + textwrap.dedent(remainder)).strip()
    cls.description = cls.description or (cls.help.strip().splitlines()[0] if cls.help else None)

    # TODO (@NiklasRosenstein): Implement automatic wrapping of description text, but we
    #   need to ignore HTML tags that are used to colour the output.

    # argument: Argument
    # for argument in cls.arguments:
    #   print(argument)
    #   argument._description = '\n'.join(textwrap.wrap(argument._description or '', 70))

    # option: Option
    # for option in cls.options:
    #   print(option)
    #   option._description = '\n'.join(textwrap.wrap(option._description or '', 70))


class CleoApplication(BaseCleoApplication):

  from cleo.io.inputs.input import Input  # type: ignore[import]
  from cleo.io.outputs.output import Output  # type: ignore[import]
  from cleo.formatters.style import Style  # type: ignore[import]

  _styles: dict[str, Style]

  def __init__(self, init: t.Callable[[IO], t.Any], name: str = "console", version: str = "") -> None:
    super().__init__(name, version)
    self._init_callback = init
    self._styles = {}

    self._initialized = True
    from slam.util.cleo import HelpCommand
    self.add(HelpCommand())
    self._default_command = 'help'

    self.add_style('code', 'dark_gray')
    self.add_style('warning', 'magenta')
    self.add_style('u', options=['underline'])
    self.add_style('i', options=['italic'])
    self.add_style('s', 'yellow')
    self.add_style('opt', 'cyan', options=['italic'])

  def add_style(self, name, fg=None, bg=None, options=None):
    self._styles[name] = self.Style(fg, bg, options)

  def create_io(
    self,
    input: Input | None = None,
    output: Output | None = None,
    error_output: Output | None = None
  ) -> IO:
    from slam.util.cleo import add_style

    io = super().create_io(input, output, error_output)
    for style_name, style in self._styles.items():
      add_style(io, style_name, style)
    return io

  def render_error(self, error: Exception, io: IO) -> None:
    import subprocess as sp

    if isinstance(error, sp.CalledProcessError):
      msg = 'Uncaught CalledProcessError raised for command <subj>%s</subj> (exit code: <val>%s</val>).'
      args: tuple[t.Any, ...] = (error.args[1], error.returncode)
      stdout: str | None = error.stdout.decode() if error.stdout else None
      stderr: str | None = error.stderr.decode() if error.stderr else None
      if stdout:
        msg += '\n  stdout:\n<fg=black;attr=bold>%s</fg>'
        stdout = textwrap.indent(stdout, '    ')
        args += (stdout,)
      if stderr:
        msg += '\n  stderr:\n<fg=black;attr=bold>%s</fg>'
        stderr = textwrap.indent(stderr, '    ')
        args += (stderr,)

      logger.error(msg, *args)

    return super().render_error(error, io)

  def _configure_io(self, io: IO) -> None:
    import logging

    from nr.util.logging.formatters.terminal_colors import TerminalColorFormatter

    fmt = '<fg=bright black>%(message)s</fg>'
    if io.input.has_parameter_option("-vvv"):
      fmt = '<fg=bright black>%(asctime)s | %(levelname)s | %(name)s | %(message)s</fg>'
      level = logging.DEBUG
    elif io.input.has_parameter_option("-vv"):
      level = logging.DEBUG
    elif io.input.has_parameter_option("-v"):
      level = logging.INFO
    elif io.input.has_parameter_option("-q"):
      level = logging.ERROR
    elif io.input.has_parameter_option("-qq"):
      level = logging.CRITICAL
    else:
      level = logging.WARNING

    logging.basicConfig(level=level)
    formatter = TerminalColorFormatter(fmt)
    assert formatter.styles
    formatter.styles.add_style('subj', 'blue')
    formatter.styles.add_style('obj', 'yellow')
    formatter.styles.add_style('val', 'cyan')
    formatter.install('tty')
    formatter.install('notty')  # Hack for now to enable it also in CI

    super()._configure_io(io)
    self._init_callback(io)

  def _run_command(self, command: Command, io: IO) -> int:
    return super()._run_command(command, io)


@dataclasses.dataclass
class ApplicationConfig:
  #: A list of application plugins to _not_ activate.
  disable: list[str] = dataclasses.field(default_factory=list)

  #: A list of plugins to enable only, causing the default plugins to not be loaded.
  enable_only: t.Annotated[list[str] | None, alias('enable-only')] = None


class Application:
  """ The application object is the main hub for command-line interactions. It is responsible for managing the project
  that is the main subject of the command-line invokation (or multiple of such), provide the #cleo command-line
  application that #ApplicationPlugin#s can register commands to, etc. """

  repository: Repository

  main_project: Once[Project | None]

  #: The application configuration loaded once via #get_application_configuration().
  config: Once[ApplicationConfig]

  #: The cleo application to which new commands can be registered via #ApplicationPlugin#s.
  cleo: CleoApplication

  def __init__(self, directory: Path | None = None, name: str = 'slam', version: str = __version__) -> None:
    from nr.util.functional import Once
    from slam.repository import Repository
    self.repository = Repository(directory or Path.cwd())
    self._plugins_loaded = False
    self.config = Once(self._get_application_configuration)
    self.cleo = CleoApplication(self._cleo_init, name, version)
    self.main_project = Once(self._get_main_project)

  def _get_application_configuration(self) -> ApplicationConfig:
    """ Loads the application-level configuration. """

    import databind.json
    from databind.core.annotations import enable_unknowns

    return databind.json.load(
      self.repository.raw_config().get('application', {}),
      ApplicationConfig,
      options=[enable_unknowns()]
    )

  def _get_main_project(self) -> Project | None:
    """ Returns the main project, which is the one closest to the current working directory. """

    closest: Project | None = None
    distance: int = 99999
    cwd = Path.cwd()

    for project in self.repository.projects():
      path = project.directory.resolve()
      if path == cwd:
        closest = project
        break

      try:
        relative = path.relative_to(cwd)
      except ValueError:
        continue

      if len(relative.parts) < distance:
        closest = project
        distance = len(relative.parts)

    return closest

  def load_plugins(self) -> None:
    """ Loads all application plugins (see #ApplicationPlugin) and activates them.

    By default, all plugins available in the `slam.application.ApplicationPlugin` entry point group are loaded. This
    behaviour can be modified by setting either the `[tool.slam.plugins.disable]` or `[tool.slam.plugins.enable]`
    configuration option (without the `tool.slam` prefix in case of a `slam.toml` configuration file). The default
    plugins delivered immediately with Slam are enabled by default unless disabled explicitly with the `disable`
    option. """

    from nr.util.plugins import iter_entrypoints
    from slam.plugins import ApplicationPlugin

    assert not self._plugins_loaded
    self._plugins_loaded = True

    config = self.config()
    disable = config.disable or []

    logger.debug('Loading application plugins')

    for plugin_name, loader in iter_entrypoints(ApplicationPlugin):  # type: ignore[misc]
      if plugin_name in disable: continue
      try:
        plugin = loader()()
      except Exception:
        logger.exception('Could not load plugin <subj>%s</subj> due to an exception', plugin_name)
      else:
        plugin_config = plugin.load_configuration(self)
        plugin.activate(self, plugin_config)

  def _cleo_init(self, io: IO) -> None:
    import sys
    from slam.repository import NotASlamRepository

    try:
      self.repository.load()
    except NotASlamRepository as exc:
      io.write_error_line(f'<error>error: this does not appear to be a directory in which you want to use Slam</error>')
      sys.exit(1)

    self.load_plugins()

  def run(self) -> None:
    """ Loads and activates application plugins and then invokes the CLI. """

    self.cleo.run()
