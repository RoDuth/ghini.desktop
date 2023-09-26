# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
# Copyright 2017 Jardín Botánico de Quito
# Copyright (c) 2020-2022 Ross Demuth <rossdemuth123@gmail.com>
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
Users, permissions, roles etc... postgresql only.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from gi.repository import Gtk
from sqlalchemy import Integer
from sqlalchemy.exc import ProgrammingError

try:
    from psycopg2 import DatabaseError
    from psycopg2.sql import SQL
    from psycopg2.sql import Identifier
    from psycopg2.sql import Literal
except ImportError:
    pass

from bauble import db
from bauble import editor
from bauble import pluginmgr
from bauble import utils
from bauble.error import check

# WARNING: "roles" are specific to PostgreSQL databases and won't work on other
# database types

# Read: can select and read data in the database
#
# Write: can add, edit and delete data but can't create new tables,
#        i.e. can't install plugins that create new tables, also
#        shouldn't be able to install a new database over an existing
#        database
#
# Admin: can create other users and grant privileges and create new
#        tables
#


def get_users():
    """Return the list of user names."""
    stmt = "SELECT rolname FROM pg_roles WHERE rolcanlogin IS TRUE"
    return [r[0] for r in db.engine.execute(stmt)]


def _create_role(name, password=None, login=False, admin=False):
    conn = db.engine.raw_connection()
    try:
        stmt = "CREATE ROLE {name} INHERIT"
        if login:
            stmt += " LOGIN"
        if admin:
            stmt += " CREATEROLE"
        if password:
            stmt += " WITH PASSWORD {password}"
        stmt = SQL(stmt).format(
            name=Identifier(name), password=Literal(password)
        )
        with conn.cursor() as cur:
            cur.execute(stmt)
    except Exception as e:
        logger.error("users._create_role(): %s(%s)", type(e).__name__, e)
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


def create_user(name, password=None, admin=False):
    """Create a role that can login."""
    _create_role(name, password, login=True, admin=admin)
    conn = db.engine.raw_connection()
    try:
        # allow the new role to connect to the database
        stmt = "GRANT CONNECT ON DATABASE {db} TO {name}"
        stmt = SQL(stmt).format(
            db=Identifier(db.engine.url.database), name=Identifier(name)
        )
        with conn.cursor() as cur:
            cur.execute(stmt)
            logger.debug(stmt.as_string(cur))
    except Exception as e:
        logger.error("users.create_user(): %s(%s)", type(e).__name__, e)
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


# ####  GROUPS - currently not implemented ...  nor proven ####
def get_groups():
    """Return the list of group names."""
    stmt = "SELECT rolname FROM pg_roles WHERE rolcanlogin IS FALSE"
    return [r[0] for r in db.engine.execute(stmt)]


def create_group(name, admin=False):
    """Create a role that can't login."""
    _create_role(name, login=False, password=None, admin=admin)


def add_member(name, groups=None):
    """Add name to groups."""
    if groups is None:
        groups = []
    conn = db.engine.raw_connection()
    try:
        for group in groups:
            stmt = "GRANT {group} TO {name}"
            stmt = SQL(stmt).format(
                group=Identifier(group), name=Identifier(name)
            )
            with conn.cursor() as cur:
                cur.execute(stmt)
                logger.debug(stmt.as_string(cur))
    except DatabaseError:
        conn.rollback()
    else:
        conn.commit()
    finally:
        conn.close()


def remove_member(name, groups=None):
    """Remove name from groups."""
    if groups is None:
        groups = []
    conn = db.engine.raw_connection()
    try:
        for group in groups:
            stmt = "REVOKE {group} FROM {name}"
            stmt = SQL(stmt).format(
                group=Identifier(group), name=Identifier(name)
            )
            with conn.cursor() as cur:
                cur.execute(stmt)
                logger.debug(stmt.as_string(cur))
    except DatabaseError:
        conn.rollback()
    else:
        conn.commit()
    finally:
        conn.close()


