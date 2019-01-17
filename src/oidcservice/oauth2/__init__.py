#
# import inspect
# import sys
# from glob import glob
# from os.path import basename, dirname, join
#
# from oidcservice.service import Service

DEFAULT_SERVICES = [
    ('Authorization', {}),
    ['AccessToken', {}],
    ('RefreshAccessToken', {}),
    ('ProviderInfoDiscovery', {})
]


# def factory(req_name, **kwargs):
#     pwd = dirname(__file__)
#     if pwd not in sys.path:
#         sys.path.insert(0, pwd)
#     for x in glob(join(pwd, '*.py')):
#         _mod = basename(x)[:-3]
#         if not _mod.startswith('__'):
#             # _mod = basename(x)[:-3]
#             if _mod not in sys.modules:
#                 __import__(_mod, globals(), locals())
#
#             for name, obj in inspect.getmembers(sys.modules[_mod]):
#                 if inspect.isclass(obj) and issubclass(obj, Service):
#                     try:
#                         if obj.__name__ == req_name:
#                             return obj(**kwargs)
#                     except AttributeError:
#                         pass
#
