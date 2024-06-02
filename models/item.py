import json


class Item:
    def __init__(self, id, band_id, slug, title, url, art_url, downloadable):
        self.id = id
        self.band_id = band_id
        self.slug = slug
        self.title = title
        self.url = url
        self.art_url = art_url
        self.downloadable = downloadable

    def json(self):
        return {
            "id": self.id,
            "band_id": self.band_id,
            "slug": self.slug,
            "title": self.title,
            "url": self.url,
            "art_url": self.art_url,
            "downloadable": self.downloadable,
        }
