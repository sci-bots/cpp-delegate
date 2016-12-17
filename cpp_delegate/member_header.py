import io

import jinja2
import pydash as py_

__all__ = ['get_functions', 'render']


member_structs_template = jinja2.Template(r'''
{% for name_i, member_i in py_.sort(members) %}
typedef struct __attribute__((packed)) {
{%- for arg_ij in member_i.arguments %}
{{ '  ' + arg_ij.type + ' ' + arg_ij.name + ';' }}
{%- endfor %}
} {{ name_i }}__Request;

typedef struct __attribute__((packed)) {
{%- if member_i.result_type %}
{{ '  ' + member_i.result_type + ' result;' }}
{%- endif %}
} {{ name_i }}__Response;
{% endfor %}

{%- for name_i, member_i in py_.sort(members) %}
const int CMD__{{ name_i }} = {{ loop.index0 }};
{%- endfor %}
'''.strip())

member_switch_template = jinja2.Template(r'''
inline UInt8Array test(uint32_t value, UInt8Array request_arr) {
    UInt8Array result = request_arr;
    switch (value) {
    {% for name_i, member_i in py_.sort(members) %}
        case CMD__{{ name_i }}:
            // {{ member_i.location }}
            {
                {%- if member_i.arguments %}
                {{ name_i }}__Request &request = *(reinterpret_cast
                                                   <{{ name_i }}__Request *>
                                                   (&request_arr.data[2]));
                {%- endif %}
                {%- if member_i.result_type %}
                {{ name_i }}__Response response;

                response.result = {% endif -%}
                {{ name_i }}({% for a in member_i.arguments %}{{ ', ' if loop.index0 > 0 else ''}}/* {{ a.type }} */ request.{{ a.name }}{% endfor %});

                /* Copy result to output buffer. */
                /* Cast start of buffer as reference of result type and assign result. */
                {{ name_i }}__Response &output = *(reinterpret_cast
                                                   <{{ name_i }}__Response *>
                                                   (&request_arr.data[0]));
                output = response;
                result.data = request_arr.data;
                result.length = sizeof(output);
            }
            break;
    {%- endfor -%}
    }
    return result;
}
'''.strip())


def get_functions(members):
    return [(v['name'], v)
            for v in py_.group_by(members.values(),
                                  lambda v: v['kind'])['FUNCTION_DECL']
            if v['result_type']
            and not v['name'].startswith('operator ')
            and not any([a['kind'] == 'POINTER' for a in v['arguments']])
            and all([a['name'] for a in v['arguments']])]


def render(functions):
    header = io.BytesIO()

    print >> header, '''
#ifndef ___MEMBER_HEADER__H___
#define ___MEMBER_HEADER__H___'''
    print >> header, str(member_structs_template.render(members=functions,
                                                        py_=py_))
    print >> header, '\n'
    print >> header, str(member_switch_template.render(members=functions,
                                                       py_=py_))
    print >> header, '''
#endif  // #ifndef ___MEMBER_HEADER__H___'''
    return header.getvalue()
