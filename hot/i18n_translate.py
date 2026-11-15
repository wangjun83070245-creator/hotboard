"""Pluggable translators. Default local stub is FakeTranslator.

Official backends are not selected in config. Azure and Google are
frames only: keys come from environment variables, are never logged or
written to disk, and HTTP is off unless allow_network is true.
This round does not call real translation or AI endpoints.

Argos is an optional local helper if already installed; it is not the
official backend and is not auto-installed here.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .common import load_yaml
from .i18n_quality import i18n_cfg
from .httputil import redact_text, redact_url, urlopen_no_redirect


class TranslationError(Exception):
    pass


def _env(name):
    if not name:
        return None
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return None
    return str(v)


_redact_url = redact_url


class Translator:
    name = "base"

    def translate(self, text, src="en", tgt="zh"):
        raise NotImplementedError


class NoneTranslator(Translator):
    """Official Actions engine: use the committed cache only. No network."""

    name = "none"

    def translate(self, text, src="en", tgt="zh"):
        raise TranslationError("translator is none")


class FakeTranslator(Translator):
    """Deterministic stub that yields quality-gate-passing Chinese. No network."""

    name = "fake"

    def __init__(self):
        self.calls = []

    def translate(self, text, src="en", tgt="zh"):
        src_text = "" if text is None else str(text)
        self.calls.append(src_text)
        return "本条已译成中文。"


class ArgosTranslator(Translator):
    """Optional local Argos engine. Import is lazy; missing install is an error."""

    name = "argos"

    def translate(self, text, src="en", tgt="zh"):
        try:
            import argostranslate.translate as at  # type: ignore
        except ImportError as e:
            raise TranslationError("argos is not installed") from e
        src_text = "" if text is None else str(text)
        try:
            out = at.translate(src_text, src or "en", "zh")
        except Exception as e:
            raise TranslationError("argos failed") from e
        return "" if out is None else str(out)


class _HttpTranslator(Translator):
    def __init__(self, opener=None, timeout=20, allow_network=False):
        self.opener = opener
        self.timeout = timeout
        self.allow_network = bool(allow_network)

    def _send(self, req):
        if not self.allow_network and self.opener is None:
            raise TranslationError("network disabled")
        open_fn = self.opener or urlopen_no_redirect
        try:
            with open_fn(req, timeout=self.timeout) as resp:
                body = resp.read()
                status = getattr(resp, "status", None) or resp.getcode()
        except urllib.error.HTTPError as e:
            raise TranslationError(f"http {e.code}") from e
        except Exception as e:
            raise TranslationError(f"http {type(e).__name__}") from e
        if status and int(status) >= 400:
            raise TranslationError(f"http {status}")
        return body


class AzureTranslator(_HttpTranslator):
    name = "azure"

    def __init__(self, cfg=None, opener=None, timeout=20, allow_network=False,
                 key=None, region=None, endpoint=None):
        super().__init__(opener=opener, timeout=timeout, allow_network=allow_network)
        ic = i18n_cfg(cfg)
        spec = (ic.get("engines") or {}).get("azure") or {}
        self._key_name = spec.get("env_key") or "AZURE_TRANSLATOR_KEY"
        self._region_name = spec.get("env_region") or "AZURE_TRANSLATOR_REGION"
        self._endpoint_name = spec.get("env_endpoint") or "AZURE_TRANSLATOR_ENDPOINT"
        self._default_endpoint = spec.get("default_endpoint") or "https://api.cognitive.microsofttranslator.com"
        self._key = key
        self._region = region
        self._endpoint = endpoint

    def translate(self, text, src="en", tgt="zh"):
        key = self._key if self._key is not None else _env(self._key_name)
        if not key:
            raise TranslationError("missing azure key")
        endpoint = (self._endpoint or _env(self._endpoint_name) or self._default_endpoint).rstrip("/")
        region = self._region if self._region is not None else _env(self._region_name)
        to = "zh-Hans" if tgt in ("zh", "zh-CN", "zh-Hans") else tgt
        url = endpoint + "/translate?api-version=3.0&from=" + urllib.parse.quote(src or "en") + "&to=" + urllib.parse.quote(to)
        headers = {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": key,
        }
        if region:
            headers["Ocp-Apim-Subscription-Region"] = region
        req = urllib.request.Request(url, data=json.dumps([{"Text": str(text or "")}]).encode("utf-8"),
                                     headers=headers, method="POST")
        raw = self._send(req)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data[0]["translations"][0]["text"]
        except Exception as e:
            raise TranslationError("bad azure payload") from e


class GoogleTranslator(_HttpTranslator):
    name = "google"

    def __init__(self, cfg=None, opener=None, timeout=20, allow_network=False, key=None, endpoint=None):
        super().__init__(opener=opener, timeout=timeout, allow_network=allow_network)
        ic = i18n_cfg(cfg)
        spec = (ic.get("engines") or {}).get("google") or {}
        self._key_name = spec.get("env_key") or "GOOGLE_TRANSLATE_API_KEY"
        self._endpoint = endpoint or spec.get("endpoint") or "https://translation.googleapis.com/language/translate/v2"
        self._key = key

    def translate(self, text, src="en", tgt="zh"):
        key = self._key if self._key is not None else _env(self._key_name)
        if not key:
            raise TranslationError("missing google key")
        target = "zh-CN" if tgt in ("zh", "zh-CN", "zh-Hans") else tgt
        # Key goes in the X-goog-api-key header, never in logs.
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": key,
        }
        body = json.dumps({
            "q": str(text or ""),
            "source": src or "en",
            "target": target,
            "format": "text",
        }).encode("utf-8")
        req = urllib.request.Request(self._endpoint, data=body, headers=headers, method="POST")
        raw = self._send(req)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data["data"]["translations"][0]["translatedText"]
        except Exception as e:
            raise TranslationError("bad google payload") from e


def available_engines():
    return ("fake", "none", "azure", "google", "argos")


def make_translator(name=None, cfg=None, opener=None, allow_network=None, **kwargs):
    ic = i18n_cfg(cfg)
    env_name = (os.environ.get("I18N_ENGINE") or "").strip().lower()
    chosen = (name or env_name or ic.get("local_engine") or "fake").strip().lower()
    if chosen in {"github_models", "github-models", "models"}:
        raise TranslationError("github models is not a supported engine")
    if allow_network is None:
        allow_network = bool(ic.get("allow_network"))
    if chosen == "fake":
        return FakeTranslator()
    if chosen == "none":
        return NoneTranslator()
    if chosen == "azure":
        return AzureTranslator(cfg=ic, opener=opener, allow_network=allow_network, **kwargs)
    if chosen == "google":
        return GoogleTranslator(cfg=ic, opener=opener, allow_network=allow_network, **kwargs)
    if chosen == "argos":
        return ArgosTranslator()
    raise TranslationError("unknown engine")


def load_i18n_cfg(cfg=None):
    return i18n_cfg(cfg)
