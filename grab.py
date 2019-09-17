#! /usr/bin/env python3

from pprint import pprint, pformat
import datetime
import traceback
import copy
from collections import OrderedDict
from itertools import chain

import sqlalchemy as sa

from ws.client import API
from ws.interactive import require_login
from ws.db.database import Database
from ws.utils.containers import dmerge
import ws.diff
from ws.parser_helpers.encodings import urldecode


def _pprint_diff(i, db_entry, api_entry):
    # diff shows just the difference
    db_f = pformat(db_entry)
    api_f = pformat(api_entry)
    print(ws.diff.diff_highlighted(db_f, api_f, "db_entry", "api_entry"))

    # full entries are needed for context
    print("db_entry no. {}:".format(i))
    pprint(db_entry)
    print("api_entry no. {}:".format(i))
    pprint(api_entry)
    print()

def _check_entries(i, db_entry, api_entry):
    try:
        assert db_entry == api_entry
    except AssertionError:
        _pprint_diff(i, db_entry, api_entry)
        raise

def _check_lists(db_list, api_list):
    try:
        assert len(db_list) == len(api_list), "{} vs. {}".format(len(db_list), len(api_list))
        last_assert_exc = None
        for i, entries in enumerate(zip(db_list, api_list)):
            db_entry, api_entry = entries
            try:
                _check_entries(i, db_entry, api_entry)
            except AssertionError as e:
                last_assert_exc = e
                pass
        if last_assert_exc is not None:
            raise AssertionError from last_assert_exc
    except AssertionError:
        traceback.print_exc()

def _check_lists_of_unordered_pages(db_list, api_list):
    # FIXME: apparently the ArchWiki's MySQL backend does not use the C locale...
    # difference between C and MySQL's binary collation: "2bwm (简体中文)" should come before "2bwm(简体中文)"
    # TODO: if we connect to MediaWiki running on PostgreSQL, its locale might be anything...
    api_list = sorted(api_list, key=lambda item: item["pageid"])
    db_list = sorted(db_list, key=lambda item: item["pageid"])

    _check_lists(db_list, api_list)

# pages may be yielded multiple times, so we need to merge them manually
def _squash_list_of_dicts(api_list, *, key="pageid"):
    api_dict = OrderedDict()
    for item in api_list:
        key_value = item[key]
        if key_value not in api_dict:
            api_dict[key_value] = item
        else:
            dmerge(item, api_dict[key_value])
    return list(api_dict.values())

def _deduplicate_list_of_dicts(l):
    return [dict(t) for t in {tuple(d.items()) for d in l}]


def check_titles(api, db):
    print("Checking individual titles...")

    titles = {"Main page", "Nonexistent"}
    pageids = {1,2,3,4,5}

    db_list = list(db.query(titles=titles))
    api_list = api.call_api(action="query", titles="|".join(titles))["pages"]

    _check_lists(db_list, api_list)

    api_dict = api.call_api(action="query", pageids="|".join(str(p) for p in pageids))["pages"]
    api_list = list(api_dict.values())
    api_list.sort(key=lambda p: ("missing" not in p, p["pageid"]))
    db_list = list(db.query(pageids=pageids))

    _check_lists(db_list, api_list)


def check_specific_titles(api, db):
    titles = [
        "Main page",
        "en:Main page",
        "wikipedia:Main page",
        "wikipedia:en:Main page",
        "Main page#section",
        "en:Main page#section",
        "wikipedia:Main page#section",
        "wikipedia:en:Main page#section",
    ]
    for title in titles:
        api_title = api.Title(title)
        db_title = db.Title(title)
        assert api_title.context == db_title.context
        assert api_title == db_title


