"""Microsoft Planetary Computer STAC access.

Same pattern as philspaceagency/sdmad-opera-waterresource (ai_water/acquire.py):
  * STAC client with retry / rate-limit back-off; PC_SDK_SUBSCRIPTION_KEY (optional) raises limits;
  * searches cached on disk, so a rerun costs no request (windows touching the last 10 days are reused for 24 h only);
  * asset URLs signed at read time (a cached search stays valid), token requests serialised.
"""

import datetime as dt
import hashlib
import json
import os
import threading
import time

MPC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

_CATALOG = None
_CACHE_DIR = None
_RATE_WAIT = (20, 40, 80, 160)
_SIGN_LOCK = threading.Lock()


def set_cache_dir(directory):
    """Keep STAC search results (and MODIS composites, see modis.py) under `directory`."""
    global _CACHE_DIR
    _CACHE_DIR = str(directory) if directory else None
    if _CACHE_DIR:
        os.makedirs(os.path.join(_CACHE_DIR, "stac"), exist_ok=True)


def cache_dir():
    return _CACHE_DIR


def _open_catalog(retries=4, fresh=False):
    global _CATALOG
    if _CATALOG is not None and not fresh:
        return _CATALOG
    import pystac_client
    from pystac_client.stac_api_io import StacApiIO
    from urllib3 import Retry
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=None)
    key = os.environ.get("PC_SDK_SUBSCRIPTION_KEY")
    headers = {"Ocp-Apim-Subscription-Key": key} if key else None
    last = None
    for i in range(retries):
        try:
            _CATALOG = pystac_client.Client.open(MPC_STAC_URL, stac_io=StacApiIO(max_retries=retry, headers=headers))
            return _CATALOG
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(2 ** i)
    raise last


def _is_rate_limit(e):
    text = f"{e.__class__.__name__} {e}".lower()
    return "rate limit" in text or "429" in text or "too many requests" in text


class SigningError(RuntimeError):
    """The Planetary Computer would not issue a read token (HTTP 403 / 429 / 5xx)."""


def sign_url(href, tries=5):
    import planetary_computer as pc
    last = None
    for k in range(tries):
        try:
            with _SIGN_LOCK:
                return pc.sign(href)
        except Exception as e:
            last = e
            if k < tries - 1:
                time.sleep(min(30, 2 ** (k + 1)))
    raise SigningError(
        f"Planetary Computer refused a read token after {tries} tries: {last!r}. A 403/429 usually means anonymous "
        "access is throttled from this network: set PC_SDK_SUBSCRIPTION_KEY "
        "(https://planetarycomputer.developer.azure-api.net) or retry later.") from last


def _cache_path(query):
    if not _CACHE_DIR:
        return None
    key = hashlib.md5(json.dumps(query, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return os.path.join(_CACHE_DIR, "stac", f"{query['collections'][0]}_{key}.json")


def _cache_fresh(path, query):
    if not os.path.exists(path):
        return False
    end = str(query.get("datetime", "")).split("/")[-1][:10]
    try:
        recent = dt.date.fromisoformat(end) >= dt.date.today() - dt.timedelta(days=10)
    except ValueError:
        recent = True
    return not recent or (time.time() - os.path.getmtime(path)) < 86400


def search(retries=5, **query):
    """STAC search -> list of unsigned pystac Items, from the disk cache when possible."""
    import pystac
    path = _cache_path(query)
    if path and _cache_fresh(path, query):
        with open(path) as fh:
            return [pystac.Item.from_dict(d) for d in json.load(fh)]
    items = []
    for i in range(retries):
        try:
            items = list(_open_catalog(fresh=i > 0).search(limit=1000, **query).items())
            break
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(_RATE_WAIT[min(i, len(_RATE_WAIT) - 1)] if _is_rate_limit(e) else 2 ** i)
    if path:
        tmp = path + ".part"
        with open(tmp, "w") as fh:
            json.dump([it.to_dict() for it in items], fh)
        os.replace(tmp, path)
    return items
