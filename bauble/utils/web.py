# Copyright 2008-2010 Brett Adams
# Copyright 2014-2017 Mario Frasca <mario@anche.no>.
# Copyright 2016-2025 Ross Demuth <rossdemuth123@gmail.com>
#
# This file is part of ghini.desktop.
#
# ghini.desktop is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ghini.desktop is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ghini.desktop. If not, see <http://www.gnu.org/licenses/>.
"""
Utils for the web...
"""
from __future__ import annotations

import json
import logging
import re
import socket
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from fnmatch import fnmatch
from http.client import HTTPResponse
from ipaddress import ip_address
from ipaddress import ip_network
from operator import attrgetter
from typing import TYPE_CHECKING
from typing import NotRequired
from typing import TypedDict

import dukpy  # type: ignore [import-untyped]

logger = logging.getLogger(__name__)

from gi.repository import Gtk

from bauble.i18n import _
from bauble.utils import desktop

if TYPE_CHECKING:
    from bauble import db

LinkDict = TypedDict(
    "LinkDict",
    {
        "_base_uri": NotRequired[str],
        "title": str,
        "tooltip": None | str,
        "name": NotRequired[str],
        "editor_button": NotRequired[bool],
    },
)

DEPRECATED_FIELD_RE = re.compile(r"%\(([a-z_\.]+)\)s")
FIELD_RE = re.compile(r"\{v\[([a-z_\.]+)\]\}")


def update_deprecated_forms(_base_uri: str) -> str:
    """Update deprecated forms of the base uri to the new format.

    This is a temporary measure to allow for backwards compatibility.
    """
    _base_uri = _base_uri.replace("%s", "{}")
    _base_uri = re.sub(
        DEPRECATED_FIELD_RE,
        r"{v[\1]}",
        _base_uri,
    )
    return _base_uri


def get_formatted_url_for_obj(
    base_uri: str, fields: list[str], obj: db.Domain
) -> str:
    """Given a base_uri template and list of fields get the formatted url for
    the object.
    """
    uri = ""
    values = {}
    if fields:
        for key in fields:
            value = attrgetter(key)(obj)
            values[key] = urllib.parse.quote(str(value or ""))
        uri = base_uri.format(v=values)
    else:
        # remove any zws (species string)
        string = urllib.parse.quote(str(obj).replace("\u200b", ""))
        uri = base_uri.format(string)

    logger.debug("uri = %s", repr(uri))

    return uri


class BaubleLinkButton(Gtk.LinkButton):
    _base_uri = "%s"
    title = _("Search")
    tooltip: str | None = None
    fields: list[str] = []

    def __init__(self) -> None:
        super().__init__(uri="", label=self.title)
        self.set_tooltip_text(self.tooltip or self.title)

        self.__class__._base_uri = update_deprecated_forms(self._base_uri)

        self.__class__.fields = FIELD_RE.findall(self._base_uri)
        self.set_halign(Gtk.Align.START)
        self.connect("activate-link", self.on_link_activated)

    def on_link_activated(self, _button) -> bool:
        logger.debug("opening link %s", self.get_uri())
        desktop.open(self.get_uri())
        return True

    def set_string(self, row: db.Domain) -> None:

        try:
            self.set_uri(
                get_formatted_url_for_obj(
                    self._base_uri,
                    self.fields,
                    row,
                )
            )
        except Exception:
            # rather than crash let the user know
            self.set_sensitive(False)
            self.set_label(f"ERROR!!! <{self.title}>")


def link_button_factory(link: LinkDict) -> BaubleLinkButton:
    return type(
        link.get("name", "LinkButton"), (BaubleLinkButton,), dict(link)
    )()


