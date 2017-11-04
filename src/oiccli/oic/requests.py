import inspect
import logging
import sys
import six
from jwkest import jws

try:
    from json import JSONDecodeError
except ImportError:  # Only works for >= 3.5
    _decode_err = ValueError
else:
    _decode_err = JSONDecodeError

from oiccli import oauth2
from oiccli import rndstr
from oiccli.exception import ConfigurationError
from oiccli.exception import ParameterError
from oiccli.oauth2 import requests
from oiccli.oic.utils import construct_redirect_uri
from oiccli.oic.utils import request_object_encryption
from oiccli.request import Request
from oicmsg import oic
from oicmsg.exception import MissingParameter
from oicmsg.exception import MissingRequiredAttribute
from oicmsg.oauth2 import ErrorResponse
from oicmsg.oauth2 import Message
from oicmsg.oic import make_openid_request

__author__ = 'Roland Hedberg'

logger = logging.getLogger(__name__)

PREFERENCE2PROVIDER = {
    # "require_signed_request_object": "request_object_algs_supported",
    "request_object_signing_alg": "request_object_signing_alg_values_supported",
    "request_object_encryption_alg":
        "request_object_encryption_alg_values_supported",
    "request_object_encryption_enc":
        "request_object_encryption_enc_values_supported",
    "userinfo_signed_response_alg": "userinfo_signing_alg_values_supported",
    "userinfo_encrypted_response_alg":
        "userinfo_encryption_alg_values_supported",
    "userinfo_encrypted_response_enc":
        "userinfo_encryption_enc_values_supported",
    "id_token_signed_response_alg": "id_token_signing_alg_values_supported",
    "id_token_encrypted_response_alg":
        "id_token_encryption_alg_values_supported",
    "id_token_encrypted_response_enc":
        "id_token_encryption_enc_values_supported",
    "default_acr_values": "acr_values_supported",
    "subject_type": "subject_types_supported",
    "token_endpoint_auth_method": "token_endpoint_auth_methods_supported",
    "token_endpoint_auth_signing_alg":
        "token_endpoint_auth_signing_alg_values_supported",
    "response_types": "response_types_supported",
    'grant_types': 'grant_types_supported'
}

PROVIDER2PREFERENCE = dict([(v, k) for k, v in PREFERENCE2PROVIDER.items()])

PROVIDER_DEFAULT = {
    "token_endpoint_auth_method": "client_secret_basic",
    "id_token_signed_response_alg": "RS256",
}