def get_members(group):
    """Return members of group

    :param group:
    """
    conn = db.engine.raw_connection()
    # get group id
    stmt = "SELECT oid FROM pg_roles WHERE rolname = {group}"
    stmt = SQL(stmt).format(group=Literal(group))
    with conn.cursor() as cur:
        cur.execute(stmt)
        logger.debug(stmt.as_string(cur))
        gid = cur.fetchone()[0]
        # get members with the gid
        stmt = (
            "SELECT rolname FROM pg_roles WHERE oid IN (SELECT member "
            "FROM pg_auth_members WHERE roleid = {gid})"
        )
        stmt = SQL(stmt).format(group=Literal(gid))
        members = cur.execute(stmt)
    conn.close()
    return [r[0] for r in members]


# ### END GROUPS


def drop(role, revoke=False):
    """Drop a user from the database

    :param role: the name of the role to drop
    :param revoke: If revoke is True then revoke the users permissions
        before dropping them
    """
    conn = db.engine.raw_connection()
    try:
        if revoke:
            # if set privilege fails then dropping the role will fail
            # because the role will still have dependent users
            set_privilege(role, None)
        stmt = "DROP ROLE {role}"
        stmt = SQL(stmt).format(role=Identifier(role))

        with conn.cursor() as cur:
            cur.execute(stmt)

    except Exception as e:
        logger.error("users.drop(): %s(%s)", type(e).__name__, e)
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


_privileges = {
    "read": ["CONNECT", "SELECT"],
    "write": [
        "CONNECT",
        "USAGE",
        "SELECT",
        "UPDATE",
        "INSERT",
        "DELETE",
        "EXECUTE",
        "TRIGGER",
        "REFERENCES",
    ],
    "admin": ["ALL"],
}

_database_privs = ["CREATE", "TEMPORARY", "TEMP"]

_table_privs = [
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "REFERENCES",
    "TRIGGER",
    "ALL",
]

_sequence_privs = ["USAGE", "SELECT", "UPDATE", "ALL"]


def can_connect(role):
    conn = db.engine.raw_connection()
    cur = conn.cursor()
    stmt = "SELECT has_database_privilege({role}, {db}, 'CONNECT')"
    stmt = SQL(stmt).format(
        role=Literal(role), db=Literal(db.engine.url.database)
    )
    cur.execute(stmt)
    result = cur.fetchone()[0]
    cur.close()
    conn.close()
    return result


def has_privileges(role, privilege):
    """Return True/False if role has the specified privilege level.

    :param role:
    :param privilege:
    """
    conn = db.engine.raw_connection()
    cur = conn.cursor()
    # if the user has all on database with grant privileges and he has
    # the grant privilege on the database then he has admin and he can
    # create roles
    # test admin privileges on the database
    # for priv in _database_privs:
    stmt = "SELECT has_database_privilege({role}, {db}, 'CREATE')"
    stmt = SQL(stmt).format(
        role=Literal(role), db=Literal(db.engine.url.database)
    )
    cur.execute(stmt)
    result = cur.fetchone()[0]

    if result and privilege != "admin":
        cur.close()
        conn.close()
        return False
    if not result and privilege == "admin":
        cur.close()
        conn.close()
        return False

    if privilege == "admin":
        privs = set(_table_privs).intersection(_privileges["write"])
    else:
        privs = set(_table_privs).intersection(_privileges[privilege])

    # test the privileges on the tables and sequences
    for table in db.metadata.sorted_tables:
        for priv in set(_table_privs).intersection(_privileges["write"]):
            stmt = "SELECT has_table_privilege({role}, {table}, {priv})"
            stmt = SQL(stmt).format(
                role=Literal(role),
                table=Literal(table.name),
                priv=Literal(priv),
            )
            cur.execute(stmt)
            try:
                result = cur.fetchone()[0]
                if result and priv not in privs:
                    cur.close()
                    conn.close()
                    return False
                if not result and priv in privs:
                    cur.close()
                    conn.close()
                    return False
            except ProgrammingError:
                # we get here if the table doesn't exists, if it
                # doesn't exist we don't care if we have permissions
                # on it...this usually happens if we are checking
                # permissions on a table in the metadata which doesn't
                # exist in the database which can happen if this
                # plugin is run on a mismatched version of bauble
                pass

    # if admin check that the user can also create roles
    stmt = (
        "SELECT rolname FROM pg_roles WHERE rolcreaterole IS TRUE AND "
        "rolname = {role}"
    )
    stmt = SQL(stmt).format(role=Literal(role))
    cur.execute(stmt)
    result = cur.fetchone()
    cur.close()
    conn.close()
    if not result and privilege == "admin":
        return False

    return True


