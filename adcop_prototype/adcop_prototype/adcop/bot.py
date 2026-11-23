"""Channel-agnostic conversation logic. handle_message(phone, text) -> reply text.
State is a list of responses in SQLite; the posterior is rebuilt by replay (stateless, auditable)."""
import hashlib, json, sqlite3, time
from .engine import Engine, Graph, load_items

MAX_Q = 8
G, ITEMS = Graph(), load_items()
ENG = Engine(G, ITEMS)
DB = sqlite3.connect("adcop.db", check_same_thread=False)
DB.execute("CREATE TABLE IF NOT EXISTS state(phone TEXT PRIMARY KEY, js TEXT)")
DB.execute("CREATE TABLE IF NOT EXISTS log(ts REAL, phone TEXT, item TEXT, answer INT, correct INT)")
DB.execute("CREATE TABLE IF NOT EXISTS consent(phone TEXT PRIMARY KEY, accepted INT NOT NULL, recorded_at REAL)")
CONSENT = ("This is a short, experimental maths check of up to 8 questions. "
           "Results are draft learning-support prompts, not grades or diagnoses. "
           "Responses may be stored on this device so the chat can resume. "
           "Reply YES only if you agree and, if applicable, a parent/guardian has agreed. "
           "Reply NO to decline. Reply DELETE at any time to remove chat records.\n\n")


def _phone_key(phone):
    return hashlib.sha256(str(phone).encode("utf-8")).hexdigest()


def _consent(phone):
    key = _phone_key(phone)
    row = DB.execute("SELECT accepted FROM consent WHERE phone=?", (key,)).fetchone()
    return bool(row and row[0])


def _delete(phone):
    key = _phone_key(phone)
    DB.execute("DELETE FROM consent WHERE phone=?", (key,))
    DB.execute("DELETE FROM state WHERE phone=?", (key,))
    DB.execute("DELETE FROM log WHERE phone=?", (key,))
    DB.commit()

def _load(p):
    r = DB.execute("SELECT js FROM state WHERE phone=?", (_phone_key(p),)).fetchone()
    return json.loads(r[0]) if r else None
def _save(p, st): DB.execute("REPLACE INTO state VALUES(?,?)", (_phone_key(p), json.dumps(st))); DB.commit()

def _ask(st, intro=""):
    marg = ENG.marginals(ENG.posterior([tuple(r) for r in st["r"]]))
    iid = ENG.next_item(marg, {r[0] for r in st["r"]})
    st["pending"] = iid
    it = ITEMS[iid]
    opts = "\n".join(f"{n}) {o}" for n, o in enumerate(it["options"], 1))
    return f"{intro}Q{len(st['r'])+1}/{MAX_Q}: {it['q']}\n{opts}\nReply 1-4."

def _diagnose(st):
    marg = ENG.marginals(ENG.posterior([tuple(r) for r in st["r"]]))
    rc = ENG.root_causes(marg)
    if not rc: return "Done. No clear prototype gap signal was found. This is not a validated result."
    k = G.nodes[rc[0]]
    return (f"Done. A possible practice focus is {k['title']} (Grade {k['grade']}).\n"
            "This is a draft inference, not a diagnosis or grade. "
            "Use classroom evidence and explain the method before practice.\n"
            "Reply START for another check or DELETE to remove chat records.")

def handle_message(phone, text):
    t, st = text.strip().upper(), _load(phone)
    if t in {"DELETE","WITHDRAW","WITHDRAW CONSENT"}:
        _delete(phone)
        return "Your consent record, chat state and response log have been removed."
    if not _consent(phone):
        if t == "YES":
            key = _phone_key(phone)
            DB.execute("REPLACE INTO consent VALUES(?,?,?)", (key,1,time.time()))
            DB.commit()
            st = {"r": [], "pending": None}
            reply = _ask(st, "Consent recorded. ")
            _save(phone, st)
            return reply
        if t == "NO":
            _delete(phone)
            return "Consent declined. No assessment data was retained."
        if st is None or t == "START":
            return CONSENT
        return "Reply YES to consent, NO to decline, or DELETE to remove chat records."
    if st is None or t == "START":
        st = {"r": [], "pending": None}; reply = _ask(st); _save(phone, st); return reply
    if not st["pending"]: return "Reply START to begin a new check."
    if t not in {"1", "2", "3", "4"}: return "Please reply with 1, 2, 3 or 4."
    it = ITEMS[st["pending"]]; ok = int(t) == it["correct"]
    st["r"].append([it["id"], ok])
    DB.execute("INSERT INTO log VALUES(?,?,?,?,?)", (time.time(), _phone_key(phone), it["id"], int(t), int(ok)))
    if len(st["r"]) >= MAX_Q or len(st["r"]) >= len(ITEMS):
        st["pending"] = None; reply = _diagnose(st)
    else: reply = _ask(st, "✅ " if ok else "❌ ")
    _save(phone, st); return reply