class AuthorizationRequest(requests.AuthorizationRequest):
    msg_type = oic.AuthorizationRequest
    response_cls = oic.AuthorizationResponse
    error_msg = oic.AuthorizationErrorResponse

    def __init__(self, httplib=None, keyjar=None, client_authn_method=None):
        super().__init__(httplib, keyjar, client_authn_method)
        self.default_request_args = {'scope': ['openid']}

    def construct(self, cli_info, request_args=None, **kwargs):
        if request_args is not None:
            if "nonce" not in request_args:
                _rt = request_args["response_type"]
                if "token" in _rt or "id_token" in _rt:
                    request_args["nonce"] = rndstr(32)
        elif "response_type" in kwargs:
            if "token" in kwargs["response_type"]:
                request_args = {"nonce": rndstr(32)}
        else:  # Never wrong to specify a nonce
            request_args = {"nonce": rndstr(32)}

        if "request_method" in kwargs:
            if kwargs["request_method"] == "file":
                request_param = "request_uri"
            else:
                request_param = "request"
            del kwargs["request_method"]

        areq = oauth2.requests.AuthorizationRequest.construct(
            self, cli_info, request_args=request_args, **kwargs)

        if 'request_param' in kwargs:
            alg = None
            for arg in ["request_object_signing_alg", "algorithm"]:
                try:  # Trumps everything
                    alg = kwargs[arg]
                except KeyError:
                    pass
                else:
                    break

            if not alg:
                try:
                    alg = cli_info.behaviour["request_object_signing_alg"]
                except KeyError:
                    alg = "none"

            kwargs["request_object_signing_alg"] = alg

            if "keys" not in kwargs and alg and alg != "none":
                _kty = jws.alg2keytype(alg)
                try:
                    _kid = kwargs["sig_kid"]
                except KeyError:
                    _kid = cli_info.kid["sig"].get(_kty, None)

                kwargs["keys"] = cli_info.keyjar.get_signing_key(_kty, kid=_kid)

            _req = make_openid_request(areq, **kwargs)

            # Should the request be encrypted
            _req = request_object_encryption(_req, **kwargs)

            if kwargs['request_param'] == "request":
                areq["request"] = _req
            else:
                try:
                    _webname = cli_info.registration_response['request_uris'][0]
                    filename = cli_info.filename_from_webname(_webname)
                except KeyError:
                    filename, _webname = construct_redirect_uri(**kwargs)
                fid = open(filename, mode="w")
                fid.write(_req)
                fid.close()
                areq["request_uri"] = _webname

        return areq

    def do_request_init(self, cli_info, scope="", body_type="json",
                        method="GET", request_args=None, http_args=None,
                        authn_method="", **kwargs):

        kwargs['algs'] = cli_info.sign_enc_algs("id_token")

        if 'code_challenge' in cli_info.config:
            _args, code_verifier = cli_info.add_code_challenge()
            request_args.update(_args)

        return requests.AuthorizationRequest.do_request_init(
            self, cli_info, scope=scope, body_type=body_type, method=method,
            request_args=request_args, http_args=http_args,
            authn_method=authn_method, **kwargs)


class AccessTokenRequest(requests.AccessTokenRequest):
    msg_type = oic.AccessTokenRequest
    response_cls = oic.AccessTokenResponse
    error_msg = oic.TokenErrorResponse

    def do_request_init(self, cli_info, scope="", body_type="json",
                        method="POST", request_args=None, http_args=None,
                        authn_method="", **kwargs):

        kwargs['algs'] = cli_info.sign_enc_algs("id_token")

        if 'code_challenge' in cli_info.config:
            _args, code_verifier = cli_info.add_code_challenge()
            request_args.update(_args)

        return requests.AccessTokenRequest.do_request_init(
            self, cli_info, scope=scope, body_type=body_type, method=method,
            request_args=request_args, http_args=http_args,
            authn_method=authn_method, **kwargs)

    def _post_parse_response(self, resp, cli_info, state=''):
        try:
            _idt = resp['id_token']
        except KeyError:
            pass
        else:
            try:
                if cli_info.state2nonce[state] != _idt['nonce']:
                    raise ParameterError('Someone has messed with "nonce"')
            except KeyError:
                pass


class RefreshAccessTokenRequest(requests.RefreshAccessTokenRequest):
    msg_type = oic.RefreshAccessTokenRequest
    response_cls = oic.AccessTokenResponse
    error_msg = oic.TokenErrorResponse


