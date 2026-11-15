"""HTTP helpers: never follow redirects; redact secrets in URLs and log text."""
import re
import urllib.error
import urllib.parse
import urllib.request

_SENSITIVE_QUERY = {
    "key", "api_key", "apikey", "token", "access_token", "subscription-key",
}
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse all redirects so credential headers cannot hop to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def opener_no_redirect():
    return urllib.request.build_opener(NoRedirectHandler)


def urlopen_no_redirect(req, timeout=None):
    return opener_no_redirect().open(req, timeout=timeout)


def redact_url(url):
    try:
        p = urllib.parse.urlsplit(url)
        q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        red = []
        for k, v in q:
            if k.lower() in _SENSITIVE_QUERY:
                red.append((k, "[redacted]"))
            else:
                red.append((k, v))
        netloc = p.netloc
        if p.username is not None or p.password is not None:
            host = p.hostname or ""
            if p.port:
                host = host + ":" + str(p.port)
            netloc = "[redacted]@" + host
        return urllib.parse.urlunsplit((p.scheme, netloc, p.path, urllib.parse.urlencode(red), p.fragment))
    except Exception:
        return "[unparsed]"


def redact_text(text):
    s = "" if text is None else str(text)
    return _URL_RE.sub(lambda m: redact_url(m.group(0)), s)