def has_implicit_sequence(column):
    # Tell me if there's an implicit sequence associated to the column, then
    # I assume that the sequence name is <table>_<column>_seq.
    # Simplified based on assuptions valid in ghini
    return (
        column.primary_key
        and column.autoincrement
        and isinstance(column.type, Integer)
        and not column.foreign_keys
    )


def set_privilege(role, privilege):
    """Set the role's privileges.

    :param role:
    :param privilege:
    """
    check(
        privilege in ("read", "write", "admin", None),
        f"invalid privilege: {privilege}",
    )
    conn = db.engine.raw_connection()
    cur = conn.cursor()

    if privilege:
        privs = _privileges[privilege]

    try:
        # revoke everything first
        for table in db.metadata.sorted_tables:
            for col in table.c:
                if has_implicit_sequence(col):
                    sequence_name = f"{table.name}_{col.name}_seq"
                    stmt = "REVOKE ALL ON SEQUENCE {seq} FROM {role}"
                    stmt = SQL(stmt).format(
                        seq=Identifier(sequence_name), role=Identifier(role)
                    )
                    cur.execute(stmt)
            stmt = "REVOKE ALL ON TABLE {table_name} FROM {role}"
            stmt = SQL(stmt).format(
                table_name=Identifier(table.name), role=Identifier(role)
            )
            cur.execute(stmt)

        stmt = "REVOKE ALL ON DATABASE {db} FROM {role}"
        stmt = SQL(stmt).format(
            db=Identifier(db.engine.url.database), role=Identifier(role)
        )
        cur.execute(stmt)

        stmt = "ALTER ROLE {role} WITH nocreaterole"
        stmt = SQL(stmt).format(role=Identifier(role))
        cur.execute(stmt)

        # privilege is None so all permissions are revoked
        if not privilege:
            conn.commit()
            return

        # change privileges on the database
        if privilege == "admin":
            stmt = "GRANT ALL ON DATABASE {db} TO {role} WITH GRANT OPTION"
            stmt = SQL(stmt).format(
                db=Identifier(db.engine.url.database), role=Identifier(role)
            )
            cur.execute(stmt)
            stmt = "ALTER ROLE {role} WITH CREATEROLE"
            stmt = SQL(stmt).format(role=Identifier(role))
            cur.execute(stmt)

        # grant privileges on the tables and sequences
        tbl_privs = [x for x in privs if x in _table_privs]
        seq_privs = [x for x in privs if x in _sequence_privs]
        for table in db.metadata.sorted_tables:
            logger.debug("granting privileges on table %s", table)
            for priv in tbl_privs:
                # priv should be fine for f-string.
                stmt = f"GRANT {priv} ON {{table_name}} TO {{role}}"
                if privilege == "admin":
                    stmt += " WITH GRANT OPTION"
                stmt = SQL(stmt).format(
                    table_name=Identifier(table.name), role=Identifier(role)
                )
                logger.debug(stmt.as_string(cur))
                cur.execute(stmt)
            for col in table.c:
                for priv in seq_privs:
                    if has_implicit_sequence(col):
                        sequence_name = f"{table.name}_{col.name}_seq"
                        logger.debug(
                            "column %s of table %s has associated "
                            "sequence %s",
                            col,
                            table,
                            sequence_name,
                        )
                        stmt = f"GRANT {priv} ON SEQUENCE {{seq}} TO {{role}}"
                        if privilege == "admin":
                            stmt += " WITH GRANT OPTION"
                        stmt = SQL(stmt).format(
                            seq=Identifier(sequence_name),
                            role=Identifier(role),
                        )
                        logger.debug(stmt.as_string(cur))
                        cur.execute(stmt)
    except Exception as e:
        logger.error("users.set_privilege(): %s(%s)", type(e).__name__, e)
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        cur.close()
        conn.close()