class ProviderInfoDiscovery(requests.ProviderInfoDiscovery):
    msg_type = oic.Message
    response_cls = oic.ProviderConfigurationResponse
    error_msg = ErrorResponse

    def _post_parse_response(self, resp, cli_info, **kwargs):
        self.match_preferences(cli_info, resp, cli_info.issuer)
        requests.ProviderInfoDiscovery._post_parse_response(self, resp,
                                                            cli_info, **kwargs)

    def match_preferences(self, cli_info, pcr=None, issuer=None):
        """
        Match the clients preferences against what the provider can do.

        :param pcr: Provider configuration response if available
        :param issuer: The issuer identifier
        """
        if not pcr:
            pcr = cli_info.provider_info

        regreq = oic.RegistrationRequest

        for _pref, _prov in PREFERENCE2PROVIDER.items():
            try:
                vals = cli_info.client_prefs[_pref]
            except KeyError:
                continue

            try:
                _pvals = pcr[_prov]
            except KeyError:
                try:
                    cli_info.behaviour[_pref] = PROVIDER_DEFAULT[_pref]
                except KeyError:
                    # cli_info.behaviour[_pref]= vals[0]
                    if isinstance(pcr.c_param[_prov][0], list):
                        cli_info.behaviour[_pref] = []
                    else:
                        cli_info.behaviour[_pref] = None
                continue

            if isinstance(vals, six.string_types):
                if vals in _pvals:
                    cli_info.behaviour[_pref] = vals
            else:
                vtyp = regreq.c_param[_pref]

                if isinstance(vtyp[0], list):
                    cli_info.behaviour[_pref] = []
                    for val in vals:
                        if val in _pvals:
                            cli_info.behaviour[_pref].append(val)
                else:
                    for val in vals:
                        if val in _pvals:
                            cli_info.behaviour[_pref] = val
                            break

            if _pref not in cli_info.behaviour:
                raise ConfigurationError(
                    "OP couldn't match preference:%s" % _pref, pcr)

        for key, val in cli_info.client_prefs.items():
            if key in cli_info.behaviour:
                continue

            try:
                vtyp = regreq.c_param[key]
                if isinstance(vtyp[0], list):
                    pass
                elif isinstance(val, list) and not isinstance(val,
                                                              six.string_types):
                    val = val[0]
            except KeyError:
                pass
            if key not in PREFERENCE2PROVIDER:
                cli_info.behaviour[key] = val


class RegistrationRequest(Request):
    msg_type = oic.RegistrationRequest
    response_cls = oic.RegistrationResponse
    error_msg = ErrorResponse
    endpoint_name = 'registration_endpoint'
    synchronous = True
    request = 'registration'

    def create_registration_request(self, cli_info, **kwargs):
        """
        Create a registration request

        :param kwargs: parameters to the registration request
        :return:
        """
        req = oic.RegistrationRequest()

        for prop in req.parameters():
            try:
                req[prop] = kwargs[prop]
            except KeyError:
                try:
                    req[prop] = cli_info.behaviour[prop]
                except KeyError:
                    pass

        if "post_logout_redirect_uris" not in req:
            try:
                req[
                    "post_logout_redirect_uris"] = \
                    cli_info.post_logout_redirect_uris
            except AttributeError:
                pass

        if "redirect_uris" not in req:
            try:
                req["redirect_uris"] = cli_info.redirect_uris
            except AttributeError:
                raise MissingRequiredAttribute("redirect_uris", req)

        try:
            if cli_info.provider_info[
                'require_request_uri_registration'] is True:
                req['request_uris'] = cli_info.generate_request_uris(
                    cli_info.requests_dir)
        except KeyError:
            pass

        return req

    def _post_parse_response(self, resp, cli_info, **kwargs):
        cli_info.registration_response = resp
        if "token_endpoint_auth_method" not in cli_info.registration_response:
            cli_info.registration_response[
                "token_endpoint_auth_method"] = "client_secret_basic"
        cli_info.client_id = resp["client_id"]
        try:
            cli_info.client_secret = resp["client_secret"]
        except KeyError:  # Not required
            pass
        else:
            try:
                cli_info.registration_expires = resp["client_secret_expires_at"]
            except KeyError:
                pass
        try:
            cli_info.registration_access_token = resp[
                "registration_access_token"]
        except KeyError:
            pass


