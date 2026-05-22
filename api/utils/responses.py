from flask import jsonify, request, g
import uuid


def _ensure_request_id():
    rid = getattr(g, 'request_id', None)
    if not rid:
        rid = str(uuid.uuid4())
        g.request_id = rid
    return rid


def make_ok(data=None, status: int = 200):
    rid = _ensure_request_id()
    payload = {
        'success': True,
        # Do not coerce falsy values like [] into {}
        'data': data if data is not None else {},
        'request_id': rid,
    }
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers['X-Request-ID'] = rid
    return resp


def make_err(code: str, message: str, details: dict | None = None, status: int = 400):
    rid = _ensure_request_id()
    payload = {
        'success': False,
        'error': {
            'code': code,
            'message': message,
            'details': details or {},
        },
        'request_id': rid,
    }
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers['X-Request-ID'] = rid
    return resp



