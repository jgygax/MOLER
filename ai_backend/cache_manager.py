import json
import os


class CacheManager:
    def __init__(self, cache_file="cache.json"):
        self.cache_file = cache_file
        self.cache = {}
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    self.cache = json.load(f)
            except:
                self.cache = {}

    def get(self, key):
        return self.cache.get(key)

    def set(self, key, value):
        self.cache[key] = value
        with open(self.cache_file, "w") as f:
            json.dump(self.cache, f, indent=1)


cache_manager = CacheManager()
