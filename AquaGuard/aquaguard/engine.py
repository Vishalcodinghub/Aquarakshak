"""AquaGuard simulation engine - pure Python standard library (no pip installs)."""
import csv
import io
import json
import math
import os
import random
import threading
import time

PARAMS = ("ph", "turb", "tds", "temp")
LABEL = {"ph": "pH", "turb": "Turbidity", "tds": "TDS", "temp": "Temperature"}
UNIT = {"ph": "", "turb": " NTU", "tds": " ppm", "temp": " \u00b0C"}
RANK = {"SAFE": 0, "WARNING": 1, "UNSAFE": 2}

DEFAULTS = dict(phMin=6.5, phMax=8.5, turbidityWarn=4.0, turbidityUnsafe=10.0,
                tdsWarn=500.0, tdsUnsafe=1200.0, tempMin=10.0, tempMax=35.0,
                alertSensitivity="normal", monitoringInterval=3, simulationMode="standard")
CHOICES = dict(alertSensitivity=("low", "normal", "high"),
               simulationMode=("standard", "stable", "volatile"))

SCENARIOS = {
    "safe": dict(name="Safe Water", ph=7.2, turb=1.2, tds=280, temp=24.0),
    "polluted": dict(name="Polluted Water", ph=8.9, turb=7.5, tds=780, temp=30.0),
    "mining": dict(name="Mining-Affected Water", ph=4.6, turb=14.0, tds=1650, temp=32.0),
}
SIGMA = dict(ph=0.04, turb=0.15, tds=8, temp=0.15)
LIMITS = dict(ph=(0, 14), turb=(0, 60), tds=(20, 3000), temp=(0, 50))
NOISE = dict(stable=0.3, standard=1.0, volatile=2.5)

STAGES = [  # name, icon, description, seconds
    ("Sediment Filter", "\U0001f9f1", "Removes sand, silt and suspended particles", 6),
    ("Activated Carbon", "\u26ab", "Reduces odour, taste and organics", 7),
    ("Membrane Filtration", "\U0001f9ec", "Reduces dissolved solids (TDS)", 8),
    ("UV Disinfection", "\U0001f506", "Inactivates microbes (simulated)", 5),
    ("Final Quality Check", "\u2705", "Verifies treated-water readings", 4),
]
TOTAL = sum(s[3] for s in STAGES)

SOURCES = [  # id, name, type, x%, y%, transform of the main reading
    ("A", "Village Well A", "Hand-pump well", 24, 38,
     lambda r: dict(ph=r["ph"], turb=r["turb"], tds=r["tds"], temp=r["temp"] - 1)),
    ("B", "River Intake B", "Surface-water intake", 58, 24,
     lambda r: dict(ph=r["ph"] + .2, turb=r["turb"] * 1.8 + .5, tds=r["tds"] * .8, temp=r["temp"] + 1.5)),
    ("C", "Borehole C - Mining Belt", "Borehole near a former mine", 74, 64,
     lambda r: dict(ph=r["ph"] - 1.2, turb=r["turb"] * 1.3 + .3, tds=r["tds"] * 2 + 80, temp=r["temp"] + .5)),
    ("D", "Community Tank D", "Treated storage tank", 38, 72,
     lambda r: dict(ph=7.2 + (r["ph"] - 7.2) * .2, turb=.4 + r["turb"] * .05, tds=r["tds"] * .3 + 40, temp=r["temp"] - .5)),
]


# ------------------------------------------------------------------ analysis
def fv(k, v):
    return "%.2f" % v if k == "ph" else "%.0f" % v if k == "tds" else "%.1f" % v


def bounds(s):
    hi = s["alertSensitivity"] == "high"          # "high" = alert earlier
    return dict(pmin=s["phMin"] + (.1 if hi else 0), pmax=s["phMax"] - (.1 if hi else 0),
                tw=s["turbidityWarn"] * (.9 if hi else 1), dw=s["tdsWarn"] * (.9 if hi else 1))


