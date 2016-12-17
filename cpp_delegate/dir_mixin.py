import six


if six.PY3:
    # There are no need to implement any aditional logic for Python 3.3+, because
    # there base class 'object' already have implemented '__dir__' method,
    # which could be accessed via super() by subclasses
    class DirMixIn:
        pass
else:
    # implement basic __dir__ to make it assessible via super() by subclasses
    class DirMixIn(object):
        """ Mix-in to make implementing __dir__ method in subclasses simpler
        """
        def __dir__(self):
            # code is based on
            # http://www.quora.com/How-dir-is-implemented-Is-there-any-PEP-related-to-that
            def get_attrs(obj):
                import types
                if not hasattr(obj, '__dict__'):
                    return []  # slots only
                if not isinstance(obj.__dict__, (dict, types.DictProxyType)):
                    raise TypeError("%s.__dict__ is not a dictionary"
                                    "" % obj.__name__)
                return obj.__dict__.keys()

            def dir2(obj):
                attrs = set()
                if not hasattr(obj, '__bases__'):
                    # obj is an instance
                    if not hasattr(obj, '__class__'):
                        # slots
                        return sorted(get_attrs(obj))
                    klass = obj.__class__
                    attrs.update(get_attrs(klass))
                else:
                    # obj is a class
                    klass = obj

                for cls in klass.__bases__:
                    attrs.update(get_attrs(cls))
                    attrs.update(dir2(cls))
                attrs.update(get_attrs(obj))
                return list(attrs)

            return dir2(self)