def check_recentchanges(api, db):
    print("Checking the recentchanges table...")

    params = {
        "list": "recentchanges",
        "rclimit": "max",
    }
    rcprop = {"title", "ids", "user", "userid", "flags", "timestamp", "comment", "sizes", "loginfo", "patrolled", "sha1", "redirect", "tags"}

    db_list = list(db.query(**params, rcprop=rcprop))
    api_list = list(api.list(**params, rcprop="|".join(rcprop)))

    # FIXME: some deleted pages stay in recentchanges, although according to the tests they should be deleted
    s = sa.select([db.page.c.page_id])
    current_pageids = {page["page_id"] for page in db.engine.execute(s)}
    new_api_list = []
    for rc in api_list:
        if "logid" in rc or rc["pageid"] in current_pageids:
            new_api_list.append(rc)
    api_list = new_api_list

    try:
        assert len(db_list) == len(api_list), "{} vs {}".format(len(db_list), len(api_list))
        for i, entries in enumerate(zip(db_list, api_list)):
            db_entry, api_entry = entries
            # TODO: how the hell should we know...
            if "autopatrolled" in api_entry:
                del api_entry["autopatrolled"]
            # TODO: I don't know what this means
            if "unpatrolled" in api_entry:
                del api_entry["unpatrolled"]

            # FIXME: rolled-back edits are automatically patrolled, but there does not seem to be any way to detect this
            # skipping all patrol checks for now...
            if "patrolled" in api_entry:
                del api_entry["patrolled"]
            if "patrolled" in db_entry:
                del db_entry["patrolled"]

            _check_entries(i, db_entry, api_entry)
    except AssertionError:
        traceback.print_exc()


def check_logging(api, db):
    print("Checking the logging table...")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=30)

    params = {
        "list": "logevents",
        "lelimit": "max",
        "ledir": "newer",
        "lestart": since,
    }
    leprop = {"user", "userid", "comment", "timestamp", "title", "ids", "type", "details", "tags"}

    db_list = list(db.query(**params, leprop=leprop))
    api_list = list(api.list(**params, leprop="|".join(leprop)))

    _check_lists(db_list, api_list)


def check_users(api, db):
    print("Checking the user table...")

    params = {
        "list": "allusers",
        "aulimit": "max",
    }
    auprop = {"groups", "blockinfo", "registration", "editcount"}

    db_list = list(db.query(**params, auprop=auprop))
    api_list = list(api.list(**params, auprop="|".join(auprop)))

    # skip the "Anynymous" dummy user residing in MediaWiki running on PostgreSQL
    api_list = [user for user in api_list if user["userid"] > 0]

    # sort user groups - neither we or MediaWiki do that
    for user in chain(db_list, api_list):
        user["groups"].sort()

    # drop autoconfirmed - not reliably refreshed in the SQL database
    # TODO: try to fix that...
    for user in chain(db_list, api_list):
        if "autoconfirmed" in user["groups"]:
            user["groups"].remove("autoconfirmed")

    _check_lists(db_list, api_list)


def check_allpages(api, db):
    print("Checking the page table...")

    params = {
        "list": "allpages",
        "aplimit": "max",
    }

    db_list = list(db.query(**params))
    api_list = list(api.list(**params))

    _check_lists_of_unordered_pages(db_list, api_list)


def check_info(api, db):
    print("Checking prop=info...")

    params = {
        "generator": "allpages",
        "gaplimit": "max",
        "prop": "info",
    }
    inprop = {"protection", "displaytitle"}

    db_list = list(db.query(**params, inprop=inprop))
    api_list = list(api.generator(**params, inprop="|".join(inprop)))

    # fix ordering of the protection lists
    for entry in chain(db_list, api_list):
        if "protection" in entry:
            entry["protection"].sort(key=lambda p: p["type"])

    # FIXME: we can't assert page_touched because we track only page edits, not cache invalidations...
    for entry in chain(db_list, api_list):
        del entry["touched"]

    _check_lists_of_unordered_pages(db_list, api_list)


def check_pageprops(api, db):
    print("Checking prop=pageprops...")

    params = {
        "generator": "allpages",
        "gaplimit": "max",
        "prop": "pageprops",
    }

    db_list = list(db.query(params))
    api_list = list(api.generator(params))

    _check_lists_of_unordered_pages(db_list, api_list)


