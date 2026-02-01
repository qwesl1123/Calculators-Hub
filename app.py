from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config["SECRET_KEY"] = "deathroll-secret"
socketio = SocketIO(app, cors_allowed_origins="*")

pvp_queue = []
pvp_rooms = {}

# ---------------- Time calculator ----------------

SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "month": 30 * 86400,
    "year": 365 * 86400,
    "decade": 10 * 365 * 86400,
}

TIME_ORDER = ["decade", "year", "month", "day", "hour", "minute", "second"]


def time_convert(value, unit):
    total_seconds = value * SECONDS[unit]
    return {u: total_seconds / SECONDS[u] for u in TIME_ORDER}


# ---------------- Resolution calculator ----------------

def resolution_convert(w, h, scales):
    out = []
    for s in scales:
        out.append({
            "scale": s,
            "w": round(w * s),
            "h": round(h * s),
        })
    return out

# ---------------- Drive price calculator ----------------

def drive_price_calc(drives):
    """
    drives: list of (tb, price)
    returns: (results, cheapest)
    """
    results = []
    for tb, price in drives:
        dptb = price / tb
        results.append((tb, price, dptb))

    cheapest = min(results, key=lambda x: x[2])
    return results, cheapest

# ---------------- Darkmoon flavor text ----------------

# thresholds
CRIT_SUCCESS_THRESHOLD = 95
CRIT_FAILURE_THRESHOLD = 5

FLAVOR_TEXT = {
    "hostile": [
        "The cards turn against you. Fate is not merely unkind — it is hostile.",
        "Dark energies coil around the spread. The Faire offers no mercy.",
        "The deck recoils. Whatever you attempt, expect resistance.",
        "You were not simply unlucky. You were actively opposed.",
    ],
    "poor": [
        "The cards waver uneasily. Fortune does not favor you today.",
        "The spread is weak, uncertain, and unreliable.",
        "Luck is thin here. Proceed, but expect setbacks.",
        "The Darkmoon cards whisper doubt and hesitation.",
    ],
    "favorable": [
        "The cards align, though imperfectly. Fortune leans your way.",
        "A modest but usable fate reveals itself.",
        "The spread shows promise, if not certainty.",
        "Luck is present, but it demands effort.",
    ],
    "strong": [
        "The cards glow faintly. Fortune is firmly on your side.",
        "A strong alignment forms across the spread.",
        "The cards smile upon this outcome.",
        "Luck gathers, steady and reliable.",
    ],
    "overwhelming": [
        "The cards blaze with power. Fate bends willingly.",
        "This is no coincidence. Fortune has chosen you.",
        "Overwhelming fortune surges through the spread.",
        "The deck sings. Victory is inevitable.",
    ],
}

CRITICAL_TEXT = {
    "success": [
        "A perfect draw! The deck smiles upon you in full glory.",
        "Fate itself bends to your will.",
        "The cards blaze with overwhelming power — victory is assured!",
    ],
    "failure": [
        "A catastrophic spread! The cards conspire against you.",
        "Critical failure! Nothing goes your way.",
        "The deck frowns. Misfortune overwhelms all attempts.",
    ],
}

