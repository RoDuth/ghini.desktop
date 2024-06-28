# Copyright (c) 2024 Ross Demuth <rossdemuth123@gmail.com>
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
Path tests
"""
import os
from pathlib import Path
from unittest import TestCase
from unittest import mock

from bauble import paths


class PathTests(TestCase):
    @mock.patch("os.path.dirname")
    def test_main_dir(self, mock_dirname):
        mock_dirname.return_value = "."
        self.assertEqual(paths.main_dir(), str(Path.cwd()))
        mock_dirname.return_value = ""
        self.assertEqual(paths.main_dir(), str(Path.cwd()))
        mock_dirname.return_value = "mock_dir"
        self.assertEqual(paths.main_dir(), str(Path.cwd() / "mock_dir"))

    def test_root_dir(self):
        self.assertEqual(paths.root_dir(), Path(__file__).parent.parent.parent)

    def test_lib_dir(self):
        self.assertEqual(paths.lib_dir(), str(Path(__file__).parent.parent))

    def test_locale_dir(self):
        self.assertEqual(
            paths.locale_dir(),
            str(Path(paths.installation_dir(), "share/locale")),
        )

    def test_installation_dir(self):
        with mock.patch(
            "sys.platform",
            new_callable=mock.PropertyMock(return_value="linux"),
        ):
            self.assertEqual(
                paths.installation_dir(), str(Path(__file__).parent.parent)
            )
        with mock.patch(
            "sys.platform",
            new_callable=mock.PropertyMock(return_value="win32"),
        ):
            self.assertEqual(paths.installation_dir(), paths.main_dir())
        with mock.patch(
            "sys.platform",
            new_callable=mock.PropertyMock(return_value="BeOS"),
        ):
            self.assertRaises(NotImplementedError, paths.installation_dir)

    def test_appdata_dir(self):
        with mock.patch(
            "sys.platform",
            new_callable=mock.PropertyMock(return_value="win32"),
        ):
            app_data = os.environ.get("APPDATA")
            uprof = os.environ.get("USERPROFILE")
            if app_data:
                del os.environ["APPDATA"]
            if uprof:
                del os.environ["USERPROFILE"]
            self.assertRaises(Exception, paths.appdata_dir)
            os.environ["APPDATA"] = "/TEST"
            self.assertEqual(
                paths.appdata_dir(), str(Path("/TEST", "Bauble").resolve())
            )
            del os.environ["APPDATA"]

            os.environ["USERPROFILE"] = "/TEST2"
            self.assertEqual(
                paths.appdata_dir(),
                str(Path("/TEST2", "Application Data", "Bauble").resolve()),
            )
            del os.environ["USERPROFILE"]

            with mock.patch(
                "bauble.paths.is_portable_installation"
            ) as mock_portable:
                mock_portable.return_value = True
                self.assertEqual(
                    paths.appdata_dir(),
                    str(Path(paths.main_dir(), "Appdata").resolve()),
                )
            if app_data:
                os.environ["APPDATA"] = app_data
            if uprof:
                os.environ["USERPROFILE"] = uprof

        with mock.patch(
            "sys.platform",
            new_callable=mock.PropertyMock(return_value="linux"),
        ):
            user = os.environ["USER"]
            home = Path.home()
            os.environ["USER"] = "/TEST"
            self.assertEqual(
                paths.appdata_dir(),
                str(Path(home, "TEST", ".bauble")),
            )
            os.environ["USER"] = user
            with mock.patch("os.path.expanduser", side_effect=Exception()):
                self.assertRaises(Exception, paths.appdata_dir)

        mock_appkit = mock.Mock()
        with mock.patch(
            "sys.platform",
            new_callable=mock.PropertyMock(return_value="darwin"),
        ), mock.patch.dict("sys.modules", AppKit=mock_appkit):
            mock_appkit.NSSearchPathForDirectoriesInDomains.return_value = (
                "/TEST_APPKIT",
            )
            self.assertEqual(
                paths.appdata_dir(),
                str(Path("/TEST_APPKIT", "Bauble").resolve()),
            )

        with mock.patch(
            "sys.platform",
            new_callable=mock.PropertyMock(return_value="BeOS"),
        ):
            self.assertRaises(Exception, paths.appdata_dir)

    def test_is_portable_installation(self):
        # should always be false while testing
        # not windows
        with mock.patch(
            "sys.platform",
            new_callable=mock.PropertyMock(return_value="linux"),
        ):
            self.assertFalse(paths.is_portable_installation())
        # windows
        with mock.patch(
            "sys.platform",
            new_callable=mock.PropertyMock(return_value="win32"),
        ):
            self.assertFalse(paths.is_portable_installation())
            with mock.patch(
                "bauble.paths.main_is_frozen", return_value=True
            ), mock.patch("bauble.paths.main_dir", return_value=paths.TEMPDIR):
                # exception
                self.assertFalse(paths.is_portable_installation())
                Path(paths.TEMPDIR, "Appdata").mkdir()
                self.assertTrue(paths.is_portable_installation())
