from CodernityDB.tree_index import TreeBasedIndex


class CollectionIndex(TreeBasedIndex):
    _version = 1

    def __init__(self, *args, **kwargs):
        kwargs['key_format'] = '256s'
        super().__init__(*args, **kwargs)

    def make_key(self, key):
        return str(key).lower()

    def make_key_value(self, data):
        if data.get('_t') == 'collection':
            return str(data.get('name', '')).lower(), None
