#!/usr/bin/env python3
"""Score committee-seat predictions against ground_truth/committee_seats.json.

Usage:  python3 score.py predictions.json

predictions.json maps each fixture key to the directors your system extracted:
{
  "amazon": {"directors": [
     {"name": "Wendell P. Weeks",
      "committeeMembership": "member",          # "member" | "none" | "" (not determined)
      "committees": [{"name": "Audit Committee", "role": "Member"}]}
  ]}
}

Scoring, per fixture:
  seats   in-scope ground-truth seats (director on the slate) found: director matched by name and committee matched
  roles   of the seats found, role equals ground truth (chair vs member)
  chairs  in-scope chairs found with role chair
  extras  predicted seats of slate directors that match no ground-truth seat
  leaving / image   out-of-scope seats found, reported for the record
  ahead   a role the filing states as taking effect at or after the meeting, reported as current
Matching is deliberately loose on spelling and strict on identity: a director is matched by surname and given name or
initial, a father and son of one name only by their generational suffix; a committee by its words, a filing's own
abbreviation (initials) or a prefix, never by a bare substring, and where a fixture holds two committees one of whose
names contains the other's, only an exact match counts.
"""
import json, math, re, sys, unicodedata
from collections import Counter

# ── names ───────────────────────────────────────────────────────────────────
GENERATION = {"jr", "sr", "ii", "iii", "iv"}
SUFFIX = GENERATION | {"phd", "md", "esq", "cpa"}
HONORIFIC = {"mr", "ms", "mrs", "dr", "hon", "prof", "sir", "dame"}


