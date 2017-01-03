from collections import OrderedDict
import datetime as dt
import hashlib
import re

from pydash import py_ as py__
import nadamq as nq
import nadamq.NadaMq
import numpy as np
import pydash as py_
import clang_helpers.clang_ast as ca

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


f_np_rec_dtype = _fp.map(py_.pipe( _fp.pick(['name', 'type']),
                                  lambda v: (str(v['name']),
                                             get_np_dtype(v['type']))))
f_arg_dtypes = py_.pipe(_fp.get('arguments'), f_np_rec_dtype)
f_arg_rec_array = py_.pipe(f_arg_dtypes,
                           lambda a: (lambda *args: np.rec.array(args,
                                                                 dtype=a)))

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
        self._functions = OrderedDict(get_functions(self.namespace['members']))
        self._get_class_json = ca.get_class_factory(self.cpp_ast_json)


class RemoteContext(Context, DirMixIn):
    '''
    This class provides access to public variables and fields within a remote
    context (i.e., namespace).

    Variables and fields are accessible as Python attributes, allowing, for
    example, tab completion in IPython.

    TODO
    ----

     - **[ ]** Add read/write support for C array attributes:
         - **[x]** `CONSTANTARRAY` constant size array
         - **[ ]** `INCOMPLETEARRAY`
     - **[x]** Add read/write support for ``CArrayDefs.h`` array attributes
     - **[ ]** Add support to call remote context functions as member functions

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
        self._carray_dtype = np.dtype([('length', 'uint32'),
                                       ('data',
                                        'u{}'.format(self.POINTER_SIZE))])

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

    def _exec(self, function_name, *args, **kwargs):
        '''
        Parameters
        ----------
        function_name : str
            Name of function in remote context.
        request : np.array(dtype='uint8')
            Request array containing packed arguments to pass to function in
            remote context.

        Returns
        -------
        np.array(dtype='uint8')
            Function return data read from remote context.
        '''
        packed_args = kwargs.pop('packed_args', None)

        # **TODO** Need to pack args based on function signature.
        # **NOTE** For now, assuming **no packed arguments**, which is OK for
        # functions that do not accept any arguments (e.g., `millis`,
        # `micros`).
        if packed_args is None:
            if self._functions[function_name]['arguments']:
                np_rec_dtype = f_arg_dtypes(self._functions[function_name])
                args_struct = np.rec.array(args, dtype=np_rec_dtype)
            else:
                args_struct = None

        packet = self._exec_packet(function_name, args_struct)
        return self._query_exec_packet(packet)

    def _query_exec_packet(self, packet):
        '''
        Send packet and wait for response.

        Parameters
        ----------
        nadamq.NadaMq.cPacket

        Returns
        -------
        np.array(dtype='uint8')
            Response data from stream.
        '''
        self.stream.write(packet.tostring())

        while not self.stream.in_waiting:
            pass
        return np.fromstring(self.stream.read(self.stream.in_waiting),
                             dtype='uint8')

    def _exec_packet(self, function_name, args_struct):
        '''
        Parameters
        ----------
        function_name : str
            Name of function in remote context.
        args_struct : np.rec.array or None
            Structure containing named arguments to pass to function.

            ``None`` if no arguments are to be passed.

        Returns
        -------
        nadamq.NadaMq.cPacket
            Packet to send to execute specified function with provided
            arguments.
        '''
        packed_args = b'' if args_struct is None else args_struct.tobytes()
        request_header_types = [('op_code', 'uint16'),
                                ('function_code', 'uint32'),
                                ('request_header',
                                 'S{}'.format(self._carray_dtype.itemsize)),
                                ('request',
                                 'S{}'.format(len(packed_args)))]
        packet_header_size = np.dtype(request_header_types[:-1]).itemsize
        packed_arg_header = np.rec.array([len(packed_args),  # length
                                          packet_header_size], # offset
                                         dtype=self._carray_dtype)

        # Get function code from remote device.
        function_code = getattr(self, 'CMD__{}'.format(function_name))

        # Get operation code for remote execution request.
        op_code = operation_code('_exec')

        rec = np.rec.array([op_code, function_code,
                            packed_arg_header.tobytes(), packed_args],
                           dtype=request_header_types)
        return nq.NadaMq.cPacket(data=rec.tobytes(),
                                 type_=nq.NadaMq.PACKET_TYPES.DATA)

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
        attribute = self._attributes[attr]
        if attribute['type'].endswith('Array') and re.match(r'U?Int\d+Array',
                                                            attribute['type']):
            data = self._mem_read(address, self._carray_dtype.itemsize)
            array_class = self._get_class_json(attribute['type'])
            element_type = array_class['members']['data']['pointee_type']
            try:
                np_dtype = get_np_dtype(element_type)
            except TypeError:
                if has_default:
                    return args[0]
                raise
            carray = np.rec.array(data, dtype=self._carray_dtype)[0]
            return self._mem_read(carray['data'], carray['length'] *
                                  np_dtype.itemsize).view(np_dtype)
        elif attribute['kind'] == 'CONSTANTARRAY':
            try:
                np_dtype = get_np_dtype(attribute['element_type'])
            except TypeError:
                if has_default:
                    return args[0]
                raise
            data = self._mem_read(address, attribute['array_size'] *
                                  np_dtype.itemsize)
            return data.view(np_dtype)
        else:
            try:
                np_dtype = get_np_dtype(attribute['type'])
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
        if attr_node['type'].endswith('Array') and re.match(r'U?Int\d+Array',
                                                            attr_node['type']):
            data = self._mem_read(address, self._carray_dtype.itemsize)
            array_class = self._get_class_json(attr_node['type'])
            element_type = array_class['members']['data']['pointee_type']
            np_dtype = get_np_dtype(element_type)
            carray = np.rec.array(data, dtype=self._carray_dtype)[0]
            if len(value) != carray['length']:
                raise ValueError('Length of specified value ({}) does not '
                                 'match remote array length ({}).'
                                 .format(len(value), carray['length']))
            data = np.asarray(value, dtype=np_dtype)
            self._mem_write(carray['data'], data)
        elif attr_node['kind'] == 'CONSTANTARRAY':
            np_dtype = get_np_dtype(attr_node['element_type'])
            if len(value) != attr_node['array_size']:
                raise ValueError('Length of specified value ({}) does not '
                                 'match remote array length ({}).'
                                 .format(len(value), attr_node['array_size']))
            data = np.asarray(value, dtype=np_dtype)
            self._mem_write(address, data)
        else:
            np_dtype = get_np_dtype(attr_node['type'])
            value = np_dtype.type(value)
            self._mem_write(address, value)
