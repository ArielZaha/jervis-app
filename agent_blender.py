"""The agent's Blender adapter: act through the scripting bridge with Jervis's building kit (blender_kit.py), read
the real scene back as structured data, and verify checks against it — no screen reading, no mouse."""
import json
import math
import os
import re

import blender_assets
import blender_kit
import blender_motion
import blender_nature
import blender_places
import blender_props
import blender_world
import cinema
import environment
import paths
import scene_edit
import scene_state
import spatial
from agent_core import AppAdapter, AppGone
from agent_core import tidy as agent_tidy
from computer_use import BLENDER_DANGEROUS_CODE

_BUILDERS = re.compile(r"\b(?:box|cube|cylinder|cone|sphere|plane|ground|roof|torus|monkey|stairs|duplicate|blob|tube|"
                       r"lathe|extrude_shape|frame)\(\s*"
                       r"['\"]([^'\"]+)['\"]")
_FLOATING_OK = re.compile(r"\b(?:float\w*|fly\w*|flies|hover\w*|hang\w*|cloud\w*|bird\w*|sky|space|planet\w*|"
                          r"balloon\w*|star\w*|moon|sun|airplane|aeroplane|drone|ufo|levitat\w*|chandelier|ceiling)\b", re.I)
_SPOT = re.compile(r"\bat x=(-?[\d.]+), y=(-?[\d.]+)")
_HINT = re.compile(r"name its parts '([^']+?) \.\.\.'")
_TURN = re.compile(r"\bturned rotation=(-?\d+)")
_REPLACE_ASKED = re.compile(r"\b(?:replace|rebuild|redo|remake|instead|start (?:over|again)|from scratch)\b", re.I)
_INSIDE_OK = re.compile(r"\b(?:inside|into|within|through|in the middle of|under|beneath|underneath)\b", re.I)
_REFERENCED = re.compile(r"\b\w+\(\s*['\"]([^'\"{}]+)['\"]")
_SIZE_WORDS = re.compile(r"\d|\b(?:size|big|bigger|small|smaller|tall|taller|short|wide|narrow|long|large|tiny|huge|"
                         r"giant|metres?|meters?|cm|feet|foot|inch\w*)\b", re.I)
_CLEARS = re.compile(r"\bclear_scene\s*\(")
_DELETES = re.compile(r"\bdelete\s*\(|\bobjects\.remove\s*\(|\bobjects\.unlink\s*\(")
_CLEAR_ASKED = re.compile(r"\b(?:clear|empty|wipe|reset|start (?:over|again|fresh)|new scene|from scratch|"
                          r"delete (?:everything|all)|remove (?:everything|all))\b", re.I)
_DELETE_ASKED = re.compile(r"\b(?:delete|remove|get rid of|erase|replace|instead of|clear|without)\b", re.I)
_DUPLICATE_NAME = re.compile(r"\bduplicate\(\s*['\"][^'\"]+['\"]\s*,\s*(?:name\s*=\s*)?['\"]([^'\"]+)['\"]")

INSTRUCTIONS = """App: Blender, driven by Python. A modeling kit is already loaded — use it (no bpy.ops, no imports; math is there).
`obj` below is an object's exact name. Every builder takes the name first, stands on `at`=(x, y, z) unless noted, and
accepts color=<material>, bevel=0.02 (rounded edges) and vary=0.2 (its own shade). Re-running a builder with the same
name replaces what this request made; it never overwrites something that was in the scene before.

FINISHED ASSETS — each is a complete, detailed model in ONE call. For any of these things, CALL THE ASSET; never
build one out of boxes, cylinders and spheres (that is a blockout, not a model):
  house(name, style='cottage'|'brick'|'modern'|'farmhouse'|'cabin', floors=1, width, depth, walls, roof_color, trim,
        door_color, roof='gable'|'hip'|'flat', window_scale=1.0, porch, chimney, shutters, path=True, rotation=0)
  tree(name, kind='oak'|'pine'|'palm'|'birch', height, leaves='autumn leaves'|<colour>, seed)
  island(name, radius=15, height=4, trees=0, tree_kind='palm', water=True, rocks=True, seed)
  water(name, size=60, color)   rock(name, size=1, count=1, moss=False, seed)   bush(name, size=1, flowers=<colour>)
  fence(name, length=6, height=1, style='picket'|'rail', color, rotation=0)
  pool(name, length=8, width=4, depth=1.5, deck=True, ladder=True, water_color, tiles, rotation=0)  a sunken
        swimming pool: tiled basin, clear water, stone coping, paved deck, ladder. `at` = the middle of the water.
  pond(name, size=4, depth=0.6, rocks=True, reeds=True)  a natural garden pond with a bank, edge stones and reeds
  bench(name, length=1.6, style='park'|'garden', color, rotation=0)   a finished bench (seat facing -y)
  lounger(name, color, cushion, rotation=0)    a sun lounger with a raised back, cushion and wheels (foot toward -y)
  fountain(name, size=3, tiers=2, color)   a stone fountain: moulded basin, pedestal, bowls, water and a jet
  villa(name, floors=2, width=20, depth=11, wings=2, glass='most'|'some', cladding, walls, rotation=0)  a modern
        villa: floor slabs, glass walls, a terrace, balcony railings, a lit interior.
  storefront(name, width=8, depth=9, floors=2, style='traditional'|'modern', color, awning, sign_color, signs=1,
        lanterns=2, rotation=0)  ANY shop, café, bakery, restaurant, bar or store: display windows, glazed door, sign,
        awning or eaves, goods, a lit interior. Never model a shop from boxes.
  road(name, length=40, width=7, sidewalks=True, markings=True, rotation=0)  a street with kerbs and pavements
  shore(name, width=120, sand_depth=30)  a beach running into the sea (sand toward -y, waves beyond)
  ground(name, size=80, kind='lawn'|'wild grass'|'sand'|'forest floor'|'paving', hilly=0)   hills(name, distance, height)
  forest(name, width, depth, count, kind='mixed'|'pine'|'palm'|'tropical'|'shrubs'|'grass'|'flowers'|'ferns'|'rocks')
  Jervis builds the world round what you make by himself afterwards — its ground, planting, street, shore, sky, light
  and camera — so build only what the request names (a bakery is one storefront(), not a street of them).
  walkway(name, start, end, width=1.2, style='pavers'|'stones'|'gravel')  a path that really connects two things:
        walkway('Path', 'Villa', 'Pool') leaves the villa's front door, goes round whatever is in the way, ends at
        the pool. Never build a path out of loose boxes.
  They stand at `at` (default X, Y) — on the terrain under them if there is one — and name their parts
  '<name> Walls', '<name> Roof', '<name> Window Frames', '<name> Door', '<name> Trunk', '<name> Leaves'...
  scatter_on('Island Terrain', count, min_height=0.6) -> free spots on a terrain (trees, rocks, huts on an island).
  rebuild_asset(name, option=value, ...) builds an existing asset again with options changed (two floors, bigger
  windows, a pine instead of an oak).   save_file() / save_file('name') saves the .blend file (only when asked). Use the kit below for anything else, and to ADD to an asset (a mailbox by the
  house, a bench under the tree, a dock on the island).

WHERE THINGS GO — never work out coordinates for a relation yourself; the kit measures the real scene:
  s = spot_near(anchor, relation, size=(width, depth), what='swimming pool') -> (x, y, z) to use as `at`.
      relation: 'beside', 'near', 'in front of', 'behind', 'left of', 'right of', 'inside' (on its floor), 'on'.
      Always outside a building's footprint (except 'inside'), clear of everything else, its entrance kept free.
      s.rotation is 90 when the thing should turn so its long side runs along the anchor's side.
      pool('Pool', at=s, rotation=s.rotation)    box('Bench Seat', (1.5, 0.42, 0.05), at=(s[0], s[1], 0.45))
  place_near(obj, anchor, relation)  moves an existing thing (a whole group) there.
  footprint(obj) -> (x0, y0, x1, y1) the ground it covers.   entrance_of(building) -> (x, y, z) outside its door.
  A house's front (its door) faces -y unless it was rotated. Outdoor things (pools, trees, cars, paths, fountains)
  never stand inside a building; furniture for a room goes spot_near(house, 'inside', ...).
  Several things relative to each other: build the main thing first, then each thing at spot_near() of the thing
  it relates to, then the paths between them (walkway), then small props and plants.

MOTION, CAMERAS, LIGHT — times are SECONDS from the start of the timeline (sec(2.5) = the frame 2.5 s in). Use these,
never hand-written keyframes: they ease, keep groups whole, follow the ground, frame subjects by the real scene.
  timeline(seconds, fps_=None)     animate(obj, prop, [(seconds, value), ...], ease='smooth', loop=False)
      prop: 'location' (world x, y, z), 'rotation' (degrees), 'scale', 'visible', 'energy' (a light), 'color', 'lens'
      ease: smooth | linear | in | out | back | bounce | constant
  move_to(obj, to, start, end)  rise(obj, metres, start, end)  spin(obj, degrees=360, axis='z', start, end, loop)
  scale_to(obj, factor, start, end)  bounce(obj, height, times, start, end)  appear(obj, at)  disappear(obj, at)
  colour_to(obj, colour, start, end)  open_door(thing, degrees=95, start, end) / close_door(...)  (a real hinge)
  drive(obj, to, start_place=None, start=0, end=None)   along the ground round obstacles, facing the way it goes
  By themselves: animate_naturally(obj) (water, fire, flags, clouds...), wind(strength) (trees sway), sway(obj),
      animate_water(obj, 'waves'|'ripples'|'flow'|'falls'), drift(obj), flicker(obj), flutter(obj)
  Moving assets: fire(name, at, size)  smoke(name, at)  rain(name)  snow(name)  cloud(name, at, size)
      flag(name, at, height, size, color)  river(name, start, end, width)  waterfall(name, at, height, width)
  camera(name='Camera', subject, shot)   shot: establishing | wide | medium | close | overhead | low
  camera_move(name='Camera', move, subject, start, end, shot_from, shot_to, sweep, direction, to)
      move: push_in | pull_out | orbit | crane | reveal | pan | tilt | overhead | flyover | fly_through | follow | track
  cut_to(camera, at)    light(name, kind='point'|'spot'|'area'|'sun', at, energy, color (or kelvin), size, aim, on)
  sky(look, start, end)  look: day | sunrise | sunset | dusk | night | dramatic | overcast | day_to_night | night_to_day
  lighting('dramatic'|'studio', subject)   lights_on(thing, start, end) / lights_off(...)   interior_lights(building)
  pool_lights(pool)     A camera never goes inside a building; a light's energy is never negative.

SHAPES
  box(name, size=(x, y, z), at, color, bevel=0.02, rotation=0)      planks, slabs, walls, seats, panels
  cylinder(name, radius, height, at, color, axis='z')  axis='x'/'y' lays it down (a wheel)   cone(name, radius, height, at, color, radius_top=0)
  sphere(name, radius, at, color)   torus(name, radius, thickness, at, color)   plane(name, size, at, color)   stairs(...)
  blob(name, radius, at, color, irregularity=0.25, squash=(1, 1, 1), seed=0, flat_bottom=0, base=True, detail=3)
      organic lump: rocks (irregularity 0.35-0.45, flat_bottom 0.15, detail 4), foliage clusters and bushes (0.2-0.3,
      base=False centres it on `at`), clouds, snow. A different seed = a different shape.
  tube(name, points, radius, radius_end, color, sides=12)   a round tube along WORLD points, tapering: trunks, branches,
      curved legs, pipes, handles, horns, tails. Make the points with path().
  lathe(name, [(radius, height), ...], at, color)   a profile spun round: vases, pots, bottles, cups, columns,
      lamp bases, mushroom caps, a trunk's flared base. List the profile bottom to top; radius 0 closes it.
  extrude_shape(name, [(x, y), ...], height, at, color, axis='z')   any outline made solid: floor plans, gable walls,
      arched doors (with arc_points), signs, leaves, shelves. axis='y' stands it upright facing front.
  frame(name, width, height, depth, border, at, color, axis='y', bars=0)   upright frame standing on `at`:
      window/door frames (bars=1 = glazing bars), picture frames, gates. axis='x' for walls facing the side.
  roof(name, width, depth, height, at, color, overhang=0.4, thickness=0.14, gable_color=<walls' material>)
      a real gable roof (two slabs + gable walls). `at` = the centre of the walls' top; width/depth = the walls'.
SHAPING
  hollow(obj, thickness=0.2, open_top=True)    opening(wall, width, height, at, axis='y')  a hole through a wall,
  `at` = bottom centre of the hole on the wall's face    cut(obj, cutter)    densify(obj, cuts=2) before deforming a box
  taper(obj, amount)   bend(obj, amount, direction=(x, y))   twist(obj, degrees)   roughen(obj, strength, scale, seed)
  subdivide(obj, levels=2) soft rounded forms   bevel(obj, width)   smooth(obj)   solidify(obj, thickness)   mirror(obj, axis)
PLACING AND ORGANISING
  move(obj, to=(x, y, z)) / move(obj, by=(dx, dy, dz))   rotate(obj, degrees, axis='z')   scale(obj, factor)
  resize(obj, (x, y, z))   duplicate(obj, new_name, at=...)   place_on(obj, base)   delete(obj)   color(obj, material)
  top(obj) -> z of its top   bottom(obj)   size(obj)   bounds(obj)   get(name)
  assemble(name)   LAST, for anything made of parts: gathers this request's parts named '<name> ...' under one
      parent + collection, so it moves as one (or assemble(name, [part names])).
  clear_scene() ONLY if the user explicitly asks to start over.
NATURAL VARIATION (repeatable)
  r = rng(seed); r.uniform(a, b); r.choice(list)   vary(value, 0.2, r)
  path(start, end, bend=(x, y, z), points=6, wobble=0.05, seed)   a curving line of points for tube()
  points_on_sphere(center, radius, count, seed, upper=True)   points_in_circle(center, radius, count, seed, min_gap)
  ring_points(center, radius, count)   corners(x, y, width, depth, inset) -> the 4 leg spots under a rectangular top
CONSTRUCTION (the kit does the geometry — use these instead of working out leg and post positions yourself)
  legs_under(top, count=4, thickness=0.05, shape='round'|'square')   legs from the ground up to the underside of a
      seat, table top, bed, desk, cabinet — under its corners (3 = stool, 2 = wide bench ends). Build the top at its
      real height FIRST, then call it.
  supports(above, below, count=2, thickness=0.04)   posts from the top of `below` up to the underside of `above`:
      a backrest above a seat, shelves, a sign, a roof on posts (below=None: from the ground).
MATERIALS (color=...)
  Textured presets: bark, wood, dark wood, light wood, leaves, autumn leaves, grass, moss, stone, rock, brick,
  roof tiles, plaster, concrete, metal, steel, iron, gold, copper, glass, water, fabric, leather, ceramic, plastic,
  rubber, sand, dirt, snow. Plain colours (red, navy, '#rrggbb'...) when the user names a colour.
Space: metres; z is up, the ground is z = 0; x is left(-)/right(+); y is front(-)/back(+). The camera looks from the front.
PRESET FOR YOU: X, Y = where to build this request (already chosen: build around them), r = a random generator.

HOW TO MODEL WELL — what separates a modelled object from primitives stuck together:
- First think like a 3D artist: what is this thing really made of? Its main masses, then its secondary parts, then
  small details. Real proportions in metres (a door 0.9 x 2.1, a chair seat at 0.45, a table at 0.75, a tree 4-8 m).
- Organic things are never bare primitives: trunks, branches, limbs, stems and tails are tube()s along curving
  path()s that taper; foliage, rocks, bushes and clouds are blob()s in varied sizes and seeds; round crafted things
  (pots, vases, columns, bottles) are lathe()s.
- Hard-surface things (furniture, buildings, vehicles): proportioned parts, every box bevelled (0.01-0.03), the parts
  a real one has, and construction details: frames and sills round windows, a door with a frame and a knob, rails
  between chair legs, a chimney with a cap, a foundation under walls.
- Repeated natural parts are never identical: different seeds, sizes (r.uniform), positions and rotations.
- Every part gets a fitting material — textured presets for wood, stone, bark, leaves, tiles, plaster, metal, glass.
- Name parts '<Thing> <Part> N' and finish with assemble('<Thing>', [...]).

Rules for code:
- Only do what the request asks. NEVER clear the scene, delete or move existing objects unless the user asked for that.
- Build new things from NEW objects. Never turn an unrelated existing object (like Blender's default 'Cube') into part
  of something new. To change something that exists, use its exact name from the state with color()/move()/scale().
- Everything stands on the ground (z = 0) or rests on/attaches to another part. Nothing floats unless asked.
- Build around X, Y (preset) unless the request says where. When it relates the new thing to something ("beside the
  house", "behind the pool", "in front of it"), X, Y is already such a spot if the state says so; otherwise use
  spot_near(). Never place an outdoor thing by guessing numbers next to a building.
- Each step builds one part of the thing (it may have many objects, loops are fine).
- Never name your own variables after kit functions (top, size, color, box, path, get, scale...).
- When the user names a colour for something with a natural material, keep the material if its colour fits ("a red
  roof" = 'roof tiles', which are red; "a brown door" = 'wood'); otherwise use the plain colour.
- Several things in one request (a scene, "two trees"): one step per thing, each at its own spot with room around it,
  each with its own name prefix ('Tree 1 Trunk', 'Tree 2 Trunk', 'Bench Seat'), each ending with assemble('Tree 1').
- Keep objects by NAME (strings), not in variables: rebuilding replaces the object a variable pointed to.
- A request to CHANGE something ("make the leaves autumn coloured") never builds new things: if what it names isn't in
  the state, ask instead.
- To change many similar parts, loop in code (for o in list(bpy.data.objects): if o.name.startswith('Tree Leaves'):
  color(o.name, 'autumn leaves')) and check them with ONE count or color check, not one check per part.

Technique examples — ADAPT them (sizes, counts, positions, materials) to what is asked; don't copy blindly:
  A garden scene: house('House', style='cottage', at=(X, Y, 0)); tree('Tree 1', kind='oak', at=(X + 7, Y + 2, 0), seed=1);
    tree('Tree 2', kind='birch', at=(X - 7, Y + 3, 0), seed=2); bush('Bush 1', at=(X + 3, Y - 4.5, 0), flowers='pink');
    fence('Fence', length=14, at=(X, Y - 7, 0))
  Something with no finished asset is modelled with the kit. A custom tree shape (only if tree() can't do it):
    trunk_end = (X + 0.2, Y + 0.1, 2.6)
    tube('Tree Trunk', path((X, Y, 0), trunk_end, bend=(0.25, 0.1, 0), points=6, wobble=0.05, seed=4), radius=0.26, radius_end=0.12, color='bark', sides=14)
    lathe('Tree Root Flare', [(0.42, 0), (0.3, 0.12), (0.24, 0.35), (0, 0.4)], at=(X, Y, 0), color='bark')
    ends = [(trunk_end[0], trunk_end[1], trunk_end[2] + 0.7)]
    for i in range(5):
        a = math.radians(i * 72 + r.uniform(-20, 20)); t = r.uniform(0.55, 0.85)
        start = (X + 0.2 * t, Y + 0.1 * t, 2.6 * t); length = r.uniform(1.0, 1.5)
        end = (start[0] + math.cos(a) * length, start[1] + math.sin(a) * length, start[2] + r.uniform(0.7, 1.2))
        tube(f'Tree Branch {i + 1}', path(start, end, bend=(0, 0, 0.25), points=4, wobble=0.05, seed=i), radius=0.1, radius_end=0.035, color='bark')
        ends.append(end)
    for i, c in enumerate(ends):
        for j in range(4):
            p = (c[0] + r.uniform(-0.45, 0.45), c[1] + r.uniform(-0.45, 0.45), c[2] + r.uniform(-0.25, 0.45))
            blob(f'Tree Leaves {i * 4 + j + 1}', r.uniform(0.38, 0.62), at=p, base=False, irregularity=0.25, squash=(1, 1, 0.8), seed=20 + i * 4 + j, color='leaves', vary=0.25, detail=4)
    assemble('Tree')
  A shed or kiosk (no asset): foundation, hollow walls with real openings, a framed door, a roof.
    box('Shed Base', (2.6, 2.1, 0.15), at=(X, Y, 0), color='concrete', bevel=0.02)
    box('Shed Walls', (2.4, 1.9, 2.1), at=(X, Y, 0.15), color='wood', bevel=0.01); hollow('Shed Walls', 0.08, open_top=True)
    opening('Shed Walls', 0.85, 1.9, at=(X, Y - 0.95, 0.17)); frame('Shed Door Frame', 0.95, 1.95, depth=0.12, border=0.05, at=(X, Y - 0.95, 0.15), color='dark wood')
    roof('Shed Roof', 2.4, 1.9, 0.7, at=(X, Y, top('Shed Walls')), color='shingles', overhang=0.2, thickness=0.08, gable_color='wood')
  Chair (furniture: the seat at its real height first, then the kit puts legs and posts where they belong):
    box('Chair Seat', (0.46, 0.44, 0.04), at=(X, Y, 0.45), color='wood', bevel=0.012)
    legs_under('Chair Seat', count=4, thickness=0.045, shape='round')
    box('Chair Cushion', (0.4, 0.38, 0.05), at=(X, Y - 0.01, top('Chair Seat')), color='fabric', bevel=0.02); subdivide('Chair Cushion', 2)
    box('Chair Backrest', (0.44, 0.03, 0.32), at=(X, Y + 0.2, top('Chair Seat') + 0.12), color='wood', bevel=0.01)
    supports('Chair Backrest', 'Chair Seat', count=2, thickness=0.035)
  Bench / table: the same idea — box('Bench Seat', (1.5, 0.42, 0.05), at=(X, Y, 0.45), color='wood', bevel=0.01),
    legs_under('Bench Seat', count=4), a backrest board raised behind it + supports('Bench Backrest', 'Bench Seat');
    a table: box('Table Top', (1.6, 0.9, 0.05), at=(X, Y, 0.72), ...), legs_under('Table Top', shape='square').

Checks (verified against Blender's real scene after each step):
  {"type": "exists", "object": "House Roof"}                  {"type": "absent", "object": "Cube"}
  {"type": "color", "object": "House Roof", "color": "red"}    color families: red/orange/yellow/green/cyan/blue/purple/pink/brown/white/gray/black
  {"type": "above", "object": "House Roof", "other": "House Walls"}     its bottom is at/above the other's top
  {"type": "touching", "object": "Door", "other": "House Walls"}  attached / in contact (eyes on a head, a door in a wall)
  {"type": "on_top", "object": "Lamp", "other": "Table"}       resting on it (touching, overlapping in x/y)
  {"type": "count", "object": "Window", "min": 2}              objects whose name contains "Window"
  {"type": "size", "object": "Table", "min": 0.5, "max": 3}    its largest dimension in metres
  {"type": "near", "object": "Chair", "other": "Table", "max": 1}   the gap between them is at most `max` metres
  {"type": "beside", "object": "Pool", "other": "Villa"}      outside its footprint and close to it; likewise
      "in_front_of", "behind", "left_of", "right_of" (the anchor's own front), "outside", "inside"
  {"type": "connects", "object": "Path", "other": "Villa", "value": "Pool"}   a path running from one to the other
  {"type": "animated", "object": "Car"}   it really moves over the timeline
  {"type": "camera_frames", "object": "Camera", "other": "Villa"}   the camera keeps it framed, unblocked, throughout
  {"type": "light_on", "object": "Pool"}   its lights are on by the end ("light_off": off)
  {"type": "moves_to", "object": "Car", "other": "Gate"}   it ends up at the other thing
  {"type": "timeline", "min": 10}   the timeline is at least that many seconds
Use above / on_top / touching only between parts of the thing you are building (a roof on its walls, a lamp on its
table, eyes on a head). To relate a NEW thing to something already there ("next to the house", "in front of it"),
use beside / in_front_of / behind / near — never above/touching against an existing object.

Answer format example — request "a stone well":
{"understanding": "Build a round stone well with a little wooden roof.", "question": "",
 "steps": [
  {"title": "Build the stone ring", "code": "lathe('Well Wall', [(0.75, 0), (0.75, 0.8), (0.6, 0.8), (0.6, 0.1), (0, 0.1)], at=(X, Y, 0), color='stone', segments=24)\\nroughen('Well Wall', 0.015, 6, seed=2)\\nblob('Well Water', 0.58, at=(X, Y, 0.3), squash=(1, 1, 0.05), irregularity=0.02, color='water')",
   "checks": [{"type": "exists", "object": "Well Wall"}]},
  {"title": "Add the posts and roof", "code": "for i, x in enumerate([-0.65, 0.65]):\\n    box(f'Well Post {i + 1}', (0.1, 0.1, 1.6), at=(X + x, Y, 0.8), color='wood', bevel=0.01)\\nroof('Well Roof', 1.5, 1.0, 0.5, at=(X, Y, top('Well Post 1')), color='roof tiles', overhang=0.15, thickness=0.06, gable_color='wood')\\nassemble('Well')",
   "checks": [{"type": "above", "object": "Well Roof", "other": "Well Wall"}]}],
 "final_checks": [{"type": "exists", "object": "Well Wall"}, {"type": "exists", "object": "Well Roof"}]}"""

