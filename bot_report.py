"""
Turns the per-game JSON lines that bot_selfplay.py writes into tables:
game length and draws; A-minus-B contrasts at the level of pairs (a pair is
the same seed played twice with the sides swapped) for win rate, placement
(winner 1 ... first eliminated 0), loot (legacy weights and "market"
weights, oil worth nothing) and eliminations; and the KPIs of the six
behaviours (first ship, water protection and retention, cards, emptied
countries, hoards, spend-down).

    python3 bot_report.py OUT.jsonl [more.jsonl ...] [--players N]
"""
import json
import sys
import statistics as st
import collections
import math

args = [a for a in sys.argv[1:] if not a.startswith("--")]
PL = None
if "--players" in sys.argv:
    PL = int(sys.argv[sys.argv.index("--players") + 1])
    args = [a for a in args if a != str(PL)]
games = []
for fn in args:
    for line in open(fn):
        g = json.loads(line)
        games.append(g)
errors = [g for g in games if "error" in g]
games = [g for g in games if "error" not in g and (PL is None or g["players"] == PL)]
print("games ok %d, crashed %d" % (len(games), len(errors)))
for e in errors[:3]:
    print("  ERR", e["i"], e["seed"], e["error"], e["tb"][-300:])


def mean(x):
    x = list(x)
    return sum(x) / len(x) if x else float("nan")


def sd(x):
    x = list(x)
    return st.stdev(x) if len(x) > 1 else float("nan")


def pct(x, q):
    x = sorted(x)
    return x[min(len(x) - 1, int(q * len(x)))]


# ---------------------------------------------------------------- length / draws
turns = [g["turns"] for g in games]
print("\n== length ==")
print("turns (turn_num incl. skipped seats): mean %.1f median %d p90 %d max %d | draws(no winner) %d/%d | wall mean %.1f s, median %.1f s" % (
    mean(turns), st.median(turns), pct(turns, .9), max(turns), sum(1 for g in games if g["winner"] is None), len(games),
    mean(g["wall"] for g in games), st.median(g["wall"] for g in games)))
by_n = collections.defaultdict(list)
for g in games:
    by_n[g["players"]].append(g)
for n, gs in sorted(by_n.items()):
    print("  %dp: games %d, turns mean %.1f median %d max %d, rounds mean %.1f, wall mean %.1f s" % (
        n, len(gs), mean(g["turns"] for g in gs), st.median(g["turns"] for g in gs), max(g["turns"] for g in gs),
        mean(g["turns"] / n for g in gs), mean(g["wall"] for g in gs)))

# ---------------------------------------------------------------- per-seat extraction
def seats(g, side):
    return [k for k, s in enumerate(g["sides"]) if s == side]


def placement(g):
    """score per seat: winner 1.0, first eliminated 0.0 (linear in elimination order)."""
    n = g["players"]
    dead = [e for e in g.get("elims", []) if "dead" in e]
    order = [e["dead"] for e in dead]
    score = {}
    for r, p in enumerate(order):            # first dead gets 0
        score[p] = r / (n - 1)
    alive = [k for k in range(n) if k not in score]
    for p in alive:
        score[p] = (len(order) + (len(alive) - 1) / 2) / (n - 1)  # winner (or draw: average of the open ranks)
    return score


def side_metrics(g, side):
    """per-seat-normalised metrics of one side in one game"""
    ss = seats(g, side)
    c = g["count"].get(side, {})
    k = g.get("k", {}).get(side, {})
    pl = placement(g)
    return dict(
        win=1.0 if g["winner"] == side else 0.0,
        win_share=(1.0 if g["winner"] == side else 0.0),
        place=mean(pl[p] for p in ss),
        loot=c.get("loot score", 0) / len(ss),
        loot_market=c.get("loot market", 0) / len(ss),
        elim_made=c.get("eliminations made", 0) / len(ss),
        elim_suffered=sum(c.get(x, 0) for x in ("eliminated by a player", "died on own turn", "died otherwise")) / len(ss),
    )


