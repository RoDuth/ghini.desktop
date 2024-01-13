#!/usr/bin/env python3
# Copyright (c) 2019-2024 Ross Demuth <rossdemuth123@gmail.com>
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
This is about as simple as a web server can get.  It is...

INTENDED FOR TESTING PURPOSES ONLY!!

and is

NOT SECURE!!

It will serve everything in the folder you run it from.
e.g.:
Put 'http://0.0.0.0:8081/test.html' in your host machine's browser to see the
test page.
In a virtualbox client vm http://10.0.2.2:8081/test.html should see the same.
"""

# Used to debug/test ghini is working with pac files
#
# Example Method (testing a frozen windows install):
#   1) create a win10 virtual machine in virtualbox, parallels, etc.
#       1.1) install ghini from a github release ghini.desktop-*-setup.exe
#       1.2) in %LocalAppData%/Roaming/Bauble/config add:
#            ['bauble.plugins.plants.ask_tpl', 'bauble.utils'] to your
#            debug_logging_modules setting and save.
#       1.2) set Settings > Network & Internet > Proxy > Automatic proxy setup
#            to:
#               Automatic detect settings = on,
#               Use setup script = on,
#               # virtualbox
#               Script address = http://10.0.2.2:8081/test.pac
#               # parallels
#               Script address = http://10.37.129.2:8081/test.pac
#            then save and close
#   2) fire up this script from a terminal in the host machine and leave it
#   running.  To be complete also pip install proxy.py in another terminal and
#   run it using proxy --hostname 127.0.0.1 --port 8080
#   3) in the win10 VM open ghini.desktop then check the logs to see if it
#   found the pacfile
#   Back in the terminal running this script you should see some like:
#       127.0.0.1 - - [23/Nov/2019 20:24:16] "GET /test.pac HTTP/1.1" 200 -
#   And in the terminal running proxy.py something like this:
#       ...server.access_log:384 - 127.0.0.1:52139 - CONNECT api.github.com...
#
#   Use Ctrl-C to stop this script.

import http.server
import socketserver
from pathlib import Path

DIRECTORY = Path(__file__).parent.resolve()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)


# consider pac files content type
Handler.extensions_map.update({".pac": "application/x-ns-proxy-autoconfig"})


class SimpleServer(socketserver.TCPServer):
    """
    Simplest way to ensure we make the socket accessible after we ctrl-c.
    """

    allow_reuse_address = True


server = SimpleServer(("0.0.0.0", 8081), Handler)

if __name__ == "__main__":
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("shutting down simple_serve")
        server.shutdown()