def key(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def name_tokens(s):
    return [t for t in key(s).split(" ") if t and t not in SUFFIX and t not in HONORIFIC]


def generation_of(s):
    g = next((t for t in key(s).split(" ") if t in GENERATION), "")
    return "" if g == "sr" else g


def same_person(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    ga, gb = generation_of(a), generation_of(b)
    if ga and gb and ga != gb:
        return False
    if ta == tb:
        return True
    if ta[-1] != tb[-1] and not (ta[-1] in tb or tb[-1] in ta):
        return False
    if len(ta) == 1 or len(tb) == 1:
        return True
    if ta[0] == tb[0]:
        return True
    return ta[0][0] == tb[0][0] and (len(ta[0]) == 1 or len(tb[0]) == 1)


def find_person(name, candidates, name_of=lambda c: c):
    loose = [c for c in candidates if same_person(name, name_of(c))]
    if len(loose) <= 1:
        return loose[0] if loose else None
    want, gen = name_tokens(name), generation_of(name)
    exact = [c for c in loose if (lambda h: h[0] == want[0] and h[-1] == want[-1])(name_tokens(name_of(c))) and generation_of(name_of(c)) == gen]
    return exact[0] if len(exact) == 1 else None


# ── committees ──────────────────────────────────────────────────────────────
FILLER = {"and", "of", "the", "on", "other", "for"}


def cmte_key(s):
    k = key((s or "").replace("&", " and "))
    k = re.sub(r"\b(the|committee|committees|of|board|on)\b", " ", k)
    return re.sub(r"\s+", " ", k).strip()


def initials_of(full):
    words = [w for w in key(full.replace("&", " and ")).split(" ") if w and w not in FILLER]
    core = "".join(w[0] for w in words if w != "committee")
    out = {core, core + "c"}
    alls = [w for w in key(full).split(" ") if w]
    for k in range(2, len(alls) + 1):
        out.add("".join(w[0] for w in alls[:k]))
    return out


def same_committee(a, b):
    ka, kb = cmte_key(a), cmte_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    wa = {w for w in ka.split(" ") if w != "and"}
    wb = {w for w in kb.split(" ") if w != "and"}
    if wa and wb and (wa <= wb or wb <= wa):
        return True
    for short, full in ((a, b), (b, a)):
        s = key(short).replace(" ", "")
        if 2 <= len(s) <= 5 and s in initials_of(full):
            return True
    core = lambda k: [w for w in k.split(" ") if w and w not in ("and", "comm", "committee")]
    ca, cb = core(ka), core(kb)
    if ca and len(ca) == len(cb):
        return all(x == y or (len(x) >= 3 and y.startswith(x)) or (len(y) >= 3 and x.startswith(y)) for x, y in zip(ca, cb))
    return False


def committee_matches(truth, extracted, fixture_committees):
    if not same_committee(truth, extracted):
        return False
    if cmte_key(truth) == cmte_key(extracted):
        return True
    for other in fixture_committees:
        if cmte_key(other) == cmte_key(truth):
            continue
        if same_committee(other, extracted):
            return False
    return True


def role_key(r):
    s = (r or "").strip().lower()
    if not s:
        return ""
    if s.startswith("member"):
        return "member"
    if s.startswith("co-chair") or s.startswith("cochair"):
        return "chair"
    if re.search(r"\bchair", s) and not re.search(r"vice|elect|emerit|former|past", s):
        return "chair"
    return "member"


# ── scoring ─────────────────────────────────────────────────────────────────
def score_fixture(f, directors):
    got, status = [], {}
    for d in directors:
        name = d.get("name") or d.get("fullName") or ""
        status[name] = d.get("committeeMembership") or ""
        for c in d.get("committees") or []:
            got.append({"director": name, "committee": c.get("name") or "", "role": role_key(c.get("role"))})
    on_slate = lambda n: any(same_person(s, n) for s in f["slate"])
    names = list(dict.fromkeys([g["director"] for g in got] + list(status)))
    fixture_committees = {s["committee"] for s in f["seats"] + f.get("imageSeats", [])}
    s = {
        "key": f["key"], "truth": f["truth"], "directors": len(directors),
        "slateMatched": sum(1 for n in f["slate"] if find_person(n, names) is not None), "slate": len(f["slate"]),
        "seats": [0, 0], "roles": [0, 0], "chairs": [0, 0], "leaving": [0, 0], "image": [0, 0],
        "extras": [], "ahead": [], "missing": [], "wrongRole": [], "status": {"none": 0, "blank": 0, "member": []},
    }
    used = set()
    truth_seats = [dict(x, kind="in" if on_slate(x["director"]) else "leaving") for x in f["seats"]] + [dict(x, kind="image") for x in f.get("imageSeats", [])]

    def match_index(t):
        who = find_person(t["director"], names)
        if who is None:
            return -1
        for i, g in enumerate(got):
            if i not in used and g["director"] == who and committee_matches(t["committee"], g["committee"], fixture_committees):
                return i
        return -1

    for t in truth_seats:
        bucket = {"in": s["seats"], "leaving": s["leaving"], "image": s["image"]}[t["kind"]]
        bucket[1] += 1
        if t["kind"] == "in":
            s["roles"][1] += 1
            if t["role"] == "chair":
                s["chairs"][1] += 1
        j = match_index(t)
        if j < 0:
            if t["kind"] == "in":
                s["missing"].append(f'{t["director"]} / {t["committee"]} ({t["role"]})')
            continue
        used.add(j)
        bucket[0] += 1
        if t["kind"] != "in":
            continue
        if got[j]["role"] == t["role"]:
            s["roles"][0] += 1
            if t["role"] == "chair":
                s["chairs"][0] += 1
        else:
            s["wrongRole"].append(f'{t["director"]} / {t["committee"]}: got {got[j]["role"] or chr(34)*2} want {t["role"]}')
    for i, g in enumerate(got):
        if i in used or not on_slate(g["director"]):
            continue
        future = next((r for r in f.get("futureRoles", []) if same_person(r["director"], g["director"]) and same_committee(r["committee"], g["committee"])), None)
        if future and g["role"] == future["role"]:
            s["ahead"].append(f'{g["director"]} / {g["committee"]} ({g["role"]})')
            continue
        s["extras"].append(f'{g["director"]} / {g["committee"]} ({g["role"]})')
    for r in f.get("futureRoles", []):
        for t in truth_seats:
            if not (same_person(t["director"], r["director"]) and same_committee(t["committee"], r["committee"])):
                continue
            j = next((i for i, g in enumerate(got) if same_person(t["director"], g["director"]) and same_committee(t["committee"], g["committee"])), -1)
            if j >= 0 and got[j]["role"] == r["role"] and got[j]["role"] != t["role"]:
                s["ahead"].append(f'{r["director"]} / {r["committee"]} ({r["role"]})')
                break
    seated = {t["director"] for t in truth_seats if t["kind"] != "leaving"}
    for name in f["slate"]:
        if any(same_person(d, name) for d in seated):
            continue
        entry = next(((n, v) for n, v in status.items() if same_person(n, name)), None)
        if not entry:
            continue
        if entry[1] == "none":
            s["status"]["none"] += 1
        elif entry[1] == "member":
            s["status"]["member"].append(name)
        else:
            s["status"]["blank"] += 1
    return s


def wilson(k, n, z=1.96):
    if n == 0:
        return (1.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def cell(t):
    return f"{(100 * (t[0] / t[1] if t[1] else 1)):3.0f}% {t[0]:3d}/{t[1]:<3d}"


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    here = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
    gt = json.load(open(__import__("os").path.join(here, "ground_truth", "committee_seats.json")))["fixtures"]
    preds = json.load(open(sys.argv[1]))
    scores, skipped = [], []
    for f in gt:
        p = preds.get(f["key"])
        if not p:
            skipped.append(f["key"]); continue
        scores.append(score_fixture(f, p.get("directors") or []))
    print("fixture          truth             dirs slate   seats (in scope)   roles             chairs           extra  leaving      image      ahead")
    for s in scores:
        print(f'{s["key"]:16s} {s["truth"]:17s} {s["directors"]:3d}  {s["slateMatched"]:2d}/{s["slate"]:<2d}  {cell(s["seats"])}   {cell(s["roles"])}   {cell(s["chairs"])}   {len(s["extras"]):3d}   {s["leaving"][0]}/{s["leaving"][1]:<3d}   {s["image"][0]}/{s["image"][1]:<3d}   {len(s["ahead"])}')
    pooled = lambda k: [sum(s[k][0] for s in scores), sum(s[k][1] for s in scores)]
    P = {k: pooled(k) for k in ("seats", "roles", "chairs", "leaving", "image")}
    extras = sum(len(s["extras"]) for s in scores); ahead = sum(len(s["ahead"]) for s in scores)
    ci = lambda t: "–".join(f"{100 * x:.0f}" for x in wilson(t[0], t[1]))
    print(f'{"POOLED":41s} {cell(P["seats"])}   {cell(P["roles"])}   {cell(P["chairs"])}   {extras:3d}   {P["leaving"][0]}/{P["leaving"][1]:<3d}   {P["image"][0]}/{P["image"][1]:<3d}   {ahead}')
    print(f'{"Wilson 95%":41s} {ci(P["seats"]):17s} {ci(P["roles"]):17s} {ci(P["chairs"])}')
    none_ = sum(s["status"]["none"] for s in scores); blank = sum(s["status"]["blank"] for s in scores)
    member = [f'{s["key"]}: {m}' for s in scores for m in s["status"]["member"]]
    print(f'status on slate directors the truth places on no committee: none {none_}, "" {blank}, member {len(member)}' + (f" ({'; '.join(member)})" if member else ""))
    if skipped:
        print("no predictions for:", ", ".join(skipped))
    print()
    for s in scores:
        for m in s["missing"]: print(f'  {s["key"]} missing: {m}')
        for w in s["wrongRole"]: print(f'  {s["key"]} role:    {w}')
        for e in s["extras"]: print(f'  {s["key"]} extra:   {e}')
        for a in s["ahead"]: print(f'  {s["key"]} ahead:   {a}  (the filing states this role as taking effect at or after the meeting)')


if __name__ == "__main__":
    main()
