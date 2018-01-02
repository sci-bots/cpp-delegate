import sys

from paver.easy import task, needs, path
from paver.setuputils import setup

sys.path.insert(0, path('.').abspath())
import version

setup(name='cpp-delegate',
      version=version.getVersion(),
      description='C++ delegation, providing access to remote contexts.',
      keywords='',
      author='Christian Fobel',
      author_email='christian@fobel.net',
      url='https://github.com/wheeler-microfluidics/cpp-delegate',
      license='MIT',
      packages=['cpp_delegate'],
      install_requires=['clang-helpers>=0.5', 'jinja2', 'nadamq', 'numpy',
                        'path-helpers', 'pydash', 'six'],
      # Install data listed in `MANIFEST.in`
      include_package_data=True)


@task
@needs('generate_setup', 'minilib', 'setuptools.command.sdist')
def sdist():
    """Overrides sdist to make sure that our setup.py is generated."""
    pass