class UserInfoRequest(Request):
    msg_type = Message
    response_cls = oic.OpenIDSchema
    error_msg = oic.UserInfoErrorResponse
    endpoint_name = 'userinfo_endpoint'
    synchronous = True
    request = 'userinfo'
    default_authn_method = 'bearer_header'

    def construct(self, cli_info, request_args=None, **kwargs):
        if request_args is None:
            request_args = {}

        if "access_token" in request_args:
            pass
        else:
            if "scope" not in kwargs:
                kwargs["scope"] = "openid"
            token = cli_info.grant_db.get_token(**kwargs)
            if token is None:
                raise MissingParameter("No valid token available")

            request_args["access_token"] = token.access_token

        return Request.construct(self, cli_info, request_args, **kwargs)

    def _post_parse_response(self, resp, client_info, **kwargs):
        self.unpack_aggregated_claims(resp, client_info)
        self.fetch_distributed_claims(resp, client_info)

    def unpack_aggregated_claims(self, userinfo, cli_info):
        if userinfo["_claim_sources"]:
            for csrc, spec in userinfo["_claim_sources"].items():
                if "JWT" in spec:
                    aggregated_claims = Message().from_jwt(
                        spec["JWT"].encode("utf-8"),
                        keyjar=cli_info.keyjar, sender=csrc)
                    claims = [value for value, src in
                              userinfo["_claim_names"].items() if
                              src == csrc]

                    if set(claims) != set(list(aggregated_claims.keys())):
                        logger.warning(
                            "Claims from claim source doesn't match "
                            "what's in "
                            "the userinfo")

                    for key, vals in aggregated_claims.items():
                        userinfo[key] = vals

        return userinfo

    def fetch_distributed_claims(self, userinfo, cli_info, callback=None):
        for csrc, spec in userinfo["_claim_sources"].items():
            if "endpoint" in spec:
                if "access_token" in spec:
                    _uinfo = self.request_and_return(spec["endpoint"],
                                                     method='GET',
                                                     token=spec["access_token"],
                                                     client_info=cli_info)
                else:
                    if callback:
                        _uinfo = self.request_and_return(
                            spec["endpoint"],
                            method='GET',
                            token=callback(spec['endpoint']),
                            client_info=cli_info)
                    else:
                        _uinfo = self.request_and_return(
                            spec["endpoint"],
                            method='GET',
                            client_info=cli_info)

                claims = [value for value, src in
                          userinfo["_claim_names"].items() if src == csrc]

                if set(claims) != set(list(_uinfo.keys())):
                    logger.warning(
                        "Claims from claim source doesn't match what's in "
                        "the userinfo")

                for key, vals in _uinfo.items():
                    userinfo[key] = vals

        return userinfo


def set_id_token(cli_info, request_args, **kwargs):
    if request_args is None:
        request_args = {}

    try:
        _prop = kwargs["prop"]
    except KeyError:
        _prop = "id_token"

    if _prop in request_args:
        pass
    else:
        id_token = cli_info._get_id_token(**kwargs)
        if id_token is None:
            raise MissingParameter("No valid id token available")

        request_args[_prop] = id_token
    return request_args


class CheckSessionRequest(Request):
    msg_type = oic.CheckSessionRequest
    response_cls = Message
    error_msg = ErrorResponse
    endpoint_name = ''
    synchronous = True
    request = 'check_session'

    def construct(self, cli_info, request_args=None, **kwargs):
        request_args = set_id_token(cli_info, request_args, **kwargs)
        return Request.construct(self, cli_info, request_args, **kwargs)


class CheckIDRequest(Request):
    msg_type = oic.CheckIDRequest
    response_cls = Message
    error_msg = ErrorResponse
    endpoint_name = ''
    synchronous = True
    request = 'check_id'

    def construct(self, cli_info, request_args=None, **kwargs):
        request_args = set_id_token(cli_info, request_args, **kwargs)
        return Request.construct(self, cli_info, request_args, **kwargs)


class EndSessionRequest(Request):
    msg_type = oic.EndSessionRequest
    response_cls = Message
    error_msg = ErrorResponse
    endpoint_name = 'end_session_endpoint'
    synchronous = True
    request = 'end_session'

    def construct(self, cli_info, request_args=None, **kwargs):
        request_args = set_id_token(cli_info, request_args, **kwargs)
        return Request.construct(self, cli_info, request_args, **kwargs)


def factory(req_name, **kwargs):
    for name, obj in inspect.getmembers(sys.modules[__name__]):
        if inspect.isclass(obj) and issubclass(obj, Request):
            try:
                if obj.__name__ == req_name:
                    return obj(**kwargs)
            except AttributeError:
                pass

    return requests.factory(req_name, **kwargs)
