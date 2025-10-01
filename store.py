class Cache:
    def __init__(self):
        self._d = {}
    def get(self, k, default=None):
        return self._d.get(k, default)
    def set(self, k, v):
        self._d[k] = v

cache = Cache()
