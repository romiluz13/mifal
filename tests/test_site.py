import unittest
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / 'site'


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.beats = []
        self.images = []
        self.buttons = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article' and 'data-beat' in attrs:
            self.beats.append(attrs['data-beat'])
        if tag == 'img':
            self.images.append(attrs)
        if tag == 'button' and 'id' in attrs:
            self.buttons[attrs['id']] = attrs


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.page = Page()
        self.page.feed((SITE / 'index.html').read_text())

    def test_historical_story_is_complete_without_javascript(self):
        self.assertEqual(self.page.beats, [
            'goal', 'staff', 'brief', 'doorbell', 'hold', 'fix', 'miss', 'ship', 'retro'
        ])

    def test_illustration_requires_enhancement_before_it_can_submit(self):
        self.assertIn('disabled', self.page.buttons.get('start-shift', {}))

    def test_workshop_is_present_without_javascript(self):
        images = [item for item in self.page.images if item.get('id') == 'workshop-poster']
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].get('alt'))
        self.assertTrue((SITE / images[0]['src']).is_file())