def contrast(metric):
    """pair-level A-B contrast: for each pair (i//2) average over the two games of (A seat-mean - B seat-mean)"""
    pairs = collections.defaultdict(list)
    per_game = []
    for g in games:
        a, b = side_metrics(g, "A")[metric], side_metrics(g, "B")[metric]
        d = a - b
        per_game.append(d)
        pairs[(g["seed"], g["players"])].append(d)
    pv = [mean(v) for v in pairs.values() if len(v) == 2]
    return per_game, pv


print("\n== A-B contrasts (per seat-mean; margin = 95%%) ==")
print("%-14s %8s | per-game: mean +- margin (sd) | per-pair: mean +- margin (sd, n pairs) | sd ratio" % ("metric", "A mean"))
for m in ("win", "place", "loot", "loot_market", "elim_made", "elim_suffered"):
    pg, pv = contrast(m)
    a_mean = mean(side_metrics(g, "A")[m] for g in games)
    print("%-14s %8.3f | %+7.3f +- %6.3f (sd %6.3f)        | %+7.3f +- %6.3f (sd %6.3f, n=%d)  | %.2f" % (
        m, a_mean, mean(pg), 1.96 * sd(pg) / math.sqrt(len(pg)), sd(pg),
        mean(pv), 1.96 * sd(pv) / math.sqrt(len(pv)) if len(pv) > 1 else float("nan"), sd(pv), len(pv),
        sd(pv) / sd(pg) if sd(pg) else float("nan")))

# ---------------------------------------------------------------- state at the end (short screens)
ends = [g for g in games if g.get("end")]
if ends:
    print("\n== state when the game stopped (per seat; strength = 3 per country + troops; share = of all players') ==")
    print("(use --maxturns 24 for a 4-player game cut after 6 rounds: the quick screen of early play)")
    print("%-4s %9s %10s %9s %10s %9s" % ("side", "alive", "countries", "troops", "strength", "share"))
    for side in "AB":
        alive_n = seat_n = 0
        cs, tr, st_, sh = [], [], [], []
        for g in ends:
            total = sum(3 * e["n"] + e["troops"] for e in g["end"]) or 1
            for k in seats(g, side):
                e = g["end"][k]
                seat_n += 1
                alive_n += 1 if e["alive"] else 0
                cs.append(e["n"])
                tr.append(e["troops"])
                st_.append(3 * e["n"] + e["troops"])
                sh.append((3 * e["n"] + e["troops"]) / total)
        print("%-4s %8.1f%% %10.2f %9.2f %10.2f %9.3f" % (side, 100.0 * alive_n / seat_n, mean(cs), mean(tr), mean(st_), mean(sh)))

# identical pairs
ident = 0
npairs = 0
pairs = collections.defaultdict(list)
for g in games:
    pairs[(g["seed"], g["players"])].append(g)
for key, v in pairs.items():
    if len(v) == 2:
        npairs += 1
        # same game <=> same turn count and the same seat wins in both
        w0 = v[0]["sides"].index(v[0]["winner"]) if v[0]["winner"] else None
        if v[0]["turns"] == v[1]["turns"] and v[0]["winner"] and v[1]["winner"]:
            ws = [g["sides"] for g in v]
            seat0 = [k for k, s in enumerate(v[0]["sides"]) if s == v[0]["winner"]]
            seat1 = [k for k, s in enumerate(v[1]["sides"]) if s == v[1]["winner"]]
            if seat0 and seat1 and seat0[0] == seat1[0]:
                ident += 1
print("\npairs with identical outcome (same turn count and same winning seat): %d of %d" % (ident, npairs))

# ---------------------------------------------------------------- KPI table
tot = collections.defaultdict(collections.Counter)
nseat = collections.Counter()
for g in games:
    for side in "AB":
        nseat[side] += len(seats(g, side))
        for key, v in g.get("k", {}).get(side, {}).items():
            tot[side][key] += v
        for key, v in g["count"].get(side, {}).items():
            tot[side]["S:" + key] += v
ngames = len(games)


