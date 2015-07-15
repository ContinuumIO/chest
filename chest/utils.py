import sys

if sys.version_info[0] == 2:
    from StringIO import StringIO as BytesIO
else:
    from io import BytesIO


def raises(err, lambda_):
    try:
        lambda_()
        return False
    except err:
        return True


def raise_KeyError(key):
    raise KeyError("I asked for one of these %s" % key)
