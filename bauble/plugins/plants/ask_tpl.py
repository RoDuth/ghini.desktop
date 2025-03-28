# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2019-2021 Ross Demuth <rossdemuth123@gmail.com>
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

import csv
import difflib
import logging
import threading
import urllib.parse

logger = logging.getLogger(__name__)

from bauble.utils import get_net_sess


class AskTPL(threading.Thread):
    running = None

    def __init__(
        self,
        binomial,
        callback,
        threshold=0.8,
        timeout=4,
        gui=False,
        group=None,
        **kwargs,
    ):
        super().__init__(group=group, target=None, name=None)
        logger.debug(
            "new %s, already running %s.",
            self.name,
            self.running and self.running.name,
        )
        if self.running is not None:
            if self.running.binomial == binomial:
                # NOTE this log entry used in test
                logger.debug(
                    "already requesting %s, ignoring repeated request",
                    binomial,
                )
                binomial = None
            else:
                logger.debug(
                    "running different request (%s), stopping it, starting %s",
                    self.running.binomial,
                    binomial,
                )
                self.running.stop()
        if binomial:
            self.__class__.running = self
        self._stop = False
        self.binomial = binomial
        self.threshold = threshold
        self.callback = callback
        self.timeout = timeout
        self.gui = gui

    def stop(self):
        self._stop = True

    def stopped(self):
        return self._stop

    def run(self):
        def ask_tpl(binomial):
            logger.debug(
                "tpl request for %s, with timeout %s", binomial, self.timeout
            )
            net_sess = get_net_sess()

            logger.debug("net session type = %s", type(net_sess))
            query = urllib.parse.urlencode({"q": binomial, "csv": "true"})

            try:
                result = net_sess.get(
                    "http://www.theplantlist.org/tpl1.1/search?" + query,
                    timeout=self.timeout,
                )
                lines = result.text[1:].split("\n")
                logger.debug(lines)
                result = list(csv.reader(str(k) for k in lines if k))
                header = result[0]
                result = result[1:]
            finally:
                net_sess.close()
            return [dict(list(zip(header, k))) for k in result]

        class ShouldStopNow(Exception):
            pass

        class NoResult(Exception):
            pass

        if self.binomial is None:
            return

        try:
            accepted = None
            logger.debug("%s before first query", self.name)
            candidates = ask_tpl(self.binomial)
            logger.debug("%s after first query", self.name)
            if self.stopped():
                raise ShouldStopNow("after first query")
            if len(candidates) > 1:
                for item in candidates:
                    if item["Taxonomic status in TPL"] == "Unresolved":
                        item["_score_"] = 0.1
                    else:
                        infrasp = ""
                        if item["Infraspecific epithet"]:
                            infrasp = (
                                f' {item["Infraspecific rank"]} '
                                f'{item["Infraspecific epithet"]} '
                            )
                        string = (
                            f'{item["Genus hybrid marker"]}'
                            f'{item["Genus"]} '
                            f'{item["Species hybrid marker"]}'
                            f'{item["Species"]}'
                            f"{infrasp}"
                        )
                        seq = difflib.SequenceMatcher(
                            a=self.binomial, b=string
                        )
                        item["_score_"] = seq.ratio()

                # put 'Accepted' last
                order = {"Accepted": 3, "Synonym": 2, "Unresolved": 1}
                found = sorted(
                    candidates,
                    key=lambda x: (
                        x["_score_"],
                        order.get(x["Taxonomic status in TPL"], 0),
                    ),
                )[-1]
                logger.debug("best match has score %s", found["_score_"])
                if found["_score_"] < self.threshold:
                    found["_score_"] = 0
            elif candidates:
                found = candidates.pop()
            else:
                raise NoResult
            if found["Accepted ID"]:
                logger.debug("found this: %s", str(found))
                accepted = ask_tpl(found["Accepted ID"])
                logger.debug("ask_tpl on the Accepted ID returns %s", accepted)
                if accepted:
                    accepted = accepted[0]
                logger.debug("%s after second query", self.name)
            if self.stopped():
                raise ShouldStopNow("after second query")
        except ShouldStopNow:
            logger.debug("%s interrupted : do not invoke callback", self.name)
            return
        except Exception as e:
            logger.debug(
                "%s %s(%s) : completed with trouble",
                self.name,
                type(e).__name__,
                e,
            )
            self.__class__.running = None
            found = accepted = None
        self.__class__.running = None
        logger.debug("%s before invoking callback" % self.name)
        if self.gui:
            from gi.repository import GLib

            GLib.idle_add(self.callback, found, accepted)
        else:
            self.callback(found, accepted)


def citation(d):
    return (
        "%(Genus hybrid marker)s%(Genus)s "
        "%(Species hybrid marker)s%(Species)s "
        "%(Infraspecific rank)s %(Infraspecific epithet)s "
        "%(Authorship)s (%(Family)s)" % d
    ).replace("   ", " ")


def what_to_do_with_it(found, accepted):
    if found is None and accepted is None:
        logger.info("nothing matches")
        return
    logger.info("%s", citation(found))
    if accepted == []:
        logger.info("invalid reference in tpl.")
    if accepted:
        logger.info("%s - is its accepted form", citation(accepted))
