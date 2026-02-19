# pylint: disable=no-self-use
# Copyright 2026 Ross Demuth <rossdemuth123@gmail.com>
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
Desktop utils tests.
"""
from unittest import TestCase
from unittest import mock

from bauble.utils import desktop


class DesktopTests(TestCase):
    @mock.patch("bauble.utils.desktop.sys.platform", "freebsd")
    def test_open_unsupported_os(self):

        with self.assertRaises(OSError) as context:
            desktop.open("test.txt")
        self.assertEqual(
            str(context.exception),
            "Unsupported operating system: freebsd",
        )

        with mock.patch(
            "bauble.utils.desktop.dialogs.message_dialog"
        ) as mock_dialog:
            desktop.open("test.txt", dialog_on_error=True)
            mock_dialog.assert_called_once_with(
                "Unsupported operating system: freebsd"
            )

    @mock.patch("bauble.utils.desktop.subprocess.call")
    @mock.patch("bauble.utils.desktop.sys.platform", "linux")
    def test_open_linux(self, mock_call):

        desktop.open("test.txt")

        mock_call.assert_called_once_with(["xdg-open", "test.txt"])

        mock_call.reset_mock()
        desktop.open("www.google.com")

        mock_call.assert_called_once_with(["xdg-open", "www.google.com"])

    @mock.patch("bauble.utils.desktop.subprocess.call")
    @mock.patch("bauble.utils.desktop.sys.platform", "darwin")
    def test_open_mac_os(self, mock_call):

        desktop.open("test.txt")

        mock_call.assert_called_once_with(["open", "test.txt"])

        mock_call.reset_mock()
        desktop.open("www.google.com")

        mock_call.assert_called_once_with(["open", "www.google.com"])

    @mock.patch("bauble.utils.desktop.os")
    @mock.patch("bauble.utils.desktop.sys.platform", "win32")
    def test_open_windows(self, mock_os):

        desktop.open("test.txt")

        mock_os.startfile.assert_called_once_with("test.txt")

        mock_os.startfile.reset_mock()
        desktop.open("www.google.com")

        mock_os.startfile.assert_called_once_with("www.google.com")