def row(label, fn, fmt="%.3f"):
    vals = []
    for side in "AB":
        try:
            vals.append(fmt % fn(tot[side], nseat[side], ngames))
        except ZeroDivisionError:
            vals.append("n/a")
    pooled = collections.Counter()
    for side in "AB":
        pooled.update(tot[side])
    try:
        pv = fmt % fn(pooled, nseat["A"] + nseat["B"], ngames * 2)
    except ZeroDivisionError:
        pv = "n/a"
    print("%-58s A %-10s B %-10s pooled %-10s" % (label, vals[0], vals[1], pv))


T = lambda t, k: t.get(k, 0)
print("\n== R1 opening / water ==")
row("free ship bought (share of seats)", lambda t, n, G: T(t, "first_ship_bought") / n)
row("  ... on own turn 1 (share of seats)", lambda t, n, G: T(t, "first_ship_turn1") / n)
row("  mean own-turn index of purchase (0 = first turn)", lambda t, n, G: T(t, "first_ship_turn_sum") / T(t, "first_ship_bought"))
row("  never bought while alive at game end (share of seats)", lambda t, n, G: T(t, "first_ship_never") / n)
row("conquests with a ship aboard, per seat-game", lambda t, n, G: T(t, "ship_conq") / n)
row("  ... in own turns 1-3, per seat", lambda t, n, G: T(t, "ship_conq_first3") / n)
row("conquests by plane crossing, per seat-game", lambda t, n, G: T(t, "plane_conq") / n)
row("attacks by kind land/sea/air: sea per seat-game", lambda t, n, G: T(t, "att_kind_sea") / n)
row("attacks by kind: air per seat-game", lambda t, n, G: T(t, "att_kind_air") / n)
row("first own turn: conquests per seat", lambda t, n, G: T(t, "t1_conq") / n)
row("first own turn: countries held at turn end", lambda t, n, G: T(t, "t1_countries") / n)
row("first own turn: troops held at turn end", lambda t, n, G: T(t, "t1_troops") / n)
print("\n-- exposure classes at turn end (F frontier: enemy land neighbour; B buffered: enemy 2 land steps away through mouse;")
print("   S sea-exposed only: enemy sea link; D behind own frontier; I interior) --")
for cls in "FBSDI":
    row("class %s: share of country-turns" % cls, lambda t, n, G, cls=cls: T(t, "cls_" + cls) / sum(T(t, "cls_" + x) for x in "FBSDI"))
    row("   units per country", lambda t, n, G, cls=cls: T(t, "cls_%s_units" % cls) / T(t, "cls_" + cls))
    row("   lost to a PLAYER before owner's next turn", lambda t, n, G, cls=cls: T(t, "cls_%s_lost_player" % cls) / T(t, "cls_" + cls))
    row("   lost to MOUSE (abandon) before next turn", lambda t, n, G, cls=cls: T(t, "cls_%s_lost_mouse" % cls) / T(t, "cls_" + cls))
row("w0 (all land links own; pure water-protected): share of country-turns", lambda t, n, G: T(t, "w0") / sum(T(t, "cls_" + x) for x in "FBSDI"))
row("   w0 lost to a player before next turn", lambda t, n, G: T(t, "w0_lost_player") / T(t, "w0"))
row("w0 country-turns per own turn", lambda t, n, G: T(t, "w0") / T(t, "turns"))

print("\n== R2 cards ==")
row("turns ending with a card (conquered an enemy player)", lambda t, n, G: T(t, "cards_earned") / T(t, "turns"))
row("card-earning conquests: target garrison <=1 (share)", lambda t, n, G: T(t, "card_conq_g1") / T(t, "card_conq"))
row("   garrison <=2 and no fort (share)", lambda t, n, G: T(t, "card_conq_g2") / T(t, "card_conq"))
row("   garrison <=3 and no fort (share)", lambda t, n, G: T(t, "card_conq_g3") / T(t, "card_conq"))
row("   mean garrison at attack start", lambda t, n, G: T(t, "card_conq_g_sum") / T(t, "card_conq"))
row("attacks on players: share with garrison 1/2/3/4+ -> 1", lambda t, n, G: T(t, "att_player_g1") / T(t, "att_player"))
row("   garrison 2", lambda t, n, G: T(t, "att_player_g2") / T(t, "att_player"))
row("   garrison 3", lambda t, n, G: T(t, "att_player_g3") / T(t, "att_player"))
row("   garrison 4+", lambda t, n, G: T(t, "att_player_g4") / T(t, "att_player"))
row("attacker troops lost per card earned (vs players)", lambda t, n, G: T(t, "att_lost_vs_player") / T(t, "card_conq"))
row("attacker troops lost per conquest from mouse", lambda t, n, G: (T(t, "att_lost") - T(t, "att_lost_vs_player")) / T(t, "conq_mouse"))
row("cards GIVEN AWAY per own turn (victim side)", lambda t, n, G: T(t, "cards_given") / T(t, "turns"))
row("   ... of which garrison <=2 when attacked", lambda t, n, G: T(t, "cards_given_g2") / T(t, "cards_given"))