# Each object is remembered by Blender's session_uid as well as its name: rebuilding an asset ("bigger windows")
# keeps the old parts aside under other names while new parts take the old names, and "undo" must bring back the
# very same objects, not whatever now carries their names.
# ... and its parent inverse: Blender resets that whenever a parent is assigned, so a restore that merely set the
# parent again once threw a group's part 41 m away.
# ... and its animation ('__anim__': actions copied aside, drivers, constraints, modifiers, the timeline, the sky):
# undoing a failed step must also take back the keyframes it added.
_SNAPSHOT_CODE = ("import json\nsnap = {o.name: [list(o.location), list(o.rotation_euler), list(o.scale), "
                  "o.active_material.name if o.active_material else None, o.parent.name if o.parent else None, "
                  "o.session_uid, [list(r) for r in o.matrix_parent_inverse]] "
                  "for o in bpy.data.objects if o.users_collection}\n"
                  "if 'anim_snapshot' in globals():\n    snap['__anim__'] = anim_snapshot()\n"
                  "RESULT = json.dumps(snap)")


def _modelled(objs: list) -> list:
    """The parts the AI modelled itself — not a finished asset's (a house(), a tree()), nor terrain or water. Assets
    are modelled and checked once, by hand: a palm's roots go below the ground on purpose, coconuts hang in the air,
    an island's seabed is under water. The structure and quality heuristics are for the AI's own geometry."""
    return [o for o in objs if not o.get("asset") and o.get("kind") not in ("terrain", "water", "asset", "particle",
                                                                            "emitter", "cutter")
            and o.get("role") not in ("library", "cutter", "sky")]


_PRIMITIVE_KINDS = {"box", "cylinder", "cone", "sphere", "plane", "torus", "monkey"}
# Things that are naturally irregular: a bare cylinder + sphere is never an acceptable tree, rock or animal.
_ORGANIC = re.compile(r"\b(?:trees?|bush\w*|shrubs?|plants?|flowers?|rocks?|stones?|boulders?|pebbles?|mountains?|"
                      r"hills?|clouds?|mushrooms?|cact\w+|logs?|branch\w*|vines?|animals?|dogs?|cats?|birds?|fish|"
                      r"creatures?|snowm[ae]n|grass|forest|garden|hedges?|palms?|pines?|oaks?|leaves|fruits?|apples?|"
                      r"pumpkins?|trunks?|crystals?)\b", re.I)
# Things that are one piece: a single well-shaped part is right, not "too few parts".
_SINGLE_PIECE = re.compile(r"\b(?:rocks?|stones?|boulders?|pebbles?|balls?|spheres?|cubes?|boxe?s?|eggs?|coins?|"
                           r"rings?|clouds?|logs?|blobs?|blocks?|bricks?|planks?|crystals?|vases?|pots?|bottles?|"
                           r"columns?|pillars?|cups?|bowls?)\b", re.I)
# "add a door to the house": a part for something already there, not a whole new thing.
_ADDITION = re.compile(r"\b(?:to|on|onto|into|for|in front of|beside|next to)\s+(?:the|my|this|that|it|its)\b", re.I)
_NAMES_A_COLOUR = re.compile(r"\b(?:red|green|blue|yellow|orange|purple|pink|white|black|gr[ae]y|brown|cyan|navy|"
                             r"gold|silver|beige|teal|maroon)\b", re.I)


def _tips_over(made: list) -> str:
    """Would this stand up? What touches the ground must spread under the whole thing: a chair on two diagonal legs,
    a table on one corner post or a lamp with no base stands on (almost) nothing. "" when it's stable."""
    grounded = [o for o in made if o["min"][2] <= 0.05]
    if not grounded or len(made) < 3:
        return ""
    lo = [min(o["min"][i] for o in made) for i in range(2)]
    hi = [max(o["max"][i] for o in made) for i in range(2)]
    area = max(1e-6, (hi[0] - lo[0]) * (hi[1] - lo[1]))
    corners = []
    for o in grounded:
        corners += [(o["min"][0], o["min"][1]), (o["min"][0], o["max"][1]), (o["max"][0], o["min"][1]),
                    (o["max"][0], o["max"][1])]
    footprint = _hull_area(corners)
    center = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
    if footprint / area >= 0.2 and _inside_hull(center, corners):
        return ""
    names = ", ".join(f"'{o['name']}'" for o in grounded[:4])
    return (f"It would tip over: only {names} touch the ground, and they don't spread under the whole thing. Give it "
            "proper support the way a real one stands (e.g. four legs at the corners, a wide base or foot).")


def _words(name: str) -> set:
    return set(re.findall(r"[a-z]+", name.lower()))


_UNDERGROUND_OK = re.compile(r"\b(?:underground|basement|cellar|pit|hole|well|pool|pond|buried|sunken|trench|"
                             r"tunnel|mine|grave|foundation)\b", re.I)


def _anatomy(made: list, goal: str = "") -> list:
    """What common part names promise about how a thing is put together — legs stand on the ground under a seat or
    top, a backrest rises from the seat, a trunk stands on the ground under its foliage, a roof sits on its walls.
    General rules about parts, not answers for particular objects; a build that breaks them is malformed."""
    issues = []
    legs = [o for o in made if _words(o["name"]) & {"leg", "legs"}]
    tops = [o for o in made if _words(o["name"]) & {"seat", "top", "tabletop", "desktop", "surface"}
            and not _words(o["name"]) & {"leg", "legs", "cushion", "back"}]
    sunk = [] if _UNDERGROUND_OK.search(goal or "") else [o for o in made if o["min"][2] < -0.1
                                                           and o.get("kind") not in ("plane",)]
    if sunk:
        issues.append(f"{', '.join(repr(o['name']) for o in sunk[:4])} reach below the ground (z < 0): everything "
                      "stands on z = 0 or higher — builders stand on `at`, so give legs and bases at z = 0.")
    if legs and tops:
        lo = [min(t["min"][i] for t in tops) for i in range(2)]
        hi = [max(t["max"][i] for t in tops) for i in range(2)]
        pad = [0.15 * (hi[i] - lo[i]) + 0.05 for i in range(2)]
        outside = [o for o in legs if not all(lo[i] - pad[i] <= (o["min"][i] + o["max"][i]) / 2 <= hi[i] + pad[i]
                                              for i in range(2))]
        if outside:
            issues.append(f"{', '.join(repr(o['name']) for o in outside[:4])} aren't under the seat/top they should "
                          f"carry (it spans x {round(lo[0], 2)}..{round(hi[0], 2)}, y {round(lo[1], 2)}..{round(hi[1], 2)}): "
                          "put the legs near its corners, underneath it.")
    if legs:
        floating_legs = [o for o in legs if o["min"][2] > 0.05]
        if floating_legs and len(floating_legs) == len(legs):
            issues.append(f"The legs ({', '.join(repr(o['name']) for o in legs[:4])}) don't reach the ground: legs "
                          "stand on the ground (their `at` z = 0) and hold the seat or top up.")
        leg_top = max(o["max"][2] for o in legs)
        leg_height = leg_top - min(o["min"][2] for o in legs)
        for top in tops:
            if top["min"][2] < leg_top - 0.25 * leg_height:
                issues.append(f"'{top['name']}' is down at z={top['min'][2]} while the legs reach z={round(leg_top, 2)}: "
                              f"the seat/top must rest ON the legs — build it at z = top() of a leg, legs below it.")
                break
    backs = [o for o in made if _words(o["name"]) & {"back", "backrest"} and not _words(o["name"]) & {"leg", "legs"}]
    seats = [o for o in tops if "seat" in _words(o["name"])]
    if backs and seats:
        seat_top = max(o["max"][2] for o in seats)
        low_backs = [o for o in backs if o["max"][2] < seat_top + 0.1]
        if low_backs:
            issues.append(f"The backrest ({', '.join(repr(o['name']) for o in low_backs[:3])}) doesn't rise above "
                          "the seat: it stands up from the seat's back edge, carried by back posts.")
    trunks = [o for o in made if "trunk" in _words(o["name"])]
    crowns = [o for o in made if _words(o["name"]) & {"leaves", "leaf", "foliage", "crown", "canopy"}]
    if trunks:
        if all(o["min"][2] > 0.3 for o in trunks):
            issues.append("The trunk doesn't stand on the ground: a trunk starts at z = 0.")
        base = min(o["min"][2] for o in trunks)
        height = max(o["max"][2] for o in trunks) - base
        if crowns and min(o["max"][2] for o in crowns) < base + 0.4 * height:
            issues.append("Some foliage sits down near the foot of the trunk: leaves belong up in the crown, around "
                          "the branch ends and the top of the trunk.")
    roofs = [o for o in made if "roof" in _words(o["name"]) and not _words(o["name"]) & {"gables"}]
    walls = [o for o in made if _words(o["name"]) & {"wall", "walls"}]
    if roofs and walls and min(o["min"][2] for o in roofs) < max(o["max"][2] for o in walls) - 1.0:
        issues.append("The roof isn't on top of the walls: build it at z = top() of the walls.")
    return issues


def _thing_of(o: dict, by_name: dict) -> str:
    """Which thing a part belongs to: its assembly (parent) if it has one, else its name's first word."""
    seen = set()
    while o.get("parent") and o["parent"] in by_name and o["parent"] not in seen:
        seen.add(o["parent"])
        o = by_name[o["parent"]]
    return o["name"] if o.get("type") == "EMPTY" else o["name"].split()[0].lower()


def _things_inside_each_other(made: list, state: dict) -> str:
    """Separate things built in one request (a bench and a tree, two trees) that stand inside each other."""
    by_name = {o["name"]: o for o in state.get("objects", [])}
    pairs = []
    for i, a in enumerate(made):
        for b in made[i + 1:]:
            if _thing_of(a, by_name) == _thing_of(b, by_name):
                continue
            pen = [min(a["max"][k], b["max"][k]) - max(a["min"][k], b["min"][k]) for k in range(3)]
            if min(pen) > 0.1:
                pairs.append((a["name"], b["name"]))
                if len(pairs) >= 3:
                    break
        if len(pairs) >= 3:
            break
    if not pairs:
        return ""
    shown = "; ".join(f"'{a}' is inside '{b}'" for a, b in pairs)
    return (f"Separate things stand inside each other ({shown}). Give each thing its own spot with room around it "
            "(move every part of one of them together, e.g. its assembly with move(name, by=(dx, dy, 0))).")


def _hull(points: list) -> list:
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _hull_area(points: list) -> float:
    h = _hull(points)
    return abs(sum(h[i][0] * h[(i + 1) % len(h)][1] - h[(i + 1) % len(h)][0] * h[i][1] for i in range(len(h)))) / 2 \
        if len(h) >= 3 else 0.0


def _inside_hull(point, points: list) -> bool:
    h = _hull(points)
    if len(h) < 3:
        return False
    x, y = point
    return all((h[(i + 1) % len(h)][0] - h[i][0]) * (y - h[i][1]) - (h[(i + 1) % len(h)][1] - h[i][1]) * (x - h[i][0])
               >= -1e-9 for i in range(len(h)))


# Real-world sizes of common things (metres): which dimension to measure, and its usual range. The AI's numbers are
# sometimes off by a factor of 3 (a bench the size of a shoe); a uniform rescale fixes that without touching the design.
TYPICAL_SIZE = {   # thing: {dimension: (usual min, usual max)}; "width" = its longest side seen from above
    "park bench": {"height": (0.4, 1.1), "width": (1.2, 2.2)}, "bench": {"height": (0.4, 1.1), "width": (1.2, 2.2)},
    "chair": {"height": (0.8, 1.15), "width": (0.38, 0.75)}, "armchair": {"height": (0.75, 1.15), "width": (0.6, 1.0)},
    "stool": {"height": (0.45, 0.85)}, "dining table": {"height": (0.7, 0.8), "width": (1.0, 2.6)},
    "table": {"height": (0.65, 0.8), "width": (0.6, 2.6)}, "desk": {"height": (0.7, 0.8), "width": (1.0, 2.0)},
    "bed": {"width": (1.9, 2.3), "height": (0.4, 1.4)}, "sofa": {"width": (1.6, 2.6), "height": (0.7, 1.1)},
    "couch": {"width": (1.6, 2.6), "height": (0.7, 1.1)}, "bookshelf": {"height": (1.5, 2.2)},
    "wardrobe": {"height": (1.8, 2.3)}, "tree": {"height": (3.0, 15.0)}, "bush": {"height": (0.5, 2.5)},
    "house": {"height": (3.5, 12.0), "width": (4.0, 20.0)}, "cottage": {"height": (3.5, 9.0), "width": (4.0, 14.0)},
    "cabin": {"height": (3.0, 8.0), "width": (3.5, 12.0)}, "car": {"width": (3.5, 5.2), "height": (1.2, 2.0)},
    "truck": {"width": (5.0, 12.0), "height": (2.0, 4.0)}, "bicycle": {"width": (1.5, 1.9), "height": (0.9, 1.2)},
    "lamp post": {"height": (2.5, 6.0)}, "street lamp": {"height": (2.5, 6.0)}, "streetlight": {"height": (2.5, 6.0)},
    "streetlamp": {"height": (2.5, 6.0)}, "door": {"height": (1.9, 2.4)}, "snowman": {"height": (1.2, 2.2)},
    "boulder": {"width": (1.0, 4.0)}, "fence": {"height": (0.8, 2.0)}, "well": {"height": (1.5, 3.2)},
    "tent": {"height": (1.2, 3.0)}, "mailbox": {"height": (1.0, 1.5)}, "barrel": {"height": (0.8, 1.2)},
    "crate": {"width": (0.4, 1.2)}, "fountain": {"width": (1.5, 6.0)}, "person": {"height": (1.5, 1.95)},
    "dog": {"height": (0.3, 0.9)}, "mushroom": {"height": (0.05, 0.4)}, "flower": {"height": (0.15, 1.2)},
    "sun lounger": {"width": (1.7, 2.3), "height": (0.3, 1.1)}, "lounger": {"width": (1.7, 2.3), "height": (0.3, 1.1)},
    "parasol": {"height": (2.0, 3.2)}, "garage": {"height": (2.2, 4.5), "width": (2.8, 9.5)},
    "gate": {"height": (0.8, 2.6)},
}
_TYPICAL_NOUN = re.compile(r"\b(" + "|".join(sorted((re.escape(k) for k in TYPICAL_SIZE), key=len, reverse=True)) +
                           r")s?\b", re.I)


def _size_verdict(goal: str, made: list):
    """Compare what was built with the real size of the one thing asked for: None (fine, or can't tell),
    ("rescale", factor, why) when one uniform scale makes every dimension right (the design is fine, only its size
    is off), or ("issue", text) when no single scale can (its proportions are wrong — a "bench" shaped like a chair)."""
    request = (goal or "").split(" — ")[0]          # not the scene's naming instructions after the dash
    if _SIZE_WORDS.search(request) or not made:
        return None
    nouns = {m.group(1).lower() for m in _TYPICAL_NOUN.finditer(request)}
    nouns = {n for n in nouns if not any(n != m and n in m for m in nouns)}   # "park bench" covers "bench"
    if len(nouns) != 1:
        return None
    noun = nouns.pop()
    lo = [min(o["min"][i] for o in made) for i in range(3)]
    hi = [max(o["max"][i] for o in made) for i in range(3)]
    have = {"height": hi[2] - max(0.0, lo[2]), "width": max(hi[0] - lo[0], hi[1] - lo[1])}
    spans = [(dim, have[dim], low, high) for dim, (low, high) in TYPICAL_SIZE[noun].items() if have[dim] > 1e-3]
    if not spans or all(low / 1.4 <= h <= high * 1.4 for _, h, low, high in spans):
        return None
    f_low = max(low / h for _, h, low, high in spans)
    f_high = min(high / h for _, h, low, high in spans)
    described = "; ".join(f"{'tall' if d == 'height' else 'wide'}: {round(h, 2)} m (a real one {low}-{high} m)"
                          for d, h, low, high in spans)
    if f_low <= f_high * 1.15:
        return "rescale", round((f_low * min(f_high, f_low * 4)) ** 0.5, 3), f"{noun}: {described}"
    return "issue", (f"Its proportions aren't those of a {noun} — {described}. Rebuild it with a real {noun}'s "
                     "measurements (keep the names), not something else's.")


def _rescale_for(goal: str, made: list):
    verdict = _size_verdict(goal, made)
    return (verdict[1], verdict[2]) if verdict and verdict[0] == "rescale" else None


def _repeated(objs: list) -> dict:
    """Parts that are copies of one design: 'Tree Leaves 1', 'Tree Leaves 2'... grouped by the name without its number."""
    groups = {}
    for o in objs:
        base = re.sub(r"\s*\d+$", "", o["name"])
        if base != o["name"]:
            groups.setdefault(base, []).append(o)
    return groups


QUALITY_GUIDANCE = {
    "simple": "QUALITY: simple — a quick but recognisable version: a few well-chosen parts (3-8) with the right shape "
              "types (blob/tube/lathe for organic and round things) and materials. 1-2 steps.",
    "normal": "QUALITY: normal — a good-looking model: main masses, secondary parts and some details (typically 8-25 "
              "parts), bevelled hard edges, textured materials, natural variation. 2-4 steps.",
    "high": "QUALITY: high — a polished, detailed model, as an artist would make it: everything for normal plus finer "
            "details (trims, frames, hardware, small props, secondary branches, many varied foliage clusters), "
            "careful proportions (typically 20-60 parts). 3-6 steps.",
}


def _restore_code(snapshot: dict) -> str:
    """Blender code that puts the scene back as `snapshot` had it: new objects removed, moved/recolored ones
    restored, and deleted ones (kept aside by the kit's trash()) put back."""
    return ("import json, mathutils\n"
            f"snap = json.loads({json.dumps(json.dumps(snapshot))})\n"
            "anim = snap.pop('__anim__', None)\n"
            "uids = {v[5]: n for n, v in snap.items() if len(v) > 5}\n"
            "def was_there(o):\n"
            "    return o.session_uid in uids if uids else o.name in snap\n"
            "for o in list(bpy.data.objects):\n"
            "    if was_there(o):\n"
            "        continue\n"
            "    if not o.get('jervis_trash'):\n"
            "        bpy.data.objects.remove(o, do_unlink=True)   # made since the snapshot\n"
            "    elif o.users_collection:   # was in the trash then, so back in the trash it goes\n"
            "        for c in list(o.users_collection): c.objects.unlink(o)\n"
            "scene = getattr(bpy.context, 'scene', None) or bpy.data.scenes[0]\n"
            "by_uid = {o.session_uid: o for o in bpy.data.objects}\n"
            "for name, entry in snap.items():   # renamed since (an asset rebuilt): its own name back\n"
            "    o = by_uid.get(entry[5]) if len(entry) > 5 else bpy.data.objects.get(name)\n"
            "    if o is not None and o.name != name:\n"
            "        other = bpy.data.objects.get(name)\n"
            "        if other is not None and other is not o: other.name = '__jervis_spare ' + name\n"
            "        o.name = name\n"
            "for name, entry in snap.items():\n"
            "    loc, rot, scl, mat, par = entry[:5]\n"
            "    o = bpy.data.objects.get(name)\n"
            "    if o is None: continue\n"
            "    if o.get('jervis_trash') and not o.users_collection:   # deleted since: put it back\n"
            "        scene.collection.objects.link(o)\n"
            "        o.use_fake_user = False\n"
            "        del o['jervis_trash']\n"
            "    o.location, o.rotation_euler, o.scale = loc, rot, scl\n"
            "    if mat and o.data is not None and hasattr(o.data, 'materials') and bpy.data.materials.get(mat):\n"
            "        if o.data.materials: o.data.materials[0] = bpy.data.materials[mat]\n"
            "    target = bpy.data.objects.get(par) if par else None\n"
            "    if o.parent != target:   # assigning a parent resets its inverse: only when it really changed\n"
            "        o.parent = target\n"
            "    if len(entry) > 6 and entry[6]:\n"
            "        o.matrix_parent_inverse = mathutils.Matrix(entry[6])\n"
            "if anim is not None and 'anim_restore' in globals(): anim_restore(anim)   # keys, drivers, timeline\n"
            "if '_rewire_holes' in globals(): _rewire_holes()   # a pool's hole in the ground comes and goes with it\n"
            "RESULT = 'restored'")


def _module_source(module) -> str:
    bundled = paths.resource(os.path.basename(module.__file__))
    path = bundled if os.path.exists(bundled) else module.__file__
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def kit_source() -> str:
    """The building kit and the finished assets built on it (blender_assets.py), as one script for the bridge —
    preceded by spatial.py as its own module `spatial`, the very code Jervis checks scenes with."""
    loader = ("import types as _jervis_types\n"
              "spatial = _jervis_types.ModuleType('jervis_spatial')\n"
              f"exec(compile({_module_source(spatial)!r}, '<spatial>', 'exec'), spatial.__dict__)\n"
              "cinema = _jervis_types.ModuleType('jervis_cinema')\n"
              "cinema.__dict__['spatial'] = spatial\n"
              f"exec(compile({_module_source(cinema)!r}, '<cinema>', 'exec'), cinema.__dict__)\n")
    return "\n\n".join([loader] + [_module_source(m) for m in (blender_kit, blender_assets, blender_motion,
                                                                blender_places, blender_nature, blender_props,
                                                                blender_world)])


def _find(objects: list, name: str):
    if not name:
        return None
    low = str(name).strip().lower()
    for test in (lambda n: n == low, lambda n: n.startswith(low), lambda n: low in n,
                 lambda n: n.replace(" ", "") == low.replace(" ", "")):
        for o in objects:
            if test(o["name"].lower()):
                return o
    return None


def _overlap(a_min, a_max, b_min, b_max, slack: float = 0.01) -> bool:
    return a_min <= b_max + slack and b_min <= a_max + slack


THIN = 0.15   # metres: a part this thin (a window, a sign, an eye) may be fixed to the side of something


def _xy_overlap(a: dict, b: dict) -> float:
    """How far two objects overlap seen from above (the smaller of the x and y overlaps; <= 0: not at all)."""
    return min(min(a["max"][i], b["max"][i]) - max(a["min"][i], b["min"][i]) for i in range(2))


def _touching(a: dict, b: dict, slack: float = 0.05) -> bool:
    """Do two objects' boxes touch or intersect (within a few centimetres)?"""
    return all(_overlap(a["min"][i], a["max"][i], b["min"][i], b["max"][i], slack) for i in range(3))


def free_spot(state: dict) -> tuple:
    """A spot on the ground with nothing on it, just beside everything already in the scene (the origin when the
    scene is empty) — so a new build doesn't land inside Blender's default cube or the last thing made."""
    meshes = [o for o in state.get("objects", []) if o["type"] == "MESH"]
    if not meshes:
        return 0, 0
    right = max(o["max"][0] for o in meshes)
    lo_y, hi_y = min(o["min"][1] for o in meshes), max(o["max"][1] for o in meshes)
    return round(right + 4), round((lo_y + hi_y) / 2)


# ---------- places asked for by name: their own finished builders, never a blockout ----------
_PLACE_REQUESTS = [   # (words, builder, its name) — a request naming one of these, and nothing else to build
    (re.compile(r"\b(?P<w>coffee shop|ice cream shop|caf[eé]|bakery|boutique|restaurant|bistro|pizzeria|pharmacy|"
                r"bookshop|bookstore|book shop|grocery(?: store)?|deli|florist|kiosk|bar|pub|shop|store|storefront|"
                r"shopfront)\b", re.I), "storefront"),
    (re.compile(r"\b(?P<w>villa|mansion)\b", re.I), "villa"),
    (re.compile(r"\b(?P<w>beach|seaside|sea ?shore|shore|coast(?:line)?)\b(?!.*\bisland\b)", re.I), "shore"),
]
_MORE_THAN_ONE = re.compile(r"\b(?:and|with|next to|beside|behind|in front of|near|plus|then|two|three|several|"
                            r"street of|row of|houses|shops)\b|,", re.I)