def check_protected_titles(api, db):
    print("Checking the protected_titles table...")

    params = {
        "list": "protectedtitles",
        "ptlimit": "max",
    }
    ptprop = {"timestamp", "user", "userid", "comment", "expiry", "level"}

    db_list = list(db.query(**params, ptprop=ptprop))
    api_list = list(api.list(**params, ptprop="|".join(ptprop)))

    for db_entry, api_entry in zip(db_list, api_list):
        # the timestamps may be off by couple of seconds, because we're looking in the logging table
        if "timestamp" in db_entry and "timestamp" in api_entry:
            if abs(db_entry["timestamp"] - api_entry["timestamp"]) <= datetime.timedelta(seconds=1):
                db_entry["timestamp"] = api_entry["timestamp"]

    _check_lists(db_list, api_list)


def check_revisions(api, db):
    print("Checking the revision table...")

    since = datetime.datetime.utcnow() - datetime.timedelta(days=30)

    params = {
        "list": "allrevisions",
        "arvlimit": "max",
        "arvdir": "newer",
        "arvstart": since,
    }
    arvprop = {"ids", "flags", "timestamp", "user", "userid", "size", "sha1", "contentmodel", "comment", "tags"}

    db_list = list(db.query(**params, arvprop=arvprop))
    api_list = list(api.list(**params, arvprop="|".join(arvprop)))

    # FIXME: hack until we have per-page grouping like MediaWiki
    api_revisions = []
    for page in api_list:
        for rev in page["revisions"]:
            rev["pageid"] = page["pageid"]
            rev["ns"] = page["ns"]
            rev["title"] = page["title"]
            api_revisions.append(rev)
    api_revisions.sort(key=lambda item: item["revid"])
    api_list = api_revisions

    # FIXME: WTF, MediaWiki does not restore rev_parent_id when undeleting...
    # https://phabricator.wikimedia.org/T183375
    for rev in chain(db_list, api_list):
        del rev["parentid"]

    _check_lists(db_list, api_list)


def check_latest_revisions(api, db):
    print("Checking latest revisions...")

    db_params = {
        "generator": "allpages",
        "prop": "latestrevisions",
    }
    api_params = {
        "generator": "allpages",
        "gaplimit": "max",
        "prop": "revisions",
    }

    db_list = list(db.query(db_params))
    api_list = list(api.generator(api_params))

    _check_lists_of_unordered_pages(db_list, api_list)


def check_revisions_of_main_page(api, db):
    print("Checking revisions of the Main page...")

    titles = {"Main page"}
    rvprop = {"ids", "flags", "timestamp", "user", "userid", "size", "sha1", "contentmodel", "comment", "tags"}
    api_params = {
        "prop": "revisions",
        "rvlimit": "max",
    }

    db_list = list(db.query(**api_params, titles=titles, rvprop=rvprop))
    api_dict = api.call_api(**api_params, action="query", titles="|".join(titles), rvprop="|".join(rvprop))["pages"]
    api_list = list(api_dict.values())

    # first check the lists without revisions
    db_list_copy = copy.deepcopy(db_list)
    api_list_copy = copy.deepcopy(api_list)
    _check_lists(db_list_copy, api_list_copy)

    # then check only the revisions
    for db_page, api_page in zip(db_list, api_list):
        _check_lists(db_page["revisions"], api_page["revisions"])


def check_templatelinks(api, db):
    print("Checking the templatelinks table...")

    params = {
        "generator": "allpages",
        "gaplimit": "max",
        "tllimit": "max",
        "tilimit": "max",
    }
    prop = {"templates", "transcludedin"}

    db_list = list(db.query(**params, prop=prop))
    api_list = list(api.generator(**params, prop="|".join(prop)))
    api_list = _squash_list_of_dicts(api_list)

    # sort the templates and templatelinks due to different locale (e.g. "Template:Related2" should come after "Template:Related")
    for entry in api_list:
        entry.get("templates", []).sort(key=lambda t: (t["ns"], t["title"]))
        entry.get("transcludedin", []).sort(key=lambda t: (t["ns"], t["title"]))

    _check_lists_of_unordered_pages(db_list, api_list)


