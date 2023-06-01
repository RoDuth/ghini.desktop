# Copyright 2023 Ross Demuth <rossdemuth123@gmail.com>
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
#
"""
synclone plugin

Description: plugin to provide cloning and syncing the database
"""
from bauble import pluginmgr


class SynClonePlugin(pluginmgr.Plugin):
    # avoid cicular imports
    from .clone import DBCloneTool
    from .sync import DBSyncTool, DBResolveSyncTool
    tools = [DBCloneTool,
             DBSyncTool,
             DBResolveSyncTool]

plugin = SynClonePlugin