class PACFile:
    """A simple PAC (proxy auto-config) parser.

    Instatiate with pac file javascript content supplied as a string.
    """

    # TODO impliment the remaining pac functions
    def __init__(self, pac: str) -> None:
        self.js_interp = dukpy.JSInterpreter()
        self.add_function("dnsDomainIs", self.dns_domain_is)
        self.add_function("isInNet", self.is_in_net)
        self.add_function("myIpAddress", self.my_ip_address)
        self.add_function("shExpMatch", self.sh_exp_match)
        self.add_function("isPlainHostName", self.is_plain_host_name)
        logger.debug("PACFILE content:\n%s", pac)
        self.js_interp.evaljs(pac)

    @staticmethod
    def parse_proxy(proxy: str) -> list[str]:
        """Given a valid PROXY output from FindProxyForURL as a string convert
        it into a list of the proxy addresses as strings.
        """
        proxy_list = []
        for url in proxy.split(";"):
            url = url.strip()
            if url.startswith("PROXY"):
                proxy_list.append(url.removeprefix("PROXY").strip())
        return proxy_list

    def add_function(self, name: str, func: Callable) -> None:
        self.js_interp.export_function(func.__name__, func)
        code = func.__code__
        params = ", ".join(code.co_varnames[: code.co_argcount])
        call = f'"{func.__name__}"'
        if params:
            call += f", {params}"
        self.js_interp.evaljs(
            f"{name} = function({params}) {{"
            f"   return call_python({call})"
            "};"
        )

    def find_proxy_for_url(self, url: str, host: str) -> str:
        return self.js_interp.evaljs(
            "FindProxyForURL(dukpy['url'], dukpy['host'])",
            url=url,
            host=host,
        )

    @staticmethod
    def dns_domain_is(host: str, domain: str) -> bool:
        return host.lower().endswith(domain)

    @staticmethod
    def is_in_net(host: str, ip_add: str, mask: str) -> bool:
        try:
            cidr = sum(bin(int(x)).count("1") for x in mask.split("."))
            host_name = socket.gethostbyname(host)
            return ip_address(host_name) in ip_network(f"{ip_add}/{cidr}")
        except socket.gaierror:
            # If gethostbyname can't resolve return False (e.g. no network
            # connection == no DNS)
            return False

    @staticmethod
    def my_ip_address() -> str:
        try:
            return socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            return ""

    @staticmethod
    def sh_exp_match(host: str, domain: str) -> bool:
        return fnmatch(host.lower(), domain.lower())

    @staticmethod
    def is_plain_host_name(host: str) -> bool:
        return "." not in host


class NetResponse:
    """Simple convenience wrapper for a HTTPResponse."""

    def __init__(self, response: HTTPResponse | None) -> None:
        self._response = response

    @property
    def ok(self) -> bool:
        if self._response:
            return self._response.status == 200
        return False

    @property
    def content(self) -> bytes | None:
        if self._response and self.ok:
            return self._response.read()
        return None

    def json(self) -> list | dict | None:
        if self._response and self.ok:
            return json.load(self._response)
        return None

    @property
    def text(self) -> str | None:
        if self._response and self.ok:
            return self._response.read().decode("utf-8")
        return None


