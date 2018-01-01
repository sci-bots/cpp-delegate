from collections import OrderedDict
import json

import clang_helpers.clang_ast as ca
import path_helpers as ph

from .address_of import get_attributes, render


def dump_cpp_ast(env):
    project_dir = ph.path(env['PROJECT_DIR'])
    project_name = project_dir.name.replace('-', '__')
    lib_dir = project_dir.joinpath('lib', project_name)
    lib_dir.makedirs_p()

    main_c_file = ph.path(env['PROJECTSRC_DIR']).joinpath('main.cpp')
    cpp_ast_json = parse_cpp_ast(main_c_file, env)

    with lib_dir.joinpath('cpp_ast.json').open('w') as output:
        json.dump(cpp_ast_json, output, indent=2)
    return cpp_ast_json


def dump_address_of_header(env, cpp_ast_json):
    project_dir = ph.path(env['PROJECT_DIR'])
    project_name = project_dir.name.replace('-', '__')
    lib_dir = project_dir.joinpath('lib', project_name)
    lib_dir.makedirs_p()

    output_path = lib_dir.joinpath('AddressOf.h')
    print ('[{name}] write to: {output_path}'
           .format(name='.'.join([__name__, 'dump_address_of_header']),
                   output_path=output_path))

    attributes = get_attributes(cpp_ast_json['members'])
    header_content = render(cpp_ast_json, attributes)

    with output_path.open('w') as output:
        output.write(header_content)
    return header_content


def parse_cpp_ast(source, env):
    # Get include paths from build environment.
    cpppath_dirs = [ph.path(env[i[1:]] if i.startswith('$') else i)
                    for i in env['CPPPATH']]
    cpppath_flags = ['-I{}'.format(p) for p in cpppath_dirs]
    # Get define flags from build environment.
    defines = [[env[d_i[1:]] if d_i.startswith('$') else d_i
                for d_i in map(str, d)] for d in env['CPPDEFINES']]
    define_keys = set([d[0] for d in defines])
    if all(['TEENSYDUINO' in define_keys, '__MK20DX256__' in define_keys]):
        defines += [[k] for k in ('KINETISK', '__arm__')
                    if k not in define_keys]
    define_flags = ['-D{}'.format(' '.join(map(str, d))) for d in defines]
    print 'CPPPATH_FLAGS:'
    for p in cpppath_dirs:
        print 3 * ' ', '{} {}'.format(p, p.isdir())
    print 'DEFINE_FLAGS:'
    for d in defines:
        print 3 * ' ', d

    return ca.parse_cpp_ast(source, *(define_flags + cpppath_flags),
                            format='json')


def test(v):
    try:
        json.dumps(v)
    except:
        return False
    else:
        return True


def dump_env(env):
    project_dir = ph.path(env['PROJECT_DIR'])
    with project_dir.joinpath('env.json').open('w') as output:
        json_safe_env = OrderedDict(sorted([(k, v) for k, v in env.items()
                                            if test(v)]))
        json.dump(json_safe_env, output, indent=4)
