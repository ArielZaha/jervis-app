"""What things ARE, and what naturally happens around them — the data the rest of Jervis reasons with.

ONTOLOGY: every kind of thing a picture or a request can mention ("palm tree", "storefront", "swimming pool") ->
its category, its semantic tags (wind_reactive, commercial, lightable, water_waves...), its usual real size, how
important it usually is in a view, and which finished asset builds it. Labels a vision model or a person uses
("coconut palm", "boutique", "plunge pool") are mapped onto these kinds.

BEHAVIOUR RULES: SCENE SEMANTICS -> CONTEXT -> RULES -> EFFECTS. A rule says when it applies (tags present, the time
of day, the weather, the wind, evidence in the picture) and what follows (open water rolls in waves; a shop at night
glows from inside; rain wets the ground). Every effect carries the reason it was chosen, so nothing is added for
spectacle and every choice can be explained. Adding a behaviour (snow on roofs, traffic on a night street) is adding
a rule here — no phrase-matching code elsewhere.

Pure Python: used by the vision layer (what it saw), the reconstruction planner, the scene editor and the tests."""
import re

# ---------- the ontology ----------
# size: (width, depth, height) in metres, typical; category as spatial.py knows them where it applies.
KINDS = {
    # buildings
    "house": dict(category="building", tags=("structure", "residential", "lightable_interior", "has_windows",
                  "static"), size=(11, 8.5, 6.5), asset="house", priority="high",
                  words="house|home|cottage|bungalow|dwelling|residence|farmhouse|cabin|chalet|townhouse"),
    "villa": dict(like="house", words="villa|mansion|luxury home|modern house|modern home", style="modern"),
    "building": dict(category="building", tags=("structure", "has_windows", "lightable_interior", "static"),
                     size=(16, 12, 14), asset="house", priority="high",
                     words="building|apartment|apartments|apartment block|office|offices|block of flats|tower|hotel|"
                           "facade|façade"),
    "shop": dict(category="building", tags=("structure", "commercial", "storefront", "has_windows",
                 "lightable_interior", "signage", "static"), size=(8, 9, 6), asset="storefront", priority="high",
                 words="shop|store|storefront|shopfront|shop front|boutique|restaurant|cafe|café|bakery|bar|pub|"
                       "market stall|stall|kiosk|diner|shopping center|shopping centre|mall|izakaya|eatery"),
    "garage": dict(category="building", tags=("structure", "static"), size=(3.6, 6.5, 2.7), asset="garage",
                   priority="medium", words="garage|carport"),
    "shed": dict(category="building", tags=("structure", "static"), size=(3, 2.5, 2.5), asset="garage",
                 priority="low", words="shed|hut|cabin shed|outbuilding"),
    # parts of buildings (they belong to a building; never placed alone)
    "window": dict(category="part", tags=("part_of_building", "glass", "lightable"), size=(1.4, 0.2, 1.5),
                   words="window|windows|glass wall|glazing|shop window|display window"),
    "door": dict(category="part", tags=("part_of_building", "openable"), size=(1.0, 0.1, 2.1),
                 words="door|doors|entrance|entry|front door|doorway|sliding door"),
    "balcony": dict(category="part", tags=("part_of_building",), size=(4, 1.5, 1.1), words="balcony|balconies|terrace"),
    "roof": dict(category="part", tags=("part_of_building",), size=(10, 8, 1.5), words="roof|rooftop|roofs"),
    "stairs": dict(category="part", tags=("part_of_building",), size=(1.5, 3, 1.5), words="stairs|staircase|steps"),
    "chimney": dict(category="part", tags=("part_of_building", "smoke_source"), size=(0.8, 0.8, 1.5),
                    words="chimney"),
    "awning": dict(category="part", tags=("part_of_building", "fabric"), size=(4, 1.2, 0.4), words="awning|canopy"),
    "sign": dict(category="part", tags=("part_of_building", "signage", "light_source_night"), size=(3, 0.2, 0.8),
                 words="sign|signboard|signage|shop sign|neon sign|billboard|banner sign|noren|lettering"),
    # water
    "swimming pool": dict(category="sunken", tags=("water", "water_calm", "reflective", "property",
                          "lightable"), size=(9, 4.5, 1.5), asset="pool", priority="high",
                          words="swimming pool|pool|infinity pool|lap pool|plunge pool"),
    "pond": dict(category="sunken", tags=("water", "water_still"), size=(5, 4, 0.8), asset="pond",
                 priority="medium", words="pond|koi pond|garden pond"),
    "fountain": dict(category="outdoor", tags=("water", "water_jet", "static"), size=(3, 3, 2), asset="fountain",
                     priority="medium", words="fountain|water jets|water feature"),
    "ocean": dict(category="ground", tags=("water", "water_waves", "large", "reflective"), size=(200, 200, 0),
                  asset="water", priority="high", words="ocean|sea|seawater|open water|surf|waves|bay"),
    "lake": dict(category="ground", tags=("water", "water_still", "large", "reflective"), size=(80, 80, 0),
                 asset="water", priority="high", words="lake|reservoir|lagoon"),
    "river": dict(category="ground", tags=("water", "water_flow"), size=(40, 6, 0), asset="river",
                  priority="high", words="river|stream|creek|brook|rapids"),
    "waterfall": dict(category="outdoor", tags=("water", "water_fall", "mist_possible"), size=(5, 3, 8),
                      asset="waterfall", priority="high", words="waterfall|falls|cascade"),
    # land
    "beach": dict(category="ground", tags=("terrain", "sand", "coastal"), size=(60, 30, 0), asset="shore",
                  priority="high", words="beach|shore|shoreline|sand|sandy beach|coast"),
    "lawn": dict(category="ground", tags=("terrain", "grass", "wind_subtle"), size=(30, 30, 0), asset="ground",
                 priority="medium", words="lawn|grass|grassland|meadow|field|yard|garden lawn"),
    "terrain": dict(category="ground", tags=("terrain",), size=(60, 60, 0), asset="ground", priority="medium",
                    words="terrain|ground|land|hillside|slope|dirt|soil"),
    "hill": dict(category="ground", tags=("terrain", "backdrop"), size=(80, 40, 15), asset="hills",
                 priority="low", words="hill|hills|mountain|mountains|ridge|cliff face|range"),
    "rock": dict(category="outdoor", tags=("static", "natural"), size=(1.5, 1.5, 1), asset="rock",
                 priority="low", words="rock|rocks|boulder|boulders|stone|stones|pebbles"),
    "island": dict(category="ground", tags=("terrain", "coastal"), size=(40, 40, 6), asset="island",
                   priority="high", words="island|islet|atoll"),
    # vegetation
    "palm tree": dict(category="outdoor", tags=("vegetation", "tree", "wind_reactive", "fronds"),
                      size=(6, 6, 8), asset="tree", kind_option="palm", priority="high",
                      words="palm tree|palm trees|palm|palms|coconut palm|coconut tree"),
    "pine tree": dict(category="outdoor", tags=("vegetation", "tree", "wind_reactive"), size=(5, 5, 10),
                      asset="tree", kind_option="pine", priority="medium",
                      words="pine|pine tree|fir|spruce|conifer|cypress|evergreen"),
    "tree": dict(category="outdoor", tags=("vegetation", "tree", "wind_reactive"), size=(6, 6, 7),
                 asset="tree", kind_option="oak", priority="medium",
                 words="tree|trees|oak|maple|birch|olive tree|deciduous tree|fern tree|tree fern"),
    "forest": dict(category="outdoor", tags=("vegetation", "wind_reactive", "many", "backdrop"),
                   size=(40, 20, 12), asset="forest", priority="medium",
                   words="forest|woods|woodland|jungle|treeline|tree line|rainforest|foliage"),
    "bush": dict(category="outdoor", tags=("vegetation", "wind_subtle"), size=(1.5, 1.5, 1.2), asset="bush",
                 priority="low", words="bush|bushes|shrub|shrubs|hedge|hedges|plants|plant|greenery|vegetation|"
                                       "flowers|flower bed|planter|shrubbery|undergrowth|ferns"),
    # vehicles
    "car": dict(category="outdoor", tags=("vehicle", "drivable", "parked_static"), size=(4.5, 1.85, 1.45),
                asset="car", priority="high", words="car|cars|sedan|suv|hatchback|automobile|vehicle|jeep|pickup|"
                                                      "pickup truck|convertible|coupe|taxi"),
    "truck": dict(like="car", size=(7, 2.5, 3), words="truck|lorry|van|bus"),
    "scooter": dict(category="outdoor", tags=("vehicle", "parked_static"), size=(1.8, 0.7, 1.1), asset="car",
                    priority="low", words="scooter|scooters|motorcycle|motorbike|moped|bicycle|bike"),
    # outdoor things
    "road": dict(category="path", tags=("surface", "asphalt", "street"), size=(40, 8, 0), asset="road",
                 priority="high", words="road|street|asphalt|highway|lane|crossing|intersection"),
    "sidewalk": dict(category="path", tags=("surface", "paving"), size=(40, 3, 0.15), asset="road",
                     priority="medium", words="sidewalk|pavement|footpath|kerb|curb"),
    "path": dict(category="path", tags=("surface", "paving"), size=(10, 1.2, 0), asset="walkway",
                 priority="medium", words="path|walkway|pathway|footpath|stepping stones|trail|driveway|deck|patio"),
    "fence": dict(category="outdoor", tags=("static",), size=(6, 0.2, 1.2), asset="fence", priority="low",
                  words="fence|railing|railings|wall fence|balustrade"),
    "gate": dict(category="outdoor", tags=("static", "openable"), size=(3.6, 0.3, 1.5), asset="gate",
                 priority="low", words="gate|gates"),
    "street lamp": dict(category="outdoor", tags=("light_source", "light_source_night", "static"),
                        size=(0.4, 0.4, 4.5), asset="street_lamp", priority="medium",
                        words="street lamp|street light|streetlight|lamp post|lamppost|light pole|wall lamp|"
                              "outdoor light|garden light"),
    "lantern": dict(category="outdoor", tags=("light_source", "light_source_night", "hanging"), size=(0.4, 0.4, 0.6),
                    asset="lantern", priority="low", words="lantern|lanterns|paper lantern|string lights|fairy lights"),
    "umbrella": dict(category="outdoor", tags=("fabric", "static"), size=(2.5, 2.5, 2.5), asset="parasol",
                     priority="low", words="umbrella|umbrellas|parasol|parasols|sunshade"),
    "sun lounger": dict(category="furniture", tags=("static",), size=(2, 0.7, 0.4), asset="lounger",
                        priority="low", words="sun lounger|lounger|loungers|sunbed|deck chair|lounge chair|daybed"),
    "bench": dict(category="outdoor", tags=("static",), size=(1.8, 0.6, 0.8), asset="bench", priority="low",
                  words="bench|benches"),
    "flag": dict(category="outdoor", tags=("wind_reactive", "cloth"), size=(1.5, 0.1, 6), asset="flag",
                 priority="low", words="flag|flags|banner|pennant"),
    "campfire": dict(category="outdoor", tags=("fire", "light_source"), size=(1.2, 1.2, 0.8), asset="fire",
                     priority="medium", words="campfire|bonfire|fire pit|firepit|fire"),
    "cart": dict(category="outdoor", tags=("static",), size=(1.6, 0.9, 1), asset="crate", priority="low",
                 words="cart|wagon|wheelbarrow|crate|crates|barrel|barrels|basket|baskets|produce display"),
    # interiors
    "room": dict(category="building", tags=("interior", "structure", "lightable_interior"), size=(6, 5, 2.8),
                 asset="room", priority="high", words="room|living room|bedroom|kitchen|interior|lounge|office room|"
                                                      "dining room|hall|studio"),
    "sofa": dict(category="furniture", tags=("furniture", "fabric"), size=(2.2, 0.9, 0.85), asset="sofa",
                 priority="high", words="sofa|sofas|couch|couches|sectional|loveseat"),
    "armchair": dict(category="furniture", tags=("furniture", "fabric"), size=(0.9, 0.9, 0.9), asset="armchair",
                     priority="medium", words="armchair|armchairs|lounge chair|easy chair|beanbag|pouf"),
    "coffee table": dict(category="furniture", tags=("furniture",), size=(1.2, 0.6, 0.42), asset="coffee_table",
                         priority="medium", words="coffee table|low table|side table|end table"),
    "table": dict(category="furniture", tags=("furniture",), size=(1.6, 0.9, 0.75), asset="table",
                  priority="medium", words="table|tables|dining table|desk|counter|bar counter|workbench"),
    "chair": dict(category="furniture", tags=("furniture",), size=(0.5, 0.5, 0.9), asset="chair",
                  priority="low", words="chair|chairs|stool|stools|dining chair"),
    "tv": dict(category="furniture", tags=("furniture", "screen"), size=(1.3, 0.1, 0.75), asset="tv",
               priority="low", words="tv|television|screen|monitor"),
    "shelf": dict(category="furniture", tags=("furniture",), size=(1.2, 0.35, 1.8), asset="shelf",
                  priority="low", words="shelf|shelves|bookshelf|bookcase|cabinet|cupboard|sideboard|tv stand|"
                                        "dresser|wardrobe"),
    "rug": dict(category="furniture", tags=("furniture", "fabric", "flat"), size=(2.4, 1.7, 0.02), asset="rug",
                priority="low", words="rug|carpet|mat"),
    "floor lamp": dict(category="furniture", tags=("furniture", "light_source"), size=(0.4, 0.4, 1.6),
                       asset="floor_lamp", priority="low", words="floor lamp|lamp|table lamp|pendant|ceiling light|"
                                                                  "chandelier|light fixture"),
    "potted plant": dict(category="furniture", tags=("vegetation", "furniture"), size=(0.6, 0.6, 1.2),
                         asset="potted_plant", priority="low",
                         words="potted plant|plant pot|houseplant|indoor plant|pot plant|vase"),
    "bed": dict(category="furniture", tags=("furniture", "fabric"), size=(2.1, 1.6, 0.6), asset="table",
                priority="medium", words="bed|beds"),
    "curtain": dict(category="part", tags=("part_of_building", "fabric", "wind_subtle"), size=(1.5, 0.1, 2.4),
                    words="curtain|curtains|drapes|blinds|noren curtain"),
    "fireplace": dict(category="furniture", tags=("fire", "light_source"), size=(1.5, 0.6, 1.2),
                      asset="fireplace", priority="medium", words="fireplace|hearth|stove|wood stove"),
    # sky and weather (environment, not objects)
    "sky": dict(category="sky", tags=("environment",), words="sky|skies|clouds sky|sunset sky"),
    "cloud": dict(category="sky", tags=("environment", "drifts"), words="cloud|clouds"),
    "person": dict(category="ignore", tags=("ignore",), words="person|people|man|woman|child|pedestrian|crowd|"
                                                               "girl|boy|tourist|customer|figure"),
}
for _k, _v in list(KINDS.items()):   # "like": inherit, then override
    if "like" in _v:
        KINDS[_k] = {**{k: v for k, v in KINDS[_v["like"]].items() if k != "words"}, **_v}

PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}

_SYNONYMS = sorted(((w.strip(), kind) for kind, spec in KINDS.items() for w in spec.get("words", "").split("|")
                    if w.strip()), key=lambda p: -len(p[0]))


def _singular(word: str) -> str:
    w = word.lower().strip()
    for suffix, repl in (("ies", "y"), ("ves", "f"), ("ches", "ch"), ("shes", "sh"), ("sses", "ss"), ("s", "")):
        if w.endswith(suffix) and len(w) > len(suffix) + 2 and not w.endswith(("ss", "us", "is")):
            return w[: -len(suffix)] + repl
    return w


def canonical(label: str):
    """The ontology kind a free label means ("coconut palms" -> "palm tree", "boutique" -> "shop"), or None. The
    longest matching phrase wins ("palm tree" before "tree"; "street lamp" before "street")."""
    text = " " + re.sub(r"[^a-z0-9 ]+", " ", str(label or "").lower()) + " "
    text = re.sub(r"\s+", " ", text)
    singular = " " + " ".join(_singular(w) for w in text.split()) + " "
    for phrase, kind in _SYNONYMS:
        p = f" {phrase} "
        if p in text or p in singular:
            return kind
    return None


def spec(kind: str) -> dict:
    return KINDS.get(kind) or {}


def tags(kind: str) -> set:
    return set(spec(kind).get("tags", ()))


