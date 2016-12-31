import datetime as dt
import hashlib

from pydash import py_ as py__
import nadamq as nq
import nadamq.NadaMq
import numpy as np
import pydash as py_

from .dir_mixin import DirMixIn
from .address_of import get_attributes
from .member_header import get_functions

_fp = py__()


def get_np_dtype(type_name, default=False):
    if type_name == 'float':
        return np.dtype('float32')
    for type_i in (type_name, type_name[:-2]):
        try:
            return np.dtype(type_i)
        except TypeError:
            pass
    else:
        if default == False:
            raise TypeError('Type not understood: {}'.format(type_name))
        else:
            return default


operation_code = lambda v: np.fromstring(hashlib.sha256(v).digest(),
                                         dtype='uint8').view('uint16')[0]


def get_namespace_path(namespace_str):
    parts_i = filter(None, namespace_str.split('::'))
    return ('namespaces.' + '.namespaces.'.join(parts_i)
            if parts_i else '')


class Context(object):
    def __init__(self, cpp_ast_json, namespace=''):
        self.cpp_ast_json = cpp_ast_json
        self.namespace_str = namespace
        if namespace:
            self.namespace = py_.get(cpp_ast_json,
                                     get_namespace_path(namespace))
        else:
            self.namespace = self.cpp_ast_json
        self._attributes = get_attributes(self.namespace['members'])
        self._functions = get_functions(self.namespace['members'])


