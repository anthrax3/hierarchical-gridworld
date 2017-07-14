from fuzzywuzzy import fuzz
import heapq

def match(query, key):
    return fuzz.token_sort_ratio(query, key)

def best_matches(query, keys, n=5):
    current = []
    for key in keys:
        m = match(query, key)
        heapq.heappush(current, (-m, key))
        while len(current) > n:
            current.pop()
    return [k for (m, k) in current]

def best_dict_values(query, d, *args, **kwargs):
    keys = best_matches(query, d.keys(), *args, **kwargs)
    return [d[k] for k in keys]