def evaluate(r, s):
    b = bounds(s)
    d = max(b["pmin"] - r["ph"], r["ph"] - b["pmax"], 0)
    t = max(s["tempMin"] - r["temp"], r["temp"] - s["tempMax"], 0)
    return dict(
        ph="SAFE" if d <= 0 else "WARNING" if d <= 1 else "UNSAFE",
        turb="UNSAFE" if r["turb"] > s["turbidityUnsafe"] else "WARNING" if r["turb"] > b["tw"] else "SAFE",
        tds="UNSAFE" if r["tds"] > s["tdsUnsafe"] else "WARNING" if r["tds"] > b["dw"] else "SAFE",
        temp="SAFE" if t <= 0 else "WARNING" if t <= 10 else "UNSAFE")


def overall(st):
    return max(st.values(), key=RANK.get)


def score(r, s, st=None):
    st = st or evaluate(r, s)
    sub = dict(
        ph=1 - min(1, max(s["phMin"] - r["ph"], r["ph"] - s["phMax"], 0) / 3),
        turb=1 - min(1, max(0, r["turb"] - 1) / max(1, 2 * s["turbidityUnsafe"] - 1)),
        tds=1 - min(1, max(0, r["tds"] - 300) / max(1, 2 * s["tdsUnsafe"] - 300)),
        temp=1 - min(1, max(s["tempMin"] - r["temp"], r["temp"] - s["tempMax"], 0) / 15))
    v = 100 * (.3 * sub["ph"] + .3 * sub["turb"] + .25 * sub["tds"] + .15 * sub["temp"])
    return int(round(min(v, (100, 79, 49)[RANK[overall(st)]])))


def category(v):
    return "Good" if v >= 80 else "Fair" if v >= 50 else "Poor"


def issue(k, v, s):
    if k == "ph":
        return "too acidic (low)" if v < 7 else "too alkaline (high)"
    if k == "temp":
        return "too cold" if v < s["tempMin"] else "too hot"
    return "too high"


def reason(r, st, s):
    bad = ["%s %s%s is %s" % (LABEL[k], fv(k, r[k]), UNIT[k], issue(k, r[k], s)) for k in PARAMS if st[k] != "SAFE"]
    return "; ".join(bad) + "." if bad else "All monitored parameters are within configured thresholds."


def step(r, target, rnd, noise, rate):
    out = {}
    for k in PARAMS:
        v = r[k] + (target[k] - r[k]) * rate + rnd.gauss(0, SIGMA[k] * noise)
        lo, hi = LIMITS[k]
        out[k] = round(min(hi, max(lo, v)), 1 if k == "tds" else 2)
    return out


