def standardize_response(r):
    subs = {
            "A:":"reply",
            "A":"reply",
            "return":"reply",
            "Q:":"ask",
            "Q":"ask",
            "say":"note",
            "ask@":"resume",
        }
    for i in range(10):
        subs["reply {}".format(i)] = "resume {}".format(i)
    for k, v in subs.items():
        if starts_with(k, r):
            return v + r[len(k):]
    return r

def standardize_all_responses():
    db = sqlite3.connect("memoize.db")
    cursor = db.cursor()
    z = self.cursor.execute("SELECT * FROM responses")
    query = 
    for obs, response, src, kind in list(z):
        cursor.execute(
            "UPDATE responses SET output = ? WHERE input = ? AND kind = ? AND source = ?",
            (standardize_response(response), obs, src, kind)
        )
    db.commit()
