from pydash import py_ as py__
import jinja2
import pydash as py_

from .context import f_arg_dtypes, get_np_dtype

_fp = py__()


template = """\
from numpy import dtype
import numpy as np


class Exec(object):
    def __init__(self, parent):
        self.__parent = parent
{% for name_i, func_i in functions.items() -%}
{%- set method_name_i = name_i + '_' if name_i == 'yield' else name_i %}
{%- set np_rec_dtype_i = f_arg_dtypes(func_i) if func_i['arguments'] else [] %}
{%- set args_str_i = ', '.join(py_.map_(np_rec_dtype_i, _fp.get(0))) %}
    def {{ method_name_i }}(self{{ ', ' if func_i['arguments'] else '' }}{{ args_str_i }}):
{%- if func_i.description or func_i.arguments or func_i.result_type %}
        '''
{%- if func_i.description %}
        {{ func_i.description }}
{%- endif %}
{%- if func_i.arguments %}
        Parameters
        ----------
{%- for arg_name_ij, arg_ij in np_rec_dtype_i %}
        {{ arg_name_ij }} : np.dtype('{{ arg_ij }}')
{%- endfor %}
{%- endif %}
{%- if func_i.result_type %}
{%- if func_i.description or func_i.arguments %}
{%  endif %}
        Returns
        -------
        {{ get_np_dtype(func_i.result_type, func_i.result_type) }}
{%- endif %}
        '''
{%- endif %}
{%- if func_i.arguments %}
        np_rec_dtype = {{ np_rec_dtype_i }}
        args_struct = np.rec.array([{{ args_str_i}}], dtype=np_rec_dtype)
        packed_args = args_struct.tobytes()
{%- else %}
        args_struct = None
        packed_args = b''
{%- endif %}
        packet = self.__parent._exec_packet('{{ name_i }}', args_struct)
        response = self.__parent._query_exec_packet(packet)
{%- if func_i.result_type %}
{%- set result_dtype_i = get_np_dtype(func_i['result_type'], None) %}
{%- if result_dtype_i == None %}
        return response
{%- else %}
        result_dtype = '{{ result_dtype_i }}'
        return response.view(dtype=result_dtype)[0]
{%- endif %}
{%- endif %}
{% endfor %}
"""


def render(functions):
    return jinja2.Template(template).render(functions=functions, _fp=_fp,
                                            py_=py_, f_arg_dtypes=f_arg_dtypes,
                                            get_np_dtype=get_np_dtype)
