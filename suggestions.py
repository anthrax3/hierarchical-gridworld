from fuzzywuzzy import fuzz
import heapq
import messages
import envs

def match(query, key):
    return fuzz.token_sort_ratio(query, key)

def best_matches(query, keys, n=5):
    vs = {}
    def sort_key(k):
        if k not in vs: vs[k] = match(query, k)
        return vs[k]
    return sorted(heapq.nlargest(n, keys, key=sort_key), key=sort_key, reverse=True)

def best_dict_values(query, d, deduplicate=True, n=5, filter=lambda x:True):
    keys = best_matches(query, d.keys(), n=3*n)
    result = []
    for k in keys:
        v = d[k]
        if len(result) < n and v not in result and filter(v):
            result.append(v)
    return result

def make_suggestions_and_shortcuts(env, obs, cache, num_suggestions=5, num_shortcuts=5):
    shortcuts = []
    def add_shortcut(m):
        h = m.format(["()"] * m.size)
        if useful_shortcut(h) and len(shortcuts) < num_shortcuts and h not in shortcuts:
            shortcuts.append(h)
    def useful_shortcut(h):
        return len(h) > 8
    for m in env.messages:
        if not messages.is_addressed(m):
            add_shortcut(m)
        elif messages.is_addressed(m):
            add_shortcut(messages.unaddressed_message(m))
    for c in env.actions:
        for m in envs.get_messages_in(c):
            for h in messages.submessages(m, include_root=True):
                add_shortcut(h)
    def useful_suggestion(h):
        c = envs.parse_command(h)
        for m in envs.get_messages_in(c):
            try:
                m.instantiate(env.args)
            except messages.BadInstantiation:
                return False
        return (isinstance(c, envs.Reply) or isinstance(c, envs.Ask)) and len(h) >= 8
    suggestions = best_dict_values(obs, cache, filter=useful_suggestion)
    for h in suggestions:
        c = envs.parse_command(h)
        for m in envs.get_messages_in(c):
            add_shortcut(m)
    return suggestions, shortcuts
