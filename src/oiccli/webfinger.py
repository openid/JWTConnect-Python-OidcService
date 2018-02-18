# coding=utf-8
import logging
import re

from oiccli.exception import OicCliError
from six.moves.urllib.parse import urlencode
from six.moves.urllib.parse import urlparse


"""
Implements WebFinger RFC 7033
"""
__author__ = 'Roland Hedberg'

logger = logging.getLogger(__name__)

WF_URL = "https://%s/.well-known/webfinger"
OIC_ISSUER = "http://openid.net/specs/connect/1.0/issuer"


class WebFingerError(OicCliError):
    pass



# -- Normalization --
# A string of any other type is interpreted as a URI either the form of scheme
# "://" authority path-abempty [ "?" query ] [ "#" fragment ] or authority
# path-abempty [ "?" query ] [ "#" fragment ] per RFC 3986 [RFC3986] and is
# normalized according to the following rules:
#
# If the user input Identifier does not have an RFC 3986 [RFC3986] scheme
# portion, the string is interpreted as [userinfo "@"] host [":" port]
# path-abempty [ "?" query ] [ "#" fragment ] per RFC 3986 [RFC3986].
# If the userinfo component is present and all of the path component, query
# component, and port component are empty, the acct scheme is assumed. In this
# case, the normalized URI is formed by prefixing acct: to the string as the
# scheme. Per the 'acct' URI Scheme [I‑D.ietf‑appsawg‑acct‑uri], if there is an
# at-sign character ('@') in the userinfo component, it needs to be
# percent-encoded as described in RFC 3986 [RFC3986].
# For all other inputs without a scheme portion, the https scheme is assumed,
# and the normalized URI is formed by prefixing https:// to the string as the
# scheme.
# If the resulting URI contains a fragment portion, it MUST be stripped off
# together with the fragment delimiter character "#".
# The WebFinger [I‑D.ietf‑appsawg‑webfinger] Resource in this case is the
# resulting URI, and the WebFinger Host is the authority component.
#
# Note: Since the definition of authority in RFC 3986 [RFC3986] is
# [ userinfo "@" ] host [ ":" port ], it is legal to have a user input
# identifier like userinfo@host:port, e.g., alice@example.com:8080.


class URINormalizer(object):
    @staticmethod
    def has_scheme(inp):
        if "://" in inp:
            return True
        else:
            authority = inp.replace('/', '#').replace('?', '#').split("#")[0]

            if ':' in authority:
                scheme_or_host, host_or_port = authority.split(':', 1)
                # Assert it's not a port number
                if re.match('^\d+$', host_or_port):
                    return False
            else:
                return False
        return True

    @staticmethod
    def acct_scheme_assumed(inp):
        if '@' in inp:
            host = inp.split('@')[-1]
            return not (':' in host or '/' in host or '?' in host)
        else:
            return False

    def normalize(self, inp):
        if self.has_scheme(inp):
            pass
        elif self.acct_scheme_assumed(inp):
            inp = "acct:%s" % inp
        else:
            inp = "https://%s" % inp
        return inp.split("#")[0]  # strip fragment


class WebFinger(object):
    def __init__(self, default_rel=None, httpd=None):
        self.default_rel = default_rel
        self.httpd = httpd
        self.jrd = None
        self.events = None

    def query(self, resource, rel=None):
        resource = URINormalizer().normalize(resource)

        info = [("resource", resource)]

        if rel is None:
            if self.default_rel:
                info.append(("rel", self.default_rel))
        elif isinstance(rel, str):
            info.append(("rel", rel))
        else:
            for val in rel:
                info.append(("rel", val))

        if resource.startswith("http"):
            part = urlparse(resource)
            host = part.hostname
            if part.port is not None:
                host += ":" + str(part.port)
        elif resource.startswith("acct:"):
            host = resource.split('@')[-1]
            host = host.replace('/', '#').replace('?', '#').split("#")[0]
        elif resource.startswith("device:"):
            host = resource.split(':')[1]
        else:
            raise WebFingerError("Unknown schema")

        return "%s?%s" % (WF_URL % host, urlencode(info))

    def http_args(self, jrd=None):
        if jrd is None:
            if self.jrd:
                jrd = self.jrd
            else:
                return None

        return {
            "headers": {"Access-Control-Allow-Origin": "*",
                        "Content-Type": "application/json; charset=UTF-8"},
            "body": jrd.to_json()
        }