def place_request(what: str):
    """(builder, said word) for a request whose one subject is a place-scale thing ("a little bakery", "a modern
    villa", "a beach"), or None."""
    if not what or _MORE_THAN_ONE.search(what):
        return None
    for pattern, builder in _PLACE_REQUESTS:
        for m in pattern.finditer(what):
            # the thing itself, not a word describing another ("a beach hut", "a bar stool"): only a qualifier may
            # follow it ("in Blender", "at sunset", "please")
            if _PLACE_TAIL.match(what[m.end():]):
                return builder, m.group("w").lower()
    return None


_PLACE_TAIL = re.compile(r"^\s*(?:(?:in|on|at|by|for|near|during|under|please|now|for me)\b.*)?[.!]?\s*$", re.I)


def _place_options(builder: str, what: str) -> dict:
    w = what.lower()
    opts = {}
    floors = {"one": 1, "single": 1, "1": 1, "two": 2, "2": 2, "three": 3, "3": 3}
    m = re.search(r"\b(one|single|two|three|[123])[- ]?(?:stor(?:e)?y|floor|level)", w)
    if m:
        opts["floors"] = floors[m.group(1)]
    if builder == "storefront":
        if re.search(r"\b(?:modern|contemporary|glass|minimal)", w):
            opts["style"] = "modern"
        if re.search(r"\b(?:little|small|tiny|cosy|cozy)\b", w):
            opts.update(width=6.5)
            opts.setdefault("floors", 1)
        elif re.search(r"\b(?:big|large|huge)\b", w):
            opts.update(width=12.0)
        colour = next((c for c in sorted(blender_kit.COLORS, key=len, reverse=True)
                       if re.search(rf"\b{re.escape(c)}\b", w)), None)
        if colour:
            opts["color"] = colour
    elif builder == "villa":
        if re.search(r"\b(?:small|little)\b", w):
            opts.update(width=14.0, wings=1)
        elif re.search(r"\b(?:big|large|huge|luxury|luxurious)\b", w):
            opts.update(width=26.0)
    elif builder == "shore":
        opts.update(width=160, sand_depth=40)
    return opts


# ---------- finished assets: the request is "build a <house/tree/island...>", or "change its <option>" ----------
_BUILD_VERB = re.compile(r"^(?:(?:please|can you|could you|would you|will you|now|also|then|and|ok|okay|jervis|"
                         r"hey)\b[\s,]*)*(?:create|make|build|add|generate|model|design|put|place|give me|i (?:want|need)|"
                         r"i'd like|let's (?:make|build|have|add|plant)|draw|construct|plant|grow|scatter|spawn|"
                         r"set up|raise|erect)\b\s*(?:me |us )?", re.I)
_CHANGE_TARGET = re.compile(r"^(?:the|it|its|this|that|them|those|these|his|her|their|my)\b", re.I)
_PLAIN_COLOURS = set(blender_kit.COLORS) - {"wood", "dark wood", "stone", "brick", "glass", "water", "grass", "leaf",
                                            "snow", "dirt", "concrete", "metal", "steel", "sand", "skin", "sky"}
_MAIN_PART_MOVING = {"fire": "Flame 1", "flag": "Cloth", "waterfall": "Water", "cloud": "Puffs", "smoke": "Source",
                     "river": "Water"}
_MAIN_PART = {"house": "Walls", "tree": "Trunk", "island": "Terrain", "water": "Surface", "rock": "Stone",
              "bush": "Leaves", "fence": "Boards", "pool": "Water", "pond": "Water", "bench": "Seat",
              "lounger": "Bed", "fountain": "Basin", "car": "Body", "garage": "Walls", "gate": "Leaf 1"}
_SPACING = {"house": 15.0, "tree": 5.5, "rock": 3.0, "bush": 2.5, "fence": 1.0, "water": 0.0, "island": 0.0,
            "pool": 13.0, "pond": 7.0, "bench": 2.6, "lounger": 1.3, "fountain": 5.0}
_MAIN_PART.update(_MAIN_PART_MOVING)
_SPACING.update({"car": 6.0, "garage": 9.0, "gate": 5.0, "fire": 3.0, "flag": 3.0, "waterfall": 12.0, "river": 0.0, "cloud": 15.0, "smoke": 2.0})
_ROTATES = {"house", "fence", "pool", "pond", "bench", "lounger", "car", "garage", "gate"}
# Things with a front that turns to suit what they stand by: a bench sits with its back to it, a lounger's foot
# points at it (a pool). +1: front away from the anchor, -1: toward it.
_FACES = {"bench": 1, "lounger": -1}   # assets that take rotation= (turned to line up with what they stand by)


def _footprint(kind: str, options: dict) -> float:
    """Roughly how far an asset reaches from where it stands (metres), so it's placed clear of what's there."""
    if kind == "house":
        return max(float(options.get("width") or 8), float(options.get("depth") or 6.5)) / 2 + 6.0   # + its path
    if kind == "island":
        return float(options.get("radius") or 15) * (2.6 if options.get("water", True) else 1.3)
    if kind == "water":
        return float(options.get("size") or 60) / 2
    if kind == "tree":
        return float(options.get("height") or 7) * 0.4
    if kind == "fence":
        return float(options.get("length") or 6) / 2
    if kind == "pool":
        return float(options.get("length") or 8) / 2 + float(options.get("deck_width") or 1.2) + 0.5
    if kind == "pond":
        return float(options.get("size") or 4) * 0.6 + 0.5
    return 1.5


def _asset_size(kind: str, options: dict) -> tuple:
    """(width, depth) of the ground an asset will cover, to find room for it before it exists."""
    if kind == "house":
        return float(options.get("width") or 9) + 1.0, float(options.get("depth") or 7) + 1.0
    if kind == "pool":
        deck = 2 * float(options.get("deck_width") or 1.2) if options.get("deck", True) else 0.0
        length, width = float(options.get("length") or 8), float(options.get("width") or 4)
        return max(length, width) + 1.0 + deck, min(length, width) + 1.0 + deck
    if kind == "tree":   # measured on the assets: an oak's crown is about as wide as it is tall
        kind_ = str(options.get("kind") or "oak")
        ratio = {"pine": 0.48, "birch": 0.48, "palm": 0.76}.get(kind_, 1.06)
        height = float(options.get("height") or {"pine": 10.4, "birch": 8.5, "palm": 8.3}.get(kind_, 6.2))
        return (height * ratio,) * 2
    if kind == "rock":
        return (float(options.get("size") or 1) * 2.2,) * 2
    if kind == "bush":
        return (float(options.get("size") or 1) * 1.6,) * 2
    if kind == "fence":
        return float(options.get("length") or 6), 0.4
    if kind == "pond":
        size = float(options.get("size") or 4)
        return size * 1.15 + 0.6, size * 0.85 + 0.6
    if kind == "bench":
        return (float(options.get("length") or 1.6) + 0.2,) * 2   # square: it turns to face away
    if kind == "lounger":
        return 2.2, 2.2
    if kind == "fountain":
        return (float(options.get("size") or 3) + 0.4,) * 2
    if kind == "car":
        return float(options.get("length") or 4.4) + 0.6, float(options.get("length") or 4.4) * 0.41 + 0.6
    if kind == "garage":
        return float(options.get("width") or 3.6) + 0.6, float(options.get("depth") or 6.5) + 1.8   # + its apron
    if kind == "gate":
        return float(options.get("width") or 3.6) + 0.8, 0.8
    if kind == "fire":
        return (float(options.get("size") or 1) * 1.6 + 0.4,) * 2
    if kind == "flag":
        return (float(options.get("size") or 1.5) + 0.6,) * 2
    if kind == "waterfall":
        w = float(options.get("width") or 2.5)
        return w + 4.0, max(6.0, w * 2.5)
    if kind == "river":
        return float(options.get("length") or 40), float(options.get("width") or 4) + 3
    return 2.0, 2.0


def _facing(kind: str, spot: dict, anchor_category: str = "building"):
    """The rotation (degrees) that turns a thing to what it was placed by: a bench sits with its back to a house but
    looks at a fountain, a pond or a pool; a lounger's foot points at what it's by."""
    sign = _FACES.get(kind)
    if kind == "bench" and anchor_category != "building":
        sign = -1
    away = spot.get("away") if isinstance(spot, dict) else None
    if not sign or not away:
        return None
    fx, fy = away[0] * sign, away[1] * sign      # where its front should point
    return round(math.degrees(math.atan2(fx, -fy))) % 360
_OPTION_TYPES = {   # JSON types for the options in blender_assets.ASSET_TYPES
    "floors": "integer", "count": "integer", "trees": "integer", "seed": "integer",
    "width": "number", "depth": "number", "height": "number", "radius": "number", "size": "number",
    "length": "number", "window_scale": "number", "lean": "number", "waves": "number", "rotation": "number",
    "chimney": "boolean", "porch": "boolean", "shutters": "boolean", "path": "boolean", "water": "boolean",
    "rocks": "boolean", "moss": "boolean", "deck": "boolean", "ladder": "boolean", "deck_width": "number",
    "reeds": "boolean", "tiers": "integer", "logs": "boolean", "stones": "boolean", "heavy": "boolean"}

ASSET_PROMPT = """You map a request for a 3D model onto a library of finished, detailed assets. Reply as JSON.
Assets and their options:
{catalogue}
- "asset": the ONE thing the request asks to build, from the list; "none" if it isn't one of them (a chair, a car,
  a castle, a bridge...).
- "options": only what the user's words say or clearly imply; leave everything else out (the defaults are good).
  Colour words go to the part they describe ("a red roof" -> roof_color "red", "a blue door" -> door_color "blue",
  "white walls" -> walls "white"); materials and styles: "brick house" -> style "brick", "log cabin" / "wooden
  cabin" -> style "cabin", "modern villa" -> style "modern", "stone walls" -> walls "stone"; "two-storey" /
  "two floors" -> floors 2; "big windows" -> window_scale 1.4; "palm tree" -> kind "palm"; "autumn tree" -> leaves
  "autumn leaves"; "a tropical island with palm trees" -> trees 6, tree_kind "palm"; "a big island" -> radius 30;
  "a mossy rock" -> moss true; "some rocks" -> count 5.
- "count": how many separate ones (two trees -> 2, a forest -> 8); 1 if not said.
- "understanding": what to do, as a short command: "Build a two-storey brick house".
- "other_things": anything else the request asks for that is NOT part of this asset and not an option ("with a
  swing hanging from it", "and a car in front"), in the user's words; "" if nothing."""

EDIT_PROMPT = """A finished 3D asset is in the scene. Decide whether the user's request is a change to one of its
OPTIONS, and which. Reply as JSON.
Asset: {kind} '{name}', options now: {params}
Options it has: {options}
- "fits": true only if the request is fully done by changing these options ("bigger windows" -> window_scale
  larger; "make it two floors" -> floors 2; "give it a red roof" -> roof_color "red"; "make it a pine" -> kind
  "pine"; "no chimney" -> chimney false; "more trees on the island" -> trees larger). false for anything else:
  moving it, resizing the whole thing, deleting it, adding a separate thing, or changing a part no option covers.
- "changes": the options to change, with their new values (sizes relative to now: "bigger" ~ x1.35).
- "understanding": what to do, as a short command of a few words: "Make the windows bigger"."""


def _catalogue() -> str:
    lines = []
    for kind, spec in blender_assets.ASSET_TYPES.items():
        opts = ", ".join(f"{k} ({'|'.join(v) if isinstance(v, list) else v})" for k, v in spec["options"].items())
        lines.append(f"  {kind}: {opts}")
    return "\n".join(lines)


def _options_schema(kinds) -> dict:
    props = {}
    for kind in kinds:
        for key, kind_spec in blender_assets.ASSET_TYPES[kind]["options"].items():
            if isinstance(kind_spec, list):
                props[key] = {"type": "string", "enum": kind_spec}
            else:
                props[key] = {"type": _OPTION_TYPES.get(key, "string")}
    return {"type": "object", "properties": props}


def _clean_options(kind: str, options: dict) -> dict:
    """The AI's options, kept only where the asset really has them and the value has the right type."""
    allowed = blender_assets.ASSET_TYPES[kind]["options"]
    out = {}
    for key, value in (options or {}).items():
        if key not in allowed or value is None or value == "":
            continue
        spec, wanted = allowed[key], _OPTION_TYPES.get(key, "string")
        try:
            if isinstance(spec, list):
                value = str(value).lower()
                if value not in spec:
                    continue
            elif wanted == "integer":
                value = int(round(float(value)))
            elif wanted == "number":
                value = round(float(value), 3)
            elif wanted == "boolean":
                value = value if isinstance(value, bool) else str(value).lower() in ("true", "yes", "1")
            else:
                value = str(value).strip()
                if not value or value.lower() in ("none", "default", "null"):
                    continue
        except (TypeError, ValueError):
            continue
        out[key] = value
    return out


# What the user must have said for the AI's option to be kept. A 7B model asked for "only what the user said" still
# fills in every option it can (a palm tree came back with leaves='autumn leaves', a house with a grey roof and no
# path): the model proposes, the user's own words confirm.
_SIZE_SAID = r"\b(?:big|bigger|large|larger|huge|giant|massive|small|smaller|tiny|little|tall|taller|short|wide|narrow|" \
             r"long|high|low|\d+(?:\.\d+)?\s*(?:m|meters?|metres?|feet|ft)\b)"
_OPTION_SAID = {
    "style": None,   # see _STYLE_SAID
    "floors": r"\b(?:stor(?:e)?y|stories|storeys|floors?|levels?|\d+|one|two|three|single|double|triple)\b",
    "roof": r"\b(?:gable|hip|hipped|flat)\b", "window_scale": r"\bwindows?\b",
    "chimney": r"\bchimneys?\b", "porch": r"\b(?:porch|veranda|deck)\b", "shutters": r"\bshutters?\b",
    "path": r"\b(?:path|walkway|stones?)\b", "rotation": r"\b(?:rotat\w*|turn\w*|facing|faces|degrees?)\b",
    "kind": r"\b(?:oak|maple|pine|fir|spruce|conifer|christmas|palm|coconut|tropical|birch|aspen)\b",
    "trees": r"\b(?:trees?|palms?|forest|jungle|woods|vegetation|pines?|oaks?)\b", "tree_kind": None,
    "water": r"\b(?:water|sea|ocean|lake|lagoon)\b", "rocks": r"\b(?:rocks?|stones?|boulders?)\b",
    "moss": r"\b(?:moss|mossy)\b", "count": None, "style_fence": r"\b(?:picket|rail)\b",
    "waves": r"\b(?:wav\w*|calm\w*|rough\w*|chopp\w*|still\w*|storm\w*|smooth\w*|swell\w*)\b",
    "deck": r"\b(?:deck\w*|terrace|patio|paving|pavers|tiles?)\b", "ladder": r"\bladders?\b",
    "reeds": r"\b(?:reeds?|rushes|cattails?|bulrush\w*)\b", "tiers": r"\b(?:tiers?|tiered|levels?|bowls?)\b",
}
_STYLE_SAID = {"cottage": r"\b(?:cottage|country)\b", "brick": r"\bbrick\b",
               "modern": r"\b(?:modern|contemporary|minimal\w*|villa)\b", "farmhouse": r"\b(?:farm\w*|barn)\b",
               "cabin": r"\b(?:cabin|log|wooden|wood|chalet|hut)\b", "picket": r"\bpicket\b", "rail": r"\brail\w*\b",
               "park": r"\b(?:park|cast[- ]iron|iron|classic)\b", "garden": r"\b(?:garden|wooden|simple|plain|rustic)\b"}
_WALLS_TO_STYLE = {"brick": "brick", "logs": "cabin", "log": "cabin", "wood": "cabin", "wooden": "cabin",
                   "siding": "farmhouse"}


# "Improve the water", "make the roof nicer": the user leaves the choice to Jervis — for the part they named.
_IMPROVE = re.compile(r"\b(?:improve|better|nicer|prettier|more (?:realistic|detailed|beautiful|natural|interesting)|"
                      r"enhance|upgrade|polish|fix up|look good|beautify)\b", re.I)
_PART_OPTIONS = [(re.compile(r"\b(?:water|sea|ocean|waves?|surf|shore)\b", re.I), {"waves", "sea_color", "foam"}),
                 (re.compile(r"\broof\b", re.I), {"roof", "roof_color", "chimney"}),
                 (re.compile(r"\bwindows?\b", re.I), {"window_scale", "shutters", "shutter_color", "trim"}),
                 (re.compile(r"\bwalls?\b", re.I), {"walls", "trim"}),
                 (re.compile(r"\bdoor\b", re.I), {"door_color", "porch"}),
                 (re.compile(r"\b(?:trees?|palms?|vegetation|forest)\b", re.I), {"trees", "tree_kind", "kind", "leaves"}),
                 (re.compile(r"\b(?:rocks?|stones?)\b", re.I), {"rocks", "moss", "count"})]


_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "a few": 3, "some": 4, "several": 5, "many": 8, "lots of": 10}
_WATER_WORDS = re.compile(r"\b(?:water|sea|ocean|waves?|surf|shore)\b", re.I)
_MORE_TREES = re.compile(r"\b(?:more|add|plant|extra|another|grow)\b.*\b(?:trees?|palms?|pines?|oaks?|birch\w*)\b", re.I)


def _how_many(text: str, default: int) -> int:
    m = re.search(r"\b(\d+|a few|lots of|an?|one|two|three|four|five|six|seven|eight|nine|ten|some|several|many)\s+"
                  r"(?:more\s+)?(?:\w+\s+)?(?:trees?|palms?|pines?|oaks?|birch\w*)\b", text or "", re.I)
    if not m:
        return default
    word = m.group(1).lower()
    return int(word) if word.isdigit() else _NUMBER_WORDS.get(word, default)


def _known_change(kind: str, text: str, params: dict):
    """Changes whose meaning is clear without asking the AI: "more trees on the island", "improve the water"."""
    if kind == "island" and _MORE_TREES.search(text):
        change = {"trees": min(30, int(params.get("trees") or 0) + _how_many(text, 4))}
        for pattern, value in (("palm", "palm"), ("pine", "pine"), ("oak", "oak"), ("birch", "birch")):
            if re.search(rf"\b{pattern}", text, re.I):
                change["tree_kind"] = value
        return change
    if kind == "island" and _IMPROVE.search(text) and _WATER_WORDS.search(text):
        return {"waves": max(0.65, float(params.get("waves") or 0.35)), "foam": True}
    if kind == "house" and _IMPROVE.search(text) and re.search(r"\bwindows?\b", text, re.I):
        return {"window_scale": round(min(1.6, float(params.get("window_scale") or 1.0) * 1.2), 3), "shutters": True}
    return None


_RESIZE_SAID = re.compile(r"\b(bigger|larger|smaller|wider|narrower|taller|higher|shorter|lower|deeper|shallower|"
                          r"(?:as|so) (?:big|large|wide|tall|high|deep))\b", re.I)
_RESIZE_KEYS = {"bigger": ("width", "depth", "size", "length", "height"), "wider": ("width", "size"),
                "taller": ("height",), "higher": ("height",), "deeper": ("depth",)}
_RESIZE_KEYS.update({"larger": _RESIZE_KEYS["bigger"], "smaller": _RESIZE_KEYS["bigger"], "narrower": ("width", "size"),
                     "shorter": ("height", "length"), "lower": ("height",), "shallower": ("depth",)})


def _size_change(text: str, params: dict):
    """"Make the house bigger", "a wider shop": the size options a place-scale asset (a villa, a storefront, a
    forest...) has, scaled by a third — the asset rebuilt, not stretched. A building's height is its floors."""
    m = _RESIZE_SAID.search(text or "")
    if not m:
        return None
    word = m.group(1).lower()
    if word.startswith(("as ", "so ")):   # "twice as wide"
        word = {"big": "bigger", "large": "larger", "wide": "wider", "tall": "taller", "high": "higher",
                "deep": "deeper"}[word.split()[1]]
    grow = word in ("bigger", "larger", "wider", "taller", "higher", "deeper")
    factor = 1.0 + _how_much(text) / 100.0 if grow and _how_much(text) else (1.3 if grow else 1 / 1.3)
    out = {}
    for key in _RESIZE_KEYS[word]:
        value = params.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            out[key] = round(float(value) * factor, 2)
    if "floors" in params and word in ("taller", "higher", "shorter", "lower"):
        out.pop("height", None)
        out["floors"] = max(1, int(params["floors"] or 1) + (1 if grow else -1))
    return out or None


