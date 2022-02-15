
import shutil
import textwrap
import typing as t
from pathlib  import Path

from slam.application import Application, Command, option
from slam.plugins import ApplicationPlugin


class LinkCommand(Command):
  """
  Symlink your Python package with the help of Flit.

  This command uses <u>Flit [0]</u> to symlink the Python package you are currently
  working on into your Python environment's site-packages. This is particulary
  useful if your project is using a <u>PEP 517 [1]</u> compatible build system that does
  not support editable installs.

  When you run this command, the <u>pyproject.toml</u> will be temporarily rewritten such
  that Flit can understand it. The following ways to describe a Python project are
  currently supported be the rewriter:

  1. <u>Poetry [2]</u>

    Supported configurations:
      - <fg=cyan>version</fg>
      - <fg=cyan>plugins</fg> (aka. "entrypoints")
      - <fg=cyan>scripts</fg>

  <b>Example usage:</b>

    <fg=yellow>$</fg> slam link
    <fg=dark_gray>Discovered modules in /projects/my_package/src: my_package
    Extras to install for deps 'all': {{'.none'}}
    Symlinking src/my_package -> .venv/lib/python3.10/site-packages/my_package</fg>

  <u>[0]: https://flit.readthedocs.io/en/latest/</u>
  <u>[1]: https://www.python.org/dev/peps/pep-0517/</u>
  <u>[2]: https://python-poetry.org/</u>
  """

  name = "link"
  help = textwrap.dedent(__doc__)
  options = [
    option(
      "python",
      description="The Python executable to link the package to.",
      flag=False,
      default="python",
    ),
    option(
      "dump-pyproject",
      description="Dump the updated pyproject.toml and do not actually do the linking.",
    )
  ]

  def __init__(self, app: Application):
    super().__init__()
    self.app = app

  def _get_source_directory(self) -> Path:
    directory = Path.cwd()
    if (src_dir := directory / 'src').is_dir():
      directory = src_dir
    return directory

  def _setup_flit_config(self, module: str, dist_name: str, data: dict[str, t.Any]) -> bool:
    """ Internal. Makes sure the configuration in *data* is compatible with Flit. """

    poetry = data['tool'].get('poetry', {})
    flit = data['tool'].setdefault('flit', {})
    plugins = poetry.get('plugins', {})
    scripts = poetry.get('scripts', {})
    project = data.setdefault('project', {})

    if plugins:
      project['entry-points'] = plugins
    if scripts:
      project['scripts'] = scripts

    # TODO (@NiklasRosenstein): Do we need to support gui-scripts as well?

    project['name'] = dist_name
    project['version'] = poetry['version']
    project['description'] = ''
    flit['module'] = {'name': module}

    return True

  def handle(self) -> int:
    from flit.install import Installer  # type: ignore[import]
    from nr.util.fs import atomic_swap

    from slam.util.pygments import toml_highlight

    # logging.basicConfig(level=logging.INFO, format='%(message)s')

    # TODO (@NiklasRosenstein): Ensure that dependencies are installed?

    num_projects = 0
    num_skipped = 0

    for project in self.app.projects:
      if not project.is_python_project:
        continue

      packages = project.packages()
      if not packages:
        continue

      num_projects += 1
      if len(packages) > 1:
        self.line_error('warning: multiple packages can not currently be installed with <opt>slam link</opt>')
        num_skipped += 1
        continue

      config = project.pyproject_toml.value()
      dist_name = project.get_dist_name() or project.directory.resolve().name
      if not self._setup_flit_config(packages[0].name, dist_name, config):
        return 1

      if self.option('dump-pyproject'):
        self.line(f'<fg=dark_gray># {project.pyproject_toml.path}</fg>')
        self.line(toml_highlight(config))
        continue

      with atomic_swap(project.pyproject_toml.path, 'w', always_revert=True) as fp:
        fp.close()
        project.pyproject_toml.value(config)
        project.pyproject_toml.save()
        installer = Installer.from_ini_path(
          project.pyproject_toml.path,
          python=shutil.which(self.option("python")),
          symlink=True
        )
        self.line(f'symlinking <info>{dist_name}</info>')
        installer.install()

    return 1 if num_skipped > 0 and num_projects == 1 else 0


class LinkCommandPlugin(ApplicationPlugin):

  def load_configuration(self, app: Application) -> None:
    return None

  def activate(self, app: Application, config: None):
    app.cleo.add(LinkCommand(app))