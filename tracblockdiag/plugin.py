# -*- coding: utf-8 -*-

import re
from bz2 import compress, decompress
from base64 import b64encode, b64decode

from trac.config import BoolOption, IntOption, ListOption, Option
from trac.core import Component, implements
from trac.util.html import html
from trac.web import IRequestHandler
from trac.wiki import IWikiMacroProvider

from . import diag, cache

_template = u"""
= What's this? =
Generate %(kind)s diagram from source text.

See [http://blockdiag.com/en/%(module)s/ %(module)s (en)] or
[http://blockdiag.com/ja/%(module)s/ for Japanese]

== Arguments (Only Trac 0.12 or later) ==
 `type`:: Image format (png or svg)
 `others`:: Used to IMG tag attributes
"""

_descriptions = {
    'blockdiag': {'kind': 'block', 'module': 'blockdiag'},
    'seqdiag': {'kind': 'sequence', 'module': 'seqdiag'},
    'actdiag': {'kind': 'activity', 'module': 'actdiag'},
    'nwdiag': {'kind': 'network', 'module': 'nwdiag'},
    'rackdiag': {'kind': 'rack', 'module': 'nwdiag'}
}

macro_defs = {}
for name in diag.available_builders:
    macro_defs[name] = _template % _descriptions[name]

content_types = {'png': 'image/png',
                 'svg': 'image/svg+xml'}
_conf_section = 'tracblockdiag'

ALTERNATIVE_TEXT = "Your browser doesn't support svg"

class BlockdiagRenderer(Component):

    implements(IWikiMacroProvider, IRequestHandler)

    font = ListOption(_conf_section, 'font',
        doc="Paths to font file which are used in PNG generation.")

    default_type = Option(_conf_section, 'default_type', 'svg',
        doc="Default diagram type to generate.")

    fallback = BoolOption(_conf_section, 'fallback', 'disabled',
        doc="Fallback to png image when a browser is not support svg. Note "
            "that using fallback causes double image generation because major "
            "browsers request png image whether svg rendering succeeded or "
            "not. So, enabling this option may causes high load.")

    syntax_check = BoolOption(_conf_section, 'syntax_check', 'enabled',
        doc="Check syntax of source text and show error instead of 500 "
            "response. Note that when using syntax check, the performance is "
            "slightly down.")

    cachetime = IntOption(_conf_section, 'cachetime', '300',
        doc="Time in seconds which the plugin caches a generated diagram in.")

    gc_interval = IntOption(_conf_section, 'gc_interval', '100',
        doc="The number of diagram generation. Unused cache is cleared every "
            "this count.")

    url = re.compile(r'/blockdiag/([a-z]+)/(png|svg)/(.+)')

    url_template = 'blockdiag/%(diag)s/%(type)s/%(data)s'

    def __init__(self):
        cache.set_gc_params(self.gc_interval, self.cachetime)
        self.get_diag = cache.memoize(self.cachetime)(diag.get_diag)

    def get_macros(self):
        return macro_defs.keys()

    def get_macro_description(self, name):
        return macro_defs.get(name, '')

    def expand_macro(self, formatter, name, content, args=None):
        args = args or {}
        diag = name[:-4]
        if self.syntax_check:
            result = self.check_syntax(diag, content)
            if result is not True:
                return result

        type_ = args.pop('type', self.default_type)
        data = b64encode(compress(content.encode('utf-8')))

        png_url = formatter.req.href(self.get_url(diag, 'png', data))
        svg_url = formatter.req.href(self.get_url(diag, 'svg', data))

        if type_ == 'png':
            return self.make_png_element(png_url, **args)
        if not self.fallback:
            return self.make_svg_element(svg_url, **args)(ALTERNATIVE_TEXT)
        svg = self.make_svg_element(svg_url, **args)
        return svg(self.make_png_element(png_url, **args))

    def match_request(self, req):
        return bool(self.url.match(req.path_info))

    def process_request(self, req):
        type_, fmt, data = self.url.match(req.path_info).groups()
        text = decompress(b64decode(data)).decode('utf-8')
        diag = self.get_diag(type_, text, fmt, self.font)
        req.send(diag, content_types.get(fmt.lower(), ''), status=200)

    def make_png_element(self, url, **kwargs):
        kwargs['src'] = url
        return html.img(**kwargs)

    def make_svg_element(self, url, **kwargs):
        kwargs['data'] = url
        kwargs['type'] = content_types['svg']
        return html.object(**kwargs)

    def get_url(self, diag, type_, data):
        return self.url_template % {'diag': diag, 'type': type_, 'data': data}

    def check_syntax(self, kind, content):
        try:
            diag.get_builder(kind)().parse_string(content)
            return True
        except:
            msg = kind + 'diag: an error occurred while parsing source text.'
            msg = html.strong(msg)
            pre = html.pre(content)
            return html.div(msg, pre)