def current_user():
    """Return the name of the current user."""
    return db.current_user()


def set_password(password, user=None):
    """Set a user's password.

    If user is None then change the password of the current user.
    """
    if not user:
        user = current_user()
    conn = db.engine.raw_connection()
    cur = conn.cursor()
    try:
        stmt = "ALTER ROLE {role} WITH ENCRYPTED PASSWORD {password}"
        stmt = SQL(stmt).format(
            role=Identifier(user), password=Literal(password)
        )
        cur.execute(stmt)
    except DatabaseError as e:
        logger.error("users.set_password(): %s(%s)", type(e).__name__, e)
        conn.rollback()
    else:
        conn.commit()
    finally:
        cur.close()
        conn.close()


class UsersDialogPresenter(editor.GenericEditorPresenter):
    view_accept_buttons = ["main_ok_button"]

    buttons = {
        "admin": "admin_button",
        "write": "write_button",
        "read": "read_button",
    }

    new_user_message = _("Enter a user name")

    def __init__(self, view):
        super().__init__(model=None, view=view, session=False)
        self.view.widgets.users_column.set_cell_data_func(
            self.view.widgets.users_cell_renderer, utils.default_cell_data_func
        )
        self.view.widgets.filter_check.set_active(True)

        self.view.connect("read_button", "toggled", self.on_toggled, "read")
        self.view.connect("write_button", "toggled", self.on_toggled, "write")
        self.view.connect("admin_button", "toggled", self.on_toggled, "admin")

        logger.debug("current user is %s", current_user())

    def refresh(self):
        active = self.view.widgets.filter_check.get_active()
        self.populate_users_tree(active)

    def get_selected_user(self):
        """Return the user name currently selected in the users_tree."""
        tree = self.view.widgets.users_tree
        path, _column = tree.get_cursor()
        if path:
            return tree.get_model()[path][0]
        return None

    def on_cursor_changed(self, _tree):
        def _set_buttons(mode):
            logger.debug("%s: %s", role, mode)
            if mode:
                self.view.widgets[self.buttons[mode]].set_active(True)
            else:
                self.view.widgets.none_button.set_active(True)

        role = self.get_selected_user()
        if role not in get_users():
            _set_buttons(None)
            return

        if has_privileges(role, "admin"):
            _set_buttons("admin")
        elif has_privileges(role, "write"):
            _set_buttons("write")
        elif has_privileges(role, "read"):
            _set_buttons("read")
        else:
            _set_buttons(None)

    def on_filter_check_toggled(self, button, *_args):
        active = button.get_active()
        self.populate_users_tree(active)

    def populate_users_tree(self, only_bauble=True):
        """Populate the users tree with the users from the database.

        :param only_bauble: Show only those users with at least read
            permissions on the database.
        """
        tree = self.view.widgets.users_tree
        utils.clear_model(tree)
        model = Gtk.ListStore(str)
        if has_privileges(current_user(), "admin"):
            for user in get_users():
                if only_bauble and can_connect(user):
                    model.append([user])
                elif not only_bauble:
                    model.append([user])
        else:
            model.append([current_user()])
            self.view.widgets.users_box.set_sensitive(False)
            self.view.widgets.permissions_frame.set_sensitive(False)
        tree.set_model(model)
        if len(model) > 0:
            tree.set_cursor("0")

    def on_toggled(self, button, priv=None):
        role = self.get_selected_user()
        active = button.get_active()
        if active and not has_privileges(role, priv):
            logger.debug("grant %s to %s", priv, role)
            try:
                set_privilege(role, priv)
            except DatabaseError as e:
                utils.message_dialog(
                    str(e),
                    Gtk.MessageType.ERROR,
                    parent=self.view.get_window(),
                )
        return True

    def on_add_button_clicked(self, _button, *_args):
        name = self.view.run_entry_dialog(
            _("Enter a user name"),
            self.view.get_window(),
            buttons=("OK", Gtk.ResponseType.ACCEPT),
            modal=True,
            destroy_with_parent=True,
        )
        if name == "":
            return
        tree = self.view.widgets.users_tree
        model = tree.get_model()
        treeiter = model.append([name])
        path = model.get_path(treeiter)
        column = tree.get_column(0)
        tree.set_cursor(path, column)
        try:
            create_user(name)
            set_privilege(name, "read")
        except DatabaseError as e:
            utils.message_dialog(
                str(e), Gtk.MessageType.ERROR, parent=self.view.get_window()
            )
            model.remove(model.get_iter(path))
        else:
            self.view.widgets.read_button.set_active(True)

    def on_remove_button_clicked(self, _button, *_args):
        user = self.get_selected_user()
        msg = _(
            "Are you sure you want to remove user <b>%(name)s</b>?\n\n"
            "<i>It is possible that this user could have permissions "
            "on other databases not related to Ghini.</i>"
        ) % {"name": user}
        if not utils.yes_no_dialog(msg):
            return

        try:
            drop(user, revoke=True)
        except DatabaseError as e:
            utils.message_dialog(
                str(e), Gtk.MessageType.ERROR, parent=self.view.get_window()
            )
        else:
            self.refresh()

    def on_pwd_button_clicked(self, _button, *_args):
        dialog = self.view.widgets.pwd_dialog
        dialog.set_transient_for(self.view.get_window())

        self.view.widgets.pwd_entry1.set_text("")
        self.view.widgets.pwd_entry2.set_text("")

        response = dialog.run()

        pwd1 = self.view.widgets.pwd_entry1.get_text()
        pwd2 = self.view.widgets.pwd_entry2.get_text()

        dialog.hide()
        if response == Gtk.ResponseType.OK:
            user = self.get_selected_user()
            if pwd1 == "" or pwd2 == "":
                msg = (
                    _(
                        "The password for user <b>%s</b> has not been "
                        "changed."
                    )
                    % user
                )
                utils.message_dialog(
                    msg, Gtk.MessageType.WARNING, parent=self.view.get_window()
                )
                return
            if pwd1 != pwd2:
                msg = (
                    _(
                        "The passwords do not match.  The password for "
                        "user <b>%s</b> has not been changed."
                    )
                    % user
                )
                utils.message_dialog(
                    msg, Gtk.MessageType.WARNING, parent=self.view.get_window()
                )
                return
            try:
                set_password(pwd1, user)
            except DatabaseError as e:
                utils.message_dialog(
                    str(e),
                    Gtk.MessageType.ERROR,
                    parent=self.view.get_window(),
                )


class UsersTool(pluginmgr.Tool):
    label = _("Users")

    @classmethod
    def start(cls):
        view = editor.GenericEditorView(
            str(Path(__file__).resolve().parent / "users.glade"),
            root_widget_name="main_dialog",
        )
        presenter = UsersDialogPresenter(view)
        presenter.start()


class UsersPlugin(pluginmgr.Plugin):
    tools = []

    @classmethod
    def init(cls):
        # disable the tool if not postgres
        if db.engine.name != "postgresql":
            del cls.tools[:]
        elif db.engine.name == "postgresql" and not cls.tools:
            cls.tools.append(UsersTool)


plugin = UsersPlugin
