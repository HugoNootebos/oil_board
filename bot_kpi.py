"""
KPI recorder for headless bot games: the counters behind the six behaviours
the bots are tuned for (first ship, water protection and retention, cards,
emptied countries, hoards, spend-down, game length) -- see bot_report.py for
what each means and bot_selfplay.py for how it is switched on.

One Kpi per process (it wraps game methods once); reset(app) before each
game, then call tick() after every frame. The counters per side end up in
kpi.k, the per-turn series in kpi.series and the eliminations in kpi.elims.
Nothing here changes how a game is played.
"""

import collections
import os
import sys

import engine as engine_module
import phases
from models import CardMenu

RES = ("wood", "steel", "oil", "nuclear", "food")


def wrap(cls, name, before=None, after=None):
    original = getattr(cls, name)

    def wrapper(self, *args, **kwargs):
        state = before(self, *args, **kwargs) if before else None
        result = original(self, *args, **kwargs)
        if after:
            after(self, result, state, *args, **kwargs)
        return result
    wrapper.__name__ = name
    setattr(cls, name, wrapper)


class Kpi:
    """The KPIs of the six behaviours.  One instance per process; reset() per game."""

    VOLUNTARY = {"_finish_conquest", "_adjust_units", "_finish_redistribute"}

    def __init__(self, stats):
        self.stats = stats
        self.reset(None)
        self._install()

    # ------------------------------------------------------------------ state
    def reset(self, app):
        self.app = app
        self.k = collections.defaultdict(collections.Counter)      # side -> counters
        self.series = {}                                           # player idx -> list of per-own-turn records
        self.own_turn = collections.Counter()                      # player -> own turns started
        self.last_key = {}                                         # player -> turn_num of last _start_turn
        self.pending = {}                                          # player -> snapshot at turn end
        self.conq_turn = collections.defaultdict(list)             # player -> [(name, prev_kind)] this turn
        self.att = {}                                              # (player, target name) -> record
        self.vac = collections.defaultdict(list)                   # player -> [(name, units)] vacated
        self.elims = []
        self.ledger = None
        self.adj = collections.defaultdict(lambda: [0] * 6)
        self.last_stock = {}
        self.cur = {}                                              # player -> record of the own turn in progress
        self.first_ship = {}
        self.al_turn = collections.Counter()
        self.bought_now = collections.defaultdict(collections.Counter)   # player -> {country: assets bought this turn}

    def side(self, p):
        return self.stats.side_of.get(p)

    def add(self, p, key, n=1):
        s = self.side(p)
        if s is not None:
            self.k[s][key] += n

    def pidx(self, p):
        return self.app.players.index(p)

    # --------------------------------------------------------- exposure classes
    def exposure(self, P):
        eng = self.app
        mouse = eng.default_player
        land = collections.defaultdict(set)
        sea = collections.defaultdict(set)
        for c in eng.connections:
            a, b = c.connection
            tgt = land if c.kind == "land" else sea
            tgt[a].add(b)
            tgt[b].add(a)
        C = eng.countries

        def foe(n):
            o = C[n].owner
            return o is not P and o is not mouse
        out = {}
        front = set()
        for n, c in C.items():
            if c.owner is P and any(foe(m) for m in land[n]):
                front.add(n)
        for n, c in C.items():
            if c.owner is not P:
                continue
            if n in front:
                cls = "F"
            elif any(C[m].owner is mouse and any(foe(k) for k in land[m]) for m in land[n]):
                cls = "B"
            elif any(foe(m) for m in sea[n]):
                cls = "S"
            elif any(m in front for m in land[n]):
                cls = "D"
            else:
                cls = "I"
            w0 = all(C[m].owner is P for m in land[n])
            out[n] = (cls, w0, c.units)
        return out

    # ----------------------------------------------------------------- install
    def _install(self):
        me = self

        # --- frame-level resource ledger (called from the game loop) -----------------------------
        # (see tick())

        # --- turn start: retention of what was held at the previous turn end ----------------------
        def start_before(phase):
            P = phase.player
            m = phase.manager
            if me.last_key.get(P) == m.turn_num:
                return
            me.last_key[P] = m.turn_num
            me.own_turn[P] += 1
            eng = phase.engine
            snap = me.pending.pop(P, None)
            mouse = eng.default_player
            if snap:
                for n, (cls, w0, units) in snap["classes"].items():
                    o = eng.countries[n].owner
                    me.add(P, "cls_" + cls, 1)
                    me.add(P, "cls_%s_units" % cls, units)
                    if w0:
                        me.add(P, "w0", 1)
                    if o is not P:
                        kind = "mouse" if o is mouse else "player"
                        me.add(P, "cls_%s_lost_%s" % (cls, kind), 1)
                        if w0:
                            me.add(P, "w0_lost_" + kind, 1)
                for n, prev in snap["conq"]:
                    o = eng.countries[n].owner
                    me.add(P, "conq_%s_n" % prev, 1)
                    if o is P:
                        me.add(P, "conq_%s_kept" % prev, 1)
                    elif o is mouse:
                        me.add(P, "conq_%s_to_mouse" % prev, 1)
                    else:
                        me.add(P, "conq_%s_retaken" % prev, 1)
            if snap:
                for n, (ships, tanks, planes, fort) in snap.get("assets", {}).items():
                    cls, w0, units = snap["classes"][n]
                    held = eng.countries[n].owner is P
                    count = ships + tanks + planes + fort
                    for tag in ("all", "cls_" + cls, "units1" if units <= 1 else "units2p"):
                        me.add(P, "ast_end_" + tag, count)
                        if not held:
                            me.add(P, "ast_end_%s_lost" % tag, count)
                    for kind, k in (("ships", ships), ("tanks", tanks), ("planes", planes), ("fort", fort)):
                        me.add(P, "ast_end_kind_" + kind, k)
                        if not held:
                            me.add(P, "ast_end_kind_%s_lost" % kind, k)
                    young = min(count, snap.get("bought", {}).get(n, 0))
                    me.add(P, "ast_end_young", young)
                    if not held:
                        me.add(P, "ast_end_young_lost", young)
                        me.add(P, "ast_end_old_lost", count - young)
            for n, units, ntrn in me.vac.pop(P, []):
                o = eng.countries[n].owner
                me.add(P, "vac_n", 1)
                me.add(P, "vac_units", units)
                me.add(P, "vac_" + ("still_mouse" if o is mouse else "back_to_self" if o is P else "taken_by_player"), 1)
            me.cur[P] = dict(t=m.turn_num, idx=me.own_turn[P] - 1, spent=[0] * 6, gained=[0] * 6, loot=[0] * 6)
        wrap(phases.ReinforcementPhase, "_start_turn", before=start_before)

        # --- turn end: snapshot ---------------------------------------------------------------------
        def end_before(manager):
            eng = manager.engine
            P = eng.players[eng.turn]
            if P.attack != 2 or P.eliminated:
                return
            cls = me.exposure(P)
            assets = {}
            for n, c in eng.countries.items():
                if c.owner is P and (c.ships or c.tanks or c.planes or c.fort_lvl):
                    assets[n] = (c.ships, c.tanks, c.planes, c.fort_lvl)
            me.pending[P] = dict(classes=cls, conq=list(me.conq_turn.pop(P, [])), assets=assets,
                                 bought=dict(me.bought_now.pop(P, {})))
            own = [c for c in eng.countries.values() if c.owner is P]
            troops = sum(c.units for c in own)
            cur = me.cur.get(P) or dict(t=manager.turn_num, idx=me.own_turn[P] - 1, spent=[0] * 6, gained=[0] * 6, loot=[0] * 6)
            idx = me.own_turn[P] - 1
            rec = dict(t=manager.turn_num, idx=idx, p=me.pidx(P), n=len(own), troops=troops,
                       stock=[P.wood, P.steel, P.oil, P.nuclear, P.food, len(P.cards)],
                       spent=cur["spent"], gained=cur["gained"], loot=cur["loot"],
                       card=bool(manager.conquered_enemy_this_turn), alive=sum(1 for q in eng.players if not q.eliminated),
                       mouse=sum(1 for c in eng.countries.values() if c.owner is eng.default_player),
                       lost=me.al_turn[P])
            me.series.setdefault(me.pidx(P), []).append(rec)
            me.al_turn[P] = 0
            me.add(P, "turns", 1)
            me.add(P, "cards_earned", 1 if manager.conquered_enemy_this_turn else 0)
            if idx == 0:
                me.add(P, "t1_countries", len(own))
                me.add(P, "t1_troops", troops)
        wrap(phases.TurnManager, "end_phase", before=end_before)

        # --- first ship ------------------------------------------------------------------------------
        def ship_before(phase, attr, cost, name):
            P = phase.player
            if attr == "ships" and P.start_ship:
                idx = me.own_turn[P] - 1
                me.first_ship[P] = (idx, name)
                me.add(P, "first_ship_bought", 1)
                me.add(P, "first_ship_turn_sum", idx)
                if idx == 0:
                    me.add(P, "first_ship_turn1", 1)
                me.add(P, "first_ship_free_cost_wood", cost.get("wood", 0))
        wrap(phases.ShopPhase, "place_unit", before=ship_before)

        # --- assets: bought, destroyed (and why) ------------------------------------------------------
        def unit_before(phase, attr, cost, name):
            me.bought_now[phase.player][name] += 1
            me.add(phase.player, "ast_bought_" + attr, 1)
            for r, v in cost.items():
                me.add(phase.player, "ast_spent_" + r, v)
        wrap(phases.ShopPhase, "place_unit", before=unit_before)

        def fort_before(phase, name):
            c = phase.engine.countries[name]
            if c.owner == phase.player and c.fort_lvl <= 2 and phase.player.wood >= phase.fort_cost(c):
                me.bought_now[phase.player][name] += 1
                me.add(phase.player, "ast_bought_fort", 1)
                me.add(phase.player, "ast_spent_wood", phase.fort_cost(c))
        wrap(phases.ShopPhase, "place_fort", before=fort_before)

        orig_destroyed = engine_module.Engine.log_destroyed

        def destroyed(eng, owner, country_name, ships=0, tanks=0, planes=0, fort=0):
            if owner is not None and me.side(owner) is not None and (ships or tanks or planes or fort):
                names = []
                f = sys._getframe(1)
                while f is not None and len(names) < 7:
                    names.append(f.f_code.co_name)
                    f = f.f_back
                if "_conquer" in names:
                    cause = "conquest"
                elif "abandon" in names:
                    last = max(i for i, n in enumerate(names) if n == "abandon")    # the wrapper below it is ours
                    cause = "abandon:" + (names[last + 1] if last + 1 < len(names) else "?")
                elif "_apply_combat_results" in names:
                    cause = "landing"
                else:
                    cause = names[1] if len(names) > 1 else "?"
                for kind, k in (("ships", ships), ("tanks", tanks), ("planes", planes), ("fort", fort)):
                    if k:
                        me.add(owner, "ast_lost_" + kind, k)
                        me.add(owner, "ast_lost_cause_" + cause, k)
                if ships or tanks or planes or fort:
                    me.add(owner, "ast_lost_events", 1)
            return orig_destroyed(eng, owner, country_name, ships, tanks, planes, fort)
        engine_module.Engine.log_destroyed = destroyed

        # --- the one move a turn (_reposition): what moved ---------------------------------------------------
        import bot as bot_module

        def rep_before(ctl, phase):
            return {c.name: (c.units, c.ships, c.tanks, c.planes) for c in ctl._owned()}

        def rep_after(ctl, res, st, phase):
            if not res:
                return
            P = ctl.player
            me.add(P, "rep_moves", 1)
            moved_assets = False
            troops = 0
            for c in ctl._owned():
                before = st.get(c.name)
                if before is None:
                    continue
                units, ships, tanks, planes = before
                if c.units < units:
                    troops += units - c.units
                if c.ships < ships:
                    me.add(P, "rep_ships", 1)
                    moved_assets = True
                if c.tanks < tanks:
                    me.add(P, "rep_tanks", tanks - c.tanks)
                    moved_assets = True
                if c.planes < planes:
                    me.add(P, "rep_planes", 1)
                    moved_assets = True
            me.add(P, "rep_troops", troops)
            if moved_assets:
                me.add(P, "rep_with_assets", 1)
                if troops <= 1:
                    me.add(P, "rep_assets_only", 1)
        wrap(bot_module.BotController, "_reposition", before=rep_before, after=rep_after)

        # --- attacks -------------------------------------------------------------------------------------
        def att_after(phase, res, st, hover, is_land, via_air=False):
            if phase.attack_from is None:
                return
            eng = phase.engine
            fc, tg = eng.countries[phase.attack_from], eng.countries[hover]
            P = phase.player
            me.att[(P, hover)] = dict(g0=tg.units, fort=tg.fort_lvl, tanks=tg.tanks, a0=fc.units,
                                      kind="land" if is_land else ("air" if via_air else "sea"),
                                      owner=("mouse" if tg.owner is eng.default_player else "player"))
            me.add(P, "att_" + me.att[(P, hover)]["owner"], 1)
            me.add(P, "att_kind_" + me.att[(P, hover)]["kind"], 1)
            if tg.owner is not eng.default_player:
                me.add(P, "att_player_g%d" % min(tg.units, 4), 1)
        wrap(phases.AttackPhase, "_start_attack", after=att_after)

        def comb_before(phase):
            eng = phase.engine
            fc, tg = eng.countries[phase.attack_from], eng.countries[phase.defence_country]
            return (fc.units, tg.units, phase.attack_from, phase.defence_country, tg.owner is eng.default_player)

        def comb_after(phase, res, st):
            eng = phase.engine
            a0, d0, fn, tn, was_mouse = st
            fc, tg = eng.countries[fn], eng.countries[tn]
            P = phase.player
            if tg.owner is P:
                al, dl = a0 - (fc.units + tg.units), d0
            else:
                al, dl = a0 - fc.units, d0 - tg.units
            me.add(P, "att_lost", al)
            me.al_turn[P] += al
            me.add(P, "def_lost", dl)
            if not was_mouse:
                me.add(P, "att_lost_vs_player", al)
                me.add(P, "kills_player", dl)
        wrap(phases.AttackPhase, "_apply_combat_results", before=comb_before, after=comb_after)

        def conq_before(phase, defence, attack_from, *a, **kw):
            eng = phase.engine
            return (defence.owner, phase.manager.conquered_enemy_this_turn, defence.name)

        def conq_after(phase, res, st, defence, attack_from, *a, **kw):
            prev, flag, name = st
            eng = phase.engine
            P = phase.player
            real = prev is not eng.default_player
            rec = me.att.pop((P, name), None)
            kind = "player" if real else "mouse"
            me.conq_turn[P].append((name, kind))
            me.add(P, "conq_" + kind, 1)
            if me.own_turn[P] == 1:
                me.add(P, "t1_conq", 1)
            if not phase.attack_via_land and phase.selected_ships > 0:
                me.add(P, "ship_conq", 1)
                if me.own_turn[P] <= 3:
                    me.add(P, "ship_conq_first3", 1)
            if not phase.attack_via_land and phase.selected_ships == 0:
                me.add(P, "plane_conq", 1)
            if real and not flag:                                   # this conquest earns the turn's card
                g0 = rec["g0"] if rec else 0
                fort = rec["fort"] if rec else 0
                me.add(P, "card_conq", 1)
                for kk in (1, 2, 3):
                    if g0 <= kk and fort == 0:
                        me.add(P, "card_conq_g%d" % kk, 1)
                me.add(P, "card_conq_g_sum", g0)
                me.add(P, "card_conq_tanks_or_fort", 1 if (rec and (rec["tanks"] or rec["fort"])) else 0)
                if prev is not None and me.side(prev) is not None:
                    me.add(prev, "cards_given", 1)
                    if g0 <= 2:
                        me.add(prev, "cards_given_g2", 1)
            if real and me.side(prev) is not None:
                me.add(prev, "countries_lost_to_player", 1)
        wrap(phases.AttackPhase, "_conquer", before=conq_before, after=conq_after)

        # --- abandons (buffer / forced) ---------------------------------------------------------------------
        orig_abandon = phases.Phase.abandon

        def abandon(phase, country):
            eng = phase.engine
            owner = country.owner
            if owner is not eng.default_player and me.side(owner) is not None:
                f1 = sys._getframe(1)
                cause = f1.f_code.co_name
                base = os.path.basename(f1.f_code.co_filename)
                if base == "events.py":
                    cause = "event:" + cause
                elif base.startswith("bot"):
                    cause = "bot:" + cause                       # a bot module calling abandon() itself = by design
                me.add(owner, "abandon:" + cause, 1)
                if (cause in me.VOLUNTARY or cause.startswith("bot:")) and owner is eng.players[eng.turn]:
                    me.add(owner, "vacated_design", 1)
                    me.vac[owner].append((country.name, country.units, phase.manager.turn_num))
                else:
                    me.add(owner, "abandon_forced", 1)
            return orig_abandon(phase, country)
        phases.Phase.abandon = abandon

        # --- eliminations / loot ----------------------------------------------------------------------------------
        def took_before(phase, player, country):
            return (country.owner, phase.manager.elimination_loot.get(country.owner))

        def took_after(phase, res, st, player, country):
            loser, before = st
            entry = phase.manager.elimination_loot.get(loser)
            if entry is None or entry is before:
                return
            victor, loot = entry
            d = {r: n for n, r in loot}
            for i, r in enumerate(RES):
                if d.get(r):
                    me.adj[loser][i] -= d[r]          # not a spend of the victim ...
                    if me.cur.get(victor):
                        me.cur[victor]["loot"][i] += d[r]
            if d.get("cards"):
                me.adj[loser][5] -= d["cards"]
                if me.cur.get(victor):
                    me.cur[victor]["loot"][5] += d["cards"]
            sr = me.series.get(me.pidx(loser), [])
            hoard = (sr[-1]["stock"][:4], sr[-1]["stock"][5]) if sr else None
            me.elims.append(dict(t=phase.manager.turn_num, victim=me.pidx(loser), victor=me.pidx(victor),
                                 loot=d, hoard_prev=hoard,
                                 victim_cards_now=d.get("cards", 0),
                                 victor_cards_before=len(victor.cards) - d.get("cards", 0),
                                 victor_spent=list(me.cur[victor]["spent"][:4]) if me.cur.get(victor) else None,
                                 victor_turn_idx=me.own_turn[victor] - 1))
        wrap(phases.Phase, "take_last_country", before=took_before, after=took_after)

        def elim_before(manager, player):
            eng = manager.engine
            victor = manager.elimination_loot.get(player, (None, []))[0]
            me.elims.append(dict(t=manager.turn_num, dead=me.pidx(player), by=me.pidx(victor) if victor else None,
                                 own_turn=bool(player is eng.players[eng.turn])))
        wrap(phases.TurnManager, "_eliminate", before=elim_before)

        # --- trades --------------------------------------------------------------------------------------------------
        def trade_before(menu, reward, amount):
            me.add(menu.player, "trade_n", 1)
            me.add(menu.player, "trade_cards", len(menu.trade_cards))
            me.add(menu.player, "trade_" + reward, 1)
            if reward == "helmets":
                me.add(menu.player, "trade_troops", amount)
        wrap(CardMenu, "_execute_trade", before=trade_before)

    # ----------------------------------------------------------------- ledger
    def tick(self):
        eng = self.app
        for p in eng.players:
            cur = [p.wood, p.steel, p.oil, p.nuclear, p.food, len(p.cards)]
            last = self.last_stock.get(p)
            self.last_stock[p] = cur
            if last is None:
                continue
            adj = self.adj.pop(p, None)
            rec = self.cur.get(p)
            if rec is None:
                continue
            for i in range(6):
                d = cur[i] - last[i] - (adj[i] if adj else 0)
                if d < 0:
                    rec["spent"][i] += -d
                elif d > 0:
                    rec["gained"][i] += d
        self.adj.clear()