def check_pagelinks(api, db):
    print("Checking the pagelinks table...")

    params = {
        "generator": "allpages",
        "gaplimit": "max",
        "pllimit": "max",
        "lhlimit": "max",
    }
    prop = {"links", "linkshere"}

    db_list = list(db.query(**params, prop=prop))
    api_list = list(api.generator(**params, prop="|".join(prop)))
    api_list = _squash_list_of_dicts(api_list)

    # fix sorting due to different locale
    for page in api_list:
        page.get("links", []).sort(key=lambda d: (d["ns"], d["title"]))
        page.get("linkshere", []).sort(key=lambda d: (d["pageid"]))

    _check_lists_of_unordered_pages(db_list, api_list)


def check_imagelinks(api, db):
    print("Checking the imagelinks table...")

    params = {
        "generator": "allpages",
        "gaplimit": "max",
        "imlimit": "max",
    }
    prop = {"images"}

    db_list = list(db.query(**params, prop=prop))
    api_list = list(api.generator(**params, prop="|".join(prop)))
    api_list = _squash_list_of_dicts(api_list)

    _check_lists_of_unordered_pages(db_list, api_list)


def check_categorylinks(api, db):
    print("Checking the categorylinks table...")

    params = {
        "generator": "allpages",
        "gaplimit": "max",
        "cllimit": "max",
    }
    prop = {"categories"}

    db_list = list(db.query(**params, prop=prop))
    api_list = list(api.generator(**params, prop="|".join(prop)))
    api_list = _squash_list_of_dicts(api_list)

    # drop unsupported automatic categories: http://w.localhost/index.php/Special:TrackingCategories
    automatic_categories = {
        "Category:Indexed pages",
        "Category:Noindexed pages",
        "Category:Pages using duplicate arguments in template calls",
        "Category:Pages with too many expensive parser function calls",
        "Category:Pages containing omitted template arguments",
        "Category:Pages where template include size is exceeded",
        "Category:Hidden categories",
        "Category:Pages with broken file links",
        "Category:Pages where node count is exceeded",
        "Category:Pages where expansion depth is exceeded",
        "Category:Pages with ignored display titles",
        "Category:Pages using invalid self-closed HTML tags",
        "Category:Pages with template loops",
    }
    for page in api_list:
        if "categories" in page:
            page["categories"] = [cat for cat in page["categories"] if cat["title"] not in automatic_categories]
            # remove empty list
            if not page["categories"]:
                del page["categories"]

    _check_lists_of_unordered_pages(db_list, api_list)


def check_interwiki_links(api, db):
    print("Checking the langlinks and iwlinks tables...")

    params = {
        "generator": "allpages",
        "gaplimit": "max",
        "iwlimit": "max",
        "lllimit": "max",
    }
    prop = {"langlinks", "iwlinks"}

    db_list = list(db.query(**params, prop=prop))
    api_list = list(api.generator(**params, prop="|".join(prop)))
    api_list = _squash_list_of_dicts(api_list)

    # In our database, we store spaces instead of underscores and capitalize first letter.
    def ucfirst(s):
        if s:
            return s[0].upper() + s[1:]
        return s
    for page in api_list:
        for link in chain(page.get("langlinks", []), page.get("iwlinks", [])):
            link["*"] = ucfirst(link["*"].replace("_", " "))
        # deduplicate, [[w:foo]] and [[w:Foo]] should be equivalent
        if "langlinks" in page:
            page["langlinks"] = _deduplicate_list_of_dicts(page["langlinks"])
        if "iwlinks" in page:
            page["iwlinks"] = _deduplicate_list_of_dicts(page["iwlinks"])
        # fix sorting due to different locale
        page.get("langlinks", []).sort(key=lambda d: (d["lang"], d["*"]))
        page.get("iwlinks", []).sort(key=lambda d: (d["prefix"], d["*"]))

    _check_lists_of_unordered_pages(db_list, api_list)


