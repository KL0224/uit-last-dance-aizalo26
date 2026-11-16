"""Bounded exact-value verification; timeout is never negative evidence."""
from collections import OrderedDict
from threading import Timer
from time import perf_counter

class ValueVerificationProvider:
    def __init__(self, index):
        self.index = index
        self.cache = OrderedDict()

    def verify(self, requests):
        import duckdb
        result = {}
        deadline = perf_counter() + .2
        queries = 0
        with duckdb.connect(str(self.index.database), read_only=True) as connection:
            for ref, values in requests.items():
                if ref not in self.index.columns:
                    raise ValueError('unknown value lookup column')
                table, column = ref.rsplit('.', 1)
                quote = lambda value: '"' + value.replace('"', '""') + '"'
                key = (ref, tuple(values))
                if key in self.cache:
                    self.cache.move_to_end(key)
                    result[ref] = self.cache[key]
                    continue
                remaining = min(.1, deadline - perf_counter())
                if queries >= 2 or remaining <= 0:
                    result[ref] = None
                    continue
                queries += 1
                timer = Timer(remaining, connection.interrupt)
                timer.start()
                try:
                    placeholders = ','.join('?' for _ in values)
                    rows = connection.execute(f'SELECT DISTINCT {quote(column)} FROM {quote(table)} WHERE {quote(column)} IN ({placeholders}) LIMIT 6', values).fetchall()
                    found = [row[0] for row in rows]
                    result[ref] = found if len(found) <= 5 else None
                    if result[ref] is not None:
                        self.cache[key] = found
                        if len(self.cache) > 4096:
                            self.cache.popitem(last=False)
                except duckdb.Error:
                    result[ref] = None
                finally:
                    timer.cancel()
                    timer.join()
        return result
