from api.utils.responses import make_err


def validate_int(val, name: str, min: int = 1, max: int | None = None):
    try:
        ival = int(val)
    except Exception:
        return None, make_err('BAD_REQUEST', f"{name} mora biti celo število.")
    if ival < min or (max is not None and ival > max):
        return None, make_err('BAD_REQUEST', f"{name} mora biti v območju {min}..{max if max is not None else '∞'}.")
    return ival, None


def validate_str(val, name: str, max_len: int = 128, min_len: int = 0):
    if val is None:
        sval = ''
    else:
        sval = str(val)
    if len(sval) < min_len:
        return None, make_err('BAD_REQUEST', f"{name} mora imeti vsaj {min_len} znakov.")
    if len(sval) > max_len:
        return None, make_err('BAD_REQUEST', f"{name} ne sme presegati {max_len} znakov.")
    return sval, None



