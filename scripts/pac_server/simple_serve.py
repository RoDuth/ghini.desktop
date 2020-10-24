#!/usr/bin/env python
# Copyright (c) 2019 Ross Demuth <rossdemuth123@gmail.com>
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
Put 'http://0.0.0.0:8080/test.html' in your host machine's browser to see the
test page.
In a virtualbox client vm http://10.0.2.2:8080/test.html should see the same.
"""

# Used to manually debug/test ghini is working with pac files via pypac and
# bauble.utils.getsession() in ghini.desktop-1.0.92-BBG.
#
# Example Method (testing a py2exe build):
#   1) create a win10 virtual machine in virtualbox
#       1.1) install ghini from a github release ghini.desktop-*-setup.exe
#       1.2) in %LocalAppData%/Roaming/Bauble/config add:
#            ['bauble.plugins.plants.ask_tpl', 'bauble.utils'] to your
#            debug_logging_modules setting and save.
#       1.2) set Settings > Network & Internet > Proxy > Automatic proxy setup
#            to:
#               Automatic detect settings = on,
#               Script address = http://10.0.2.2:80800/test.pac
#            then save and close
#   2) fire up this script from a terminal in the host machine and leave it
#   running:
#       $ ./simple_serve.py
#   3) in the win10 VM open ghini.desktop > connect to a DB > open a
#   species_editor window > click the ask_tpl button (green dot next to
#   Species field) > close the editor windows down > "help" >
#   "Open the log-file"
#   You should see lines that end with:
#       pac_file = <pypac.parser.PACFile object at 0x12345678>
#       session type = <class 'pypac.api.PACSession'>
#       session proxies = {}
#   back in you host where you executed this script you should see a line like
#   this for each time ghini is opened and grabs the pac file (ghini should
#   grab the pac file once each session - in a py2exe frozen version this is
#   when you first open and check for a new installer):
#       127.0.0.1 - - [23/Nov/2019 20:24:16] "GET /test.pac HTTP/1.1" 200 -
#   if you don't see these lines and want to check the server is connecting:
#   unset the proxy settings above and put http://10.0.2.2:8080/test.html in
#   your VM's browser address bar to check you can retrieve the simple test
#   page.
#   Use Ctrl-C to stop this script.

import http.server
import socketserver

HANDLER = http.server.SimpleHTTPRequestHandler

# consider pac files content type
HANDLER.extensions_map.update({'.pac': 'application/x-ns-proxy-autoconfig'})


class SimpleServer(socketserver.TCPServer):
    """
    Simplest way to ensure we make the socket accessable after we ctrl-c.
    """
    allow_reuse_address = True


server = SimpleServer(('0.0.0.0', 8080), HANDLER)

server.serve_forever()