print("\n== R3 retention ==")
for kind in ("mouse", "player"):
    row("conquests from %s per seat-game" % kind, lambda t, n, G, kind=kind: T(t, "conq_" + kind) / n)
    row("   kept at owner's next turn start", lambda t, n, G, kind=kind: T(t, "conq_%s_kept" % kind) / T(t, "conq_%s_n" % kind))
    row("   retaken by another player before it", lambda t, n, G, kind=kind: T(t, "conq_%s_retaken" % kind) / T(t, "conq_%s_n" % kind))
    row("   lost to mouse (abandon) before it", lambda t, n, G, kind=kind: T(t, "conq_%s_to_mouse" % kind) / T(t, "conq_%s_n" % kind))
row("countries lost to players per own turn", lambda t, n, G: T(t, "countries_lost_to_player") / T(t, "turns"))
row("troops lost attacking, per own turn", lambda t, n, G: T(t, "att_lost") / T(t, "turns"))

print("\n== R4 buffer ==")
row("countries emptied by design per seat-game", lambda t, n, G: T(t, "vacated_design") / n)
row("forced abandons per seat-game", lambda t, n, G: T(t, "abandon_forced") / n)
causes = sorted({k for s in "AB" for k in tot[s] if k.startswith("abandon:")})
for cz in causes:
    row("   " + cz + " per seat-game", lambda t, n, G, cz=cz: T(t, cz) / n)
row("vacated: still mouse at owner's next turn", lambda t, n, G: T(t, "vac_still_mouse") / T(t, "vac_n"))
row("vacated: taken by another player", lambda t, n, G: T(t, "vac_taken_by_player") / T(t, "vac_n"))

print("\n== R5/R6 stocks ==")
# hoard (loot value) series
def loot_value(stock):
    return stock[0] + stock[1] + stock[2] + stock[3] + CARD * stock[5]


CARD = 8
hoard_at = collections.defaultdict(list)           # fraction -> [loot values of alive players]
hoard_comp = collections.defaultdict(lambda: collections.defaultdict(list))
for g in games:
    T_ = g["turns"]
    died = {e["dead"]: e["t"] for e in g.get("elims", []) if "dead" in e}
    for p, ser in g.get("series", {}).items():
        for frac in (0.25, 0.5, 0.75):
            if int(p) in died and died[int(p)] <= frac * T_:
                continue                      # already eliminated at that point of the game
            cut = [r for r in ser if r["t"] <= frac * T_]
            if not cut:
                continue
            r = cut[-1]
            # only count the player if still alive at the cut (turn after the record exists and elimination later)
            hoard_at[frac].append(loot_value(r["stock"]))
            for i, nm in enumerate(("wood", "steel", "oil", "nuclear", "food", "cards")):
                hoard_comp[frac][nm].append(r["stock"][i])
for frac in (0.25, 0.5, 0.75):
    v = hoard_at[frac]
    comp = hoard_comp[frac]
    print("hoard (wood+steel+oil+nuclear+8*cards) at %d%% of game, per player still alive at that point: mean %.1f median %.1f p90 %.1f (n=%d) | wood %.1f steel %.1f oil %.1f nuc %.1f food %.1f cards %.2f" % (
        frac * 100, mean(v), st.median(v), pct(v, .9), len(v), mean(comp["wood"]), mean(comp["steel"]), mean(comp["oil"]),
        mean(comp["nuclear"]), mean(comp["food"]), mean(comp["cards"])))