DECK_FLAVOR = {
    "Furies": [
        "Relentless wrath courses through the spread.",
        "The cards burn with barely restrained fury.",
        "Anger and retribution press heavily upon fate.",
    ],

    "Nightmares": [
        "Distorted visions coil through the cards.",
        "The spread reeks of dread and broken dreams.",
        "Unsettling omens seep from every draw.",
    ],

    "Deception": [
        "Illusions twist the truth beyond recognition.",
        "The cards conceal as much as they reveal.",
        "Nothing in this spread is as it appears.",
    ],

    "Vengeance": [
        "Old debts demand to be answered.",
        "The deck remembers every slight.",
        "Retribution waits patiently within the cards.",
    ],

    "Commendation": [
        "Recognition glimmers faintly within the spread.",
        "The cards acknowledge effort, if not triumph.",
        "Merit is noted, though rewards remain uncertain.",
    ],

    "Resurrection": [
        "Faded fortunes stir back toward life.",
        "What was lost may yet return altered.",
        "The deck hums with renewed possibility.",
    ],

    "War": [
        "The spread echoes with the din of battle.",
        "Victory and loss hang in fragile balance.",
        "The deck rumbles...",
    ],

    "Tragedy": [
        "Sorrow weighs heavily upon the cards.",
        "The spread speaks of loss long endured.",
        "Fate turns cruel and unyielding.",
    ],

    "Madness": [
        "Reason fractures beneath chaotic forces.",
        "The cards refuse orderly interpretation.",
        "Unstable energies warp the spread.",
    ],

    "Hopes": [
        "A fragile optimism lingers within the cards.",
        "Possibility flickers, uncertain but present.",
        "The spread suggests promise not yet realized.",
    ],

    "Fables": [
        "Ancient stories whisper through the draw.",
        "Lessons of old shape the present fate.",
        "Myth and meaning entwine within the cards.",
    ],

    "Dominion": [
        "Authority asserts itself across the spread.",
        "Power gathers, demanding command.",
        "The cards favor control and resolve.",
    ],

    "Judgment": [
        "Actions are weighed with impartial clarity.",
        "The cards offer no mercy, only truth.",
        "Consequences reveal themselves without bias.",
    ],
}

def darkmoon_flavor_from_chance(chance, deck):
    # ---------- Critical results override EVERYTHING ----------
    if chance >= CRIT_SUCCESS_THRESHOLD:
        return random.choice(CRITICAL_TEXT["success"])

    if chance <= CRIT_FAILURE_THRESHOLD:
        return random.choice(CRITICAL_TEXT["failure"])

    # ---------- Normal tier flavor ----------
    if chance < 25:
        tier = "hostile"
    elif chance < 50:
        tier = "poor"
    elif chance < 75:
        tier = "favorable"
    elif chance < 95:
        tier = "strong"
    else:
        tier = "overwhelming"

    base = random.choice(FLAVOR_TEXT[tier])

    # ---------- Deck overlay (non-critical only) ----------
    if deck in DECK_FLAVOR:
        overlay = random.choice(DECK_FLAVOR[deck])
        return f"{base} {overlay}"

    return base

# ---------------- Darkmoon luck calculator ----------------

import random

CARD_VALUES = {
    "Ace": 10,
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "10": 10,
    "Jack": -5,
    "Queen": -8,
    "King": -10,
}

DIFFICULTY = {
    "trivial": 20,
    "normal": 40,
    "epic": 70,
    "legendary": 100,
}

def darkmoon_draw_cards(n):
    """
    n: number of cards to draw
    returns: list of (card_name, value)
    """
    return random.choices(list(CARD_VALUES.items()), k=n)


def darkmoon_apply_deck(draws, deck):
    """
    draws: list of (card, value)
    deck: deck name (string)
    returns: modified luck score (float)
    """
    values = [v for _, v in draws]

    if deck == "Judgment":
        return sum(values)

    if deck == "Commendation":
        return sum(values) * 1.1

    if deck == "Hopes":
        return sum(values) + 5

    if deck == "Furies":
        return sum(v * 1.3 if v > 0 else v * 0.8 for v in values)

    if deck == "Vengeance":
        return sum(v * 1.4 if v > 0 else v * 1.2 for v in values)

    if deck == "War":
        return sum(v * random.uniform(0.5, 1.8) for v in values)

    if deck == "Nightmares":
        return sum(v * random.uniform(0.5, 1.1) for v in values)

    if deck == "Tragedy":
        return sum(v * 0.7 if v > 0 else v * 1.5 for v in values)

    if deck == "Resurrection":
        return sum(v if v > 0 else v * 0.3 for v in values)

    if deck == "Deception":
        avg = sum(values) / len(values)
        return avg * len(values)

    if deck == "Madness":
        return sum(v * random.uniform(0.3, 2.0) for v in values)

    if deck == "Fables":
        return sum(v * random.uniform(0.9, 1.3) for v in values)

    if deck == "Dominion":
        total = sum(values)
        return total * 1.5 if total > 0 else total * 1.3

    raise ValueError("Unknown deck")


