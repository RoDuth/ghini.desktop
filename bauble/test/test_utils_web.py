# pylint: disable=no-self-use,protected-access,too-many-public-methods
# Copyright (c) 2024-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Web utils tests
"""
import os
import socket
import sys
import threading
from tempfile import mkstemp
from unittest import TestCase
from unittest import mock

from bauble import prefs
from bauble.test import BaubleTestCase
from bauble.utils.web import NetResponse
from bauble.utils.web import NetSession
from bauble.utils.web import NetSessionFunctor
from bauble.utils.web import PACFile
from bauble.utils.web import link_button_factory
from scripts.pac_server.simple_serve import server


class LinkButtonTests(TestCase):
    def test_factory(self):
        link = {
            "_base_uri": "http://www.google.com/search?q={}",
            "title": "Search Test",
            "tooltip": "TEST",
        }
        btn = link_button_factory(link)
        for k, v in link.items():
            self.assertEqual(getattr(btn, k), v)

    def test_set_string_basic(self):
        link = {
            "_base_uri": "http://www.google.com/search?q={}",
            "title": "Search Test",
            "tooltip": "TEST",
        }
        btn = link_button_factory(link)
        btn.set_string("Eucalyptus major")
        self.assertEqual(
            btn.get_uri(), "http://www.google.com/search?q=Eucalyptus%20major"
        )

    def test_set_string_w_fields(self):
        link = {
            "_base_uri": "http://en.wikipedia.org/wiki/{v[genus.epithet]}_{v[epithet]}",
            "title": "Search Wikipedia",
            "tooltip": "open the wikipedia page about this species",
        }
        btn = link_button_factory(link)
        mock_row = mock.Mock(
            genus=mock.Mock(epithet="Eucalyptus"),
            epithet="major",
        )
        btn.set_string(mock_row)
        self.assertEqual(
            btn.get_uri(),
            "http://en.wikipedia.org/wiki/Eucalyptus_major",
        )

    @mock.patch("bauble.utils.web.desktop.open")
    def test_on_link_activate(self, mock_open):
        link = {
            "_base_uri": "http://www.google.com/search?q={}",
            "title": "Search Test",
            "tooltip": "TEST",
        }
        btn = link_button_factory(link)
        btn.set_string("Eucalyptus major")
        btn.on_link_activated(None)
        mock_open.assert_called_with(
            "http://www.google.com/search?q=Eucalyptus%20major"
        )

    def test_depricated_format_wo_field(self):
        link = {
            "_base_uri": "http://www.google.com/search?q=%s",
            "title": "Search Test",
            "tooltip": "TEST",
        }
        btn = link_button_factory(link)
        btn.set_string("Eucalyptus major")
        self.assertEqual(
            btn.get_uri(), "http://www.google.com/search?q=Eucalyptus%20major"
        )

    def test_depricated_format_w_field(self):
        link = {
            "_base_uri": "http://en.wikipedia.org/wiki/%(genus.genus)s_%(sp)s",
            "title": "Search Wikipedia",
            "tooltip": "open the wikipedia page about this species",
        }
        btn = link_button_factory(link)
        mock_row = mock.Mock(genus=mock.Mock(genus="Eucalyptus"), sp="major")
        btn.set_string(mock_row)
        self.assertEqual(
            btn.get_uri(),
            "http://en.wikipedia.org/wiki/Eucalyptus_major",
        )

    def test_url_encoded(self):
        link = {
            "_base_uri": "https://plantsearch.bgci.org/search?"
            "filter%5Bgenus%5D={v[genus.epithet]}&"
            "filter%5bspecific_epithet%5D={v[epithet]}&"
            "sort=name",
            "title": "Search BGCI",
            "tooltip": "Search Botanic Gardens Conservation International",
        }
        btn = link_button_factory(link)
        mock_row = mock.Mock(
            genus=mock.Mock(epithet="Lenwebbia"),
            epithet="sp. (Main Range P.R. Sharpe+ 4877)",
        )
        btn.set_string(mock_row)
        self.assertEqual(
            btn.get_uri(),
            "https://plantsearch.bgci.org/search?"
            "filter%5Bgenus%5D=Lenwebbia&"
            "filter%5bspecific_epithet%5D="
            "sp.%20%28Main%20Range%20P.R.%20Sharpe%2B%204877%29&sort=name",
        )


class PACFileTests(TestCase):
    def test_parse_proxy(self):
        self.assertEqual(
            PACFile.parse_proxy(
                "PROXY 165.225.98.34:10170; PROXY 165.225.114.16:10170"
            ),
            ["165.225.98.34:10170", "165.225.114.16:10170"],
        )

    def test_dns_domain_is(self):
        self.assertTrue(
            PACFile.dns_domain_is("test.url.company.org", "company.org")
        )
        self.assertFalse(
            PACFile.dns_domain_is("test.url.company.org", "other.org")
        )

    def test_is_in_net(self):
        self.assertTrue(
            PACFile.is_in_net("10.10.10.10", "10.0.0.0", "255.0.0.0")
        )
        self.assertTrue(
            PACFile.is_in_net("10.10.10.10", "10.10.0.0", "255.255.0.0")
        )
        self.assertTrue(
            PACFile.is_in_net("10.10.10.10", "10.10.10.0", "255.255.255.0")
        )
        self.assertTrue(
            PACFile.is_in_net("10.10.10.10", "10.10.10.10", "255.255.255.255")
        )
        self.assertFalse(
            PACFile.is_in_net("10.10.10.10", "10.11.0.0", "255.255.0.0")
        )
        self.assertFalse(
            PACFile.is_in_net("10.10.10.10", "10.10.11.0", "255.255.255.0")
        )
        self.assertFalse(
            PACFile.is_in_net("11.10.10.10", "10.10.10.11", "255.255.255.255")
        )
        with mock.patch("bauble.utils.web.socket.gethostbyname") as mock_name:
            mock_name.side_effect = socket.gaierror
            self.assertFalse(
                PACFile.is_in_net("10.10.10.10", "10.10.10.0", "255.255.255.0")
            )

    def test_my_ip_address(self):
        # pointless...
        self.assertEqual(
            PACFile.my_ip_address(), socket.gethostbyname(socket.gethostname())
        )
        self.assertNotEqual(PACFile.my_ip_address(), "8.8.8.8")
        with mock.patch("bauble.utils.web.socket.gethostbyname") as mock_name:
            mock_name.side_effect = socket.gaierror
            self.assertEqual(PACFile.my_ip_address(), "")

    def test_sh_exp_match(self):
        self.assertTrue(PACFile.sh_exp_match("api.github.com", "*.github.com"))
        self.assertTrue(PACFile.sh_exp_match("api.github.com", "api.*.com"))
        self.assertTrue(
            PACFile.sh_exp_match("api.github.com", "api.github.com")
        )
        self.assertFalse(PACFile.sh_exp_match("api.github.com", "*.test.com"))
        self.assertFalse(
            PACFile.sh_exp_match("api.github.com", "api.test.com")
        )

    def test_is_plain_host_name(self):
        self.assertTrue(PACFile.is_plain_host_name("www"))
        self.assertFalse(PACFile.is_plain_host_name("www.mozzila.com"))

    def test_find_proxy_for_url(self):
        pac = """
        function FindProxyForURL(url, host)
        {
        if (url.substring(0, 4) == "ftp:")
        {
        return "DIRECT";
        }
        if (isInNet(host, "8.8.0.0", "255.255.0.0"))
        {
        return "PROXY 100.0.0.1:8080; PROXY 110.0.0.1:8080";
        }
        if (dnsDomainIs(host,"api.github.com"))
        {
        return "PROXY 120.0.0.1:8080";
        }
        if (shExpMatch(host, "*.google.com"))
        {
        return "PROXY 130.0.0.1:8080";
        }
        return "DIRECT"
        }
        """
        pacfile = PACFile(pac)

        self.assertEqual(
            pacfile.find_proxy_for_url(
                "ftp://some.server.org", "some.server.org"
            ),
            "DIRECT",
        )
        self.assertEqual(
            pacfile.find_proxy_for_url(
                "https://www.google.com/test", "www.google.com"
            ),
            "PROXY 130.0.0.1:8080",
        )
        self.assertEqual(
            pacfile.find_proxy_for_url(
                "https://api.github.com/test", "api.github.com"
            ),
            "PROXY 120.0.0.1:8080",
        )
        self.assertEqual(
            pacfile.find_proxy_for_url("https://8.8.8.8/test", "8.8.8.8"),
            "PROXY 100.0.0.1:8080; PROXY 110.0.0.1:8080",
        )
        self.assertEqual(
            pacfile.find_proxy_for_url(
                "http://some.server.org", "some.server.org"
            ),
            "DIRECT",
        )

    def test_add_function(self):
        pacfile = PACFile("")

        def test_func(param1, param2, param3):
            return param1 + param2 + param3

        pacfile.add_function("testFunc", test_func)
        self.assertEqual(pacfile.js_interp.evaljs("testFunc(1, 1, 1)"), 3)
        self.assertNotEqual(pacfile.js_interp.evaljs("testFunc(10, 10, 1)"), 3)


class NetResponseTests(TestCase):
    def setUp(self):
        mock_response = mock.Mock()
        mock_response.read.return_value = b'{"test": "value"}'
        mock_response.status = 200
        self.net_resp = NetResponse(mock_response)

    def test_ok(self):
        self.assertTrue(self.net_resp.ok)
        self.net_resp._response.status = 500
        self.assertFalse(self.net_resp.ok)
        self.net_resp._response = None
        self.assertFalse(self.net_resp.ok)

    def test_content(self):
        self.assertEqual(self.net_resp.content, b'{"test": "value"}')
        self.net_resp._response.status = 500
        self.assertIsNone(self.net_resp.content)

    def test_json(self):
        self.assertEqual(self.net_resp.json(), {"test": "value"})
        self.net_resp._response.status = 500
        self.assertIsNone(self.net_resp.json())

    def test_text(self):
        self.assertEqual(self.net_resp.text, '{"test": "value"}')
        self.net_resp._response.status = 500
        self.assertIsNone(self.net_resp.text)


class NetSessionTests(TestCase):
    def test_get_pac_path_w_prefs(self):
        net_sess = NetSession()
        net_sess.proxies = "no_pac"
        self.assertEqual(net_sess._get_pac_path(), "")
        net_sess.proxies = "PAC_FILE: /some/local/file.pac"
        self.assertEqual(net_sess._get_pac_path(), "/some/local/file.pac")
        net_sess.proxies = {"https": "10.10.10.10:8080"}
        self.assertEqual(net_sess._get_pac_path(), "")

    @mock.patch("bauble.utils.web.sys")
    def test_get_pac_path_from_windows_system(self, mock_sys):
        mock_sys.platform = "win32"
        mock_winreg = mock.MagicMock()
        mock_winreg.QueryValueEx.return_value = ["/path/to/file.pac"]
        with mock.patch.dict(sys.modules, {"winreg": mock_winreg}):
            net_sess = NetSession()
            self.assertEqual(net_sess._get_pac_path(), "/path/to/file.pac")
            mock_winreg.QueryValueEx.side_effect = OSError("failed")
            self.assertEqual(net_sess._get_pac_path(), "")

    @mock.patch("bauble.utils.web.sys")
    def test_get_pac_path_from_mac_system(self, mock_sys):
        mock_sys.platform = "darwin"
        mock_sys_conf = mock.Mock()
        mock_sys_conf.SCDynamicStoreCopyProxies.return_value = {
            "ProxyAutoConfigEnable": True,
            "ProxyAutoConfigURLString": "/path/to/file.pac",
            "ProxyAutoDiscoveryEnable": 0,
        }
        with mock.patch.dict(
            sys.modules, {"SystemConfiguration": mock_sys_conf}
        ):
            net_sess = NetSession()
            self.assertEqual(net_sess._get_pac_path(), "/path/to/file.pac")
            mock_sys_conf.SCDynamicStoreCopyProxies.side_effect = (
                AttributeError("failed")
            )
            self.assertEqual(net_sess._get_pac_path(), "")

    def test_set_pac_w_pref(self):
        net_sess = NetSession()
        net_sess.proxies = "no_pac"
        net_sess.set_pac()
        self.assertIsNone(net_sess.pac_file)
        net_sess.proxies = {"https": "10.10.10.10:8080"}
        net_sess.set_pac()
        self.assertIsNone(net_sess.pac_file)

    def test_set_pac_w_local_pac_file_pref(self):
        pac_js = """\
        function FindProxyForURL(url, host)
        {
        return "DIRECT"
        }
        """
        handle, pname = mkstemp(suffix=".pac")
        with open(pname, "w", encoding="utf-8") as f:
            f.write(pac_js)

        net_sess = NetSession()
        net_sess.proxies = f"PAC_FILE: {pname}"
        net_sess.set_pac()
        self.assertIsNotNone(net_sess.pac_file)

        # check the pac file is valid
        self.assertEqual(
            net_sess.pac_file.find_proxy_for_url(
                "http://google.com", "google.com"
            ),
            "DIRECT",
        )
        os.close(handle)

    def test_set_pac_w_url_pac_file_pref(self):
        serv_thread = threading.Thread(target=server.serve_forever)
        serv_thread.start()

        net_sess = NetSession()
        self.assertIsNone(net_sess.pac_file)
        net_sess.proxies = "PAC_FILE: http://127.0.0.1:8081/test.pac"
        net_sess.set_pac()
        self.assertIsNotNone(net_sess.pac_file)
        # check the pac file is valid
        self.assertEqual(
            net_sess.pac_file.find_proxy_for_url(
                "http://api.github.com/test", "api.github.com"
            ),
            "PROXY 127.0.0.1:8080",
        )
        server.shutdown()

    def test_set_pac_w_url_pac_file_error(self):
        serv_thread = threading.Thread(target=server.serve_forever)
        serv_thread.start()

        net_sess = NetSession()
        self.assertIsNone(net_sess.pac_file)
        net_sess.proxies = "PAC_FILE: http://9.9.9.9:8081/test.pac"
        # timeout defaults to 7 seconds, use lower to speed up test as we know
        # it will fail
        net_sess.set_pac(timeout=0.5)
        self.assertIsNone(net_sess.pac_file)
        server.shutdown()

    def test_get_w_no_proxies(self):
        net_sess = NetSession()
        net_sess._get_response = mock.Mock(return_value=None)
        url = "http://api.github.com/test"
        response = net_sess.get(url)
        self.assertIsInstance(response, NetResponse)
        self.assertIsNone(response._response)
        net_sess._get_response.assert_called_with(url, {}, 5.0)

    def test_get_w_user_set_proxies(self):
        net_sess = NetSession()
        proxies = {"https": "10.10.10.10:8080"}
        net_sess.proxies = proxies
        net_sess._get_response = mock.Mock(return_value=None)
        url = "http://api.github.com/test"
        response = net_sess.get(url)
        self.assertIsInstance(response, NetResponse)
        self.assertIsNone(response._response)
        net_sess._get_response.assert_called_with(url, proxies, 5.0)

    def test_get_w_pac_file(self):
        pac_js = """\
        function FindProxyForURL(url, host)
        {
        if (dnsDomainIs(host,"api.github.com"))
        {
        return "PROXY 127.0.0.1:8080";
        }
        return "DIRECT"
        }
        """
        net_sess = NetSession()
        net_sess.pac_file = PACFile(pac_js)
        net_sess._get_response = mock.Mock(return_value=mock.Mock())
        url = "https://api.github.com/test"
        response = net_sess.get(url)
        self.assertIsInstance(response, NetResponse)
        self.assertIsNotNone(response._response)
        net_sess._get_response.assert_called_with(
            url, {"https": "127.0.0.1:8080"}, 5.0
        )

    def test_get_proxies(self):
        net_sess = NetSession()
        self.assertEqual(net_sess.get_proxies(), {})
        os.environ["HTTPS_PROXY"] = "127.0.0.1:8080"
        self.assertEqual(net_sess.get_proxies(), {"https": "127.0.0.1:8080"})
        del os.environ["HTTPS_PROXY"]
        proxies = {"https": "10.10.10.10:8080"}
        net_sess.proxies = proxies
        self.assertEqual(net_sess.get_proxies(), proxies)
        net_sess.proxies = "no_proxies"
        self.assertEqual(net_sess.get_proxies(), {})

    def test_get_response(self):
        net_sess = NetSession()
        net_sess._create_opener = mock.Mock(return_value=None)
        net_sess.opener = mock.Mock()
        net_sess.opener.open.return_value = "TEST"
        url = "http://api.github.com/test"
        proxies = {"https": "10.10.10.10:8080"}
        response = net_sess._get_response(url, proxies, 5.0)
        self.assertEqual(response, "TEST")
        net_sess._create_opener.assert_called_with(proxies)
        net_sess.opener.open.side_effect = OSError("test")
        response = net_sess._get_response(url, proxies, 5.0)
        self.assertIsNone(response)

    def test_create_opener(self):
        net_sess = NetSession()
        start_opener = net_sess.opener
        self.assertIsNone(net_sess._last_proxies)
        proxies = {"https": "10.10.10.10:8080"}
        net_sess._create_opener(proxies)
        self.assertEqual(net_sess._last_proxies, proxies)
        self.assertNotEqual(start_opener, net_sess.opener)

    def test_close(self):
        net_sess = NetSession()
        mock_response = mock.Mock()
        net_sess._response = mock_response
        net_sess.close()
        self.assertIsNone(net_sess._response)
        mock_response.close.assert_called()


class GetNetSessTests(BaubleTestCase):
    def test_no_net_session_until_called(self):
        get_net_sess = NetSessionFunctor()
        self.assertIsNone(get_net_sess.net_sess)
        get_net_sess()
        self.assertIsNotNone(get_net_sess.net_sess)

    @mock.patch("bauble.utils.web.NetSession")
    def test_set_net_sess(self, mock_net_sess):
        get_net_sess = NetSessionFunctor()
        self.assertIsNone(get_net_sess.net_sess)
        get_net_sess.set_net_sess()
        self.assertIsNotNone(get_net_sess.net_sess)
        mock_net_sess.assert_called()
        mock_net_sess().set_pac.assert_called()

    def test_set_net_sess_respects_user_set_proxies(self):
        prefs.prefs[prefs.web_proxy_prefs] = None
        get_net_sess = NetSessionFunctor()
        self.assertIsNone(get_net_sess.net_sess)
        get_net_sess.set_net_sess()
        self.assertIsNone(get_net_sess.net_sess.proxies)

        proxies = {"https": "10.10.10.10:8080"}
        prefs.prefs[prefs.web_proxy_prefs] = proxies
        get_net_sess.set_net_sess()
        self.assertEqual(get_net_sess.net_sess.proxies, proxies)