def category(kind: str) -> str:
    return spec(kind).get("category", "object")


def typical_size(kind: str) -> tuple:
    return tuple(spec(kind).get("size") or (1.0, 1.0, 1.0))


def priority(kind: str, area_share: float = 0.0, depth: str = "midground") -> str:
    """How much effort a thing deserves in THIS view: its usual importance, raised when it fills much of the picture
    or stands in the foreground, lowered when it's a speck in the distance."""
    base = PRIORITY_RANK.get(spec(kind).get("priority", "low"), 1)
    if area_share > 0.12 or (depth == "foreground" and area_share > 0.04):
        base += 1
    elif area_share < 0.004 and depth == "background":
        base -= 1
    return {4: "high", 3: "high", 2: "medium"}.get(base, "low")


# ---------- context, rules, effects ----------

TIMES = ("sunrise", "morning", "day", "afternoon", "golden hour", "sunset", "dusk", "night")
DARK_TIMES = ("dusk", "night")
_TIME_WORDS = {"midday": "day", "noon": "day", "daytime": "day", "daylight": "day", "evening": "dusk",
               "twilight": "dusk", "blue hour": "dusk", "midnight": "night", "nighttime": "night", "dawn": "sunrise",
               "early morning": "morning", "late afternoon": "golden hour"}