# at elimination: last turn-end stock of the dead player; loot taken
dead_h, loots, dead_n, dead_t = [], [], [], []
for g in games:
    for e in g.get("elims", []):
        if "victim" in e:
            loots.append(sum(v for r, v in e["loot"].items() if r != "food" and r != "cards") + CARD * e["loot"].get("cards", 0))
            if e["hoard_prev"]:
                w = e["hoard_prev"]
                dead_h.append(sum(w[0]) + CARD * w[1])
            dead_t.append(e["t"] / g["players"])
print("eliminations by a player: n=%d, loot score per elimination mean %.1f median %.1f (hoard of victim at its last turn end: mean %.1f), at round %.1f (mean)" % (
    len(loots), mean(loots), st.median(loots), mean(dead_h), mean(dead_t)))
nelim = sum(1 for g in games for e in g.get("elims", []) if "dead" in e)
print("eliminations per game %.2f (by a player %.2f), first elimination at turn %.1f" % (
    nelim / len(games), len(loots) / len(games),
    mean(min((e["t"] for e in g.get("elims", []) if "dead" in e), default=g["turns"]) for g in games)))

# end of game: winner's stock at the end and in its last turn
endv, endc = [], collections.defaultdict(list)
for g in games:
    if g["winner"] is None:
        continue
    for e in g["end"]:
        if e["alive"]:
            endv.append(loot_value(e["stock"]))
            for i, nm in enumerate(("wood", "steel", "oil", "nuclear", "food", "cards")):
                endc[nm].append(e["stock"][i])
print("winner's stock at game end (n=%d): loot value mean %.1f | wood %.1f steel %.1f oil %.1f nuclear %.1f food %.1f cards %.2f" % (
    len(endv), mean(endv), mean(endc["wood"]), mean(endc["steel"]), mean(endc["oil"]), mean(endc["nuclear"]), mean(endc["food"]), mean(endc["cards"])))
# spend-down: spent per own turn in the last N own turns of the winner vs earlier
for N in (3, 5):
    last, early = collections.defaultdict(list), collections.defaultdict(list)
    for g in games:
        if g["winner"] is None:
            continue
        w = g["sides"].index(g["winner"]) if False else None
        for e in g["end"]:
            if not e["alive"]:
                continue
            ser = g["series"].get(str(e["p"]), [])
            if len(ser) < 2 * N:
                continue
            for r in ser[-N:]:
                for i, nm in enumerate(("wood", "steel", "oil", "nuclear")):
                    last[nm].append(r["spent"][i] / max(1, r["spent"][i] + r["stock"][i]))   # share of what it had that it spent
            for r in ser[len(ser) // 2 - N // 2: len(ser) // 2 - N // 2 + N]:
                for i, nm in enumerate(("wood", "steel", "oil", "nuclear")):
                    early[nm].append(r["spent"][i] / max(1, r["spent"][i] + r["stock"][i]))
    print("winner, share of (spent+left) that was spent per own turn, last %d turns vs %d turns around its middle: " % (N, N) + " | ".join(
        "%s %.2f vs %.2f" % (nm, mean(last[nm]), mean(early[nm])) for nm in ("wood", "steel", "oil", "nuclear")) + " (n=%d)" % len(last["wood"]))
# trades
row("cards traded per seat-game", lambda t, n, G: T(t, "trade_cards") / n)
row("   for troops (share of trades)", lambda t, n, G: T(t, "trade_helmets") / T(t, "trade_n"))
row("   mean troops per trade for troops", lambda t, n, G: T(t, "trade_troops") / T(t, "trade_helmets"))
row("loot score per elimination made (Stats, legacy weights)", lambda t, n, G: T(t, "S:loot score") / T(t, "S:eliminations made"))
row("loot score per elimination made (market weights: oil 0)", lambda t, n, G: T(t, "S:loot market") / T(t, "S:eliminations made"))
row("eliminations made per seat-game", lambda t, n, G: T(t, "S:eliminations made") / n)
