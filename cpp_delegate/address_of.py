from pydash import py_ as py__
import clang_helpers as ch
import jinja2
import path_helpers as ph
import pydash as py_

_fp = py__()

# **TODO**: Move `get_typedef_path` and `get_typedef_factory` into
# `clang_helpers.clang_ast` module.
def get_typedef_path(typedef_str):
    parts_i = typedef_str.split('::')
    return ('namespaces.' + '.namespaces.'.join(parts_i[:-1]) + '.'
            if parts_i[:-1] else '') + 'typedefs.' + parts_i[-1]

get_typedef_factory = lambda ast: py_.pipe(get_typedef_path,
                                           py_.curry(py_.get, arity=2)(ast))


def get_definition_header(cpp_ast_json, type_):
    '''
    Parameters
    ----------
    cpp_ast_json : dict
        JSON-serializable C++ abstract syntax tree.
    type_ : str
        Name of C++ type defined within C++ abstract syntax tree.

    Returns
    -------
    path_helpers.path
        Path to header where type of variable is defined.

    Raises
    ------
    IOError
        If header containing type definition cannot be located.
    '''
    get_class_json = ch.clang_ast.get_class_factory(cpp_ast_json)
    get_typedef_json = get_typedef_factory(cpp_ast_json)

    if get_class_json(type_):
        node = get_class_json(type_)
    elif get_typedef_json(type_):
        node = get_typedef_json(type_)
    else:
        raise IOError('Definition header not found for type: {}'.format(type_))
    return ph.path(py_.get(node, 'location.file')).realpath()


# Create an object composed of the object properties predicate returns truthy
# for. The predicate is invoked with two arguments: (value, key).
#
# See [lodash.pickBy][1].
#
# [1]: https://lodash.com/docs/4.17.2#pickBy
py_.pick_by = lambda obj, predicate=None:\
    dict([(k, v) for k, v in obj.iteritems()
          if predicate is None or predicate(v, k)])


__all__ = ['get_attributes', 'render']


template = '''
#ifndef ___ADDRESS_OF__H__
#define ___ADDRESS_OF__H__

#include <string.h>
#include "Arduino.h"
#include "avr_emulation.h"
{% for header_i in namespace_headers -%}
#include "{{ header_i.name }}"
{% endfor -%}

{% for name_i, attr_i in attributes.iteritems() %}
extern {{ 'volatile ' if attr_i.volatile else '' }}{{ 'const ' if attr_i.const else '' }}{{ attr_i.type if attr_i.kind != 'CONSTANTARRAY' else attr_i.element_type }} {{ name_i }}{%if attr_i.kind == 'CONSTANTARRAY' %}[{{ attr_i.array_size }}]{% endif %};
{%- endfor %}

inline uint32_t address_of(char const *member_name) {
    {%- for name_i, attr_i in attributes.iteritems() -%}
    {{ ' else ' if loop.index0 else '\n    ' }}if (strcmp(member_name, "{{ name_i }}") == 0) {
        return reinterpret_cast<uint32_t>(&{{ name_i }});
    }
    {%- endfor %}
    return 0;
}

#endif  // #ifndef ___ADDRESS_OF__H__
'''


def get_attributes(members):
    return py_.pick_by(members, lambda v, k:
                       (v['kind'] not in ('FUNCTION_DECL', 'CXX_METHOD'))
                       and (v['name'] not in ('SREG', 'DDRB', 'DDRC', 'DDRD',
                                              'SPDR', 'SPSR', 'Serial6',
                                              'Serial5', 'Serial4', 'PORTB',
                                              'PORTD', 'PORTC', 'PINB',
                                              'Teensy3Clock', 'PIND', 'PINC',
                                              'SPCR', 'EIMSK'))
                       and '()' not in v['underlying_type']
                       and 'INCOMPLETEARRAY' not in v['kind']
                       and not k.startswith('__'))


def render(cpp_ast_json, attributes):
    namespace_types = [v['type'] for k, v in attributes.iteritems()
                       if '::' in v['type']]
    namespace_headers = map(lambda v: get_definition_header(cpp_ast_json, v),
                            namespace_types)
    return jinja2.Template(template).render(attributes=attributes,
                                            namespace_headers=
                                            namespace_headers)
