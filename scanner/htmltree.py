"""Tiny stdlib HTML tree for semantic containers; never parse entire pages by regex."""
from html.parser import HTMLParser
import re

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
    @property
    def text(self):
        return re.sub(r'\s+', ' ', ' '.join(c if isinstance(c, str) else c.text for c in self.children)).strip()
    def find(self, tag=None, cls=None, **attrs):
        out = []
        for c in self.children:
            if isinstance(c, Node):
                if (not tag or c.tag == tag) and (not cls or cls in c.attrs.get('class', '').split()) and all(c.attrs.get(k) == v for k,v in attrs.items()):
                    out.append(c)
                out.extend(c.find(tag, cls, **attrs))
        return out
class Tree(HTMLParser):
    def __init__(self, page):
        super().__init__(convert_charrefs=True)
        self.root = Node('root'); self.stack = [self.root]
        self.feed(page)
    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs); self.stack[-1].children.append(n)
        if tag not in VOID:self.stack.append(n)
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]; break
    def handle_data(self, text):
        self.stack[-1].children.append(text)


def document(page):
    return Tree(page).root