class NetSession:
    """Provides methods to ensure correct proxies are used for web requests."""

    def __init__(self) -> None:
        self.proxies: str | dict[str, str] | None = None
        self.pac_file: PACFile | None = None
        self._response: HTTPResponse | None = None
        self._last_proxies: dict[str, str] | None = None
        proxy_handler = urllib.request.ProxyHandler(self.get_proxies())
        self.opener = urllib.request.build_opener(proxy_handler)

    def _get_pac_path(self) -> str:
        path = ""

        if isinstance(self.proxies, str):
            # allow user to supply a path to the pac file
            if self.proxies.startswith("PAC_FILE:"):
                return self.proxies.removeprefix("PAC_FILE:").strip()
            return path
        if isinstance(self.proxies, dict):
            return path

        if sys.platform == "win32":
            import winreg  # pylint: disable=import-error

            try:
                reg_path = "\\".join(
                    (
                        "Software",
                        "Microsoft",
                        "Windows",
                        "CurrentVersion",
                        "Internet Settings",
                    )
                )
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                    path = winreg.QueryValueEx(key, "AutoConfigURL")[0]
            except OSError as e:
                logger.error("%s(%s)", type(e).__name__, e)
        elif sys.platform == "darwin":
            import SystemConfiguration  # type: ignore [import-untyped]

            try:
                # pylint: disable=no-member
                proxy_config = SystemConfiguration.SCDynamicStoreCopyProxies(
                    None
                )
                if (
                    "ProxyAutoConfigEnable" in proxy_config
                    and "ProxyAutoConfigURLString" in proxy_config
                    and not proxy_config.get("ProxyAutoDiscoveryEnable", 0)
                ):
                    path = str(
                        proxy_config.get("ProxyAutoConfigURLString", "")
                    )
            except AttributeError as e:
                logger.error("%s(%s)", type(e).__name__, e)
        return path

    def _get_pac_contents(self, path: str, timeout: float = 5.0) -> str:
        pac_js = ""

        try:
            logger.debug("attempting to open PACFile from file path")
            with open(path, encoding="UTF-8") as pac:
                pac_js = pac.read()
        except OSError as e:
            logger.debug("%s(%s)", type(e).__name__, e)

        if not pac_js:
            try:
                logger.debug("attempting to open PACFile from url")
                with urllib.request.urlopen(path, timeout=timeout) as response:
                    content_type = response.headers.get("Content-Type")
                    if (
                        "application/x-ns-proxy-autoconfig" in content_type
                        or "application/x-javascript-config" in content_type
                    ):
                        pac_js = response.read().decode("utf-8")
            except OSError as e:
                logger.error("%s(%s)", type(e).__name__, e)
        return pac_js

    def set_pac(self, timeout: float = 5.0) -> None:
        """Discover and load a system pac file if available."""
        path = self._get_pac_path()
        if not path:
            return

        logger.debug("PACFile path: %s", path)
        pac_js = self._get_pac_contents(path, timeout)

        if pac_js:
            self.pac_file = PACFile(pac_js)

    def get(self, url: str, timeout: float = 5.0, **kwargs) -> NetResponse:
        """Make a GET request to the supplied url.

        Uses an appropriate proxy when required.

        `close` should be called after you have finished with the response.

        :param url: The url to open.
        :param timeout: The timeout in seconds for the request.
        :param kwargs: Any additional arguments are passed to the
            `urllib.request.Request` object.
        """
        if self.pac_file:
            split = urllib.parse.urlsplit(url)
            proxy = self.pac_file.find_proxy_for_url(url, split.netloc)

            logger.debug("PACFile found proxy: %s", proxy)

            if proxy != "DIRECT":
                for proxy_url in self.pac_file.parse_proxy(proxy):
                    proxies = {split.scheme: proxy_url}
                    self._response = self._get_response(
                        url, proxies, timeout, **kwargs
                    )
                    if self._response:
                        return NetResponse(self._response)
        proxies = self.get_proxies()
        logger.debug("proxies now: %s", proxies)
        self._response = self._get_response(url, proxies, timeout, **kwargs)
        return NetResponse(self._response)

    def get_proxies(self) -> dict:
        """Returns proxies as supplied (from prefs), as defined in the
        environemnt or an empty dict if neither.
        """
        if isinstance(self.proxies, dict):
            return self.proxies
        if not self.proxies:
            return urllib.request.getproxies()
        return {}

    def _get_response(
        self, url: str, proxies: dict[str, str], timeout: float, **kwargs
    ) -> HTTPResponse | None:
        # recreate the opener if the proxies are the not the same as last time
        if proxies != self._last_proxies:
            self._create_opener(proxies)

        logger.debug("attempting to open url: %s", url)
        try:
            req_url = urllib.request.Request(url, **kwargs)
            return self.opener.open(req_url, timeout=timeout)
        except OSError as e:
            # NOTE to avoid SSL: CERTIFICATE_VERIFY_FAILED in frozen state need
            # to add SSL_CERT_FILE envvar pointing to certifi's cacert.pem at
            # program start, see bauble.__init__()
            logger.error("%s(%s)", type(e).__name__, e)
            return None

    def _create_opener(self, proxies: dict[str, str]):
        proxy_handler = urllib.request.ProxyHandler(proxies)
        self.opener = urllib.request.build_opener(proxy_handler)
        logger.debug("new opener created with proxies: %s", proxies)
        self._last_proxies = proxies

    def close(self) -> None:
        """If a response is open then close it.

        Should be called after any GET request.
        """
        if self._response:
            self._response.close()
            self._response = None


class NetSessionFunctor:
    """Functor to return a global network Session.

    Defers creating the NetSession until first use.  Beware of race conditions
    if first use is within multiple threads.  Calling early in a single short
    lived thread (i.e. `connmgr.notify_new_release()`) avoids this problem.

    If proxy settings are set in config they are used.
    """

    def __init__(self) -> None:
        self.net_sess: NetSession | None = None

    def __call__(self):
        if self.net_sess is None:
            self.set_net_sess()
        return self.net_sess

    def set_net_sess(self):
        # Avoid circular imports
        from bauble import prefs

        prefs_proxies = prefs.prefs.get(prefs.web_proxy_prefs)
        logger.debug("proxies in prefs: %s", prefs_proxies)
        self.net_sess = NetSession()
        if prefs_proxies:
            self.net_sess.proxies = prefs_proxies
        self.net_sess.set_pac()


get_net_sess = NetSessionFunctor()
