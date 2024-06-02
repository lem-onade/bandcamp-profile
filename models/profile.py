import json


class Profile:
    def __init__(self, id, url, items):
        self.id = id
        self.url = url
        self.items = items
        self.item_count = len(items)

    def json(self):
        return {
            "id": self.id,
            "url": self.url,
            "items": [item.json() for item in self.items],
            "item_count": self.item_count,
        }
