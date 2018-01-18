#! /usr/bin/env python3

import urllib.parse
import string

from ws.parser_helpers.encodings import *

class test_encodings:
    ascii_all = "".join(chr(i) for i in range(128))
    url_unreserved = string.ascii_letters + string.digits + "-_.~"
    unicode_sample = "ěščřžýáíéúů,.-§€¶ŧ→øþłŁ°ΩŁE®Ŧ¥↑ıØÞŁ&̛ĦŊªÐ§Æ<>©‘’Nº×÷˙ß˝"

    def test_skip_chars(self):
        for s in [self.ascii_all, self.unicode_sample]:
            e1 = encode(s, skip_chars=self.url_unreserved)
            e2 = urllib.parse.quote(s, safe=self.url_unreserved)
            assert e1 == e2

    def test_escape_char(self):
        for s in [self.ascii_all, self.unicode_sample]:
            e1 = encode(s, escape_char=".", skip_chars=self.url_unreserved)
            e2 = urllib.parse.quote(s, safe=self.url_unreserved)
            e2 = e2.replace("%", ".")
            assert e1 == e2

    def test_encode_chars(self):
        enc = string.digits + string.ascii_letters
        skip = string.punctuation + string.whitespace
        all_ = enc + skip

        e1 = encode(all_, encode_chars=enc)
        e2 = encode(all_, skip_chars=skip)
        assert e1 == e2

    def test_urlencode(self):
        for s in [self.ascii_all, self.unicode_sample]:
            e1 = urlencode(s)
            e2 = urllib.parse.quote(s, safe=self.url_unreserved)
            assert e1 == e2

    def test_urldecode(self):
        for s in [string.ascii_letters, self.ascii_all, self.unicode_sample]:
            enc = urlencode(s)
            dec = urldecode(enc)
            assert dec == s

    def test_urldecode_noop(self):
        for s in [string.ascii_letters, self.ascii_all, self.unicode_sample]:
            dec = urldecode(s)
            assert dec == s

    def test_queryencode(self):
        skipped = string.ascii_letters + string.digits + "-_."
        for s in [self.ascii_all, self.unicode_sample]:
            e1 = queryencode(s)
            e2 = urllib.parse.quote(s, safe=skipped)
            e2 = e2.replace("%20", "+")
            assert e1 == e2

    def test_querydecode(self):
        for s in [string.ascii_letters, self.ascii_all, self.unicode_sample]:
            enc = queryencode(s)
            dec = querydecode(enc)
            assert dec == s

    def test_dotencode_basic(self):
        skipped = string.ascii_letters + string.digits + "-_.:"
        # assume that the tested strings are context-free
        for s in [string.ascii_letters, string.digits, string.punctuation, self.unicode_sample]:
            e1 = dotencode(s)
            e2 = urllib.parse.quote(s, safe=skipped)
            e2 = e2.replace("%", ".")
            e2 = e2.replace("%20", "_")
            assert e1 == e2

    def test_dotencode_spaces(self):
        s = " Foo   bar "
        e = "Foo_bar"
        assert dotencode(s) == e

    def test_dotencode_underscores(self):
        s = "_Foo__  __bar_"
        e = "Foo_bar"
        assert dotencode(s) == e

    def test_dotencode_whitespace(self):
        s = " Foo \t\t  bar "
        e = "Foo_.09.09_bar"
        assert dotencode(s) == e

    def test_dotencode_colons(self):
        s = " :: :: Foo bar"
        e = "_::_Foo_bar"
        assert dotencode(s) == e

    def test_dotencode_T20431(self):
        """ test case from https://phabricator.wikimedia.org/T20431
        """
        s = "_ +.3A%3A]]"
        # this is what [[#_ +.3A%3A&#93;&#93;]] produces (WTF?)
#        e = "_.3A:.5D.5D"
        # this is what the actual anchor is (i.e. <span id=".2B.3A.253A.5D.5D" ...>)
        # (also linked correctly from TOC)
        e = ".2B.3A.253A.5D.5D"
        assert dotencode(s) == e