def normal_time(value: str) -> str:
    v = str(value or "").strip().lower()
    v = _TIME_WORDS.get(v, v)
    return v if v in TIMES else "day"


def context_of(things: list, environment: dict) -> dict:
    """What a scene is, as rules read it: its things by kind and by tag, and its time, weather, wind, atmosphere
    and setting. `things`: [{"name", "kind"}] (from a picture or the live scene)."""
    by_kind, by_tag = {}, {}
    for t in things or []:
        kind = t.get("kind")
        if not kind:
            continue
        by_kind.setdefault(kind, []).append(t["name"])
        for tag in tags(kind):
            by_tag.setdefault(tag, []).append(t["name"])
    env = environment or {}
    return {"kinds": by_kind, "tags": by_tag, "time": normal_time(env.get("time_of_day") or env.get("time")),
            "weather": str(env.get("weather") or "clear").lower(), "wind": str(env.get("wind") or "none").lower(),
            "atmosphere": str(env.get("atmosphere") or "clear").lower(),
            "setting": str(env.get("setting") or "").lower(), "scene_type": str(env.get("scene_type") or "").lower(),
            "evidence": env.get("evidence") or {}}


def _match(cond: dict, ctx: dict) -> bool:
    for key, want in cond.items():
        if key == "tag" and not ctx["tags"].get(want):
            return False
        if key == "any_tag" and not any(ctx["tags"].get(t) for t in want):
            return False
        if key == "kind" and not ctx["kinds"].get(want):
            return False
        if key == "no_tag" and ctx["tags"].get(want):
            return False
        if key in ("time", "weather", "wind", "atmosphere", "setting", "scene_type"):
            values = want if isinstance(want, (list, tuple)) else [want]
            if ctx[key] not in values:
                return False
        if key == "not_time" and ctx["time"] in want:
            return False
        if key == "evidence" and not all(ctx["evidence"].get(k) == v for k, v in want.items()):
            return False
    return True


