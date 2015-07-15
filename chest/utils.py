import sys

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

if PY2:
    from StringIO import StringIO as BytesIO  # pragma: no cover
else:
    from io import BytesIO  # pragma: no cover


def raises(err, lambda_):
    try:
        lambda_()
        return False
    except err:
        return True


def raise_KeyError(key):
    raise KeyError("I asked for one of these %s" % key)