def check_external_links(api, db):
    print("Checking the externallinks table...")

    params = {
        "generator": "allpages",
        "gaplimit": "max",
        "ellimit": "max",
    }
    prop = {"extlinks"}

    db_list = list(db.query(**params, prop=prop))
    api_list = list(api.generator(**params, prop="|".join(prop)))
    api_list = _squash_list_of_dicts(api_list)

    for page in db_list:
        if "extlinks" in page:
            # MediaWiki does not track external links to itself
            page["extlinks"] = [el for el in page["extlinks"] if not el["*"].startswith(api.index_url)]
    for page in api_list:
        if "extlinks" in page:
            # MediaWiki does not order the URLs
            page["extlinks"].sort(key=lambda d: d["*"])
            # MediaWiki has some characters URL-encoded and others decoded
            for el in page["extlinks"]:
                el["*"] = urldecode(el["*"])

    _check_lists_of_unordered_pages(db_list, api_list)


def check_redirects(api, db):
    print("Checking the redirects table...")

    params = {
        "generator": "allpages",
        "gaplimit": "max",
        "rdlimit": "max",
    }
    prop = {"redirects"}
    rdprop = {"pageid", "title", "fragment"}

    db_list = list(db.query(**params, prop=prop, rdprop=rdprop))
    api_list = list(api.generator(**params, prop="|".join(prop), rdprop="|".join(rdprop)))
    api_list = _squash_list_of_dicts(api_list)

    _check_lists_of_unordered_pages(db_list, api_list)


if __name__ == "__main__":
    import ws.config
    import ws.logging

    argparser = ws.config.getArgParser(description="Test grabbers")
    API.set_argparser(argparser)
    Database.set_argparser(argparser)

    argparser.add_argument("--sync", dest="sync", action="store_true", default=True,
            help="synchronize the SQL database with the remote wiki API (default: %(default)s)")
    argparser.add_argument("--no-sync", dest="sync", action="store_false",
            help="opposite of --sync")
    argparser.add_argument("--parser-cache", dest="parser_cache", action="store_true", default=False,
            help="update parser cache (default: %(default)s)")
    argparser.add_argument("--no-parser-cache", dest="parser_cache", action="store_false",
            help="opposite of --parser-cache")

    args = argparser.parse_args()

    # set up logging
    ws.logging.init(args)

    api = API.from_argparser(args)
    db = Database.from_argparser(args)

    if args.sync:
        require_login(api)

        db.sync_with_api(api)
        db.sync_latest_revisions_content(api)

        check_titles(api, db)
        check_specific_titles(api, db)

        check_recentchanges(api, db)
        check_logging(api, db)
        # TODO: select active users
        check_users(api, db)
        check_allpages(api, db)
        check_info(api, db)
        check_pageprops(api, db)
        check_protected_titles(api, db)
        check_revisions(api, db)
        check_latest_revisions(api, db)
        check_revisions_of_main_page(api, db)

    if args.parser_cache:
        db.update_parser_cache()

        # fails due to https://github.com/earwig/mwparserfromhell/issues/198
        # ([[Template:META Error]] gets expanded because of it)
#        check_templatelinks(api, db)

        # fails due to https://github.com/earwig/mwparserfromhell/issues/198
        # ([[Help:Template]], transcluded from [[Template:META Error]], is linked because of it)
#        check_pagelinks(api, db)

        check_imagelinks(api, db)

        # fails due to https://github.com/earwig/mwparserfromhell/issues/198
        # ([[Template:META Error]] adds the pages using it to [[Category:Pages with broken templates]])
#        check_categorylinks(api, db)

        check_interwiki_links(api, db)

        # fails due to https://github.com/earwig/mwparserfromhell/issues/197
        # (URLs preceded by punctuation characters are not parsed)
#        check_external_links(api, db)

        check_redirects(api, db)