# Each rule: when (all must hold), do (effects), why (said to the user). Effects name a target tag (whose things they
# act on) and parameters; the planner turns them into kit calls. Strengths are deliberately modest: subtle unless the
# context says otherwise.
RULES = [
    dict(id="ocean_waves", when={"tag": "water_waves"}, why="open water rolls in waves",
         do=[dict(effect="water", target="water_waves", mode="waves")]),
    dict(id="lake_surface", when={"tag": "water_still"}, why="still water stirs only slightly",
         do=[dict(effect="water", target="water_still", mode="still")]),
    dict(id="pool_ripples", when={"tag": "water_calm"}, why="a pool's water ripples gently",
         do=[dict(effect="water", target="water_calm", mode="ripples")]),
    dict(id="river_flow", when={"tag": "water_flow"}, why="a river flows downstream",
         do=[dict(effect="water", target="water_flow", mode="flow")]),
    dict(id="waterfall_falls", when={"tag": "water_fall"}, why="a waterfall's water falls",
         do=[dict(effect="water", target="water_fall", mode="falls")]),
    dict(id="waterfall_mist", when={"tag": "water_fall", "not_time": ("night",)},
         why="spray rises where a waterfall lands", do=[dict(effect="mist", target="water_fall", density=0.3)]),
    dict(id="trees_in_wind", when={"tag": "wind_reactive", "wind": ("light", "strong")},
         why="the wind moves the trees", do=[dict(effect="sway", target="wind_reactive")]),
    dict(id="coastal_breeze", when={"tag": "wind_reactive", "setting": ("coastal",), "wind": ("none",)},
         why="a sea breeze stirs palms by the shore", do=[dict(effect="sway", target="fronds", strength=0.5)]),
    dict(id="flags_flutter", when={"tag": "cloth"}, why="a flag flutters", do=[dict(effect="flutter", target="cloth")]),
    dict(id="fire_burns", when={"tag": "fire"}, why="flames flicker and light their surroundings",
         do=[dict(effect="fire", target="fire")]),
    dict(id="shop_lit_at_night", when={"tag": "commercial", "time": DARK_TIMES},
         why="a shop that's open after dark is lit from inside, its signs too",
         do=[dict(effect="interior_glow", target="commercial", level=1.0, share=0.9),
             dict(effect="sign_glow", target="signage")]),
    dict(id="homes_lit_at_night", when={"tag": "residential", "time": DARK_TIMES},
         why="some rooms of a home are lit after dark",
         do=[dict(effect="interior_glow", target="residential", level=0.7, share=0.5)]),
    dict(id="buildings_lit_at_night", when={"tag": "has_windows", "no_tag": "residential", "time": DARK_TIMES},
         why="a few windows glow after dark", do=[dict(effect="interior_glow", target="has_windows", level=0.6,
                                                      share=0.35)]),
    dict(id="pool_lit_at_night", when={"tag": "water_calm", "time": DARK_TIMES},
         why="pool lights come on after dark", do=[dict(effect="pool_lights", target="water_calm")]),
    dict(id="street_lights_at_night", when={"tag": "light_source_night", "time": DARK_TIMES},
         why="street lamps and lanterns are on after dark", do=[dict(effect="lamps_on", target="light_source_night")]),
    dict(id="streets_at_night", when={"tag": "street", "time": DARK_TIMES, "no_tag": "light_source_night"},
         why="a street at night has street lights", do=[dict(effect="add_street_lights", target="street")]),
    dict(id="interior_lights", when={"scene_type": "interior", "time": DARK_TIMES},
         why="a room at night is lit by its lamps", do=[dict(effect="lamps_on", target="light_source")]),
    dict(id="rain", when={"weather": ("rain", "storm")}, why="rain falls and wets every surface",
         do=[dict(effect="rain"), dict(effect="wet")]),
    dict(id="storm", when={"weather": "storm"}, why="a storm brings dark cloud, strong wind and rough water",
         do=[dict(effect="clouds", cover=0.9), dict(effect="sway", target="wind_reactive", strength=2.0),
             dict(effect="water", target="water_waves", mode="waves", strength=2.0)]),
    dict(id="snow", when={"weather": "snow"}, why="snow falls and settles", do=[dict(effect="snow")]),
    dict(id="fog", when={"atmosphere": ("fog", "mist", "haze")}, why="the air is thick with fog",
         do=[dict(effect="fog")]),
    dict(id="cloudy", when={"weather": ("cloudy", "overcast")}, why="the sky is clouded over",
         do=[dict(effect="clouds", cover=0.7)]),
]


def behaviours(ctx: dict, rules=None) -> list:
    """The effects a scene calls for: [{"effect", "targets": [names], ..., "rule", "why"}] — each justified by its
    rule, none without a target where it needs one, and no effect twice on the same things."""
    out, seen = [], set()
    for rule in rules or RULES:
        if not _match(rule["when"], ctx):
            continue
        for eff in rule["do"]:
            targets = list(ctx["tags"].get(eff["target"], [])) if eff.get("target") else []
            if eff.get("target") and not targets and eff["effect"] not in ("add_street_lights",):
                continue
            key = (eff["effect"], tuple(sorted(targets)), eff.get("mode"))
            if key in seen:   # the same effect from two rules (waves, and a storm's waves): the stronger one stands
                prev = next(b for b in out if (b["effect"], tuple(sorted(b["targets"])), b.get("mode")) == key)
                if float(eff.get("strength", 1.0)) > float(prev.get("strength", 1.0)):
                    prev["strength"] = eff["strength"]
                    prev["why"] += f"; {rule['why']}"
                continue
            seen.add(key)
            out.append({**{k: v for k, v in eff.items() if k != "target"}, "targets": targets,
                        "rule": rule["id"], "why": rule["why"]})
    return out
