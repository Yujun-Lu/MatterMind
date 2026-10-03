"""Verify published PDFs, static resources, and citation identity (standard library)."""
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'docs'


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = []
        self.image_count = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        for field in ('href', 'src', 'poster'):
            if attrs.get(field):
                self.links.append(attrs[field])
        if tag == 'img':
            assert 'alt' in attrs, f'Image missing alt attribute: {attrs}'
            self.image_count += 1


def check_link(source, href, ids=None):
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return
    target = (source.parent / unquote(parsed.path)).resolve() if parsed.path else source
    assert target.is_relative_to(ROOT), f'Link escapes repository: {source}: {href}'
    assert target.exists(), f'Broken local link: {source}: {href}'
    if ids is not None and target == source and parsed.fragment:
        assert unquote(parsed.fragment) in ids, f'Missing anchor: {href}'


def main():
    manifest = json.loads((SITE / 'papers/manifest.json').read_text(encoding='utf-8-sig'))
    assert len(manifest) == 3
    for record in manifest:
        content = (SITE / 'papers' / record['file']).read_bytes()
        assert len(content) == record['bytes'], f"Byte count: {record['file']}"
        assert sha256(content).hexdigest() == record['sha256'], f"Checksum: {record['file']}"
        assert content.startswith(b'%PDF-'), f"PDF signature: {record['file']}"
        print(f"PDF verified: {record['file']} ({len(content):,} bytes)")

    html_path = SITE / 'index.html'
    html = html_path.read_text(encoding='utf-8')
    page = Page()
    page.feed(html)
    assert len(page.ids) == len(set(page.ids)), 'Duplicate HTML IDs'
    assert re.search(r'<html[^>]+lang="en"', html), 'Missing document language'
    assert 'name="viewport"' in html
    assert len(re.findall(r'<h1[ >]', html)) == 1, 'Expected a single H1'
    for href in page.links:
        check_link(html_path, href, page.ids)
    for source in [ROOT / 'README.md', *sorted((ROOT / 'guidance').glob('*.md'))]:
        prose = source.read_text(encoding='utf-8')
        for href in re.findall(r'\]\(([^\s)]+)\)', prose):
            check_link(source, href)
    for source in SITE.glob('*.css'):
        for href in re.findall(r'url\([\'"]?([^\)\'"\s]+)', source.read_text(encoding='utf-8')):
            check_link(source, href)
    bib = (SITE / 'citation.bib').read_text(encoding='utf-8')
    cff = (ROOT / 'CITATION.cff').read_text(encoding='utf-8')
    assert '10.1002/mgea.70075' in bib and '10.1002/mgea.70075' in cff
    assert 'Xu, Kaiyang and Lu, Yujun and Liu, Lifeng and Zhang, Lei' in bib
    assert 'Lu, Yujun and Xu, Kaiyang and Zhang, Lei' in bib
    assert '@unpublished{LuMatterMindExtended' in bib
    assert (SITE / '.nojekyll').exists()
    print(f'Publication checks passed: {len(page.links)} HTML links, {page.image_count} images, 3 original PDFs.')


if __name__ == '__main__':
    main()
