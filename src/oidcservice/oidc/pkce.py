from cryptojwt import b64e
from oidcservice import unreserved, CC_METHOD
from oidcservice.exception import Unsupported


def add_code_challenge(service_context, state):
    """
    PKCE RFC 7636 support

    :return:
    """
    try:
        cv_len = service_context.config['code_challenge']['length']
    except KeyError:
        cv_len = 64  # Use default

    # code_verifier: string of length cv_len
    code_verifier = unreserved(cv_len)
    _cv = code_verifier.encode()

    try:
        _method = service_context.config['code_challenge']['method']
    except KeyError:
        _method = 'S256'

    try:
        # Pick hash method
        _hash_method = CC_METHOD[_method]
        # Use it on the code_verifier
        _hv = _hash_method(_cv).hexdigest()
        # base64 encode the hash value
        code_challenge = b64e(_hv.encode()).decode()
    except KeyError:
        raise Unsupported(
            'PKCE Transformation method:{}'.format(_method))

    service_context.state_db.add_info(state, code_verifier=code_verifier,
                                  code_challenge_method=_method)

    return {"code_challenge": code_challenge,
            "code_challenge_method": _method}


def get_code_verifier(service_context, state):
    return service_context.state_db[state]['code_verifier']
