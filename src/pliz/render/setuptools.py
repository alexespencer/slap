# -*- coding: utf8 -*-
# Copyright (c) 2019 Niklas Rosenstein
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

from nr.interface import implements
from .base import IRenderer, FileToRender
from .util import find_readme_file, Readme
import json
import os
import textwrap
import sys


def _normpath(x):
  return os.path.normpath(x).replace(os.sep, '/')


@implements(IRenderer)
class SetuptoolsRenderer(object):

  ENTRYPOINT_VARS = {
    'python-major-version': 'sys.version[0]',
    'python-major-minor-version': 'sys.version[:3]'
  }

  def files_for_package(self, package):
    yield FileToRender('setup.py', self._render_setup, package)

  def _render_setup(self, fp, package):
    # Write the header/imports.
    fp.write(textwrap.dedent('''
      import io
      import re
      import setuptools
      import sys
    '''))

    # Write the hepler that extracts the version number from the entry file.
    entry_file = package.package.entry_file or package.get_default_entry_file()
    fp.write(textwrap.dedent('''
      with io.open({entrypoint_file!r}, encoding='utf8') as fp:
        version = re.search(r"__version__\s*=\s*'(.*)'", fp.read()).group(1)
    ''').format(entrypoint_file=_normpath(entry_file)))

    # Write the part that reads the readme for the long description.
    readme = find_readme_file(package.directory)
    if readme:
      fp.write(textwrap.dedent('''
        with io.open({readme!r}, encoding='utf8') as fp:
          long_description = fp.read()
      ''').format(readme=readme.file))
    else:
      fp.write(textwrap.dedent('''
        long_description = {long_description!r}
      '''.format(long_description=package.package.long_description)))
      readme = Readme(None, 'text/plain')

    # Write the install requirements.
    fp.write('\n')
    self._render_requirements(fp, 'requirements', package.requirements)
    if package.requirements.extra:
      fp.write('extras_require = {}\n')
      for key, value in package.requirements.extra.items():
        self._render_requirements(fp, 'extras_require[{!r}]'.format(key), value)
      extras_require = 'extras_require'
    else:
      extras_require = '{}'
    if package.requirements.test:
      fp.write('tests_require = []\n')
      self._render_requirements(fp, 'tests_require', package.requirements.test)
      tests_require = 'tests_require'
    else:
      tests_require = '[]'

    # TODO @NiklasRosenstein: Include datafiles in MANIFEST.in
    if package.datafiles:
      self._render_datafiles(fp, package.package.name, package.datafiles)
      data_files = 'data_files'
    else:
      data_files = '[]'

    exclude_packages = []
    for pkg in package.package.exclude_packages:
      exclude_packages.append(pkg)
      exclude_packages.append(pkg + '.*')

    # Write the setup function.
    fp.write(textwrap.dedent('''
      setuptools.setup(
        name = {package.name!r},
        version = version,
        author = {package.author.name!r},
        author_email = {package.author.email!r},
        description = {description!r},
        long_description = long_description,
        long_description_content_type = {long_description_content_type!r},
        url = {package.url!r},
        license = {package.license!r},
        packages = setuptools.find_packages({src_directory!r}, {exclude_packages!r}),
        package_dir = {{'': {src_directory!r}}},
        include_package_data = {include_package_data!r},
        install_requires = requirements,
        extras_require = {extras_require},
        tests_require = {tests_require},
        python_requires = None, # TODO: {python_requires!r},
        data_files = {data_files},
        entry_points = {entry_points}
      )
    ''').format(
      package=package.package,
      description=package.package.description.replace('\n\n', '%%%%').replace('\n', ' ').replace('%%%%', '\n').strip(),
      long_description_content_type=readme.content_type,
      extras_require=extras_require,
      tests_require=tests_require,
      python_requires=package.requirements.python.to_setuptools() if package.requirements.python else None,
      src_directory=package.package.source_directory,
      exclude_packages=exclude_packages,
      include_package_data=False,#package.package_data != [],
      data_files=data_files,
      entry_points=self._render_entrypoints(package.entrypoints),
    ))

  def _render_entrypoints(self, entrypoints):
    if not entrypoints:
      return '{}'
    lines = ['{']
    for key, value in entrypoints.items():
      lines.append('    {!r}: ['.format(key))
      for item in value:
        item = repr(item)
        args = []
        for varname, expr in self.ENTRYPOINT_VARS.items():
          varname = '{{' + varname + '}}'
          if varname in item:
            item = item.replace(varname, '{' + str(len(args)) + '}')
            args.append(expr)
        if args:
          item += '.format(' + ', '.join(args) + ')'
        lines.append('      ' + item.strip() + ',')
      lines.append('    ],')
    lines[-1] = lines[-1][:-1]
    lines.append('  }')
    return '\n'.join(lines)

  def _render_datafiles(self, fp, package_name, datafiles):
    fp.write(textwrap.dedent('''
      import os, fnmatch
      def _collect_data_files(data_files, target, path, include, exclude):
        for root, dirs, files in os.walk(path):
          parent_dir = os.path.normpath(os.path.join(target, os.path.relpath(root, path)))
          install_files = []
          for filename in files:
            filename = os.path.join(root, filename)
            if include and not any(fnmatch.fnmatch(filename, x) for x in include):
              continue
            if exclude and any(fnmatch.fnmatch(filename, x) for x in exclude):
              continue
            install_files.append(filename)
          data_files.setdefault(parent_dir, []).extend(install_files)

      data_files = {}
    '''))
    for entry in datafiles:
      fp.write('_collect_data_files(data_files, {!r}, {!r}, {!r}, {!r})\n'.format(
        'data/{}/{}'.format(package_name, entry.target.lstrip('/')),
        entry.source, entry.include, entry.exclude))
    fp.write('data_files = list(data_files.items())\n')

  @staticmethod
  def _format_reqs(reqs):
    return [x.to_setuptools() for x in reqs]

  def _render_requirements(self, fp, target, requirements):
    fp.write('{} = {!r}\n'.format(target, self._format_reqs(requirements.required)))
    for os_name in requirements.platforms:
      fp.write('if sys.platform.startswith({!r}):\n'.format(os_name))
      fp.write('  {} += {!r}\n'.format(target, self._format_reqs(requirements.platforms[os_name])))
