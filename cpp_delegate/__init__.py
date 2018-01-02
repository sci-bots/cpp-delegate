from collections import OrderedDict
import gzip
import json

import clang_helpers.clang_ast as ca
import path_helpers as ph

from .address_of import get_attributes, render
from .execute import render as exe_render
from .context import Context


def dump_cpp_ast(env, exclude_dirs=None):
    '''
    Parameters
    ----------
    env : SCons.Script.SConscript.SConsEnvironment
    exclude_dirs : list, optional
        Exclude classes and attributes found in headers within any specified
        directory during abstract syntax tree scan.

    Returns
    -------
    cpp_ast_json : dict
        JSON-friendly C++ source abstract syntax tree.
    '''
    if exclude_dirs is None:
        exclude_dirs = []

    project_dir = ph.path(env['PROJECT_DIR'])
    project_name = project_dir.name.replace('-', '__')
    lib_dir = project_dir.joinpath('lib', project_name)
    lib_dir.makedirs_p()

    project_dir = ph.path(env['PROJECTSRC_DIR']).realpath()
    if project_dir.files('*.ino'):
        # Project is an Arduino sketch
        main_c_file = ph.path(env['PROJECTSRC_DIR']).files('*.ino.cpp')[0]
    else:
        main_c_file = project_dir.joinpath('main.cpp')
    cpp_ast_json = parse_cpp_ast(main_c_file, env)

    # Exclude members from specified exclude dirs.
    selected_members = {name_i: member_i
                        for name_i, member_i in
                        cpp_ast_json['members'].iteritems()
                        if not any([_isindir(exclude_dir_j,
                                             member_i['location']['file'])
                                    for exclude_dir_j in exclude_dirs])}
    cpp_ast_json['members'] = selected_members

    output_path = lib_dir.joinpath('cpp_ast.json.gz')
    with gzip.open(output_path, 'wb') as output:
        json.dump(cpp_ast_json, output, indent=2)
    return cpp_ast_json


def _isindir(root, file_path):
    '''
    Parameters
    ----------
    root : str
        Root directory.
    file_path : str
        File to test for membership in root.

    Returns
    -------
    bool
        ``True`` if file is contained within directory structure under
        specified root.
    '''
    root = ph.path(root).realpath()
    file_path = ph.path(file_path).realpath()
    return not root.relpathto(file_path).startswith('..')


def dump_execute_py(env, cpp_ast_json):
    '''
    Parameters
    ----------
    env : SCons.Script.SConscript.SConsEnvironment
    cpp_ast_json : dict
        C++ source abstract syntax tree.

    Returns
    -------
    str
        Python bindings code.
    '''
    project_dir = ph.path(env['PROJECT_DIR'])
    project_name = project_dir.name.replace('-', '__')
    lib_dir = project_dir.joinpath('bindings', 'python', project_name)
    lib_dir.makedirs_p()

    ctx = Context(cpp_ast_json)

    # Generate Python code for each function to pack arguments, call function,
    # and unpack result.
    python_code = exe_render(ctx._functions)

    # Create `__init__.py` if it doesn't exist.
    lib_dir.joinpath('__init__.py').touch()

    # Write generated Python code to `execute.py`.
    with lib_dir.joinpath('execute.py').open('w') as output:
        output.write(python_code)
    return python_code


def dump_address_of_header(env, cpp_ast_json):
    '''
    Parameters
    ----------
    env : SCons.Script.SConscript.SConsEnvironment
    cpp_ast_json : dict
        C++ source abstract syntax tree.

    Returns
    -------
    str
        Contents of C++ header defining address of each addressable attribute.
    '''
    project_dir = ph.path(env['PROJECT_DIR'])
    project_name = project_dir.name.replace('-', '__')
    lib_dir = project_dir.joinpath('lib', project_name)
    lib_dir.makedirs_p()

    output_path = lib_dir.joinpath('AddressOf.h')
    print ('[{name}] write to: {output_path}'
           .format(name='.'.join([__name__, 'dump_address_of_header']),
                   output_path=output_path))

    attributes = get_attributes(cpp_ast_json['members'])
    # Path to ARM toolchain.
    toolchain_dir = ph.path(env['PIOHOME_DIR']).joinpath('packages',
                                                         'toolchain-'
                                                         'gccarmnoneeabi')
    attributes = {k: v for k, v in attributes.iteritems()
                  if not _isindir(toolchain_dir, v['location']['file'])}
    header_content = render(cpp_ast_json, attributes)

    with output_path.open('w') as output:
        output.write(header_content)
    return header_content


def parse_cpp_ast(source, env):
    '''
    Parameters
    ----------
    source : str
        C++ source file path.
    env : SCons.Script.SConscript.SConsEnvironment

    Returns
    -------
    dict
        C++ source abstract syntax tree.
    '''
    # Get define flags from build environment.
    defines = [[env[d_i[1:]] if d_i.startswith('$') else d_i
                for d_i in map(str, d)] for d in env['CPPDEFINES']]
    define_keys = set([d[0] for d in defines])
    if all(['TEENSYDUINO' in define_keys, '__MK20DX256__' in define_keys]):
        defines += [[k] for k in ('KINETISK', '__arm__')
                    if k not in define_keys]
    define_flags = ['-D{}'.format(' '.join(map(str, d))) for d in defines]

    # Get include paths from build environment.
    cpppath_dirs = [ph.path(env[i[1:]] if i.startswith('$') else i)
                    for i in env['CPPPATH']]
    if env["CC"] == "arm-none-eabi-gcc":
        # Explicitly add parent dir of `stdint.h` to list of include paths.
        gcc_include_dir = (ph.path(env['PIOHOME_DIR']).realpath()
                           .joinpath('packages', 'toolchain-gccarmnoneeabi',
                                     'arm-none-eabi', 'include'))
        if gcc_include_dir.isdir():
            cpppath_dirs += [gcc_include_dir]
    cpppath_flags = ['-I{}'.format(p) for p in cpppath_dirs]

    print 'CPPPATH_FLAGS:'
    for p in cpppath_dirs:
        print 3 * ' ', '{} {}'.format(p, p.isdir())
    print 'DEFINE_FLAGS:'
    for d in define_flags:
        print 3 * ' ', d

    return ca.parse_cpp_ast(source, *(define_flags + cpppath_flags),
                            format='json')


def test(v):
    try:
        json.dumps(v)
    except Exception:
        return False
    else:
        return True


def dump_env(env):
    project_dir = ph.path(env['PROJECT_DIR'])
    with project_dir.joinpath('env.json').open('w') as output:
        json_safe_env = OrderedDict(sorted([(k, v) for k, v in env.items()
                                            if test(v)]))
        json.dump(json_safe_env, output, indent=4)