class RemoteContext(Context, DirMixIn):
    '''
    This class provides access to public variables and fields within a remote
    context (i.e., namespace).

    Variables and fields are accessible as Python attributes, allowing, for
    example, tab completion in IPython.

    Parameters
    ----------
    stream : serial.Serial
        A serial connection to the remote device.
    cpp_ast_json : dict
        A JSON-serializable C++ abstract syntax tree, as parsed by
        `clang_helpers.clang_ast.parse_cpp_ast(..., format='json')`.
    namespace : str, optional
        A namespace specifier (e.g., ``"foo::bar"``) indicating the namespace
        to expose.

        A value of ``""`` corresponds to the top-level namespace.

    Attributes
    ----------
    .<remote variable/field>
        An attribute corresponding to each public variable or field within the
        remote context :attr:`namespace`.
    '''
    def __init__(self, stream, cpp_ast_json, namespace='', timeout=None):
        self.stream = stream
        super(RemoteContext, self).__init__(cpp_ast_json, namespace=namespace)
        self._addresses = dict([(k, self._address_of(str(k), timeout=timeout))
                                for k in sorted(self._attributes.keys())])

    def __dir__(self):
        '''
        Add remote attribute keys to :func:`dir` result.

        Allows, for example, tab completion for remote attributes in IPython.
        '''
        return super(RemoteContext, self).__dir__() + self._attributes.keys()

    def __getattr__(self, attr):
        '''
        If :data:`attr` matches the name of a variable or field in the remote
        context, return the corresponding value.

        Returns
        -------
        type of attr
            Value of specified attribute in remote context.

            If type is not supported (i.e., not a plain old data type), return
            ``None``.

        See also
        --------
        :meth:`_read_attribute`
        '''
        if attr in self._attributes:
            return self._read_attribute(attr, None)
        else:
            raise AttributeError

    def __setattr__(self, attr, value):
        '''
        If :data:`attr` matches the name of a variable or field in the remote
        context, set the corresponding value.

        Parameters
        ----------
        attr : str
            Name of attribute in remote context.
        value : type of attr
            Value to set for specified attribute in remote context.

        Raises
        ------
        TypeError
            If attribute type is not supported (i.e., not a plain old data
            type).

        See also
        --------
        :meth:`__getattr__`, :meth:`_read_attribute`
        '''
        if hasattr(self, '_attributes') and attr in self._attributes:
            self._write_attribute(attr, value)
        else:
            super(RemoteContext, self).__setattr__(attr, value)

    def _address_of(self, label, timeout=None):
        '''
        Parameters
        ----------
        label : str
            Name/label of variable or field in remote context.

        Returns
        -------
        int
            Address in memory of specified variable or field in remote context.
        '''
        op_code = operation_code('address_of')
        rec = np.rec.array([op_code, label], dtype=[('op_code', 'uint16'),
                                                    ('address', 'S{}'
                                                     .format(len(label)))])
        packet = nq.NadaMq.cPacket(data=rec.tobytes(),
                                   type_=nq.NadaMq.PACKET_TYPES.DATA)
        self.stream.write(packet.tostring())

        start = dt.datetime.now()
        while not self.stream.in_waiting:
            if timeout is not None and (dt.datetime.now() -
                                        start).total_seconds() > timeout:
                raise RuntimeError('Timed out waiting for address of %s' %
                                   label)
        return np.fromstring(self.stream.read(self.stream.in_waiting),
                             dtype='uint32')[0]

    def _mem_read(self, address, size):
        '''
        Parameters
        ----------
        address : int
            Memory address in remote context.
        size : int
            Number of bytes to read.

        Returns
        -------
        np.array(dtype='uint8')
            Array of data read from remote context.

        See also
        --------
        :meth:`_read_attribute`
        '''
        op_code = operation_code('mem_read')
        rec = np.rec.array([op_code, address, size],
                           dtype=[('op_code', 'uint16'), ('address', 'uint32'),
                                  ('size', 'uint16')])
        packet = nq.NadaMq.cPacket(data=rec.tobytes(),
                                   type_=nq.NadaMq.PACKET_TYPES.DATA)

        self.stream.write(packet.tostring())

        while not self.stream.in_waiting:
            pass
        return np.fromstring(self.stream.read(self.stream.in_waiting),
                             dtype='uint8')

    def _mem_write(self, address, data):
        '''
        Write data to specified address in remote context.

        Parameters
        ----------
        address : int
            Memory address in remote context.
        data : numpy.array-like
            Array or :module:`numpy` data type.

        See also
        --------
        :meth:`_write_attribute`
        '''
        op_code = operation_code('mem_write')
        bytes_ = data.tobytes()
        rec = np.rec.array([op_code, address, len(bytes_), bytes_],
                           dtype=[('op_code', 'uint16'), ('address', 'uint32'),
                                  ('size', 'uint16'),
                                  ('bytes', 'S{}'.format(len(bytes_)))])
        packet = nq.NadaMq.cPacket(data=rec.tobytes(),
                                   type_=nq.NadaMq.PACKET_TYPES.DATA)

        self.stream.write(packet.tostring())

    def _read_attribute(self, attr, *args):
        '''
        Parameters
        ----------
        attr : str
            Name of attribute in remote context.
        default : object, optional
            Default return value.

        Returns
        -------
        type of attr
            Value of specified attribute in remote context.

            If type is not supported (i.e., not a plain old data type),
            :data:`default` is returned (if specified).
        '''
        has_default = True if args else False

        address = self._addresses[attr]
        try:
            np_dtype = get_np_dtype(self._attributes[attr]['type'])
        except TypeError:
            if has_default:
                return args[0]
            raise
        data = self._mem_read(address, np_dtype.itemsize)
        return data.view(np_dtype)[0]

    def _read_attributes(self):
        '''
        Returns
        -------
        dict
            Value of each attribute in remote context.

            For each attribute, if type is not supported (i.e., not a plain old
            data type), value is set to ``None``.

        See also
        --------
        :meth:`_write_attribute`
        '''
        return py_.map_values(self._attributes, lambda v, k:
                              self._read_attribute(k, None))

    def _write_attribute(self, attr, value):
        '''
        Parameters
        ----------
        attr : str
            Name of attribute in remote context.
        value : type of attr
            Value to set for specified attribute in remote context.

        Raises
        ------
        TypeError
            If attribute type is not supported (i.e., not a plain old data
            type).

        See also
        --------
        :meth:`_read_attribute`
        '''
        address = self._addresses[attr]
        attr_node = self._attributes[attr]
        if attr_node['const']:
            location = attr_node['location']
            raise AttributeError('Attribute "{}" is read-only (declared as '
                                 '"const" at `{} (line: {}, col: {})`)'
                                 .format(attr, location['file'],
                                         location['start']['line'],
                                         location['start']['column']))
        np_dtype = get_np_dtype(attr_node['type'])
        value = np_dtype.type(value)
        self._mem_write(address, value)
