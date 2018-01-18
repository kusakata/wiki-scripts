#! /usr/bin/env python3

# TODO: rvprop=timestamp ??

import logging

from . import CacheDb
from .. import utils

logger = logging.getLogger(__name__)

__all__ = ["LatestRevisionsText"]

class LatestRevisionsText(CacheDb):
    def __init__(self, api, cache_dir, autocommit=True):
        super().__init__(api, cache_dir, "LatestRevisionsText", autocommit)

    def init(self, ns=None):
        """
        :param ns: namespace index where the revisions are taken from.
                   Internally functions as the database key.
        """
        # make sure we work with string keys (needed for JSON serialization)
        ns = str(ns) if ns is not None else "0"

        logger.info("Running LatestRevisionsText.init(ns=\"{}\")".format(ns))
        if self.data is None:
            self.data = {}
        self.data[ns] = []

        # not necessary to wrap in each iteration since lists are mutable
        wrapped_titles = utils.ListOfDictsAttrWrapper(self.data[ns], "title")

        allpages = self.api.generator(generator="allpages", gaplimit="max", gapfilterredir="nonredirects", gapnamespace=ns, prop="info|revisions", rvprop="content")
        for page in allpages:
            # the same page may be yielded multiple times with different pieces
            # of the information, hence the utils.dmerge
            try:
                db_page = utils.bisect_find(self.data[ns], page["title"], index_list=wrapped_titles)
                utils.dmerge(page, db_page)
            except IndexError:
                utils.bisect_insert_or_replace(self.data[ns], page["title"], data_element=page, index_list=wrapped_titles)

        self._update_timestamp()

        if self.autocommit is True:
            self.dump()

    def update(self, ns=None):
        """
        :param ns: namespace index where the revisions are taken from.
                   Internally functions as the database key.
        """
        # make sure we work with string keys (needed for JSON serialization)
        ns = str(ns) if ns is not None else "0"

        if ns not in self.data:
            self.init(ns)
            return

        logger.info("Running LatestRevisionsText.update(ns=\"{}\")".format(ns))
        for_update = self._get_for_update(ns)
        if len(for_update) > 0:
            logger.info("Fetching {} new revisions...".format(len(for_update)))

            # not necessary to wrap in each iteration since lists are mutable
            wrapped_titles = utils.ListOfDictsAttrWrapper(self.data[ns], "title")

            for snippet in utils.list_chunks(for_update, self.api.max_ids_per_query):
                result = self.api.call_api(action="query", pageids="|".join(str(pageid) for pageid in snippet), prop="info|revisions", rvprop="content")
                for page in result["pages"].values():
                    utils.bisect_insert_or_replace(self.data[ns], page["title"], data_element=page, index_list=wrapped_titles)

            self._update_timestamp()

            if self.autocommit is True:
                self.dump()

    def _get_for_update(self, ns):
        pageids = []

        # not necessary to wrap in each iteration since lists are mutable
        wrapped_titles = utils.ListOfDictsAttrWrapper(self.data[ns], "title")

        allpages = self.api.generator(generator="allpages", gaplimit="max", gapfilterredir="nonredirects", gapnamespace=ns, prop="info")
        for page in allpages:
            title = page["title"]
            pageid = page["pageid"]
            try:
                db_page = utils.bisect_find(self.data[ns], title, index_list=wrapped_titles)
                if page["touched"] > db_page["touched"]:
                    pageids.append(page["pageid"])
            except IndexError:
                # not found in db, needs update
                pageids.append(pageid)
        return pageids