def _how_much(text: str) -> float:
    """"50% bigger" → 50; "twice as big" → 100; nothing said → 0."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text or "")
    if m:
        return float(m.group(1))
    return 100.0 if re.search(r"\b(?:twice|double)\b", text or "", re.I) else 0.0


def _grounded(kind: str, options: dict, text: str, new: bool = True) -> dict:
    """Only the options the request's own words support. new: a new build ("a brick house" means the brick style;
    for an existing house, "brick walls" changes just its walls)."""
    said = (text or "").lower()
    if not new and _IMPROVE.search(said):   # "improve the water": the AI chooses — among that part's options
        named = set().union(*[opts for pattern, opts in _PART_OPTIONS if pattern.search(said)] or [set(options)])
        return {k: v for k, v in options.items() if k in named and k != "seed"}
    out = {}
    for key, value in options.items():
        if key == "seed":
            continue
        if key == "style":
            pattern = _STYLE_SAID.get(str(value))
        elif key == "tree_kind":
            pattern = _OPTION_SAID["kind"]
        elif key in ("width", "depth", "height", "radius", "size", "length", "deck_width"):
            pattern = _SIZE_SAID
        elif key in _OPTION_SAID:
            pattern = _OPTION_SAID[key]
        else:   # a colour or material (walls, roof_color, trim, door_color, leaves, color, flowers...): its own words
            words = [w for w in re.findall(r"[a-z]+", str(value).lower()) if len(w) > 2]
            pattern = r"\b(?:" + "|".join(map(re.escape, words)) + r")\b" if words else None
        if pattern is None or re.search(pattern, said):
            out[key] = value
    if new and kind == "house" and "style" not in out and str(out.get("walls", "")).lower() in _WALLS_TO_STYLE:
        out["style"] = _WALLS_TO_STYLE[str(out.pop("walls")).lower()]   # "a brick house" is the brick style
    if kind == "tree" and out.get("kind") and not re.search(_OPTION_SAID["kind"], said):
        out.pop("kind")
    return out


# "... and save it" at the end of a request: carried out and verified, never silently dropped.
_SAVE_CLAUSE = re.compile(r"(?:,\s*|\s+)(?:and\s+|then\s+|and then\s+)*save\s*(?:it|this|that|everything|the\s+"
                          r"(?:file|scene|project|work|blend(?:er)?\s+file))?(?:\s+(?:as|to)\s+(?P<name>[\w .-]+?))?"
                          r"\s*[.!]?$", re.I)
# "... on the island", "... next to the house": what the request is about, already in the scene.
_ANCHOR = re.compile(r"\b(?P<rel>on|onto|to|in|into|at|around|near|next to|beside|by|behind|in front of)\s+"
                     r"(?:the|my|this|that|its|our)\s+(?P<word>[a-z]+)", re.I)
_NOUN_STYLE = [(re.compile(r"\b(?:cabin|hut|chalet|log)\b", re.I), "cabin"),
               (re.compile(r"\bcottage\b", re.I), "cottage"),
               (re.compile(r"\b(?:villa|modern|contemporary)\b", re.I), "modern"),
               (re.compile(r"\b(?:farmhouse|farm|barn)\b", re.I), "farmhouse"),
               (re.compile(r"\b(?:mansion|townhouse)\b", re.I), "brick")]
_SMALL = re.compile(r"\b(?:small|little|tiny|cozy|cosy)\b", re.I)
_BIG = re.compile(r"\b(?:big|large|huge|grand|mansion)\b", re.I)


_SAVE_ONLY = re.compile(r"^(?:(?:and|then|also|now|please)\s+)*save\s*(?:it|this|that|everything|the\s+"
                        r"(?:file|scene|project|work|blend(?:er)?\s+file))?(?:\s+(?:as|to)\s+(?P<name>[\w .-]+?))?"
                        r"\s*[.!]?$", re.I)


def save_request(goal: str):
    """(the goal without a trailing "and save it", the file name asked for or "" — or None if no save was asked)."""
    text = " ".join((goal or "").split())
    m = _SAVE_CLAUSE.search(text)
    if not m or not text[:m.start()].strip():
        return text, None
    return text[:m.start()].strip(" ,"), (m.group("name") or "").strip()


_KIT_NAMES = {n for n in dir(blender_kit) if callable(getattr(blender_kit, n)) and not n.startswith("_")} | set(
    blender_assets.ASSET_BUILDERS) | {"pool", "pond", "walkway", "spot_near", "place_near", "footprint", "entrance_of"}


def _unshadow(code: str) -> str:
    """The AI's code with its own variables renamed where they reuse a kit function's name (color = 'wood', then
    color(...) -> "'str' object is not callable"; top = 2.5, then top('Walls')). Only names the code assigns AND
    calls are touched, and never a keyword argument (box(..., color='wood')) or an attribute (o.location)."""
    import io
    import tokenize
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code or "").readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return code
    assigned, called = set(), set()
    depth = 0
    for i, tok in enumerate(tokens):
        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string in ")]}":
            depth = max(0, depth - 1)
        if tok.type != tokenize.NAME or tok.string not in _KIT_NAMES:
            continue
        prev = tokens[i - 1].string if i else ""
        nxt = tokens[i + 1].string if i + 1 < len(tokens) else ""
        if prev == ".":
            continue
        if nxt == "(":
            called.add(tok.string)
        elif depth == 0 and (nxt == "=" or prev in ("for", ",") or nxt == ","):
            assigned.add(tok.string)
    clash = assigned & called
    if not clash:
        return code
    out, depth = [], 0
    for i, tok in enumerate(tokens):
        if tok.type == tokenize.OP and tok.string in "([{":
            depth += 1
        elif tok.type == tokenize.OP and tok.string in ")]}":
            depth = max(0, depth - 1)
        string = tok.string
        if tok.type == tokenize.NAME and string in clash:
            prev = tokens[i - 1].string if i else ""
            nxt = tokens[i + 1].string if i + 1 < len(tokens) else ""
            keyword_arg = depth > 0 and nxt == "=" and (tokens[i + 2].string if i + 2 < len(tokens) else "") != "="
            if prev != "." and nxt != "(" and not keyword_arg:
                string = f"{string}_value"
        out.append(tok._replace(string=string))
    try:
        return tokenize.untokenize(out)
    except ValueError:
        return code


def _usage(fn: str) -> str:
    """How the instructions show a kit function being called ("walkway(name, start, end, width=1.2, ...)")."""
    for line in INSTRUCTIONS.splitlines():   # its signature: the name with arguments, not "path()s" in a sentence
        m = re.search(r"(?<![\w.])" + re.escape(fn) + r"\((?!\))", line)
        if m:
            return " ".join(line[m.start():].split())[:180]
    return ""


def _code_only(code: str) -> str:
    """The code without comments and string contents (a builder's name in a comment or a message isn't a call)."""
    code = re.sub(r"#[^\n]*", "", code or "")
    return re.sub(r"(['\"])(?:\\.|(?!\1).)*\1", "''", code)


def _strip_relation(text: str, intent: dict) -> str:
    """The request without where it goes ("a swimming pool beside the villa" -> "a swimming pool"): the asset
    chooser decides only WHAT it is; where is measured on the scene."""
    anchor = str(intent.get("anchor") or "").strip("'")
    rel = spatial._REL_RE.pattern
    for pattern in (rf",?\s*(?:{rel})\s+(?:(?:the|a|an|my|our|this|that|its)\s+)?(?:[\w'-]+\s+){{0,2}}?"
                    rf"{re.escape(anchor)}(?:e?s)?\b", rf",?\s*(?:{rel})\s+(?:it|them|this|that)\b"):
        stripped = re.sub(pattern, " ", text, count=1, flags=re.I)
        if stripped != text:
            return " ".join(stripped.split())
    return text


# the words for the place-scale builders (blender_places / blender_props), which aren't in the asset catalog
_PLACE_WORDS = {"villa": r"villa|house|home|mansion", "storefront": r"shop|store|storefront|shopfront",
                "ground": r"ground|terrain|lawn|grass", "road": r"road|street", "shore": r"beach|shore|sea|ocean",
                "hills": r"hills?|mountains?", "forest": r"forest|woods?|trees", "room": r"room",
                "coffee_table": r"coffee table", "floor_lamp": r"floor lamp|lamp", "potted_plant": r"potted plant|plant",
                "street_lamp": r"street ?lamp|lamp ?post|street ?light"}


def _asset_words(kind: str) -> re.Pattern:
    spec = blender_assets.ASSET_TYPES.get(kind)
    words = spec["words"] if spec else _PLACE_WORDS.get(kind, re.escape(str(kind).replace("_", " ")))
    return re.compile(r"\b(?:" + words + r")(?:e?s)?\b", re.I)


def _free_prefix(base: str, state: dict) -> str:
    names = [o["name"].lower() for o in state.get("objects", [])]
    taken = lambda p: any(n == p.lower() or n.startswith(p.lower() + " ") for n in names)
    if not taken(base):
        return base
    k = 2
    while taken(f"{base} {k}"):
        k += 1
    return f"{base} {k}"


def _colour_checks(kind: str, name: str, options: dict) -> list:
    """A colour the user named for a part is checked on that part in the real scene."""
    leaves = {"palm": "Fronds", "pine": "Needles"}.get(str(options.get("kind") or "").lower(), "Leaves")
    # "color" paints the asset's main part: a fence's boards, a car's body, a bench's seat, a flag's cloth
    parts = {"roof_color": "Roof", "walls": "Walls", "door_color": "Door", "leaves": leaves,
             "color": _MAIN_PART.get(kind, "Boards")}
    if kind in ("pool", "pond"):
        parts = {"tiles": "Basin", "water_color": "Water"}
    checks = []
    for option, part in parts.items():
        value = str(options.get(option) or "").lower()
        if value in _PLAIN_COLOURS:
            family = blender_kit.color_name(blender_kit.rgb_of(value))
            checks.append({"type": "color", "object": f"{name} {part}", "color": family})
    return checks


_MOTION_CHECKS = {"animated", "keyframes", "camera_frames", "light_on", "light_off", "moves_to", "timeline", "still"}
_MOTION_WORDS = {"waves": "the water rolls in slow waves", "ripples": "the water ripples", "flow": "the water flows",
                 "falls": "the water pours down", "fire": "the flames flicker", "smoke": "the smoke rises",
                 "rain": "the rain falls", "snow": "the snow falls", "drift": "drifts slowly",
                 "flutter": "ripples in the wind", "sway": "sways in the wind", "spin": "turns"}


# A thing of a scene, placed by its relation to another (AgentTask._run_scene writes these into the thing's request).
_STANDING = re.compile(r"\bstanding (?P<rel>[a-z ]+?) '(?P<anchor>[^']+)'")
_RUNNING = re.compile(r"\brunning from '(?P<a>[^']+)' to '(?P<b>[^']+)'")
# Code that is meant to make something: if a step with it made nothing, it failed, whatever it returned.
_MAKES = re.compile(r"\b(?:box|cube|cylinder|cone|sphere|plane|ground|roof|torus|monkey|stairs|blob|tube|lathe|"
                    r"extrude_shape|frame|house|tree|island|water|rock|bush|fence|pool|walkway|legs_under|supports|"
                    r"duplicate|array)\(")
_SPATIAL_CHECKS = {"beside": "beside", "in_front_of": "front", "behind": "behind", "left_of": "left",
                   "right_of": "right", "inside": "inside", "outside": "outside", "connects": "connects"}


# A shot that moves (the director's, cinema.py) rather than a camera placed somewhere (scene_edit.py)
_CAMERA_MOVES = re.compile(r"\b(?:orbit\w*|circl\w* (?:around|round)|push(?:es|ing)? (?:in|toward|towards)|pull(?:s|ing)? "
                           r"(?:out|back)|dolly|fly ?(?:over|through|by)|flyover|flythrough|track(?:s|ing)?|follow\w*|"
                           r"chas\w*|crane\w*|reveal\w*|approach\w*|sweep\w*|descend\w*|start (?:above|at))\b", re.I)


_GROWS = {"width", "depth", "length", "size", "floors", "radius", "height"}
_TIMED = re.compile(r"\b(?:gradually|slowly|over time|over \d|fades?|fading|halfway|near the end|at the end|"
                    r"at \d+(?:\.\d+)? ?(?:s|sec|seconds)|after \d|then)\b", re.I)


class BlenderAdapter(AppAdapter):
    name = "blender"
    label = "Blender"
    check_types = ("exists", "absent", "color", "above", "on_top", "touching", "count", "size", "near",
                   "beside", "in_front_of", "behind", "left_of", "right_of", "inside", "outside", "connects",
                   "animated", "keyframes", "camera_frames", "light_on", "light_off", "moves_to", "timeline", "still",
                   "env", "camera_safe")

    def __init__(self, bridge, session=None):
        self.bridge = bridge
        self.session = session
        self.goal = ""
        self.intents = []          # where the request says things go (spatial.parse_relations + the scene's layout)
        self.spot_note = ""        # how X, Y was chosen, for the AI
        self.relation_spot = None  # {"x", "y", "rotation", "relation", "anchor"} when X, Y stands by something
        self.notes = []            # what the kit had to work around in this request's steps (unknown colours...)
        self._motion_cache = None  # the last motion_report(), until the scene changes
        self.retired = []          # what the kit took away on purpose this request (never reported as "lost")
        self.directed = None       # (events, seconds, fps) of the timeline this request directs
        self.direction_note = ""   # the request's timeline worked out (for the planner when it writes the code)
        self.reconstruction = None  # {"scene", "built", "image", ...} while rebuilding a picture (reconstruct.py)
        self.reference_image = None # the picture a request is about, when the app hands one over
        self.progress = None       # say(text): how a long planning step is going (set by the agent)
        self.edit = None           # the scene edit this request is (scene_edit.py), for its summary

    def _hint(self) -> str:
        m = _HINT.search(self.goal or "")
        return m.group(1) if m else ""

    def _intents(self, goal: str) -> list:
        """Where the request says things go: its own words ("a pool beside the villa", "a path from the door to the
        pool") and, for one thing of a scene, the relation the layout gave it ("standing beside 'Villa'")."""
        request = (goal or "").split(" — ")[0]
        out = [dict(i) for i in spatial.parse_relations(request)]
        hint = _HINT.search(goal or "")
        m = _STANDING.search(goal or "")
        if m and hint:
            out.append({"subject": f"'{hint.group(1)}'", "relation": spatial.normalize_relation(m.group("rel")),
                        "anchor": f"'{m.group('anchor')}'", "to": None})
        m = _RUNNING.search(goal or "")
        if m and hint:
            out.append({"subject": f"'{hint.group(1)}'", "relation": "connects", "anchor": f"'{m.group('a')}'",
                        "to": f"'{m.group('b')}'"})
        return out

    def _relation_spot(self, goal: str, state: dict):
        """X, Y for a new thing the request places by something already there ("a fountain behind the house"):
        found on the real scene, outside the anchor's footprint and clear of everything. None otherwise."""
        ts = spatial.things(state)
        if not ts:
            return None
        for intent in self.intents:
            rel = spatial.normalize_relation(intent.get("relation"))
            if rel in ("connects", "between", ""):
                continue
            subject = str(intent.get("subject") or "").strip("'")
            if subject and spatial.find_thing(ts, subject) is not None and not _BUILD_VERB.match(goal or ""):
                continue   # it's already there: a move, not a build
            anchor = spatial.find_thing(ts, intent.get("anchor"))
            if anchor is None:
                continue
            size = spatial.estimate_size(subject or "thing")
            spot = spatial.place_relative(anchor, rel, size, ts, spatial.category_of(subject))
            if spot is None:
                continue
            spot = dict(spot, relation=rel, anchor=anchor["name"], subject=subject)
            z = spot.get("z")
            self.spot_note = (f"X, Y = ({spot['x']}, {spot['y']}){f', z = {z}' if z is not None else ''} is a free "
                              f"spot {spatial._phrase(rel)} '{anchor['name']}' for {subject or 'it'} (measured: "
                              f"outside its footprint, clear of everything"
                              + (f"; turn it rotation={spot['rotation']} so its long side runs along it"
                                 if spot.get("rotation") else "") + "). Build it there.")
            return spot
        return None

    def available(self) -> tuple:
        if self.bridge is None or not self.bridge.ping(timeout=3):
            return False, "I can't reach Blender's scripting bridge, so I can't build there right now."
        return True, ""

    def prepare(self) -> None:
        # The kit is reloaded whenever its source differs from what this Blender has (a hash, not a hand-kept
        # version number: an edit without a version bump once left Blender running an older kit).
        import hashlib
        source = kit_source()
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]
        response = self.bridge.run("RESULT = str(globals().get('KIT_HASH'))", timeout=8)
        if response.get("output") != digest:
            # Compiled under its own name, so an error inside the kit is never reported as a line of the AI's code.
            loaded = self.bridge.run(f"exec(compile({source!r}, '<kit>', 'exec'), globals())\n"
                                     f"KIT_HASH = {digest!r}\nRESULT = str(KIT_VERSION)", timeout=20)
            if not loaded.get("ok"):
                raise RuntimeError(f"Blender couldn't load my building kit: {self._short_error(loaded)}")
        # What's in the scene now is the user's (or an earlier request's): this request may only replace it when
        # it asks to. And the last request's "undo" has moved on, so its trash can go.
        protect = "set()" if _REPLACE_ASKED.search(self.goal or "") else (
            "{o.name for o in bpy.data.objects if o.users_collection}")
        import random
        state = self.observe()
        x, y = free_spot(state)
        self.intents = self._intents(self.goal)
        self.spot_note, self.relation_spot, self.notes = "", None, []
        self.directed = None   # (events, seconds, fps) of the timeline this request directs, for its summary
        self.retired = []      # what the kit took away on purpose this request (never reported as "lost")
        spot = _SPOT.search(self.goal or "")
        if spot:
            x, y = float(spot.group(1)), float(spot.group(2))
        else:
            self.relation_spot = self._relation_spot(self.goal, state)
            if self.relation_spot:
                x, y = self.relation_spot["x"], self.relation_spot["y"]
        hint = _HINT.search(self.goal or "")
        self.direction_note = self._direction_note(self.goal, state)
        salt = random.randint(1, 10 ** 6)
        # X, Y: where this request builds (the free spot, or where a scene placed it); r: a random generator.
        ready = self.bridge.run(f"purge_trash()\nif 'purge_snapshots' in globals(): purge_snapshots()\n"
                                f"PROTECTED.clear()\nPROTECTED.update({protect})\nALIASES.clear()\n"
                                f"SALT = {salt}\nNAME_HINT = {(hint.group(1) if hint else '')!r}\nX, Y = {x}, {y}\n"
                                f"r = rng({salt % 1000})\nRESULT = 'ready'", timeout=10)
        if not ready.get("ok"):
            # Never build on a half-prepared Blender: X, Y and the protected names would be the last request's.
            raise RuntimeError(f"Blender couldn't get ready for this: {self._short_error(ready)}")

    def observe(self) -> dict:
        response = self.bridge.run("RESULT = scene_state()", timeout=10)
        if not response.get("ok"):
            return {"objects": [], "error": self._short_error(response)}
        try:
            return json.loads(response.get("output") or "{}")
        except ValueError:
            return {"objects": [], "error": "the scene couldn't be read"}

    def describe(self, state: dict) -> str:
        if state.get("error"):
            return f"(couldn't read the scene: {state['error']})"
        lines = []
        objects = state.get("objects", [])
        groups = _repeated([o for o in objects if o["type"] == "MESH"])
        summarised = set()
        for base, objs in groups.items():
            if len(objs) >= 4:
                mn = [min(o["min"][i] for o in objs) for i in range(3)]
                mx = [max(o["max"][i] for o in objs) for i in range(3)]
                colors = sorted({o.get("color_name") or "none" for o in objs})
                lines.append(f"- '{base} 1'..'{base} {len(objs)}' ({len(objs)} similar parts): together x {mn[0]}..{mx[0]}, "
                             f"y {mn[1]}..{mx[1]}, z {mn[2]}..{mx[2]}, color {'/'.join(colors)}")
                summarised |= {o["name"] for o in objs}
        for o in [o for o in objects if o["name"] not in summarised][:60]:
            if o["type"] == "MESH":
                mn, mx, s = o["min"], o["max"], o["size"]
                lines.append(f"- '{o['name']}': x {mn[0]}..{mx[0]}, y {mn[1]}..{mx[1]}, z {mn[2]}..{mx[2]} "
                             f"(size {s[0]} x {s[1]} x {s[2]}), color {o.get('color_name') or 'none'}")
            else:
                lines.append(f"- '{o['name']}' ({o['type'].lower()}) at {o['location']}")
        extra = len([o for o in objects if o["name"] not in summarised]) - 60
        if extra > 0:
            lines.append(f"(+{extra} more objects)")
        if state.get("active"):
            lines.append(f"Selected/active: '{state['active']}'")
        taken = sorted({o["name"].split()[0] for o in objects if o["type"] in ("MESH", "EMPTY")})
        if taken:
            lines.append("Name prefixes already in use (pick new ones for new things, e.g. 'Bench 2'): " +
                         ", ".join(taken[:30]))
        ts = spatial.things(state)
        if ts:
            lines.append("The things in the scene (footprints seen from above; place new things by them with "
                         "spot_near(), never inside a building's footprint):")
            lines += spatial.describe(ts, limit=20)
        fx, fy = free_spot(state)
        lines.append(f"Free space for something new: around x={fx}, y={fy} (z=0), clear of everything above. Build "
                     "new things there unless the request says where (\"next to the house\": spot_near('House', "
                     "'beside', ...)).")
        if self.spot_note:
            lines.append(self.spot_note)
        tl = state.get("timeline")
        if tl:
            fps_ = float(tl.get("fps") or 24)
            seconds = (int(tl.get("end", 250)) - int(tl.get("start", 1)) + 1) / fps_
            lines.append(f"Timeline: frames {tl.get('start')}-{tl.get('end')} at {fps_:g} fps ({seconds:.1f} s); "
                         f"active camera: {tl.get('camera') or 'none'}. Times in kit calls are seconds.")
        moving = [o["name"] for o in objects if o.get("animated") and not o.get("parent")]
        if moving:
            lines.append("Already animated: " + ", ".join(repr(n) for n in moving[:12]))
        cams = [f"'{o['name']}' (lens {o['camera']['lens']}" + (f", filming {o['camera']['subject']}" if
                                                                 o['camera'].get('subject') else "") + ")"
                for o in objects if o.get("camera")]
        lights_ = [f"'{o['name']}' ({o['light']['kind'].lower()}, {o['light']['energy']:g} W)" for o in objects
                   if o.get("light")]
        if cams:
            lines.append("Cameras: " + ", ".join(cams[:6]))
        if lights_:
            lines.append("Lights: " + ", ".join(lights_[:10]) + (f" (+{len(lights_) - 10} more)" if len(lights_) > 10
                                                                  else ""))
        if self.direction_note:
            lines.append(self.direction_note)
        return "\n".join(lines)


    def instructions(self) -> str:
        return INSTRUCTIONS

    def quick_plan(self, goal: str, state: dict, ask_json):
        """A plan without the general planner when the request is about a finished asset: building one ("a detailed
        house", "two palm trees", "a tropical island with palm trees") is ONE structured choice of the asset and its
        options, and changing one ("bigger windows", "make it two floors") is a rebuild with options changed. None:
        plan normally."""
        text, _ = save_request(" ".join((goal or "").split()).split(" — ")[0])   # (the save: closing_steps)
        hint = _HINT.search(goal or "")   # one thing of a scene, already named and placed (AgentTask._run_scene)
        if not hint:
            closer = self._match_reference_plan(text)   # (before a rebuild: "more like the photo" says "photo" too)
            if closer is not None:
                return closer
            rebuild = self._reconstruction_plan(text, state)
            if rebuild is not None:
                return rebuild
            # a change to what's there ("add fog", "make it sunset", "move the camera closer") comes before
            # directing — except a timed or moving shot ("a 10-second orbit"), which is the director's
            timed = cinema.parse_duration(text) is not None or _CAMERA_MOVES.search(text) or _TIMED.search(text)
            if not timed:
                edit = self._edit_plan(text)
                if edit is not None:
                    return edit
            direction = self._direction_plan(text, state)
            if direction is not None:
                return direction
            if timed:
                edit = self._edit_plan(text)
                if edit is not None:
                    return edit
        path = self._path_plan(goal, text, state, hint.group(1) if hint else None)
        if path is not None:
            return path
        build = _BUILD_VERB.match(text)
        if build and not hint and not _CHANGE_TARGET.match(text[build.end():]):
            place = self._place_build_plan(text, text[build.end():], state)
            if place is not None:
                return place
        if hint or (build and not _CHANGE_TARGET.match(text[build.end():])):
            return self._asset_build_plan(text, state, ask_json, hint.group(1) if hint else None)
        return self._asset_edit_plan(text, state, ask_json)

    # ---------- a picture, rebuilt in 3D ----------
    def set_progress(self, say) -> None:
        self.progress = say

    def _say(self, text: str) -> None:
        if self.progress is not None:
            try:
                self.progress(text)
            except Exception:
                pass

    @staticmethod
    def _latest_image():
        try:
            import images
            last = images.last_image(1)
            return last[-1]["path"] if last and os.path.exists(last[-1]["path"]) else None
        except Exception:
            return None

    def _reconstruction_plan(self, text: str, state: dict):
        """"Recreate this picture in Blender": look at it properly (visual_scene: what, where, how big, lit how,
        from where), then a plan of verified steps that rebuilds it with finished assets (reconstruct.py)."""
        import reconstruct   # (here, not at the top: Blender imports this module too, and has no Pillow)
        if not reconstruct.is_reconstruction_request(text):
            return None
        image = self.reference_image or self._latest_image()
        if not image:
            return {"understanding": text, "steps": [], "final_checks": [],
                    "question": "Which picture? Attach the image you want rebuilt, then ask me again."}
        import vision
        import visual_scene
        try:
            self._say("Looking at the picture…")
            scene = visual_scene.analyze(image, progress=self._say)
        except vision.VisionUnavailable as e:
            return {"understanding": text, "steps": [], "final_checks": [],
                    "question": f"I can't rebuild it: {e}."}
        finally:
            try:   # the 6 GB vision model out of the GPU: Blender (and the agent's model, if a repair needs it) next
                import local_llm
                local_llm.unload_all(wait=4.0)
            except Exception:
                pass
        # what's already in the scene stays: the rebuild goes beside it, never on top of it
        offset = (0.0, 0.0)
        mine = [t for t in spatial.things(state) if t["category"] not in ("ground", "sky")]
        if mine:
            far = max(t["outer"][2] for t in mine)
            offset = (far + 60.0, 0.0)
        self._say("Planning the rebuild…")
        plan = reconstruct.build_plan(scene, state, offset)
        self.reconstruction = {"scene": scene, "built": plan["built"], "image": image,
                               "behaviours": plan.get("behaviours", []), "offset": offset}
        return plan

    _MORE_LIKE = re.compile(r"\b(?:more like|closer to|match|compare (?:it )?(?:with|to))\b.*\b(?:photo|picture|"
                            r"image|reference|original)\b", re.I)

    def _match_reference_plan(self, text: str):
        """"Make it look more like the photo": the reference this scene was rebuilt from (kept, scene_state) is
        compared with the scene as it is now, and the biggest differences fixed — only when asked; the reference
        never overrides changes the user made by itself."""
        if not self._MORE_LIKE.search(text or "") or self.bridge is None:
            return None
        current = scene_state.read_current(self.bridge)
        ref = scene_state.load_reference(current.get("scene_id")) if current.get("scene_id") else None
        if not ref or not os.path.exists(str(ref.get("image") or "")):
            return {"understanding": text, "steps": [], "final_checks": [],
                    "question": "This scene wasn't rebuilt from a picture I still have — attach the photo and ask me "
                                "to recreate it."}
        self.reconstruction = {"scene": ref["visual_scene"], "built": ref["built"], "image": ref["image"],
                               "behaviours": [], "again": True}
        return {"understanding": "Compare the scene with its photo and fix the biggest differences",
                "question": "", "final_checks": [], "reconstruction": True,
                "steps": [{"title": "Look at the scene as it is", "code": "RESULT = env_state()", "checks": []}]}

    def vision_compare(self, reference_path: str, render_path: str):
        import visual_critique
        return visual_critique.vision_compare(reference_path, render_path)

    def _resolver(self):
        """What 'that', 'it' and 'the one I mentioned' mean carries over from one request to the next."""
        holder = self.session if self.session is not None else BlenderAdapter
        res = getattr(holder, "scene_resolver", None)
        if res is None:
            res = scene_state.Resolver()
            try:
                setattr(holder, "scene_resolver", res)
            except Exception:
                pass
        return res

    def _edit_plan(self, text: str):
        """A change to the scene that exists ("add fog", "turn on the house lights", "show it from behind"), read
        against the scene as it is NOW (scene_state)."""
        if self.bridge is None:
            return None
        current = scene_state.read_current(self.bridge)
        if not current:
            return None
        plan = scene_edit.plan(text, current, self._resolver())
        if plan is not None and plan.get("steps"):
            self.edit = {"text": text, "understanding": plan.get("understanding"), "scene_id": current.get("scene_id")}
        return plan

    # ---------- directing: time, cameras, light and motion ----------
    def stages(self, goal: str) -> list:
        """A request that builds AND directs ("create a villa with a pool and make a 10-second cinematic where the
        camera approaches it") as two stages: the scene first, then the cinematic of it."""
        if _HINT.search(goal or ""):
            return [goal]
        text, saving = save_request(" ".join((goal or "").split()))
        parts = cinema.split_stages(text)
        if not parts:
            return [goal]
        if saving is not None:   # "... and save it": after everything
            parts[-1] += " and save it" + (f" as {saving}" if saving else "")
        return parts

    @staticmethod
    def _direction_note(goal: str, state: dict) -> str:
        """The request's timing worked out in seconds AND frames, for the planner's code."""
        text = (goal or "").split(" — ")[0]
        if not cinema.is_direction(text):
            return ""
        tl = state.get("timeline") or {}
        fps_ = float(tl.get("fps") or 24)
        d = cinema.parse_direction(text, fps=fps_)
        if not d["events"]:
            return ""
        events, D = cinema.schedule(d)
        start = int(tl.get("start") or 1)
        lines = [f"The request's timeline: {D:g} s = frames {start}-{cinema.to_frame(D, d['fps'] or fps_, start)} at "
                 f"{d['fps'] or fps_:g} fps (call timeline({D:g}) first). Its events:"]
        for e in events:
            lines.append(f"  {e['start']:g}-{e['end']:g} s: {e['clause']} ({e['kind']} {e['move']}"
                         + (f", {e['subject']}" if e.get('subject') else "") + ")")
        return "\n".join(lines)

    def _direction_plan(self, text: str, state: dict):
        """A request that only directs what's there — time, cameras, light, motion — as a timeline of kit calls,
        every subject found in the real scene and every call verified (keys made, motion real, subject framed,
        lights on). None when it isn't one, or the parser didn't understand all of it (the planner then gets the
        timeline as context)."""
        if not cinema.is_direction(text):
            return None
        tl = state.get("timeline") or {}
        fps_ = float(tl.get("fps") or 24)
        d = cinema.parse_direction(text, fps=fps_)
        if not d["events"] or not d["understood"] or any(cinema.is_build(c) for c in d["clauses"]):
            return None
        ts = spatial.things(state)
        existing = None
        if d["duration"] is None and any(o.get("animated") for o in state.get("objects", [])) and tl:
            existing = round((int(tl.get("end", 250)) - int(tl.get("start", 1))) / fps_, 2)
        events, D = cinema.schedule(d, d["duration"] or existing)
        missing = []

        def name_of(noun, required=True, e=None):
            """The thing a noun means — or, when no whole thing does, the parts of one it means ("the palm trees"
            on an island): all of them when said in the plural, else the first."""
            if not noun:
                return None
            t = spatial.find_thing(ts, noun)
            if t is None and noun in spatial.DOOR_WORDS:
                t = next((x for x in ts if any(w in n.lower() for n in x["names"] for w in ("door", "gate"))), None)
            if t is None:
                parts = [n for _, n in spatial.find_parts(ts, noun)]
                if parts:
                    plural = e is not None and self._subject_phrase(e).lower().endswith("s")
                    return parts[:6] if plural and len(parts) > 1 else parts[0]
            if t is None and required:
                missing.append(noun)
            return t["name"] if t else None
        buildings = [t for t in ts if t["category"] == "building"]
        main = max(buildings or [t for t in ts if t["category"] not in ("ground", "sky")] or [None],
                   key=lambda t: spatial.area(t["outer"]) if t else 0)
        main_name = main["name"] if main else None

        def sky_changes(e):
            return e["move"] in ("day_to_night", "night_to_day") or e.get("explicit") or re.search(
                r"\b(?:sets?|rises?|falls?|becomes?|turns?|changes?|fades?|goes? down|comes? up)\b", e["clause"], re.I)
        # Wind, weather, a sky that stays as it is: they go on for as long as the scene's timeline does — nothing to
        # time, so the timeline is left alone (and not announced as "a 10.38-second shot").
        timeless = d["duration"] is None and not cinema.parse_fps(text) and all(
            e["kind"] in ("wind", "weather") or (e["kind"] == "sky" and not sky_changes(e)) for e in events)
        steps = [] if timeless else [
            {"title": f"Set the timeline to {D:g} seconds", "checks": [],
             "code": f"RESULT = str(timeline({D:g}" + (f", fps_={cinema.parse_fps(text)}" if cinema.parse_fps(text)
                                                     else "")
                     # a length the user said is the length: an older, longer move doesn't stretch it
                     + (", keep_longer=False" if d["duration"] else "") + "))"}]
        final = [] if timeless else [{"type": "timeline", "min": round(D, 2)}]
        for e in events:
            st, en = round(e["start"], 2), round(e["end"], 2)
            kind, move, p = e["kind"], e["move"], e.get("params") or {}
            title, code, checks = e["clause"][:70], None, []
            if kind in ("camera", "shot"):
                subj = name_of(e["subject"], required=bool(e["subject"]), e=e)
                args = [repr("Camera"), repr(move), repr(subj), f"start={st}", f"end={en}"]
                if kind == "camera":
                    if p.get("shot") and move in ("push_in", "reveal", "crane"):
                        args.append(f"shot_to={p['shot']!r}")
                    if p.get("sweep") is not None:
                        args.append(f"sweep={p['sweep']}")
                    if p.get("direction"):
                        args.append(f"direction={p['direction']!r}")
                    if move == "pan" and p.get("to"):
                        to = name_of(p["to"])
                        if p.get("from"):
                            args[2] = repr(name_of(p["from"]))
                        args.append(f"to={to!r}")
                code = f"camera_move({', '.join(args)})"
                checks = [{"type": "camera_frames", "object": "Camera",
                           "other": (subj[0] if isinstance(subj, list) else subj) or ""}]
            elif kind == "lights":
                subj = name_of(e["subject"], required=False) if e["subject"] else None
                if subj is None and (p.get("inside") or not any(o.get("type") == "LIGHT" for o in state.get("objects", [])
                                                                if (o.get("light") or {}).get("kind") != "SUN")):
                    subj = main_name
                fn = "lights_on" if move == "on" else "lights_off"
                code = f"{fn}({subj!r}, start={st}, end={en}, ease='smooth')"
                checks = [{"type": "light_on" if move == "on" else "light_off", "object": subj or ""}]
            elif kind == "sky":
                if move == "dramatic":
                    code = f"lighting('dramatic', {main_name!r})"
                elif sky_changes(e):
                    code = f"sky({move!r}, start={st}, end={en})"
                    checks = [{"type": "animated", "object": "Sun"}]
                else:
                    code = f"sky({move!r})"
                    checks = [{"type": "exists", "object": "Sun"}]
            elif kind == "weather":
                code = f"{move}({move.title()!r}, heavy={bool(p.get('heavy'))})"
                checks = [{"type": "animated", "object": move.title()}]
            elif kind == "wind":
                blown = self._wind_targets(ts)
                if not blown:
                    return {"understanding": text, "steps": [], "final_checks": [],
                            "question": "There's nothing here the wind would move — no trees, bushes or flags. "
                                        "Should I add some?"}
                code = f"RESULT = str(wind({p.get('strength', 1.0)}))"
                checks = [{"type": "animated", "object": n} for n in blown[:3]]
            elif kind == "action":
                # whose door it is, when said ("the garage door"): that building's, not just any building's
                subj = name_of(p["of"]) if move in ("open", "close") and p.get("of") else name_of(e["subject"], e=e)
                group = subj if isinstance(subj, list) else None   # "the palm trees sway": each of them
                subj = group[0] if group else subj
                if move in ("open", "close"):
                    code = (f"open_door({subj!r}, start={st}, end={en}, ease='out')" if move == "open" else
                            f"close_door({subj!r}, start={st}, end={en})")
                elif move == "travel":
                    to = name_of(p.get("to")) if p.get("to") else None
                    frm = name_of(p.get("from"), required=False) if p.get("from") else None
                    if to is None:
                        missing.append(p.get("to") or "where it should go")
                    end_arg = f"end={en}" if e.get("explicit") or e.get("end") else "end=None"
                    code = f"drive({subj!r}, {to!r}, start_place={frm!r}, start={st}, {end_arg})"
                    checks = [{"type": "moves_to", "object": subj, "other": to or ""}]
                elif move == "sway":
                    code = f"sway({subj!r}, strength={p.get('strength', 1.0)})" if subj else "RESULT = str(wind())"
                elif move == "spin":
                    code = (f"spin({subj!r}, {p.get('degrees', 360.0)}, {p.get('axis', 'z')!r}, start={st}, end={en}, "
                            f"ease={'linear' if e.get('loop') else e.get('ease', 'smooth')!r}, loop={bool(e.get('loop'))})")
                elif move == "bounce":
                    code = f"bounce({subj!r}, {p.get('distance', 1.0)}, 3, start={st}, end={en})"
                elif move == "rise":
                    code = f"rise({subj!r}, {p.get('distance', 2.0)}, start={st}, end={en})"
                elif move == "fall":
                    code = f"rise({subj!r}, -bottom({subj!r}), start={st}, end={en}, ease='in')"
                elif move in ("grow", "shrink"):
                    code = f"scale_to({subj!r}, {1.5 if move == 'grow' else 0.6}, start={st}, end={en})"
                elif move == "appear":
                    code = f"appear({subj!r}, at={st})"
                elif move == "disappear":
                    code = f"disappear({subj!r}, at={st})"
                elif move == "colour":
                    code = f"colour_to({subj!r}, {p.get('colour', 'red')!r}, start={st}, end={en})"
                if subj and not checks:
                    checks = [{"type": "animated", "object": subj}]
                if group and code and move not in ("open", "close", "travel"):
                    code = "\n".join(code.replace(repr(subj), repr(n)) for n in group)
                    checks = [{"type": "animated", "object": n} for n in group[:3]]
            if code is None:
                return None
            if kind in ("sky", "weather", "wind"):   # (said in passing — "orbits the villa at sunset" — so named apart)
                title = {"sky": f"{move.replace('_', ' ')} light", "wind": "the wind blows"}.get(
                    kind, f"{move} falls")
            steps.append({"title": title[0].upper() + title[1:], "code": code, "checks": checks})
            final += [c for c in checks if c not in final]
        if missing:
            return {"understanding": text, "question": f"I can't find {missing[0]!r} in the scene — should I build it "
                                                       "first, or did you mean something else?",
                    "steps": [], "final_checks": []}
        understanding = agent_tidy(text[0].upper() + text[1:], "Direct the scene")
        self.directed = (events, None if timeless else D, d["fps"] or fps_)
        return {"understanding": understanding, "question": "", "steps": steps, "final_checks": final,
                "direction": True}

    def finishing_touches(self, before, goal: str) -> list:
        if self.reconstruction is not None:
            return self._finish_reconstruction()
        touches = self._natural_touches(before, goal)
        try:
            touches += self._environment_touches(before, goal)
        except AppGone:
            raise
        except Exception as e:   # the thing asked for is built either way; its world is a finish, said if it fails
            print(f"Environment failed: {type(e).__name__}: {e}", flush=True)
        return touches

    def _environment_touches(self, before, goal: str) -> list:
        """What was built stands in a place (environment.py): its ground, planting, what stands with it, its sky,
        light and air, a breeze — then a camera that shows it all, checked from the camera by eye (a render: the
        subject whole and well placed, sky in view, light readable) and adjusted until it is."""
        request = (goal or "").split(" — ")[0]
        if before is None or self.directed or self.edit is not None or self.bridge is None:
            return []
        state = self.observe()
        plan = environment.plan(request, state, before)
        if plan is None:
            return []
        self._say(f"Building its surroundings ({plan['setting']})…")
        done = []
        for st in plan["steps"]:
            response = self.bridge.run(st["code"], timeout=240)
            if response.get("ok"):
                done.append(st["title"])
            else:
                print(f"Environment step {st['title']!r} failed: {self._short_error(response)}", flush=True)
        if not done:
            return []
        self.bridge.run(f"bpy.context.scene['jervis_environment'] = {plan['setting']!r}\nRESULT = 'ok'", timeout=10)
        self._motion_cache = None
        looked = self._frame_environment(plan)
        said = ", ".join(plan["said"][:6])
        out = [f"set it in its place ({plan['setting']}): {said}"]
        if looked:
            out.append(looked)
        return out

    def _frame_environment(self, plan: dict) -> str:
        """A camera on the whole place — the subject with ground before it and sky above — rendered and looked at:
        cut off, lost, sky-less, too dark or washed out is fixed (closer, farther, tilted, exposed) and looked at
        again, a few times at most. Says what it checked."""
        import tempfile
        try:
            import image_analysis
            from PIL import Image
        except ImportError:
            return ""
        subjects = plan["subjects"]
        shot = "wide" if plan["setting"] != "interior" else "medium"
        # low, as an architectural or landscape photograph is taken: ground before it, the subject, sky above
        elevation = 7 if plan["setting"] != "interior" else 4
        if plan.get("place"):   # a place asked for itself: its land (measured in Blender), not its sea
            ok = self.bridge.run(f"camera_on_place('Camera', {plan['place']!r}, {shot!r}, elevation={elevation})\n"
                                 "RESULT = 'ok'", timeout=60).get("ok")
            if not ok and plan.get("frame_box"):
                lo, hi = plan["frame_box"]
                self.bridge.run(f"camera_on_box('Camera', {lo!r}, {hi!r}, {shot!r}, elevation={elevation})\n"
                                "RESULT = 'ok'", timeout=60)
        else:
            self.bridge.run(f"camera('Camera', {subjects!r}, {shot!r}, elevation={elevation})\nRESULT = 'ok'",
                            timeout=60)
        fixed, problems = [], []
        work = tempfile.mkdtemp(prefix="jervis-env-")
        for k in range(4):
            # nothing planted between the camera and it (a stand of trees grew where the camera came to stand)
            self.bridge.run(f"RESULT = clear_view('Camera', {subjects or None!r})", timeout=60)
            path = os.path.join(work, f"look_{k}.png")
            r = self.bridge.run(f"RESULT = render_view({path!r}, width=480, samples=8)", timeout=240)
            if not r.get("ok") or not os.path.exists(path):
                return ""
            frames = {}
            try:
                frames = json.loads(self.bridge.run("RESULT = thing_frames()", timeout=30).get("output") or "{}")
            except ValueError:
                pass
            seen = [frames[n] for n in subjects if n in frames] if subjects else \
                [[0.2, 0.2, 0.8, 0.8, 1.0]]   # (a stretch of a place: no one thing to find in the frame)
            frame = None
            if seen:
                frame = (min(f[0] for f in seen), min(f[1] for f in seen), max(f[2] for f in seen),
                         max(f[3] for f in seen), min(f[4] for f in seen))
            img = Image.open(path).convert("RGB")
            st = image_analysis.stats(img)
            try:   # the sky's share, from the camera itself (pale sand, snow or sea look like sky to a pixel test)
                horizon = float(self.bridge.run("RESULT = camera_horizon('Camera')", timeout=20).get("output"))
            except (TypeError, ValueError):
                horizon = None
            m = {"frame": frame, "sky": horizon, "brightness": st.get("brightness", st.get("mean"))}
            problems = environment.assess(m, plan["setting"])
            if not problems:
                break
            text, fix = problems[0]
            if k == 3:
                break
            if fix.get("reframe"):
                code = f"camera('Camera', {subjects!r}, 'establishing')"
            elif "exposure" in fix:
                code = (f"bpy.context.scene.view_settings.exposure = "
                        f"max(-2.0, min(2.5, bpy.context.scene.view_settings.exposure + {fix['exposure']}))")
            else:
                code = "camera_edit('Camera', " + ", ".join(f"{a}={v}" for a, v in fix.items()) + ")"
            if self.bridge.run(code + "\nRESULT = 'ok'", timeout=60).get("ok"):
                fixed.append(text)
        if fixed:
            return "looked at it from the camera and fixed: " + "; ".join(dict.fromkeys(fixed))
        return "looked at it from the camera: " + ("all of it in view, sky above, well lit" if not problems
                                                  else "still " + problems[0][0])

    def _finish_reconstruction(self) -> list:
        """A rebuilt picture, checked by eye: render, compare with the picture, fix the biggest mismatch, again
        (visual_critique) — then its reference kept with the scene (scene_state)."""
        import visual_critique
        rec = self.reconstruction
        touches = []
        try:
            self._say("Comparing the render with the picture…")
            result = visual_critique.run(self, rec["scene"], rec["built"], rec["image"], log=print)
            rec["critique"] = result
            if result.get("fixes"):
                touches.append(f"compared it with the photo and {'; '.join(result['fixes'][:3])} "
                               f"(match {result['score_before']:.2f} -> {result['score_after']:.2f})")
            elif "score_after" in result:
                touches.append(f"compared it with the photo (match {result['score_after']:.2f})")
            remaining = (result.get("remaining") or {}).get("biggest_differences") or []
            if remaining:
                rec["remaining"] = remaining
        except Exception as e:
            print(f"Critique failed: {type(e).__name__}: {e}", flush=True)
        try:
            if rec.get("again"):
                raise StopIteration   # the reference is kept as it was
            scene_id = scene_state.save_reference(rec["scene"], rec["built"], rec["image"])
            self.bridge.run(f"bpy.context.scene['jervis_scene_id'] = {scene_id!r}\nRESULT = 'ok'", timeout=10)
            rec["scene_id"] = scene_id
        except (Exception, StopIteration):
            pass
        touches += [b for b in rec.get("behaviours", [])[:3]]
        return touches

    def _natural_touches(self, before, goal: str) -> list:
        """Whatever this request made that moves by nature now moves — water, fire, smoke, rain, snow, clouds, a
        flag, a windmill, and trees when the request speaks of wind — unless it asked for it static. Only motion
        Blender really shows over the timeline is reported."""
        request = (goal or "").split(" — ")[0]
        if before is None or cinema.is_static(request) or self.directed:   # (directed: it did what was asked)
            return []
        state = self.observe()
        by_name = {o["name"]: o for o in state.get("objects", [])}
        strength = 2.0 if re.search(r"\b(?:storm\w*|rough|wild|gale|choppy|huge waves|big waves|strong wind)\b",
                                    request, re.I) else \
            0.5 if re.search(r"\b(?:calm|gentle|still|quiet|peaceful|light breeze)\b", request, re.I) else 1.0
        done = []
        for t in spatial.things(state, before):
            if not t["new"]:
                continue
            motion = cinema.natural_motion(t, request)
            if not motion:
                continue
            already = any((by_name.get(n) or {}).get("motion") for n in t["names"])
            if not already:
                response = self.bridge.run(f"animate_naturally({t['name']!r}, {motion!r}, strength={strength})\n"
                                           "RESULT = 'ok'", timeout=60)
                if not response.get("ok"):
                    print(f"Natural motion for {t['name']} failed: {self._short_error(response)}", flush=True)
                    continue
            done.append((t["name"], motion))
        if cinema._WIND.search(request) and not any(m == "sway" for _, m in done):
            response = self.bridge.run(f"RESULT = json.dumps(wind({strength}))", timeout=60)
            try:
                done += [(n, "sway") for n in json.loads(response.get("output") or "[]")] if response.get("ok") else []
            except ValueError:
                pass
        if not done:
            return []
        self._motion_cache = None
        report = self._motion_report()
        state = self.observe()
        out = []
        for name, motion in done:
            entries = self._report_objects(report, name, state)
            if any(self._moved(e) for _, e in entries):
                out.append(f"{name} {_MOTION_WORDS.get(motion, 'moves')}" if motion in ("drift", "flutter", "sway", "spin")
                           else f"{_MOTION_WORDS.get(motion, 'it moves')} ({name})")
            else:
                print(f"Natural motion for {name} didn't show in Blender: not reported", flush=True)
        return list(dict.fromkeys(out))

    def _path_plan(self, goal: str, text: str, state: dict, given_name=None):
        """A path between two things that are there ("a path from the house to the pool", "a walkway to the
        garage", or a scene's path "running from 'Villa' to 'Pool'"): walkway() routes it on the real scene, from the
        building's door round everything in the way. None when it isn't such a request."""
        m = _RUNNING.search(goal or "")
        ts = spatial.things(state)
        if m and given_name:
            a, b = m.group("a"), m.group("b")
        else:
            if not set(spatial.words_of(text)) & spatial.PATH or not (given_name or _BUILD_VERB.match(text)):
                return None
            conn = next((i for i in spatial.parse_relations(text) if i["relation"] == "connects"), None)
            a_t = spatial.find_thing(ts, conn["anchor"]) if conn else None
            b_t = spatial.find_thing(ts, conn["to"], exclude=(a_t["name"],) if a_t else ()) if conn else None
            if a_t is None or b_t is None:
                return None
            a, b = a_t["name"], b_t["name"]
        name = given_name or _free_prefix("Path", state)
        style = ("stones" if re.search(r"\bstepping\b", text, re.I) else
                 "gravel" if re.search(r"\bgravel\b", text, re.I) else "pavers")
        width = 1.8 if re.search(r"\b(?:wide|broad|big)\b", text, re.I) else \
            0.8 if re.search(r"\b(?:narrow|small|little|thin)\b", text, re.I) else 1.2
        colour = next((c for c in sorted(blender_kit.COLORS, key=len, reverse=True)
                       if re.search(r"\b" + re.escape(c) + r"\b", text, re.I) and c not in ("water", "grass", "sky")),
                      None)
        extra = f", color={colour!r}" if colour else ""
        understanding = agent_tidy(text[0].upper() + text[1:], f"Build a path from {a} to {b}")
        return {"understanding": understanding, "question": "", "quick": True,
                "steps": [{"title": f"Lay a path from {a} to {b}", "quick": True, "checks": [],
                           "code": f"walkway({name!r}, {a!r}, {b!r}, width={width}, style={style!r}{extra})"}],
                "final_checks": [{"type": "exists", "object": f"{name} Bed"},
                                 {"type": "connects", "object": name, "other": a, "value": b}]}

    def _generic_anchor(self, text: str, state: dict):
        """(relation, the anchor thing's name, the intent) when the request places a new thing by anything already
        there ("a fountain behind the villa"), whatever built it. None otherwise."""
        ts = spatial.things(state)
        for intent in spatial.parse_relations(text):
            rel = spatial.normalize_relation(intent.get("relation"))
            if rel not in ("beside", "near", "front", "behind", "left", "right"):
                continue
            a = spatial.find_thing(ts, intent.get("anchor"))
            if a is not None:
                return rel, a["name"], intent
        return None

    @staticmethod
    def _anchor_category(name, state: dict) -> str:
        t = spatial.find_thing(spatial.things(state), name) if name else None
        return t["category"] if t else "building"

    def _spatial_spots(self, kind: str, options: dict, count: int, relation: str, anchor_name: str, state: dict):
        """`count` free spots for an asset `relation` a thing, each clear of the others: [{"x", "y", "rotation"}]."""
        ts = spatial.things(state)
        anchor = spatial.find_thing(ts, anchor_name)
        if anchor is None:
            return None
        size = _asset_size(kind, options)
        category = spatial.category_of(kind, kind)
        spots = []
        for i in range(count):
            spot = spatial.place_relative(anchor, relation, size, ts, category, orient=kind in ("pool", "fence"))
            if spot is None:
                return None
            spots.append(spot)
            ts = ts + [spatial.virtual_thing(f"__planned {i}", spot["rect"], category)]
        return spots

    def save_step(self, part: str):
        m = _SAVE_ONLY.match(" ".join((part or "").split()))
        if not m:
            return None
        name = (m.group("name") or "").strip()
        return {"title": "Save the file", "code": f"RESULT = save_file({name or None!r})", "checks": [], "quick": True}

    def subject_of(self, before, state: dict):
        roots = [(o["name"], o.get("asset_type")) for o in state.get("objects", [])
                 if o.get("kind") == "asset" and o.get("asset") == o["name"] and not o.get("parent")
                 and o["name"] not in (before or {})]
        return roots[-1] if roots else None

    def contextualize(self, part: str, subject) -> str:
        """After "create an island": "add trees" means on the island; after "build a house": "add a fence" means next
        to it. Only for a new thing that says nowhere itself."""
        if not subject or _ANCHOR.search(part) or not _BUILD_VERB.match(part):
            return part
        name, kind = subject
        return f"{part} on the {name}" if kind == "island" else f"{part} next to the {name}"

    def closing_steps(self, goal: str, plan: dict) -> list:
        """A save asked for at the end ("... and save it") runs after the plan, verified on disk."""
        _, name = save_request(goal)
        if name is None or any("save_file(" in s.get("code", "") for s in plan.get("steps", [])):
            return []
        return [{"title": "Save the file", "code": f"RESULT = save_file({name or None!r})", "checks": [],
                 "quick": True}]

    @staticmethod
    def _asset_roots(state: dict) -> dict:
        """The top-level finished assets in the scene: {root name: type}. An island's own palm trees are part of
        the island, not separate things a request could mean."""
        by_name = {o["name"]: o for o in state.get("objects", [])}
        roots = {}
        for o in state.get("objects", []):
            if not (o.get("asset") and o.get("asset_type")):
                continue
            root = by_name.get(o["asset"], {})
            if root.get("parent") and by_name.get(root["parent"], {}).get("asset"):
                continue   # inside another asset
            roots.setdefault(o["asset"], o["asset_type"])
        return roots

    def _anchor(self, text: str, state: dict):
        """(relation, asset root, its type, the phrase) when the request is about an asset already in the scene ("on
        the island", "next to the house"), else None."""
        roots = self._asset_roots(state)
        for m in _ANCHOR.finditer(text):
            word = m.group("word").lower()
            for root, kind in reversed(list(roots.items())):   # the most recent one of that kind
                if word in root.lower().split() or _asset_words(kind).fullmatch(word):
                    relation = m.group("rel").lower()
                    if kind == "island" and relation in ("to", "at", "around"):
                        relation = "on"   # "add trees to the island" puts them on it
                    return relation, root, kind, m.group(0)
        return None

    def _asset_build_plan(self, text: str, state: dict, ask_json, given_name=None):
        anchor = None if given_name else self._anchor(text, state)
        generic = None if given_name or anchor else self._generic_anchor(text, state)
        # Where it goes is decided here, from the scene; the AI only chooses what it is ("a cabin", not "on the
        # island" — which it once reported as a separate thing, sending the request to the general planner).
        what = " ".join(text.replace(anchor[3], " ").split()) if anchor else text
        if generic:
            what = _strip_relation(what, generic[2])
        elif given_name:   # a thing of a scene is already placed: "a pine tree behind it" is just "a pine tree"
            for intent in spatial.parse_relations(what):
                what = _strip_relation(what, intent)
        kinds = [k for k in blender_assets.ASSET_TYPES if _asset_words(k).search(what)]
        if not kinds:
            return None
        schema = {"type": "object", "properties": {
            "asset": {"type": "string", "enum": list(blender_assets.ASSET_TYPES) + ["none"]},
            "options": _options_schema(blender_assets.ASSET_TYPES),
            "count": {"type": "integer"}, "understanding": {"type": "string"}, "other_things": {"type": "string"}},
            "required": ["asset", "options", "count", "understanding", "other_things"]}
        try:
            raw = ask_json([{"role": "system", "content": ASSET_PROMPT.format(catalogue=_catalogue())},
                            {"role": "user", "content": f"Request: {what}"}], schema, max_tokens=400, temperature=0.1,
                           timeout=60)
        except Exception as e:   # no local AI: the general planner reports that properly
            print(f"Asset choice unavailable: {str(e)[:120]}", flush=True)
            return None
        kind = raw.get("asset")
        if anchor and (kind == anchor[2] or (anchor[2] == "island" and kind == "tree" and anchor[0] == "on")):
            # "add more trees to the island": a change to the island that's there, not a second island
            edit = self._asset_edit_plan(text, state, ask_json, root=anchor[1])
            if edit is not None or kind == anchor[2]:
                return edit
            # (no option change fits: new trees, standing on the island — placed below)
        # Only an asset the request itself names (the AI can't turn "a castle" into a house), and only when nothing
        # else was asked for alongside it (the general planner composes those, with the assets).
        if kind not in kinds or str(raw.get("other_things") or "").strip(" .").lower() not in ("", "none", "nothing"):
            return None
        options = _grounded(kind, _clean_options(kind, raw.get("options")), what)
        if kind == "house":
            for pattern, style in _NOUN_STYLE:   # "a cabin" is the cabin style, "a villa" the modern one
                if "style" not in options and pattern.search(what):
                    options["style"] = style
            if "width" not in options and _SMALL.search(what):
                options.update(width=5.6, depth=4.8)
            elif "width" not in options and _BIG.search(what):
                options.update(width=11.0, depth=8.5)
                options.setdefault("floors", 2)
        count = max(1, min(8 if kind in ("tree", "rock", "bush") else 3, int(raw.get("count") or 1)))
        if kind in ("island", "water") or given_name:
            count = 1
        said = _asset_words(kind).search(what).group(0).lower()
        said = re.sub(r"e?s$", "", said) if count > 1 and said not in ("grass",) else said
        base = said.title() if kind in ("house", "tree", "bench", "lounger") and said not in ("home", "dwelling") \
            else kind.title()
        if kind == "tree" and options.get("kind") and said == "tree":
            base = f"{options['kind'].title()} Tree"
        fn = kind
        spacing = _SPACING[kind] + (float(options.get("length") or 6.0) if kind == "fence" else 0.0)
        place = self._placement(kind, options, count, anchor, state) if anchor and not given_name else None
        if anchor and not given_name and place is None and anchor[0] in ("on", "onto", "in", "into", "at"):
            return None   # "a tree on the house": not something an asset placement can do; the planner decides
        if generic and kind not in ("island", "water"):
            place = self._spatial_spots(kind, options, count, generic[0], generic[1], state)
            if place is None:
                return None   # no room there: the planner explains or finds another way
        turns = [None] * count
        turned = _TURN.search(self.goal or "") if given_name else None
        if turned:   # a scene thing laid out along what it stands by ("turned rotation=90")
            turns = [int(turned.group(1))] * count
        if place and isinstance(place[0], dict):   # measured spots: (x, y) and which way to turn it
            anchor_cat = self._anchor_category(generic[1] if generic else (anchor[1] if anchor else None), state)
            turns = [_facing(kind, p, anchor_cat) if kind in _FACES else p.get("rotation") for p in place]
            place = [f"({p['x']:.2f}, {p['y']:.2f}, 0)" for p in place]
        # (X, Y) is a free spot 4 m beside what's already there: a big asset needs its centre further out.
        meshes = [o for o in state.get("objects", []) if o.get("type") == "MESH"]
        shift = 0.0 if given_name or not meshes else max(0.0, _footprint(kind, options) - 3.0) + (
            (count - 1) / 2 * spacing)
        lines, final = [], []
        used = dict(state)
        for i in range(count):
            name = given_name or _free_prefix(base if count == 1 else f"{base} {i + 1}", used)
            used = {"objects": used.get("objects", []) + [{"name": name}]}
            dx = (i - (count - 1) / 2) * spacing
            opts = dict(options)
            if turns[i] and kind in _ROTATES and kind != "house" and "rotation" not in opts:
                opts["rotation"] = turns[i]
            if count > 1 and kind in ("tree", "rock", "bush"):
                opts["seed"] = int(opts.get("seed", 0)) * 10 + i + 1
            args = "".join(f", {k}={v!r}" for k, v in opts.items())
            where = place[i] if place else f"(X + {dx + shift:.2f}, Y, 0)"
            lines.append(f"{fn}({name!r}, at={where}{args})")
            final.append({"type": "exists", "object": f"{name} {_MAIN_PART[kind]}"})
            final += _colour_checks(kind, name, opts)
        # The user's own words, never the AI's restatement: it once listed options it had made up ("a red roof,
        # rotate it 45 degrees") that were rightly NOT built — and the reply would have claimed them.
        understanding = agent_tidy(text[0].upper() + text[1:], "Build it")
        code = "\n".join(lines)
        if place and place[0].startswith("spots["):
            terrain = f"{anchor[1]} Terrain"
            room = round(_footprint(kind, options) * (0.55 if kind == "house" else 0.8), 1)
            flat = 12 if kind == "house" else 28
            # the flattest, clearest ground first; then a little steeper and closer to what's there
            code = (f"spots = []\n"
                    f"for slope, room in (({flat}, {room}), ({flat + 8}, {round(room * 0.7, 1)}), "
                    f"({flat + 14}, {round(room * 0.45, 1)})):\n"
                    f"    spots = scatter_on({terrain!r}, {count}, min_height=0.5, max_slope=slope, "
                    f"min_gap=room * 2, seed=SALT % 97, avoid=room)\n"
                    f"    if len(spots) >= {count}:\n"
                    f"        break\n"
                    f"if len(spots) < {count}:\n"
                    f"    raise ValueError('There is not enough free, level ground on {anchor[1]} for that.')\n" + code)
        return {"understanding": understanding, "question": "", "quick": True,
                "steps": [{"title": understanding.rstrip("."), "code": code, "checks": [], "quick": True}],
                "final_checks": final}

    def _place_build_plan(self, text: str, what: str, state: dict):
        """"Make a little bakery", "build a modern villa", "make a beach": the place-scale builder itself
        (storefront, villa, shore) — a finished model, never boxes — at a free spot; its world follows
        (environment.py, in the finishing touches)."""
        found = place_request(what)
        if found is None:
            return None
        builder, word = found
        opts = _place_options(builder, what)
        name = _free_prefix(word.title() if builder != "shore" else "Beach", state)
        args = "".join(f", {k}={v!r}" for k, v in opts.items())
        at = "(X, Y + 18, 0)" if builder == "shore" else "(X, Y, 0)"   # (a beach's sand runs toward -y)
        kind = {"storefront": "shop", "villa": "villa", "shore": "beach"}[builder]
        role = "the main building" if builder != "shore" else "the beach and the sea"
        code = (f"{builder}({name!r}, at={at}{args})\n"
                f"tag_semantic({name!r}, {kind!r}, role={role!r}, source='request')")
        understanding = agent_tidy(text[0].upper() + text[1:], "Build it")
        return {"understanding": understanding, "question": "", "quick": True,
                "steps": [{"title": understanding.rstrip("."), "code": code, "checks": [], "quick": True}],
                "final_checks": [{"type": "exists", "object": name}]}

    def _placement(self, kind: str, options: dict, count: int, anchor, state: dict):
        """Where new things go relative to an asset already there: ON an island (free, flat spots on its
        terrain), or BESIDE something (just clear of its footprint). None when the relation can't be placed."""
        relation, root, root_kind, _ = anchor
        if relation in ("on", "onto", "in", "into", "at") and root_kind == "island":
            return [f"spots[{i}]" for i in range(count)]
        rel = {"to": "beside", "by": "beside", "next to": "beside", "around": "near"}.get(
            relation, spatial.normalize_relation(relation))
        if rel in ("beside", "near", "front", "behind", "left", "right"):
            # Measured on the real scene: outside the anchor's footprint on the side asked (its own front, if it
            # was turned), its entrance kept free, clear of everything else that's there.
            return self._spatial_spots(kind, options, count, rel, root, state)
        return None

    def _asset_edit_plan(self, text: str, state: dict, ask_json, root: str = None):
        roots = self._asset_roots(state)
        if not roots:
            return None
        low = text.lower()
        focus = getattr(self.session, "blender_focus", None) if self.session is not None else None
        by_name = {o["name"]: o for o in state.get("objects", [])}
        named = [r for r in roots if re.search(r"\b" + re.escape(r.lower()) + r"\b", low)]
        typed = [r for r, kind in roots.items() if _asset_words(kind).search(text)
                 or (kind == "island" and _WATER_WORDS.search(text))]   # an island's sea is the island's
        focused = [by_name[focus]["asset"]] if focus in by_name and by_name[focus].get("asset") else []
        candidates = named or typed or (focused if re.search(r"\b(?:it|its|that|this)\b", low) else []) or (
            list(roots) if len(roots) == 1 else [])
        if root is None and len(set(candidates)) > 1 and typed and self.bridge is not None:
            # "the house" among several: in a rebuilt scene, the one the photo is about (its semantic role)
            current = scene_state.read_current(self.bridge)
            main = [t["name"] for t in current.get("things", []) if t.get("name") in candidates
                    and str(t.get("role") or "").startswith("the main")]
            if len(main) == 1:
                candidates = main
        if root is None:
            if len(set(candidates)) != 1:
                return None
            root = candidates[0]
        kind = roots[root]
        info = self.bridge.run(f"RESULT = json.dumps(asset_info({root!r}))", timeout=8)
        try:
            params = json.loads(info.get("output") or "null")["params"]
        except (TypeError, ValueError, KeyError):
            return None
        if kind not in blender_assets.ASSET_TYPES:   # a place-scale asset (villa, storefront, forest...): sizes
            options, known = {}, _size_change(text, params)
            if not known:
                return None
        else:
            options = blender_assets.ASSET_TYPES[kind]["options"]
            known = _known_change(kind, text, params)
        if known:
            known = {k: v for k, v in known.items() if params.get(k) != v}
            if known:
                args = ", ".join(f"{k}={v!r}" for k, v in known.items())
                if _GROWS & set(known):
                    args += f")\nmake_room({root!r}"
                what = text[0].upper() + text[1:]
                return {"understanding": what, "question": "", "quick": True,
                        "steps": [{"title": what, "code": f"rebuild_asset({root!r}, {args})", "checks": [],
                                   "quick": True}],
                        "final_checks": [{"type": "exists", "object": root}]}
            if kind not in blender_assets.ASSET_TYPES:
                return None
        schema = {"type": "object", "properties": {"fits": {"type": "boolean"}, "understanding": {"type": "string"},
                                                   "changes": _options_schema([kind])},
                  "required": ["fits", "changes", "understanding"]}
        try:
            raw = ask_json([{"role": "system", "content": EDIT_PROMPT.format(
                kind=kind, name=root, params=json.dumps({k: v for k, v in params.items() if v is not None}),
                options=json.dumps(options))}, {"role": "user", "content": f"Request: {text}"}], schema,
                max_tokens=300, temperature=0.1, timeout=60)
        except Exception as e:
            print(f"Asset change unavailable: {str(e)[:120]}", flush=True)
            return None
        changes = _grounded(kind, _clean_options(kind, raw.get("changes")), text, new=False)
        changes ={k: v for k, v in changes.items() if params.get(k) != v}
        if not raw.get("fits") or not changes:
            return None
        args = ", ".join(f"{k}={v!r}" for k, v in changes.items())
        if _GROWS & set(changes):   # bigger: what stood beside it keeps its place beside it, just clear of it
            args += f")\nmake_room({root!r}"
        understanding = agent_tidy(text[0].upper() + text[1:], f"Change {root}")   # (the user's words, see above)
        final = [{"type": "exists", "object": f"{root} {_MAIN_PART[kind]}"}] + _colour_checks(kind, root, changes)
        return {"understanding": understanding, "question": "", "quick": True,
                "steps": [{"title": understanding.rstrip("."), "code": f"rebuild_asset({root!r}, {args})",
                           "checks": [], "quick": True}],
                "final_checks": final}

    def quality_guidance(self, tier: str) -> str:
        return QUALITY_GUIDANCE.get(tier, QUALITY_GUIDANCE["normal"])

    scene_layout = True

    def known_names(self, state: dict):
        return {o["name"] for o in state.get("objects", [])}

    def place_scene(self, things: list, state: dict) -> list:
        """Put the AI's layout at the free spot beside what's already there, and push apart any two things whose
        footprints (by the AI's own radius) would overlap — so each thing gets room before it's built."""
        fx, fy = free_spot(state)
        used = {o["name"].lower() for o in state.get("objects", [])}
        prefixes = {n.rsplit(" ", 1)[0] for n in used} | {n.split()[0] for n in used if n}
        placed = []
        for t in things:
            name = str(t.get("name") or "Thing").strip()
            numbered = re.match(r"^(.*\S)\s+(\d+)$", name)
            base, k = (numbered.group(1), int(numbered.group(2)) + 1) if numbered else (name, 2)
            while name.lower() in prefixes or any(u.startswith(name.lower() + " ") for u in used):
                name, k = f"{base} {k}", k + 1
            prefixes.add(name.lower())
            t = dict(t, name=name)
            r = max(0.5, min(8.0, float(t.get("radius") or 1.5)))
            x, y = float(t.get("x") or 0), float(t.get("y") or 0)
            for _ in range(50):
                clash = next((p for p in placed if ((p["x"] - x) ** 2 + (p["y"] - y) ** 2) ** 0.5 < p["r"] + r + 1.0), None)
                if clash is None:
                    break
                dx, dy = x - clash["x"], y - clash["y"]
                d = (dx * dx + dy * dy) ** 0.5 or 1.0
                push = clash["r"] + r + 1.0 - d + 0.1
                x, y = x + dx / d * push if dx or dy else x + push, y + dy / d * push
            placed.append({"x": x, "y": y, "r": r})
            t = dict(t, x=round(fx + r + x, 2), y=round(fy + y, 2))
            placed[-1]["t"] = t
        return [p["t"] for p in placed]

    def place_thing(self, thing: dict, state: dict) -> dict:
        """Where one thing of a scene goes, measured on the scene as it is now (what it stands by is built by
        then): `relation` its anchor — outside a building's footprint, on the side asked, clear of everything — or,
        with no relation, the layout's spot nudged clear of what's there. A path just runs between its two ends."""
        ts = spatial.things(state)
        rel = spatial.normalize_relation(thing.get("relation"))
        # what the thing itself is (never what it stands by: "a tree near the bench" is no bench)
        words = f"{thing.get('name', '')} {spatial._first_noun(thing.get('request', '')) or ''}"
        category = spatial.category_of(thing.get("name", ""))
        if category == "object":
            category = spatial.category_of(spatial._first_noun(thing.get("request", "")) or "")
        if rel == "connects":
            a = spatial.find_thing(ts, thing.get("anchor"))
            b = spatial.find_thing(ts, thing.get("to"), exclude=(a["name"],) if a else ())
            if a is not None and b is not None:
                start = spatial.path_ends(a, b)[0]
                return dict(thing, x=start[0], y=start[1], placed=f"running from '{a['name']}' to '{b['name']}'")
            return thing
        try:
            w, d = float(thing.get("width") or 0), float(thing.get("depth") or 0)
        except (TypeError, ValueError):
            w = d = 0.0
        if not (0.2 <= w <= 80 and 0.2 <= d <= 80):
            # what it is: its name, else the first thing its request names ("a bench near the fountain": a bench)
            w, d = spatial.estimate_size(thing.get("name", ""), default=(0, 0))
            if not w:
                w, d = spatial.estimate_size(spatial._first_noun(thing.get("request", "")) or "", default=(0, 0))
            if not w:
                r = max(0.5, min(8.0, float(thing.get("radius") or 1.5)))
                w = d = 2 * r
        anchor = spatial.find_thing(ts, thing.get("anchor")) if rel else None
        if anchor is not None and rel not in ("between", ""):
            spot = spatial.place_relative(anchor, rel, (w, d), ts, category, orient=category in ("sunken",))
            if spot is not None:
                placed = f"standing {spatial._phrase(rel)} '{anchor['name']}'"
                kind = next((k for k in _FACES if re.search(r"\b(?:" + blender_assets.ASSET_TYPES[k]["words"] + r")",
                                                             words, re.I)), None)
                turn = _facing(kind, spot, anchor["category"]) if kind else spot.get("rotation")
                if turn:
                    placed += f", turned rotation={turn}"
                return dict(thing, x=spot["x"], y=spot["y"], placed=placed)
        spot = spatial.place_free(float(thing.get("x") or 0), float(thing.get("y") or 0), (w, d), ts, category)
        return dict(thing, x=spot["x"], y=spot["y"]) if spot else thing

    def scene_fix(self, before, state: dict, goal: str, things: list) -> tuple:
        """The whole scene, once every thing is built: each one where the layout said relative to the others,
        nothing standing inside anything, paths that really join their two ends. Repairs what it can (moves a
        thing, re-lays a path); returns (what it fixed, what's still wrong)."""
        intents = []
        for t in things:
            rel = spatial.normalize_relation(t.get("relation"))
            if rel and t.get("anchor"):
                intents.append({"subject": f"'{t['name']}'", "relation": rel, "anchor": f"'{t['anchor']}'",
                                "to": f"'{t['to']}'" if t.get("to") else None})
        intents += [i for i in spatial.parse_relations(goal) if i not in intents]
        request = (goal or "").split(" — ")[0]
        options = dict(underground_ok=bool(_UNDERGROUND_OK.search(request)), inside_ok=bool(_INSIDE_OK.search(request)))
        fixed = []
        try:
            fixed = self._spatial_repairs(lambda st: spatial.validate(st, before, intents, **options), state)
            if fixed:
                state = self.observe()
            wrong = [i["text"] for i in spatial.validate(state, before, intents, **options)]
        except Exception as e:
            print(f"Scene check failed: {type(e).__name__}: {e}", flush=True)
            return fixed, []
        return fixed, wrong

    @staticmethod
    def _short_error(response: dict) -> str:
        text = (response.get("error") or "unknown error").strip()
        lines = [l for l in text.splitlines() if l.strip()]
        where = next((l.strip() for l in reversed(lines) if '"<jervis>", line' in l), "")
        line_no = re.search(r"line (\d+)", where)
        last = lines[-1] if lines else text
        missing = re.match(r"NameError: name '(\w+)' is not defined", last)
        if missing:   # the model invented a helper (door(), window()): say what exists instead
            last += (f". There is no {missing.group(1)}() in the kit: build it from box/cylinder/cone/sphere/roof "
                     "(a door or window is a thin box), and use only the kit's functions")
        wrong_call = re.match(r"TypeError: (\w+)\(\) (?:got|missing|takes)", last)
        usage = _usage(wrong_call.group(1)) if wrong_call else ""
        if usage:   # a kit function called the wrong way: the next try sees how it's meant to be called
            last += f". Call it like this: {usage}"
        return (f"{last} (at line {line_no.group(1)} of your code)" if line_no else last)[:500]

    def execute(self, code: str) -> dict:
        self._motion_cache = None
        # Undo any kit name the last code reused as a variable, and start this step's record of what it makes.
        self.bridge.run("globals().update(_KIT)\ntry:\n    step_begin()\nexcept NameError:\n    pass", timeout=8)
        response = self.bridge.run(code + "\ntry:\n    _update()\nexcept Exception:\n    pass", timeout=45)
        if not response.get("ok") and "didn't answer in time" in (response.get("error") or "") \
                and not self.bridge.ping(timeout=3):
            raise AppGone("Blender stopped answering in the middle of that — it may have crashed, or be busy with "
                          "something else. Whatever it finished is still there; check Blender, then ask me again.")
        if not response.get("ok"):
            return {"ok": False, "output": response.get("output") or "", "error": self._short_error(response)}
        output = response.get("output") or ""
        step = self._step_record()
        if step is not None:
            made = [n for n in step.get("made", []) if not str(n).startswith("__")]
            notes = [str(w) for w in step.get("warnings", [])][:4]
            self.notes += [n for n in notes if n not in self.notes]
            self.retired += [n for n in step.get("retired", []) if n not in self.retired]
            if _MAKES.search(_code_only(code)) and not made:
                # The builders were never reached (a loop over an empty list, a function defined but not called):
                # the step ran without an error, but it did NOT do what it was for.
                return {"ok": False, "output": output, "error": "The code ran but built nothing: no builder call was "
                        "actually reached (check loops, conditions and functions that are never called)."}
            if notes:
                output = (output + " " if output else "") + "(Notes: " + "; ".join(notes) + ")"
        return {"ok": True, "output": output, "error": ""}

    def _step_record(self):
        """What the last step made and the kit's notes about it ({"made", "warnings"}), or None if unknown."""
        try:
            response = self.bridge.run("RESULT = json.dumps(STEP)", timeout=8)
            data = json.loads(response.get("output") or "") if response.get("ok") else None
        except (ValueError, TypeError, AttributeError):
            return None
        return data if isinstance(data, dict) and isinstance(data.get("made"), list) else None

    def snapshot(self):
        response = self.bridge.run(_SNAPSHOT_CODE, timeout=10)
        try:
            return json.loads(response.get("output") or "{}") if response.get("ok") else None
        except ValueError:
            return None

    def rollback(self, snapshot) -> None:
        self._motion_cache = None
        if snapshot is None:
            return
        response = self.bridge.run(_restore_code(snapshot), timeout=20)
        if not response.get("ok") and response.get("error"):
            # A repair must never start from a half-undone scene: try once more, then stop the task honestly.
            response = self.bridge.run(_restore_code(snapshot), timeout=30)
            if not response.get("ok") and response.get("error"):
                raise AppGone("I couldn't undo a failed step in Blender (" + self._short_error(response)[:160] +
                              "), so I stopped rather than build on top of it. Check the scene, then ask me again.")

    def evaluate(self, check: dict, state: dict) -> tuple:
        objects = [o for o in state.get("objects", [])]
        aliases = state.get("aliases") or {}
        kind = check.get("type")
        name = aliases.get(check.get("object") or "", check.get("object") or "")
        if check.get("other") in aliases:
            check = dict(check, other=aliases[check["other"]])
        if kind == "env":
            return self._env_check(check)
        if kind == "camera_safe":
            return self._camera_safe(name)
        if kind in _SPATIAL_CHECKS:
            return self._spatial_check(kind, dict(check, object=name), state)
        if kind in _MOTION_CHECKS:
            return self._motion_check(kind, dict(check, object=name), state)
        obj = _find(objects, name)
        if kind == "exists":
            return (obj is not None), f"'{name}' exists" if obj else f"there is no object named '{name}'"
        if kind == "absent":
            return (obj is None), f"'{name}' is gone" if obj is None else f"'{obj['name']}' is still there"
        if kind == "count":
            n = sum(1 for o in objects if name.lower() in o["name"].lower())
            low, high = check.get("min"), check.get("max")
            ok = (low is None or n >= low) and (high is None or n <= high)
            return ok, f"{n} object(s) named like '{name}'" + ("" if ok else f" (wanted {low if low is not None else 0}"
                                                                         f"{'' if high is None else f' to {high}'})")
        if obj is None:
            return False, f"there is no object named '{name}'"
        if kind == "color":
            wanted = check.get("color") or check.get("value") or ""
            try:
                family = blender_kit.color_name(blender_kit.rgb_of(wanted))
            except ValueError:
                return None, f"unknown color '{wanted}'"
            actual = obj.get("color_name")
            return actual == family, f"'{obj['name']}' is {actual or 'uncolored'}" + ("" if actual == family else
                                                                                     f", not {wanted}")
        if kind == "size":
            biggest = max(obj["size"])
            if biggest < 1e-6:   # a group's empty root ('House' of a built house): the whole group's extent
                kids, frontier = [], {obj["name"]}
                while frontier:
                    step_ = [o for o in objects if o.get("parent") in frontier and o.get("min") and o.get("max")
                             or (o.get("parent") in frontier and o.get("type") == "EMPTY")]
                    kids += step_
                    frontier = {o["name"] for o in step_} - frontier
                boxes = [o for o in kids if o.get("min") and o.get("max")]
                if boxes:
                    biggest = max(max(o["max"][i] for o in boxes) - min(o["min"][i] for o in boxes) for i in range(3))
            low, high = check.get("min"), check.get("max")
            ok = (low is None or biggest >= low - 1e-3) and (high is None or biggest <= high + 1e-3)
            return ok, f"'{obj['name']}' is {biggest:.2f} m across" + ("" if ok else f" (wanted {low}..{high})")
        other = _find(objects, check.get("other") or "")
        if other is None:
            return False, f"there is no object named '{check.get('other')}'"
        if kind == "above":
            # A crown sinking a little into its trunk, a roof's eaves overlapping the walls: still "above".
            sink = max(0.05, 0.25 * (obj["max"][2] - obj["min"][2]))
            ok = obj["min"][2] >= other["max"][2] - sink
            return ok, (f"'{obj['name']}' starts at z={obj['min'][2]}, '{other['name']}' ends at "
                        f"z={other['max'][2]}" + ("" if ok else f": '{obj['name']}' isn't above it"))
        if kind == "on_top":
            touching = abs(obj["min"][2] - other["max"][2]) <= 0.15
            over = (_overlap(obj["min"][0], obj["max"][0], other["min"][0], other["max"][0]) and
                    _overlap(obj["min"][1], obj["max"][1], other["min"][1], other["max"][1]))
            ok = touching and over
            return ok, (f"'{obj['name']}' is on '{other['name']}'" if ok else
                        f"'{obj['name']}' isn't resting on '{other['name']}' (its bottom z={obj['min'][2]}, "
                        f"the top of '{other['name']}' z={other['max'][2]}"
                        + ("" if over else ", and they don't overlap from above") + ")")
        if kind == "touching":
            ok = _touching(obj, other)
            return ok, f"'{obj['name']}' " + ("touches" if ok else "doesn't touch") + f" '{other['name']}'"
        if kind == "near":
            gap = sum(max(0.0, obj["min"][i] - other["max"][i], other["min"][i] - obj["max"][i]) ** 2
                      for i in range(3)) ** 0.5
            limit = check.get("max") if check.get("max") is not None else 1.5
            return gap <= limit, f"'{obj['name']}' is {gap:.1f} m from '{other['name']}'" + (
                "" if gap <= limit else f" (wanted at most {limit})")
        return None, f"unknown check type {kind!r}"

    def _env_check(self, check: dict) -> tuple:
        """{"type": "env", "path": "live.fog_density", "op": ">", "value": 0.0}: the environment as Blender has it."""
        response = self.bridge.run("RESULT = env_state()", timeout=15)
        try:
            env = json.loads(response.get("output") or "{}")
        except ValueError:
            return None, "the environment couldn't be read"
        cur = env
        for key in str(check.get("path") or "").split("."):
            cur = cur.get(key) if isinstance(cur, dict) else None
        want, op = check.get("value"), check.get("op", "==")
        try:
            ok = {"==": lambda a, b: a == b, ">": lambda a, b: float(a or 0) > float(b),
                  ">=": lambda a, b: float(a or 0) >= float(b), "<": lambda a, b: float(a or 0) < float(b),
                  "<=": lambda a, b: float(a or 0) <= float(b)}[op](cur, want)
        except (TypeError, ValueError, KeyError):
            ok = False
        return ok, f"{check.get('path')} is {cur!r}" + ("" if ok else f" (wanted {op} {want!r})")

    def _camera_safe(self, name: str) -> tuple:
        response = self.bridge.run(f"RESULT = camera_check({name or None!r})", timeout=20)
        try:
            c = json.loads(response.get("output") or "{}")
        except ValueError:
            return False, response.get("error") or "the camera couldn't be checked"
        if not c:
            return False, f"there's no camera {name!r}"
        if c.get("inside"):
            return False, f"'{c['camera']}' is inside {', '.join(c['inside'])}"
        if c.get("below_ground"):
            return False, f"'{c['camera']}' is below the ground"
        return True, f"'{c['camera']}' stands clear" + (f" (its view passes {c['blocked_by'][0]})"
                                                       if c.get("blocked_by") else "")

    # ---------- motion: what Blender really does over the timeline ----------
    def _motion_report(self, refresh: bool = False) -> dict:
        """motion_report() from Blender (sampled across the timeline), kept until the scene changes."""
        if self._motion_cache is not None and not refresh:
            return self._motion_cache
        response = self.bridge.run("RESULT = motion_report()", timeout=60) if self.bridge is not None else {}
        try:
            report = json.loads(response.get("output") or "") if response.get("ok") else None
        except (ValueError, TypeError):
            report = None
        self._motion_cache = report if isinstance(report, dict) else {"scene": {}, "objects": {}, "world": []}
        return self._motion_cache

    @staticmethod
    def _report_objects(report: dict, ref: str, state: dict) -> list:
        """The report's entries for what `ref` means: an object, or every object of the thing it names."""
        objs = report.get("objects", {})
        if not ref:
            return []
        if ref in objs:
            return [(ref, objs[ref])]
        t = spatial.find_thing(spatial.things(state), ref)
        names = set(t["names"]) if t else set()
        hits = [(n, e) for n, e in objs.items() if n in names or (t and e.get("parent") in names)
                or n.lower().startswith(str(ref).lower() + " ")]
        if not hits:
            low = str(ref).lower()
            hits = [(n, e) for n, e in objs.items() if low in n.lower()]
        return hits

    @staticmethod
    def _moved(entry: dict) -> bool:
        samples = [{k: v for k, v in s.items() if k not in ("view", "frame", "hidden")} for s in entry.get("samples", [])]
        if entry.get("particles"):
            return True
        return cinema.moved(samples)

    def _motion_check(self, kind: str, check: dict, state: dict) -> tuple:
        report = self._motion_report()
        scene = report.get("scene") or {}
        name, other = check.get("object") or "", check.get("other") or ""
        if kind == "timeline":
            fps_ = float(scene.get("fps") or 24)
            seconds = (int(scene.get("end", 0)) - int(scene.get("start", 0)) + 1) / fps_ if scene else 0.0
            want = float(check.get("min") or 0)
            return seconds >= want - 1 / fps_, f"the timeline is {seconds:.1f} s at {fps_:g} fps" + (
                "" if seconds >= want - 1 / fps_ else f" (wanted {want:g} s)")
        entries = self._report_objects(report, name, state)
        if kind in ("animated", "still"):
            if not entries:
                return (kind == "still"), f"nothing called '{name}' moves" if kind == "animated" else f"'{name}' is still"
            moving = [n for n, e in entries if self._moved(e)]
            if kind == "still":
                return not moving, f"'{name}' " + ("is still" if not moving else f"moves ({moving[0]})")
            return bool(moving), (f"'{moving[0]}' moves over the timeline" if moving else
                                  f"'{name}' has animation but doesn't actually move between frames "
                                  f"{scene.get('start')} and {scene.get('end')}")
        if kind == "keyframes":
            count = sum(e.get("keys", 0) for _, e in entries)
            want = int(check.get("min") or 1)
            return count >= want, f"'{name}' has {count} keyframes" + ("" if count >= want else f" (wanted {want})")
        if kind == "camera_frames":
            cams = [(n, e) for n, e in entries if e.get("type") == "CAMERA"] or \
                [(n, e) for n, e in report.get("objects", {}).items() if e.get("type") == "CAMERA" and
                 n == (scene.get("camera") or "")]
            if not cams:
                return False, f"there is no camera called '{name}'"
            cam_name, cam = cams[0]
            views = [s.get("view") for s in cam.get("samples", []) if s.get("view")]
            if not views:
                return None, f"'{cam_name}' films nothing I can check"
            subject = cam.get("camera", {}).get("subject") or []
            if other and subject and not any(other.lower() in n.lower() or n.lower() in other.lower() for n in subject):
                t = spatial.find_thing(spatial.things(state), other)
                if t is not None and t["name"] not in subject:
                    return False, f"'{cam_name}' films {', '.join(subject)}, not '{other}'"
            lost = [v for v in views if v["visible"] < 0.5 or not v["in_front"]]
            blocked = [v["blocked_by"] for v in views if v.get("blocked_by")]
            ok = len(lost) <= len(views) // 4 and len(blocked) <= len(views) // 4
            detail = f"'{cam_name}' keeps {', '.join(subject) or 'its subject'} in frame"
            if lost:
                detail = f"'{cam_name}' loses {', '.join(subject) or 'its subject'} out of frame in {len(lost)} of {len(views)} checked frames"
            if blocked:
                detail += f"; its view is blocked by '{blocked[0]}' in {len(blocked)} of {len(views)}"
            return ok, detail
        if kind in ("light_on", "light_off"):
            lights = [(n, e) for n, e in entries if e.get("type") == "LIGHT"]
            if not lights and not name:
                lights = [(n, e) for n, e in report.get("objects", {}).items() if e.get("type") == "LIGHT"
                          and e.get("light", {}).get("kind") != "SUN"]
            if not lights:
                return False, f"there are no lights for '{name or 'the scene'}'"
            ends = [e["samples"][-1].get("energy", 0.0) for _, e in lights if e.get("samples")]
            if kind == "light_on":
                on = [x for x in ends if x and x > 0.01]
                return bool(on) and len(on) == len(ends), (f"{len(on)} of {len(lights)} light(s) for '{name or 'the scene'}'"
                                                           " are on at the end")
            off = [x for x in ends if not x or x <= 0.01]
            return len(off) == len(ends), f"{len(off)} of {len(lights)} light(s) are off at the end"
        if kind == "moves_to":
            if not entries:
                return False, f"there is no '{name}' moving"
            first = min((e["samples"][0] for _, e in entries if e.get("samples")), key=lambda x: 0, default=None)
            last_lo = [min(e["samples"][-1]["lo"][i] for _, e in entries if e.get("samples")) for i in range(3)]
            last_hi = [max(e["samples"][-1]["hi"][i] for _, e in entries if e.get("samples")) for i in range(3)]
            t = spatial.find_thing(spatial.things(state), other) if other else None
            if t is None:
                return None, f"there is no '{other}' to reach"
            g = spatial.gap(spatial.rect_of(last_lo, last_hi), t["outer"])
            ok = g <= max(3.0, 0.5 * max(last_hi[0] - last_lo[0], last_hi[1] - last_lo[1]))
            return ok, f"'{name}' ends {g:.1f} m from '{t['name']}'" + ("" if ok else " (it should get there)") \
                if first is not None else f"'{name}' never moves"
        return None, f"unknown check type {kind!r}"

    def _motion_issues(self, before, state: dict, goal: str) -> list:
        """What's wrong with this request's motion, as [(text, repair code or None)]: a camera inside something or
        with its subject blocked or out of frame, an invalid light, keys outside the timeline, and anything of the
        scene that went missing although nothing was to be removed."""
        if before is None:
            return []
        issues = []
        names = {o["name"] for o in state.get("objects", [])}
        gone = [n for n in before if not str(n).startswith("__") and n not in names
                and n not in getattr(self, "retired", [])]
        if gone and not _DELETE_ASKED.search(goal or "") and not _REPLACE_ASKED.search(goal or ""):
            issues.append((f"Existing objects disappeared although nothing was to be removed: "
                           f"{', '.join(gone[:5])}", None))
        animated = any(o.get("animated") for o in state.get("objects", [])) or any(
            o.get("type") in ("CAMERA", "LIGHT") and o["name"] not in before for o in state.get("objects", []))
        if not animated:
            return issues
        report = self._motion_report()
        ts = spatial.things(state)
        for name, e in report.get("objects", {}).items():
            if e.get("type") == "LIGHT":
                lt = e.get("light") or {}
                energy = lt.get("energy")
                if energy is None or energy != energy or energy < 0 or any(c != c or c < 0 or c > 1
                                                                          for c in lt.get("color") or []):
                    issues.append((f"The light '{name}' has invalid settings (energy {energy})", "check_lights()"))
            if e.get("type") != "CAMERA" or not (e.get("camera") or {}).get("subject"):
                continue
            if name in before and not re.search(r"\b(?:camera|shot|cinematic|film|view)\b", goal or "", re.I):
                continue   # an old camera this request didn't touch
            subject = set(e["camera"]["subject"])
            boxes = cinema.obstacles_3d(ts, exclude=subject)
            inside = [s["frame"] for s in e.get("samples", []) if any(cinema._inside_box(s["loc"], lo, hi, 0.2)
                                                                       for _, lo, hi in boxes)]
            views = [s.get("view") for s in e.get("samples", []) if s.get("view")]
            blocked = [v["blocked_by"] for v in views if v.get("blocked_by")]
            if inside:
                issues.append((f"The camera '{name}' is inside something at frame(s) {inside[:3]}",
                               f"unblock_camera({name!r})"))
            elif len(blocked) > len(views) // 4 and views:
                issues.append((f"The camera '{name}' can't see {', '.join(subject)}: '{blocked[0]}' is in the way "
                               f"in {len(blocked)} of {len(views)} checked frames", f"unblock_camera({name!r})"))
            lost = [v for v in views if v["visible"] < 0.5 or not v["in_front"]]
            if views and len(lost) > len(views) // 4:
                issues.append((f"The camera '{name}' loses {', '.join(subject)} out of frame in {len(lost)} of "
                               f"{len(views)} checked frames", None))
        return issues

    @staticmethod
    def _spatial_check(kind: str, check: dict, state: dict) -> tuple:
        """Where whole things stand relative to each other, on their footprints (spatial.py): beside, in front of,
        behind, left/right of (the anchor's own front), inside, outside, and paths that connect two things."""
        ts = spatial.things(state)
        sub = spatial.find_thing(ts, check.get("object"))
        if sub is None:
            return False, f"there is no object named '{check.get('object')}'"
        other = spatial.find_thing(ts, check.get("other"), exclude=(sub["name"],))
        if other is None:
            return False, f"there is no object named '{check.get('other')}'"
        relation = _SPATIAL_CHECKS[kind]
        if relation == "connects":
            end = spatial.find_thing(ts, check.get("value"), exclude=(sub["name"], other["name"]))
            if end is None:
                return False, f"there is no object named '{check.get('value')}' for the path to reach"
            ok, problems = spatial.check_path(sub, other, end, ts)
            return ok, (f"'{sub['name']}' runs from '{other['name']}' to '{end['name']}'" if ok
                        else "; ".join(problems))
        if relation == "outside":
            ok = spatial.overlap_depth(sub["rect"], other["core"]) <= 0.05
            return ok, f"'{sub['name']}' is {'outside' if ok else 'inside'} the footprint of '{other['name']}'"
        return spatial.check_relation(sub, relation, other, ts)

    relational_checks = ("above", "on_top", "touching", "near", "beside", "in_front_of", "behind", "left_of",
                         "right_of", "inside", "outside", "connects")

    def check_is_guess(self, check: dict, code: str) -> bool:
        """An "exists" check for a name the step's code never writes is the AI guessing what the kit calls things
        ('Bench Seat Legs 1' for what legs_under() names 'Bench Leg 1', 'Log Cabin Front'). Names the code itself
        builds — quoted, or as an f-string's start — stay strict."""
        name = str(check.get("object") or "").strip()
        if check.get("type") != "exists" or not name:
            return False
        literal = re.search(r"['\"]" + re.escape(name) + r"['\"]", code or "", re.I)
        pattern = re.search(r"f['\"]" + re.escape(re.sub(r"\s*\d+$", "", name)) + r"\s*\{", code or "", re.I)
        return literal is None and pattern is None

    def auto_fix(self, before, state: dict, goal: str) -> list:
        """Settle new parts that hang in the air onto what's below them (or the ground), moving each group of
        attached parts together — a snowball with its eyes and nose drops as one. The most common small-model
        slip (an `at` a few centimetres too high), fixed in code instead of another round with the AI."""
        if before is None or _FLOATING_OK.search(goal or ""):
            return []
        fixed = []
        made = _modelled([o for o in state.get("objects", []) if o["name"] not in before
                          and not o["name"].startswith("__")])
        rescale = _rescale_for(goal, [o for o in made if o["type"] == "MESH"])
        if rescale:
            factor, why = rescale
            meshes = [o for o in made if o["type"] == "MESH"]
            cx = (min(o["min"][0] for o in meshes) + max(o["max"][0] for o in meshes)) / 2
            cy = (min(o["min"][1] for o in meshes) + max(o["max"][1] for o in meshes)) / 2
            cz = max(0.0, min(o["min"][2] for o in meshes))
            names = [o["name"] for o in made]
            code = (f"names = {names!r}\nc = mathutils.Vector(({cx}, {cy}, {cz}))\n"
                    "objs = [bpy.data.objects.get(n) for n in names]\n"
                    "for o in objs:\n"
                    "    if o is None or (o.parent is not None and o.parent.name in names): continue\n"
                    f"    o.location = c + (o.location - c) * {factor}\n"
                    f"    o.scale = tuple(v * {factor} for v in o.scale)\n"
                    "RESULT = 'ok'")
            if self.bridge.run(code, timeout=15).get("ok"):
                fixed.append(f"resized it {factor}x to real-world size ({why})")
                state = self.observe()
        # Where whole things stand: a pool inside the villa, a fountain that should be behind the house, a path that
        # doesn't reach its door — each moved / re-routed to where the request (and common sense) puts it.
        # A rebuilt picture's layout was measured and resolved before anything was built (reconstruct.py): the
        # repairs below would move whole buildings away from where the photo shows them, so they stand down.
        rebuilding = self.reconstruction is not None
        if not rebuilding:
            fixed += self._spatial_repairs(lambda st: self._spatial_issues(before, st, goal), state)
        else:   # only small things, only a short way (a lounger off a terrace wall), never a building
            fixed += self._spatial_repairs(lambda st: self._small_moves(self._spatial_issues(before, st, goal), st),
                                           state)
        if fixed:
            state = self.observe()
        for text, code in self._motion_issues(before, state, goal):   # motion: cameras, lights
            if code and self.bridge.run(code + "\nRESULT = 'ok'", timeout=60).get("ok"):
                self._motion_cache = None
                fixed.append(f"{text} — fixed")
                state = self.observe()
        if not _INSIDE_OK.search(goal or "") and not rebuilding:
            for _ in range(len(state.get("objects", [])) + 1):   # each new group, moved once, to a clear spot
                hit = self._collision(before, state)
                if not hit:
                    break
                names, other, (dx, dy) = hit
                code = "\n".join(f"get({n!r}).location.x += {dx}\nget({n!r}).location.y += {dy}" for n in names)
                if not self.bridge.run(code + "\nRESULT = 'ok'", timeout=10).get("ok"):
                    break
                fixed.append(f"'{names[0]}' was inside '{other}'; moved it beside it")
                state = self.observe()
        for _ in range(4):   # lower groups settle first; the ones resting on them follow on the next pass
            move = self._settle_once(before, state)
            if not move:
                break
            names, drop, onto = move
            code = "\n".join(f"get({n!r}).location.z -= {drop}" for n in names)
            if not self.bridge.run(code + "\nRESULT = 'ok'", timeout=10).get("ok"):
                break
            fixed.append(f"'{names[0]}'" + (f" (with {len(names) - 1} attached part(s))" if len(names) > 1 else "")
                         + f" was floating {drop:.2f} m above {onto}; set it down")
            state = self.observe()
        return fixed

    # A request that only changes something ("colour the pool beside the house blue") says nothing about where
    # things should stand; anything else that names a relation ("a villa with a pool beside it", "move the pool
    # behind the house") is held to it.
    _MOVES = re.compile(r"\b(?:move|put|place|position|shift|relocate|drag|bring|set)\b(?!\s+up\b)", re.I)
    _EDIT_ONLY = re.compile(r"^(?:(?:please|now|also|then|and|ok|okay|jervis|hey|can you|could you)\b[\s,]*)*"
                            r"(?:colou?r|paint|recolou?r|rename|resize|scale|rotate|turn|change|make (?:it|them|the|"
                            r"its|this|that)\b|give (?:it|the|them)\b|delete|remove|hide|show|select|save|undo)\b",
                            re.I)

    def _spatial_issues(self, before, state: dict, goal: str) -> list:
        """spatial.validate on what this request made: relations the request asked for, outdoor things inside
        buildings, things standing inside each other, things sunk into the ground, paths that don't connect."""
        if before is None:
            return []
        request = (goal or "").split(" — ")[0]
        placing = self._hint() or not self._EDIT_ONLY.match(request.strip())
        try:
            return spatial.validate(state, before, self.intents if placing else [],
                                    underground_ok=bool(_UNDERGROUND_OK.search(request)),
                                    inside_ok=bool(_INSIDE_OK.search(request)), subject_hint=self._hint() or None,
                                    existing_ok=bool(self._MOVES.search(request)))
        except Exception as e:   # a check that can't run must never break the build it checks
            print(f"Spatial check failed: {type(e).__name__}: {e}", flush=True)
            return []

    _FIX_ORDER = {"relation": 0, "inside_building": 1, "intersection": 2, "below_ground": 3, "path": 4}

    def _spatial_repairs(self, find_issues, state: dict, rounds: int = 8) -> list:
        """Apply the repairs find_issues(state) proposes, one at a time, re-reading the scene after each: things are
        moved first and paths re-laid last (a path is routed to where things finally stand). What was done."""
        fixed, tried = [], set()
        for _ in range(rounds):
            issues = sorted((i for i in find_issues(state) if i.get("fix") and (i["thing"], i["kind"]) not in tried),
                            key=lambda i: self._FIX_ORDER.get(i["kind"], 9))
            if not issues:
                break
            issue = issues[0]
            tried.add((issue["thing"], issue["kind"]))
            done = self._apply_spatial_fix(issue, state)
            if done:
                fixed.append(done)
                state = self.observe()
                if issue["kind"] != "path":   # something moved: a path may need laying again to reach it
                    tried = {t for t in tried if t[1] != "path"}
        return fixed

    def _apply_spatial_fix(self, issue: dict, state: dict) -> str:
        """Carry out one of spatial.validate's repairs in Blender; what was done, or "" if it couldn't be."""
        t = next((x for x in spatial.things(state) if x["name"] == issue["thing"]), None)
        names = issue.get("names") or (t["names"] if t else None)
        if not names:
            return ""
        t = t or {"names": names, "lo": [0.0, 0.0, issue.get("lo_z", 0.0)]}
        fix = issue["fix"]
        if "move" in fix:
            dx, dy = fix["move"]
            if fix.get("z") is not None:
                code = f"shift_thing({names!r}, {dx}, {dy}, {fix['z'] - t['lo'][2]}, reground=False)"
            else:
                code = f"shift_thing({names!r}, {dx}, {dy})"
            what = f"moved it {math.hypot(dx, dy):.1f} m"
        elif "lift" in fix:
            code = f"shift_thing({names!r}, 0, 0, {fix['lift']}, reground=False)"
            what = f"raised it {fix['lift']:.2f} m onto the ground"
        elif "route" in fix:
            path, a, b = fix["route"]
            roots = [n for n in names if not any(o["name"] == n and o.get("parent") in names
                                                 for o in state.get("objects", []))]
            code = f"delete(*{roots!r})\nwalkway({path!r}, {a!r}, {b!r})"
            what = f"re-laid it from {a} to {b}"
        else:
            return ""
        response = self.bridge.run(code + "\nRESULT = 'ok'", timeout=30)
        if not response.get("ok"):
            print(f"Spatial fix failed ({issue['text']}): {self._short_error(response)}", flush=True)
            return ""
        return f"{issue['text']} — {what}"

    @staticmethod
    def _groups(before, state: dict) -> tuple:
        """(all meshes, the new objects as groups of parts touching each other: a trunk with its crown...)."""
        meshes = [o for o in state.get("objects", []) if o["type"] == "MESH"]
        new = _modelled([o for o in meshes if o["name"] not in before])
        groups, seen = [], set()
        for o in sorted(new, key=lambda m: m["min"][2]):
            if o["name"] in seen:
                continue
            group, queue = [], [o]
            seen.add(o["name"])
            while queue:
                cur = queue.pop()
                group.append(cur)
                for p in new:
                    if p["name"] not in seen and _touching(cur, p):
                        seen.add(p["name"])
                        queue.append(p)
            groups.append(group)
        return meshes, groups

    @staticmethod
    def _held_up(group: list, meshes: list) -> bool:
        """Is this group standing on the ground, resting on (or set into) something below it, or — if it's thin, like
        a window or a sign — fixed to the side of something? Merely brushing the side of a tree doesn't hold a
        bench up."""
        names = {g["name"] for g in group}
        if min(g["min"][2] for g in group) <= 0.05:
            return True
        others = [p for p in meshes if p["name"] not in names]
        for g in group:
            for p in others:
                if _xy_overlap(g, p) > 0.02 and p["min"][2] - 0.05 <= g["min"][2] <= p["max"][2] + 0.1:
                    return True
        span = [max(g["max"][i] for g in group) - min(g["min"][i] for g in group) for i in range(2)]
        if min(span) < THIN and any(_touching(g, p) for g in group for p in others):
            return True
        # A part of the same thing a hand's breadth from its siblings (a foliage cluster just off its branch) is
        # part of that thing, not something to drop on the ground.
        if not all(g.get("kind") == "blob" for g in group):
            return False
        family = {g["name"].split()[0].lower() for g in group}
        return any(p["name"].split()[0].lower() in family and _touching(g, p, slack=0.3) for g in group for p in others)

    @classmethod
    def _floating_groups(cls, before, state: dict) -> list:
        """New parts hanging in the air: [(names, lowest part first), bottom z, drop to what's below, what's below)].
        Two floating parts touching each other don't hold each other up."""
        meshes, groups = cls._groups(before, state)
        floating = []
        for group in groups:
            if cls._held_up(group, meshes):
                continue
            names = {g["name"] for g in group}
            low = min(g["min"][2] for g in group)
            drop, onto = low, "the ground"
            for g in group:
                for p in meshes:
                    if p["name"] in names or p["max"][2] > g["min"][2] + 0.05 or _xy_overlap(g, p) <= 0.02:
                        continue
                    gap = g["min"][2] - p["max"][2]
                    if 0 <= gap < drop:
                        drop, onto = gap, f"'{p['name']}'"
            ordered = [g["name"] for g in sorted(group, key=lambda g: g["min"][2])]
            floating.append((ordered, round(low, 3), round(drop, 3), onto))
        return floating

    @classmethod
    def _collision(cls, before, state: dict):
        """A new (not thin) group sitting inside something that was already there: (names, what it hit, the
        smallest sideways shift (dx, dy) that clears it of EVERYTHING already there, with a little room).
        None if nothing collides."""
        meshes, groups = cls._groups(before, state)
        old = [p for p in meshes if p["name"] in before]

        def hit(lo, hi):
            for p in old:
                pen = [min(hi[i], p["max"][i]) - max(lo[i], p["min"][i]) for i in range(3)]
                if min(pen) > 0.1 and p["max"][2] - lo[2] >= 0.15:   # inside it (not just touching or on top)
                    return p
            return None

        for group in groups:
            lo = [min(g["min"][i] for g in group) for i in range(3)]
            hi = [max(g["max"][i] for g in group) for i in range(3)]
            if min(hi[i] - lo[i] for i in range(2)) < THIN:
                continue   # a window or door set into a wall is meant to be there
            first = hit(lo, hi)
            if first is None:
                continue
            ordered = [g["name"] for g in sorted(group, key=lambda g: g["min"][2])]   # its base first
            for step in range(1, 61):   # search outward, 0.5 m at a time, for a spot clear of everything
                r = step * 0.5
                for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (-r, r), (r, -r), (-r, -r)):
                    moved_lo = [lo[0] + dx, lo[1] + dy, lo[2]]
                    moved_hi = [hi[0] + dx, hi[1] + dy, hi[2]]
                    if hit([v - 0.2 for v in moved_lo[:2]] + [moved_lo[2]],
                           [v + 0.2 for v in moved_hi[:2]] + [moved_hi[2]]) is None:
                        return ordered, first["name"], (dx, dy)
        return None

    @classmethod
    def _settle_once(cls, before, state: dict):
        sizes = {o["name"]: o["size"] for o in state.get("objects", [])}
        meshes = [o for o in state.get("objects", []) if o["type"] == "MESH"]
        grounded = {o["name"].split()[0].lower() for o in meshes if o["name"] not in before and o["min"][2] <= 0.05}
        for names, _low, drop, onto in cls._floating_groups(before, state):
            thin = all(min(sizes.get(n, [1, 1, 1])) < THIN for n in names)
            torn = any(n.split()[0].lower() in grounded for n in names)
            # A slat or panel in mid-air belongs attached to something; a canopy whose own trunk stands on the
            # ground belongs back on that trunk — dropping either would tear the thing apart. Those are reported.
            if drop > 0.05 and not thin and not torn:
                return names, drop, onto
        return None

    @staticmethod
    def _small_moves(issues: list, state: dict) -> list:
        cats = {t["name"]: t["category"] for t in spatial.things(state)}
        out = []
        for i in issues:
            move = (i.get("fix") or {}).get("move")
            if cats.get(i.get("thing")) in ("building", "ground", "path") or not move:
                continue
            if math.hypot(move[0], move[1]) <= 6.0:
                out.append(i)
        return out

    def extra_failures(self, before, state: dict, goal: str) -> list:
        """Mistakes no one wrote a check for: new parts hanging in the air with nothing under them (a trunk at
        z=1 because `at` was taken as its centre). Skipped when the request is about things that do float."""
        if before is None:
            return []
        made = _modelled([o for o in state.get("objects", []) if o["type"] == "MESH" and o["name"] not in before
                          and not o["name"].startswith("__")])
        # Where things stand comes first: an outdoor thing inside a building, or a relation the request asked
        # for that the build broke, is wrong however well each part is modelled.
        placed = [i["text"] + ("" if i["kind"] != "inside_building" else
                               " (use spot_near() to find a free spot outside it)")
                  for i in self._spatial_issues(before, state, goal)][:3]
        if self.reconstruction is not None:
            # a rebuild's layout is the photo's: what is left over is said, not handed to the planner to "fix"
            self.notes += [p for p in placed if p not in self.notes]
            placed = []
        # Malformed is wrong, not just unpolished: legs not under the seat, a chair that would tip over.
        structural = placed + [t for t, _ in self._motion_issues(before, state, goal)][:3] + _anatomy(made, goal)
        if not _ORGANIC.search(goal or ""):
            wobbly = _tips_over(made)
            structural += [wobbly] if wobbly else []
        if _FLOATING_OK.search(goal or ""):
            return structural
        return structural + [f"'{names[0]}'" + (f" (and {len(names) - 1} part(s) attached to it)" if len(names) > 1 else "")
                + f" floats in the air: its bottom is at z={low} with nothing under it (it should rest on {onto}); "
                "builders stand on `at`, so give it the z of what it should rest on"
                for names, low, _drop, onto in self._floating_groups(before, state)][:4]

    # ---------- quality: does it look modelled, or like primitives stuck together? ----------
    def quality_issues(self, before, state: dict, goal: str, tier: str = "normal") -> list:
        """What an artist would object to in what this request built, as concrete fixes naming the parts and the kit
        functions to use. Judged from how each part was actually made (kind, shaping, bevels, materials), not from
        whether the code ran. [] when it's fine, or when nothing new was built (a recolour, a move)."""
        made = _modelled([o for o in state.get("objects", []) if o["type"] == "MESH" and o["name"] not in (before or {})
                          and not o["name"].startswith("__")])
        if not made:   # nothing modelled by the AI itself (a finished asset, a recolour, a move): nothing to judge
            return []
        issues = []
        n = len(made)
        names = lambda objs: ", ".join(f"'{o['name']}'" for o in objs[:6]) + (" ..." if len(objs) > 6 else "")
        bare = [o for o in made if o.get("kind") in _PRIMITIVE_KINDS and not o.get("shaped")
                and "SUBSURF" not in (o.get("modifiers") or [])]
        organic = bool(_ORGANIC.search(goal or ""))
        if organic:
            round_bare = [o for o in bare if o.get("kind") in ("sphere", "cylinder", "cone", "torus")]
            allowed = {"simple": 0.5, "normal": 0.15, "high": 0.1}.get(tier, 0.15)
            if round_bare and len(round_bare) / n > allowed:
                issues.append(f"This is organic, but {names(round_bare)} are bare primitives. Rebuild trunks, "
                              "branches, limbs and stems as tube()s along curving path()s, foliage, rocks and bushes "
                              "as blob()s in varied sizes and seeds, and round crafted parts as lathe()s.")
        if not _SINGLE_PIECE.search(goal or "") and not _ADDITION.search(goal or ""):
            need = {"simple": 1, "normal": 5, "high": 10}.get(tier, 5)
            if n < need:
                issues.append(f"Only {n} part(s): too plain for this quality. Add the secondary parts and details a "
                              "real one has (see HOW TO MODEL WELL), as new objects named like the others.")
        if tier != "simple":
            sharp = [o for o in made if o.get("kind") in ("box", "stairs") and "BEVEL" not in (o.get("modifiers") or [])
                     and min(o["size"]) > 0.015]
            boxes = [o for o in made if o.get("kind") in ("box", "stairs")]
            if sharp and (tier == "high" or len(sharp) > len(boxes) / 2):
                issues.append(f"Razor-sharp edges on {names(sharp)}: bevel(name, 0.01-0.03) each of them.")
        plain = [o for o in made if not o.get("material")]
        if plain:
            issues.append(f"No material on {names(plain)}: color(name, '<material>') with a fitting textured preset "
                          "(bark, wood, stone, leaves, plaster, roof tiles, metal, glass...).")
        if tier != "simple":
            textured = sum(1 for o in made if o.get("textured"))
            share = {"normal": 0.4, "high": 0.6}.get(tier, 0.4) / (2 if _NAMES_A_COLOUR.search(goal or "") else 1)
            if textured / n < share:
                untextured = [o for o in made if o.get("material") and not o.get("textured")]
                issues.append(f"Mostly flat colours ({names(untextured)}): give natural and building materials "
                              "textured presets (wood, bark, leaves, stone, rock, brick, roof tiles, plaster, metal); "
                              "keep a plain colour only where the user named one.")
        clash = _things_inside_each_other(made, state)
        if clash:
            issues.append(clash)
        verdict = _size_verdict(goal, made)
        if verdict and verdict[0] == "issue":
            issues.append(verdict[1])
        if organic or tier == "high":
            for base, objs in _repeated(made).items():
                sizes = {tuple(round(v, 2) for v in o["size"]) for o in objs}
                if len(objs) >= 3 and len(sizes) == 1:
                    issues.append(f"The {len(objs)} '{base}' parts are identical copies: give each its own size, seed "
                                  "and rotation (r = rng(...); r.uniform(...)) so it looks natural.")
                    break
        return issues[:5]

    def usable_checks(self, checks, goal: str) -> list:
        out = super().usable_checks(checks, goal)
        if not _SIZE_WORDS.search(goal or ""):
            # Sizes the user never asked for are the AI's own guesses — often contradicting its own code (a radius
            # 0.5 sphere "should be 0.4-0.6 m across"), which would send every repair after the wrong thing.
            out = [c for c in out if c.get("type") != "size"]
        return out

    def auto_checks(self, code: str) -> list:
        names = set(_BUILDERS.findall(code)) | set(_DUPLICATE_NAME.findall(code))
        names = {n for n in names if "{" not in n}   # f-string names can't be checked literally
        return [{"type": "exists", "object": n} for n in sorted(names)]

    def sanitize(self, code: str, goal: str) -> str:
        code = _unshadow(code)
        if _CLEAR_ASKED.search(goal or ""):
            return code
        lines = [l for l in (code or "").splitlines() if not re.fullmatch(r"\s*clear_scene\s*\([^)]*\)\s*", l)]
        return "\n".join(lines).strip()

    def guard(self, code: str, goal: str) -> str:
        """A small model sometimes starts a build with clear_scene() or deletes what's there "to make room" — wiping
        the user's own work. That only runs when the request itself asks to clear or remove something."""
        if _CLEARS.search(code) and not _CLEAR_ASKED.search(goal or ""):
            return ("clear_scene() would delete everything already in the scene, and the user didn't ask for that. "
                    "Build next to what's there instead, without clearing or deleting anything.")
        if _DELETES.search(code) and not _DELETE_ASKED.search(goal or ""):
            return ("this code deletes objects, but the user didn't ask to remove anything. Leave existing objects "
                    "alone and only add or change what was asked.")
        return ""

    def risk(self, code: str) -> str:
        match = BLENDER_DANGEROUS_CODE.search(code)
        return f"run Blender code that does “{match.group(0)}”" if match else ""

    def self_contained(self, steps: list, made: list) -> bool:
        referenced = {n.lower() for s in steps for n in _REFERENCED.findall(s["code"])}
        referenced -= set(blender_kit.COLORS)
        return referenced <= {m.lower() for m in made}

    _CAMERA_WORDS = {"push_in": "pushes in on", "pull_out": "pulls back from", "orbit": "orbits", "crane": "cranes up over",
                     "reveal": "reveals", "pan": "pans across", "tilt": "tilts over", "overhead": "looks down on",
                     "flyover": "flies over", "fly_through": "flies through", "follow": "follows", "track": "tracks"}

    @staticmethod
    def _wind_targets(ts) -> list:
        """What wind() will move here (the same choice, read from the scene description): trees, bushes, flags —
        whole things, or the ones growing on a bigger thing (an island's palms)."""
        out = []
        for t in ts:
            words = set(spatial.words_of(t["name"])) | {t.get("asset_type") or ""}
            if words & (cinema.WIND_SWAYS | {"flag", "banner", "pennant", "windsock"}) or \
                    t.get("asset_type") in ("tree", "bush", "flag"):
                out.append(t["name"])
            else:
                out += [n for _, n in spatial.find_parts([t], "tree bush shrub hedge reed bamboo fern sunflower")]
                out += [n for _, n in spatial.find_parts([t], "flag banner pennant windsock")]
        return out

    @staticmethod
    def _subject_phrase(e: dict) -> str:
        """The subject as the user said it: "palm trees", not the bare noun "palm"."""
        subj = e.get("subject") or "scene"
        if (e.get("params") or {}).get("of"):
            return f"{e['params']['of']} {subj}"   # "the garage door"
        m = re.search(r"\b(" + re.escape(subj) + r"\w*)(?:\s+(\w+))?", e.get("clause") or "", re.I)
        if not m:
            return subj
        nxt = m.group(2) or ""
        if e.get("kind") != "lights" and nxt and any(w in spatial.VOCAB for w in spatial.words_of(nxt)):
            return f"{m.group(1)} {nxt}"
        return m.group(1)

    def _directed_text(self) -> str:
        """What a directed timeline does, in words: "directed a 10-second shot at 24 fps: the camera pushes in on
        Villa; Pool's lights come up at 5 s; the door opens at 7.5 s"."""
        events, D, fps_ = self.directed
        said = []
        for e in events:
            subj = self._subject_phrase(e)
            at = f" at {e['start']:g} s" if e["start"] > 0 else ""
            if e["kind"] == "camera":
                said.append(f"the camera {self._CAMERA_WORDS.get(e['move'], e['move'])} the {subj}")
            elif e["kind"] == "shot":
                said.append(f"a {e['move']} shot of the {subj}")
            elif e["kind"] == "lights":
                said.append(f"the {subj + ' ' if e.get('subject') else ''}lights {'come up' if e['move'] == 'on' else 'go out'}{at}")
            elif e["kind"] == "sky":
                said.append(f"{e['move'].replace('_', ' ')} light")
            elif e["kind"] in ("weather", "wind"):
                said.append({"rain": "rain falls", "snow": "snow falls"}.get(e["move"], "the wind blows"))
            else:
                verb = {"open": "opens", "close": "closes", "travel": "drives", "sway": "sways", "spin": "spins",
                        "bounce": "bounces", "rise": "rises", "fall": "falls", "grow": "grows", "shrink": "shrinks",
                        "appear": "appears", "disappear": "disappears", "colour": "changes colour"}.get(e["move"], "moves")
                to = f" to the {e['params']['to']}" if e["move"] == "travel" and e.get("params", {}).get("to") else ""
                said.append(f"the {subj} {verb}{to}{at}")
        if D is None:   # nothing timed: what now goes on, all through the scene's timeline
            return "set it going: " + "; ".join(said[:6])
        n = f"{D:g}"   # "an 8-second", "an 11-second", "an 18.5-second"; "a 10-second"
        article = "an" if n.startswith("8") or n.split(".")[0] in ("11", "18") else "a"
        return f"directed {article} {n}-second shot at {fps_:g} fps: " + "; ".join(said[:6])

    def describe_made(self, before, state: dict) -> str:
        """What the finished assets this request built are, in words ("a cottage house with plastered walls, 9
        framed glass windows..."), read from Blender — '' when it built none. A directed timeline, in words."""
        if self.reconstruction is not None and self.reconstruction.get("again"):
            crit = self.reconstruction.get("critique") or {}
            text = ("changed the scene to look more like its photo: " + ("; ".join(crit.get("fixes") or [])
                                                                       or "nothing I measured got closer"))
            remaining = self.reconstruction.get("remaining") or []
            if remaining:
                text += ". The biggest difference left: " + str(remaining[0].get("what", ""))
            return text
        if self.reconstruction is not None:
            import reconstruct
            text = reconstruct.summary(self.reconstruction["scene"], self.reconstruction["built"])
            layout = [n for n in self.notes if "inside" in n or "stand" in n][:2]
            if layout:
                text += ". Not quite right yet: " + "; ".join(layout)
            remaining = self.reconstruction.get("remaining") or []
            if remaining:
                text += ". The biggest difference left: " + str(remaining[0].get("what", ""))
            return text
        if self.edit is not None:   # what changed — nothing else was rebuilt, and its parts aren't listed
            return "changed the scene that's there: " + str(self.edit.get("understanding") or "").lower()
        if self.directed:
            return self._directed_text()
        roots = [o["name"] for o in state.get("objects", []) if o.get("kind") == "asset" and o["name"] not in
                 (before or {}) and o.get("asset") == o["name"] and not (o.get("parent") or "").strip()]
        if not roots:
            return ""
        response = self.bridge.run(f"RESULT = json.dumps([get(n).get('jervis_summary', '') for n in {roots[:6]!r}])",
                                   timeout=8)
        try:
            said = [t for t in json.loads(response.get("output") or "[]") if t]
        except ValueError:
            return ""
        if not said:
            return ""
        return said[0] if len(said) == 1 else "; ".join(said[:-1]) + " and " + said[-1]

    def made(self, before, state: dict) -> list:
        old = set(before or {})
        return [o["name"] for o in state.get("objects", []) if o["name"] not in old]

    def _group_loose(self, before, state: dict) -> str:
        """Parts this request made that aren't in any group yet go under one parent named after the thing, so a
        later "move it", "make it bigger" or "delete it" takes the whole thing. The name of the group, or ""."""
        new = [o for o in state.get("objects", []) if o["name"] not in (before or {}) and not o["name"].startswith("__")]
        loose = [o["name"] for o in new if o["type"] in ("MESH", "CURVE") and not o.get("parent")]
        if not loose:
            return ""
        hint = self._hint()
        roots = [o["name"] for o in new if o["type"] == "EMPTY" and not o.get("parent")]
        name, members = "", []
        if hint:
            name = hint
            members = [n for n in loose if n.lower().startswith(hint.lower() + " ")]
        else:
            for root in roots:   # a part added after the thing was assembled ('Bench Cushion' after 'Bench')
                members = [n for n in loose if n.lower().startswith(root.lower() + " ")]
                if members:
                    name = root
                    break
            if not name and len(loose) >= 2 and not roots:
                words = [n.split() for n in loose]
                common = []
                for column in zip(*words):
                    if len({w.lower() for w in column}) != 1:
                        break
                    common.append(column[0])
                if common and len(common) < min(len(w) for w in words):
                    name, members = " ".join(common), loose
        if not name or not members:
            return ""
        response = self.bridge.run(f"RESULT = assemble({name!r}, {members!r}).name", timeout=15)
        return (response.get("output") or "").strip() if response.get("ok") else ""

    def finished(self, before, success: bool, goal: str) -> None:
        if before is not None:
            grouped = self._group_loose(before, self.observe())
            if grouped:
                print(f"Grouped this request's loose parts under '{grouped}'", flush=True)
        if before is not None and self.session is not None:
            state = self.observe()
            # "no, the roof" corrects the last quick command only while that command is the last thing done
            self.session.last_deterministic_text = None
            for name in self.made(before, state):
                self.session.remember_blender_object(name, "")
            made = self.made(before, state)
            if made:
                roots = [o["name"] for o in state.get("objects", []) if o["name"] in made and not o.get("parent")]
                # "it" is the whole thing just built: its group when there is exactly one
                self.session.blender_focus = roots[0] if len(roots) == 1 else made[-1]
                self.session.blender_focus_group = made if len(made) > 1 else None
            self.session.last_undo = {"description": goal, "code": _restore_code(before)}
        self.bridge.run("RESULT = str(frame_view())", timeout=8)