def darkmoon_luck_calc(num_cards, deck, difficulty):
    """
    num_cards: int
    deck: string
    difficulty: string
    returns: dict with score, chance, cards
    """
    draws = darkmoon_draw_cards(num_cards)
    score = darkmoon_apply_deck(draws, deck)

    required = DIFFICULTY[difficulty]
    chance = max(0, min(100, int((score / required) * 100)))

    return {
        "score": int(score),
        "chance": chance,
        "cards": [card for card, _ in draws],
        "deck": deck,
        "difficulty": difficulty.capitalize(),
        "comment": darkmoon_flavor_from_chance(chance, deck),
    }


# ---------------- Routes ----------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/time", methods=["GET", "POST"])
def time_calc():
    results = None
    if request.method == "POST":
        value = float(request.form["value"])
        unit = request.form["unit"]
        results = time_convert(value, unit)
    return render_template("time.html", results=results)


@app.route("/resolution", methods=["GET", "POST"])
def resolution_calc():
    results = None
    if request.method == "POST":
        w = int(request.form["width"])
        h = int(request.form["height"])
        scales = [float(x) for x in request.form["scales"].split(",")]
        results = resolution_convert(w, h, scales)
    return render_template("resolution.html", results=results)


@app.route("/drives", methods=["GET", "POST"])
def drives_calc():
    results = None
    cheapest = None
    error = None

    if request.method == "POST":
        raw = request.form["drives"].strip().splitlines()
        drives = []

        try:
            for line in raw:
                tb, price = line.split(":")
                tb = float(tb)
                price = float(price)
                if tb <= 0 or price < 0:
                    raise ValueError
                drives.append((tb, price))

            results, cheapest = drive_price_calc(drives)

        except Exception:
            error = "Invalid format. Use one drive per line: TB:PRICE (e.g. 8:160)"

    return render_template(
        "drives.html",
        results=results,
        cheapest=cheapest,
        error=error
    )


@app.route("/darkmoon", methods=["GET", "POST"])
def darkmoon():
    result = None
    if request.method == "POST":
        result = darkmoon_luck_calc(
            int(request.form["cards"]),
            request.form["deck"],
            request.form["difficulty"],
        )
    return render_template("darkmoon.html", result=result)

@app.route("/deathroll")
def deathroll():
    return render_template("deathroll.html")

@app.route("/deathroll-pvp")
def deathroll_pvp():
    return render_template("deathroll_pvp.html")

@socketio.on("queue")
def handle_queue():
    sid = request.sid
    pvp_queue.append(sid)

    if len(pvp_queue) >= 2:
        p1 = pvp_queue.pop(0)
        p2 = pvp_queue.pop(0)

        room = f"room-{p1[:5]}-{p2[:5]}"
        pvp_rooms[room] = {
            "players": [p1, p2],
            "bet": {},
            "max": 1000,
            "turn": p1
        }

        join_room(room, sid=p1)
        join_room(room, sid=p2)

        emit("system", "Match found! Agree on a bet.", to=room)

@socketio.on("bet")
def handle_bet(amount):
    sid = request.sid

    for room, game in pvp_rooms.items():
        if sid in game["players"]:
            game["bet"][sid] = amount

            emit("system", f"Bet set: {amount}g", to=room)

            if len(set(game["bet"].values())) == 1 and len(game["bet"]) == 2:
                emit("system", "Bets locked. Type /roll 1000 to start.", to=room)
            return

@socketio.on("roll")
def handle_roll(max_roll):
    sid = request.sid

    for room, game in pvp_rooms.items():
        if sid != game["turn"]:
            return

        if max_roll != game["max"]:
            emit("system", "Invalid roll range.", to=sid)
            return

        roll = random.randint(1, max_roll)
        emit("chat", f"Player rolled {roll} (1–{max_roll})", to=room)

        if roll == 1:
            emit("system", f"Player loses the deathroll.", to=room)
            del pvp_rooms[room]
            return

        game["max"] = roll
        game["turn"] = next(p for p in game["players"] if p != sid)


if __name__ == "__main__":
    socketio.run(host="0.0.0.0", port=5000)