# -------------------------------------------------------------------- engine
class Engine:
    def __init__(self, store_path=None):
        self.lock = threading.RLock()
        self.store_path = store_path
        self.rnd = random.Random()
        self.t0 = self.last_tick = self.last_save = time.time()
        self.last_hist = self.last_sample = self.last_pur_end = 0
        self.settings = dict(DEFAULTS)
        self.hist, self.alerts, self.recent = [], [], []
        self.aid = 0
        self.scenario = "safe"
        self.monitoring = True
        self.pur = self._new_pur()
        self._load()
        if not self.hist:
            self._seed()
        self.cur = {k: self.hist[-1][k] for k in PARAMS}
        self.last_hist = self.hist[-1]["ts"]
        self.recent = [dict(e, st=evaluate(e, self.settings)) for e in self.hist[-40:]]
        self._record(time.time(), self.cur, store=False)

    # ---- persistence
    def _load(self):
        try:
            with open(self.store_path, encoding="utf-8") as f:
                d = json.load(f)
            self.settings.update({k: v for k, v in d.get("settings", {}).items() if k in DEFAULTS})
            self.hist = [e for e in d.get("hist", []) if all(k in e for k in PARAMS + ("ts", "status"))]
            self.alerts = d.get("alerts", [])
            self.aid = int(d.get("aid", 0))
            self.scenario = d.get("scenario") if d.get("scenario") in SCENARIOS else "safe"
            self.monitoring = bool(d.get("monitoring", True))
            self.pur["mode"] = d.get("mode", "auto")
        except Exception:
            pass  # first run or unreadable file -> start clean, never fail

    def save(self):
        if not self.store_path:
            return
        try:
            with self.lock:
                os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
                tmp = self.store_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(dict(settings=self.settings, hist=self.hist, alerts=self.alerts[:300], aid=self.aid,
                                   scenario=self.scenario, monitoring=self.monitoring, mode=self.pur["mode"]),
                              f, separators=(",", ":"))
                os.replace(tmp, self.store_path)
        except OSError:
            pass

    def _seed(self, days=7):
        rnd, now, n = random.Random(42), time.time(), days * 48
        events = [(60, 70, "polluted"), (150, 162, "mining"), (250, 262, "polluted"), (300, 308, "polluted")]
        r = {k: SCENARIOS["safe"][k] for k in PARAMS}
        out = []
        for i in range(n):
            ts = now - (n - i) * 1800
            tg = dict(SCENARIOS["safe"])
            for a, b, sc in events:
                if a <= i < b:
                    tg = dict(SCENARIOS[sc])
            tg["temp"] += 3 * math.sin((((ts / 3600) % 24) - 9) / 24 * 2 * math.pi)
            r = step(r, tg, rnd, 1.0, .35)
            st = evaluate(r, self.settings)
            status = overall(st)
            out.append(dict(ts=int(ts), **r, status=status, score=score(r, self.settings, st),
                            pur=status != "SAFE" and rnd.random() < .6, scenario="seed"))
        self.hist = out

    def _new_pur(self):
        return dict(running=False, emergency=False, mode="auto", t=0.0, done=False, before=None, after=None,
                    target=None, tank_raw=80.0, tank_clean=10.0, runs=0, filter=100.0, trend=[])

    # ---- recording / alerts
    def _add(self, ts, param, sev, msg, resolved=False):
        self.aid += 1
        self.alerts.insert(0, dict(id=self.aid, ts=int(ts), param=param, label=LABEL.get(param, "System"), sev=sev,
                                   msg=msg, resolved=resolved, rts=int(ts) if resolved else None))
        del self.alerts[300:]

    def _resolve(self, a, ts):
        a["resolved"], a["rts"] = True, int(ts)

    def _check_alerts(self, ts, r, st):
        low = self.settings["alertSensitivity"] == "low"
        for k in PARAMS:
            s = st[k]
            act = [a for a in self.alerts if a["param"] == k and not a["resolved"]]
            if s == "SAFE" or (low and s == "WARNING"):
                for a in act:
                    self._resolve(a, ts)
            elif not any(a["sev"] == s for a in act):
                for a in act:
                    self._resolve(a, ts)
                self._add(ts, k, s, "%s %s%s is %s." % (LABEL[k], fv(k, r[k]), UNIT[k], issue(k, r[k], self.settings)))

    def _record(self, now, r, store=True):
        s = self.settings
        st = evaluate(r, s)
        status = overall(st)
        e = dict(ts=int(now), **r, status=status, score=score(r, s, st), pur=self.pur["running"], scenario=self.scenario)
        self.last = dict(e, st=st, reason=reason(r, st, s), cat=category(e["score"]))
        if not store:
            return
        self.recent.append(dict(e, st=st))
        del self.recent[:-60]
        if now - self.last_hist >= 60:
            self.hist.append(e)
            self.last_hist = now
            cut = now - 30 * 86400
            while self.hist and self.hist[0]["ts"] < cut:
                self.hist.pop(0)
            del self.hist[:-30000]
        self._check_alerts(now, r, st)
        p = self.pur
        if (p["mode"] == "auto" and status != "SAFE" and not p["running"] and not p["emergency"]
                and (p["t"] == 0 or p["done"]) and now - self.last_pur_end > 25):
            self._start(now, auto=True)

    # ---- time step (called once per second by the server thread)
    def tick(self):
        with self.lock:
            now = time.time()
            dt = min(5.0, now - self.last_tick)
            self.last_tick = now
            self._purify(now, dt)
            if self.monitoring and now - self.last_sample >= self.settings["monitoringInterval"] - .2:
                self.last_sample = now
                noise = NOISE[self.settings["simulationMode"]]
                self.cur = step(self.cur, SCENARIOS[self.scenario], self.rnd, noise, .22)
                self._record(now, self.cur)
            if now - self.last_save > 60:
                self.last_save = now
                self.save()

    def _stage(self):
        t, acc = self.pur["t"], 0
        for i, st in enumerate(STAGES):
            if t < acc + st[3]:
                return i, (t - acc) / st[3]
            acc += st[3]
        return len(STAGES) - 1, 1.0

    def _purify(self, now, dt):
        p = self.pur
        if p["running"]:
            p["t"] = min(TOTAL, p["t"] + dt)
            f = p["t"] / TOTAL
            e = f * f * (3 - 2 * f)
            b, tg = p["before"], p["target"]
            p["after"] = {k: round(b[k] + (tg[k] - b[k]) * e, 2) for k in PARAMS}
            p["tank_raw"] = max(0.0, p["tank_raw"] - 12 * dt / TOTAL)
            p["tank_clean"] = min(100.0, p["tank_clean"] + 12 * dt / TOTAL)
            p["trend"].append(dict(ts=int(now), before=score(b, self.settings), after=score(p["after"], self.settings)))
            del p["trend"][:-90]
            if p["t"] >= TOTAL:
                p.update(running=False, done=True, runs=p["runs"] + 1, filter=max(5.0, p["filter"] - 3))
                self.last_pur_end = now
                self._add(now, "system", "INFO", "Purification cycle completed - treated water ready.", True)
        else:
            p["tank_raw"] = min(80.0, p["tank_raw"] + .25 * dt)
            p["tank_clean"] = max(5.0, p["tank_clean"] - .03 * dt)

    def _start(self, now, auto=False):
        p = self.pur
        if p["emergency"]:
            return dict(error='Emergency shutdown is active. Press "Reset Stages" to clear it first.')
        if p["running"]:
            return dict(msg="Purification is already running.")
        if p["done"] or p["t"] <= 0:
            b = dict(self.cur)
            p.update(before=b, after=dict(b), t=0.0, done=False,
                     target=dict(ph=7.2 + (b["ph"] - 7.2) * .05, turb=min(b["turb"], .4),
                                 tds=min(b["tds"], max(90, b["tds"] * .12)), temp=b["temp"]))
        p["running"] = True
        txt = "Purification started automatically (water not SAFE)." if auto else "Purification started."
        self._add(now, "system", "INFO", txt, True)
        return dict(msg=txt)

    # ---- commands (all return {msg} or {error})
    def simulate(self, key):
        if key not in SCENARIOS:
            return dict(error="Unknown scenario")
        with self.lock:
            self.scenario, self.monitoring, self.last_sample = key, True, 0
        return dict(msg="Scenario: %s - readings will transition gradually." % SCENARIOS[key]["name"])

    def set_monitoring(self, on):
        with self.lock:
            self.monitoring = bool(on)
        return dict(msg="Live monitoring started." if on else "Monitoring paused.")

    def purification(self, cmd, mode=None):
        with self.lock:
            p, now = self.pur, time.time()
            if cmd == "start":
                return self._start(now)
            if cmd == "stop":
                p["running"] = False
                return dict(msg="Purification paused.")
            if cmd == "reset":
                p.update(running=False, emergency=False, done=False, t=0.0, before=None, after=None, target=None, trend=[])
                return dict(msg="Purification stages reset.")
            if cmd == "emergency":
                p.update(running=False, emergency=True)
                self._add(now, "system", "INFO", "EMERGENCY SHUTDOWN activated by operator.", True)
                return dict(msg="Emergency shutdown activated - pump stopped.")
            if cmd == "mode" and mode in ("auto", "manual"):
                p["mode"] = mode
                return dict(msg="%s mode selected." % mode.capitalize())
        return dict(error="Unknown command")

    def alert_action(self, action, aid=None):
        with self.lock:
            now = time.time()
            for a in self.alerts:
                if not a["resolved"] and (action == "resolve_all" or a["id"] == aid):
                    self._resolve(a, now)
        return dict(msg="Alert resolved." if action == "resolve" else "All alerts resolved.")

    def set_settings(self, d):
        with self.lock:
            if d.get("reset"):
                self.settings = dict(DEFAULTS)
            else:
                n = dict(self.settings)
                try:
                    for k, v in d.items():
                        if k in CHOICES:
                            if v not in CHOICES[k]:
                                return dict(error="Invalid value for %s" % k)
                            n[k] = v
                        elif k in DEFAULTS:
                            n[k] = max(1, min(60, int(float(v)))) if k == "monitoringInterval" else float(v)
                except (TypeError, ValueError):
                    return dict(error="Please enter valid numbers for all thresholds.")
                for lo, hi, nm in (("phMin", "phMax", "pH"), ("turbidityWarn", "turbidityUnsafe", "Turbidity"),
                                   ("tdsWarn", "tdsUnsafe", "TDS"), ("tempMin", "tempMax", "Temperature")):
                    if n[lo] >= n[hi]:
                        return dict(error="%s: the lower limit must be smaller than the upper limit." % nm)
                self.settings = n
            self._record(time.time(), self.cur, store=False)
            self.save()
        return dict(msg="Settings restored to defaults." if d.get("reset") else "Settings saved.")

    def reset_session(self):
        with self.lock:
            self.alerts, self.scenario = [], "safe"
            self.cur = {k: SCENARIOS["safe"][k] for k in PARAMS}
            self.pur.update(running=False, emergency=False, done=False, t=0.0, before=None, after=None, target=None, trend=[])
            self._record(time.time(), self.cur, store=False)
            self.recent = [dict(self.last)]
        return dict(msg="Session reset - Safe Water scenario restored.")

    def seed(self):
        with self.lock:
            self._seed()
            self.last_hist = self.hist[-1]["ts"]
        return dict(msg="Generated 7 days of demo history.")

    def wipe(self):
        with self.lock:
            self.settings, self.hist, self.alerts = dict(DEFAULTS), [], []
            self.scenario, self.cur, self.last_hist = "safe", {k: SCENARIOS["safe"][k] for k in PARAMS}, 0
            self.pur = self._new_pur()
            self.recent = []
            self._record(time.time(), self.cur)
            self.save()
        return dict(msg="All local data cleared.")

    # ---- views
    def _hist_all(self, hours):
        cut = time.time() - hours * 3600
        out = [e for e in self.hist if e["ts"] >= cut]
        lt = out[-1]["ts"] if out else 0
        out += [{k: v for k, v in e.items() if k != "st"} for e in self.recent if e["ts"] > lt and e["ts"] >= cut]
        return out

    def history(self, hours):
        with self.lock:
            out = self._hist_all(max(.1, min(720, hours)))
        if len(out) > 1500:
            out = out[::int(math.ceil(len(out) / 1500))]
        return out

    def export_csv(self):
        with self.lock:
            rows = self._hist_all(720)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Date", "Time", "pH", "Turbidity_NTU", "TDS_ppm", "Temperature_C", "Status", "Score", "Purification_Running", "Scenario"])
        for e in rows:
            lt = time.localtime(e["ts"])
            w.writerow([time.strftime("%Y-%m-%d", lt), time.strftime("%H:%M:%S", lt), e["ph"], e["turb"], e["tds"],
                        e["temp"], e["status"], e.get("score", ""), "Yes" if e.get("pur") else "No", e.get("scenario", "")])
        return buf.getvalue()

    def gateway(self):
        return dict(status="ok", service="AquaGuard mock IoT gateway", sensors="4/4 online (simulated)",
                    monitoring=self.monitoring, uptime_s=int(time.time() - self.t0), stored_samples=len(self.hist),
                    server_time=time.strftime("%Y-%m-%d %H:%M:%S"))

    def get_settings(self):
        return self.settings

    def _pur_view(self):
        p = self.pur
        idx, frac = self._stage()
        stages = []
        for i, (n, ic, d, sec) in enumerate(STAGES):
            if p["done"] or (p["t"] > 0 and i < idx):
                state, pct = "done", 100
            elif p["t"] > 0 and i == idx:
                state, pct = ("active" if p["running"] else "paused"), int(frac * 100)
            else:
                state, pct = "pending", 0
            stages.append(dict(name=n, icon=ic, desc=d, state=state, pct=pct))
        pct = int(round(100 * p["t"] / TOTAL))
        if p["emergency"]:
            label, hint = "EMERGENCY SHUTDOWN - pipeline halted", "Machine stopped. Ask the operator to reset it."
        elif p["running"]:
            label, hint = "Stage %d/%d - %s (%d%%)" % (idx + 1, len(STAGES), STAGES[idx][0], pct), "Machine is cleaning the water. Please wait."
        elif p["done"]:
            label, hint = "Purification complete - treated water ready", "Water has been treated. Boil it if unsure."
        elif p["t"] > 0:
            label, hint = "Paused at %d%%" % pct, "Machine paused. Press Start to continue."
        else:
            label, hint = "Pipeline idle", 'Press "Start Purification" on the Purification page to clean the water.'
        b = p["before"] or dict(self.cur)
        a = p["after"] if p["before"] else None
        improve, note = [], "Start purification to simulate parameter improvement across the pipeline."
        if a:
            def red(k):
                return int(max(0, min(100, (b[k] - a[k]) / b[k] * 100))) if b[k] > 0 else 0
            db, da = abs(b["ph"] - 7.2), abs(a["ph"] - 7.2)
            php = 100 if db < .05 else int(max(0, min(100, (db - da) / db * 100)))
            gain = score(a, self.settings) - score(b, self.settings)
            improve = [dict(label="Turbidity reduction", pct=red("turb"), txt="%d%%" % red("turb")),
                       dict(label="TDS reduction", pct=red("tds"), txt="%d%%" % red("tds")),
                       dict(label="pH correction", pct=php, txt="%d%%" % php),
                       dict(label="Quality score gain", pct=max(0, min(100, gain)), txt="%+d pts" % gain)]
            note = "Simulated improvement based on the raw-water snapshot taken when the run started."
        health_pct = int(p["filter"])
        return dict(
            running=p["running"], done=p["done"], emergency=p["emergency"], mode=p["mode"], progress=pct, label=label,
            hint=hint, stages=stages, before=b, before_status=overall(evaluate(b, self.settings)),
            after=a, after_status=overall(evaluate(a, self.settings)) if a else None, improve=improve, note=note,
            pump="Shutdown" if p["emergency"] else "Running" if p["running"] else "Idle",
            filter="Active - " + STAGES[idx][0] if p["running"] and idx < 3 else "Standby",
            disinfection="Active" if p["running"] and idx == 3 else "Completed" if p["done"] else "Standby",
            tank_raw=round(p["tank_raw"]), tank_clean=round(p["tank_clean"]), filter_life=health_pct, runs=p["runs"],
            trend=p["trend"])

    def _health(self):
        p = self.pur
        active = sum(1 for a in self.alerts if not a["resolved"] and a["sev"] != "INFO")
        vals = [100, 100, 40 if p["emergency"] else 100, p["filter"], min(100, p["tank_raw"] * 1.25), 100 - min(50, active * 8)]
        grade = lambda v: "good" if v >= 70 else "warn" if v >= 40 else "bad"
        up = int(time.time() - self.t0)
        tiles = [
            dict(label="Sensors", value="4 / 4 online", ok="good"),
            dict(label="IoT Gateway", value="Online", ok="good"),
            dict(label="Pump", value="Shutdown" if p["emergency"] else "Running" if p["running"] else "Idle",
                 ok="bad" if p["emergency"] else "good"),
            dict(label="Filter Life", value="%d%%" % p["filter"], ok=grade(p["filter"])),
            dict(label="Raw-Water Tank", value="%d%%" % p["tank_raw"], ok=grade(p["tank_raw"] * 1.25)),
            dict(label="Clean-Water Tank", value="%d%%" % p["tank_clean"], ok="good"),
            dict(label="Active Alerts", value=str(active), ok="good" if not active else "warn"),
            dict(label="Gateway Uptime", value="%dm %02ds" % (up // 60, up % 60), ok="good"),
        ]
        return dict(value=int(round(sum(vals) / len(vals))), tiles=tiles)

    def _sources(self):
        out = []
        for sid, name, typ, x, y, fn in SOURCES:
            v = {k: round(val, 2) for k, val in fn(self.cur).items()}
            st = evaluate(v, self.settings)
            out.append(dict(id=sid, name=name, type=typ, x=x, y=y, ph=v["ph"], turb=round(v["turb"], 1),
                            tds=int(v["tds"]), temp=round(v["temp"], 1), status=overall(st), score=score(v, self.settings, st)))
        return out

    def state(self):
        with self.lock:
            return dict(now=int(time.time()), settings=self.settings, monitoring=self.monitoring,
                        scenario=dict(key=self.scenario, name=SCENARIOS[self.scenario]["name"]),
                        reading=self.last, recent=self.recent[-40:], alerts=self.alerts[:100], pur=self._pur_view(),
                        health=self._health(), sources=self._sources())
