"""Concept 03 - CDN / global network: the edge (curved horizon) of a dark planet seen from orbit.

The planet's round horizon crosses the lower part of the frame, with a thin atmospheric glow along the edge.
Thin arcs of light jump between edge nodes on the surface, and a few clusters of city lights are visible.
The centre (above the horizon) is left dark and empty for the headline. Content is kept to the left and right sides.

Loop (5 s, 150 frames): each arc fires once per loop with phases spread evenly (so no 2.5 s repetition is visible); the planet makes a very small
sine sway about the Y axis (A*sin(2pi t/T)) -> last frame = first frame.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402

import lib  # noqa: E402

def _extra(p):
    p.add_argument("--start", type=int, default=None, help="animation start frame (chunked render)")
    p.add_argument("--end", type=int, default=None, help="animation end frame (chunked render)")
    p.add_argument("--spp", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)


args = lib.parse_args("concept_cdn_planet", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x, scene.render.resolution_y = 1920, 540
if args.engine == "cycles":
    scene.cycles.samples = args.spp or (32 if args.preview else 128)
    scene.cycles.seed = args.seed                 # fixed seed (same noise pattern every frame -> no loop seam)
    scene.cycles.use_animated_seed = False
    scene.render.use_persistent_data = True
    scene.cycles.adaptive_threshold = 0.03 if args.preview else 0.01
    try:
        scene.cycles.denoising_use_gpu = True
    except AttributeError:
        pass
    scene.cycles.max_bounces = 4
for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
    try:
        scene.view_settings.look = look
        break
    except TypeError:
        continue

N_FRAMES = args.frames
R = 100.0                      # planet radius (m)
H = 12.0                       # camera altitude
rng = random.Random(7)


# ------------------------------------------------------------------ node helpers
class NB:
    def __init__(self, nt):
        self.nt = nt

    def node(self, kind, **inputs):
        n = self.nt.nodes.new(kind)
        for k, v in inputs.items():
            self.set(n, k, v)
        return n

    def set(self, n, key, v):
        sock = n.inputs[key]
        if hasattr(v, "bl_idname") or hasattr(v, "is_output"):
            self.nt.links.new(v if hasattr(v, "is_output") else v.outputs[0], sock)
        else:
            sock.default_value = v

    def math(self, op, a, b=None, clamp=False):
        n = self.nt.nodes.new("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            self.set(n, i, v)
        return n.outputs[0]

    def vmath(self, op, a, b=None):
        n = self.nt.nodes.new("ShaderNodeVectorMath")
        n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            self.set(n, i, v)
        return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs["Vector"]

    def link(self, a, b):
        self.nt.links.new(a, b)


def new_mat(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    return mat, NB(nt), out


def loop_time():
    """Linear 0->1 over N_FRAMES, repeating periodically. Shared by the shaders."""
    holder = bpy.data.node_groups.new("LoopTime", "ShaderNodeTree")
    holder.interface.new_socket("t", in_out="OUTPUT", socket_type="NodeSocketFloat")
    v = holder.nodes.new("ShaderNodeValue")
    o = holder.nodes.new("NodeGroupOutput")
    holder.links.new(v.outputs[0], o.inputs[0])
    # linear time via a driver (in Blender 5.2 keyframes get eased). frame N+1 -> 1.0 == frame 1 (fract)
    fc = v.outputs[0].driver_add("default_value")
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = f"(frame-1)/{N_FRAMES}"
    return holder


LOOP = loop_time()


def time_socket(nb):
    g = nb.nt.nodes.new("ShaderNodeGroup")
    g.node_tree = LOOP
    return g.outputs[0]


# ------------------------------------------------------------------ world: nearly black space + faint stars
lib.set_world(color=(0.0, 0.0, 0.0, 1.0), strength=1.0)
wnt = scene.world.node_tree
wb = NB(wnt)
bg = wnt.nodes["Background"]
tc = wb.node("ShaderNodeTexCoord")
vor = wb.node("ShaderNodeTexVoronoi", Scale=260.0)
wb.link(tc.outputs["Generated"], vor.inputs["Vector"])
star = wb.math("LESS_THAN", vor.outputs["Distance"], 0.045)
twk = wb.math("POWER", wb.vmath("DOT_PRODUCT", vor.outputs["Color"], (0.333, 0.333, 0.333)), 6.0)
star = wb.math("MULTIPLY", star, twk)
# sky gradient: very pale navy near the horizon, black higher up
sep = wb.node("ShaderNodeSeparateXYZ")
wb.link(tc.outputs["Generated"], sep.inputs[0])
sky = wb.math("MULTIPLY", wb.math("POWER", wb.math("SUBTRACT", 1.0, wb.math("ABSOLUTE", sep.outputs["Z"]), clamp=True), 8.0), 0.004)
col = wb.node("ShaderNodeCombineXYZ")
wb.link(wb.math("ADD", wb.math("MULTIPLY", star, 0.35), wb.math("MULTIPLY", sky, 0.5)), col.inputs[0])
wb.link(wb.math("ADD", wb.math("MULTIPLY", star, 0.4), wb.math("MULTIPLY", sky, 0.8)), col.inputs[1])
wb.link(wb.math("ADD", wb.math("MULTIPLY", star, 0.5), wb.math("MULTIPLY", sky, 1.6)), col.inputs[2])
wb.link(col.outputs[0], bg.inputs["Color"])

# ------------------------------------------------------------------ planet (group for the sway)
planet_root = lib.group("PlanetRoot", (0, 0, -R))

bpy.ops.mesh.primitive_uv_sphere_add(radius=R, segments=512, ring_count=256, location=(0, 0, -R))
planet = bpy.context.active_object
planet.name = "Planet"
for p in planet.data.polygons:
    p.use_smooth = True
planet.parent = planet_root
planet.location = (0, 0, 0)

SUN_DIR = Vector((-0.55, 1.0, -0.22)).normalized()      # sun: behind the planet on the left, below the horizon -> thin crescent rim

mat, nb, out = new_mat("Planet Surface")
tco = nb.node("ShaderNodeTexCoord")
P = tco.outputs["Object"]
# large land/ocean pattern (abstract)
n1 = nb.node("ShaderNodeTexNoise", Scale=0.035, Detail=10.0, Roughness=0.62)
nb.link(P, n1.inputs["Vector"])
land = nb.node("ShaderNodeMapRange", **{"From Min": 0.48, "From Max": 0.56})
nb.link(n1.outputs["Fac"], land.inputs["Value"])
landf = land.outputs[0]
# city lights: on land, cluster mask * fine dots
n2 = nb.node("ShaderNodeTexNoise", Scale=0.11, Detail=4.0, Roughness=0.5)
nb.link(P, n2.inputs["Vector"])
cluster = nb.node("ShaderNodeMapRange", **{"From Min": 0.64, "From Max": 0.70})
nb.link(n2.outputs["Fac"], cluster.inputs["Value"])
v3 = nb.node("ShaderNodeTexVoronoi", Scale=2.2)
nb.link(P, v3.inputs["Vector"])
dots = nb.math("POWER", nb.math("SUBTRACT", 1.0, nb.math("MULTIPLY", v3.outputs["Distance"], 3.2), clamp=True), 3.0)
n4 = nb.node("ShaderNodeTexNoise", Scale=0.9, Detail=6.0)
nb.link(P, n4.inputs["Vector"])
fine = nb.math("POWER", n4.outputs["Fac"], 4.0)
city = nb.math("MULTIPLY", nb.math("MULTIPLY", cluster.outputs[0], landf),
               nb.math("ADD", dots, nb.math("MULTIPLY", nb.math("POWER", fine, 2.0), 0.6)))
# dim the city lights at the frame centre (world x near 0) -> clears the headline area (world coordinates, so unaffected by the sway)
tcw = nb.node("ShaderNodeNewGeometry")
sepw = nb.node("ShaderNodeSeparateXYZ")
nb.link(tcw.outputs["Position"], sepw.inputs[0])
side = nb.node("ShaderNodeMapRange", **{"From Min": 6.0, "From Max": 22.0})
nb.link(nb.math("ABSOLUTE", sepw.outputs["X"]), side.inputs["Value"])
city = nb.math("MULTIPLY", city, nb.math("ADD", 0.12, nb.math("MULTIPLY", side.outputs[0], 0.88)))
city_e = nb.node("ShaderNodeEmission", Color=(1.0, 0.56, 0.22, 1.0))
nb.link(nb.math("MULTIPLY", city, 9.0), city_e.inputs["Strength"])

bsdf = nb.node("ShaderNodeBsdfPrincipled")
base_mix = nb.node("ShaderNodeMix")
base_mix.data_type = "RGBA"
nb.link(landf, base_mix.inputs["Factor"])
base_mix.inputs["A"].default_value = (0.004, 0.010, 0.020, 1)     # ocean
base_mix.inputs["B"].default_value = (0.020, 0.024, 0.028, 1)     # land
nb.link(base_mix.outputs["Result"], bsdf.inputs["Base Color"])
rmap = nb.node("ShaderNodeMapRange", **{"To Min": 0.22, "To Max": 0.8})
nb.link(landf, rmap.inputs["Value"])
nb.link(rmap.outputs[0], bsdf.inputs["Roughness"])
add = nb.node("ShaderNodeAddShader")
nb.link(bsdf.outputs[0], add.inputs[0])
nb.link(city_e.outputs[0], add.inputs[1])
nb.link(add.outputs[0], out.inputs["Surface"])
lib.assign(planet, mat, smooth=True)

# ------------------------------------------------------------------ atmosphere rim (emissive shell)
RA = R * 1.022
bpy.ops.mesh.primitive_uv_sphere_add(radius=RA, segments=512, ring_count=256, location=(0, 0, -R))
atmo = bpy.context.active_object
atmo.name = "Atmosphere"
for p in atmo.data.polygons:
    p.use_smooth = True
atmo.parent = planet_root
atmo.location = (0, 0, 0)
atmo.visible_shadow = False

mat, nb, out = new_mat("Atmosphere")
geo = nb.node("ShaderNodeNewGeometry")
c = nb.math("ABSOLUTE", nb.vmath("DOT_PRODUCT", geo.outputs["Normal"], geo.outputs["Incoming"]))
C0 = math.sqrt(1 - (R / RA) ** 2)                                  # cos of the incidence angle of a ray grazing the planet edge
outer = nb.math("POWER", nb.math("DIVIDE", c, C0, clamp=True), 2.2)   # falls to 0 outward
inner = nb.math("EXPONENT", nb.math("MULTIPLY", nb.math("MAXIMUM", nb.math("SUBTRACT", c, C0), 0.0), -26.0))
glow = nb.math("MULTIPLY", outer, inner)
# warm on the sun side (left), cyan on the opposite side
sun_dot = nb.vmath("DOT_PRODUCT", geo.outputs["Normal"], tuple(SUN_DIR))
warm = nb.node("ShaderNodeMapRange", **{"From Min": 0.1, "From Max": 0.75})
nb.link(sun_dot, warm.inputs["Value"])
cmix = nb.node("ShaderNodeMix")
cmix.data_type = "RGBA"
nb.link(warm.outputs[0], cmix.inputs["Factor"])
cmix.inputs["A"].default_value = (0.12, 0.42, 1.0, 1)
cmix.inputs["B"].default_value = (1.0, 0.62, 0.32, 1)
# strength: bright at left/right, subtle at the centre (front) top + boost on the sun side
sepn = nb.node("ShaderNodeSeparateXYZ")
nb.link(geo.outputs["Normal"], sepn.inputs[0])
sidek = nb.node("ShaderNodeMapRange", **{"From Min": 0.20, "From Max": 0.62, "To Min": 0.09, "To Max": 1.0})   # centre rim band 0.3 -> 0.09 (AgX luma about 170 -> under 100)
nb.link(nb.math("ABSOLUTE", sepn.outputs["X"]), sidek.inputs["Value"])
strength = nb.math("MULTIPLY", nb.math("MULTIPLY", glow, sidek.outputs[0]),
                   nb.math("ADD", 1.6, nb.math("MULTIPLY", warm.outputs[0], 3.0)))
em = nb.node("ShaderNodeEmission")
nb.link(cmix.outputs["Result"], em.inputs["Color"])
camray = nb.node("ShaderNodeLightPath").outputs["Is Camera Ray"]      # camera only, so it does not light the planet
nb.link(nb.math("MULTIPLY", strength, camray), em.inputs["Strength"])
tr = nb.node("ShaderNodeBsdfTransparent")
addz = nb.node("ShaderNodeAddShader")
nb.link(tr.outputs[0], addz.inputs[0])
nb.link(em.outputs[0], addz.inputs[1])
nb.link(addz.outputs[0], out.inputs["Surface"])
lib.assign(atmo, mat, smooth=True)

# ------------------------------------------------------------------ sun (backlight from behind)
sun = lib.add_sun("Sun", (0, 0, 0), energy=1.2, color=(0.85, 0.9, 1.0))
sun.rotation_euler = (-SUN_DIR).to_track_quat("-Z", "Y").to_euler()
sun.data.angle = math.radians(0.6)

# ------------------------------------------------------------------ edge nodes + arcs
def surf(dir_vec, lift=0.0):
    """Direction -> surface point in planet-local coordinates (origin at the centre)."""
    return dir_vec.normalized() * (R + lift)


def dir_from(az_deg, dist):
    """From the point directly below the camera (planet top): azimuth az (0 = straight ahead on screen, + = right), surface distance dist (m)."""
    ang = dist / R
    az = math.radians(az_deg)
    return Vector((math.sin(ang) * math.sin(az), math.sin(ang) * math.cos(az), math.cos(ang)))


nodes = []
for side_sign in (-1, 1):
    for _ in range(20):
        az = side_sign * rng.uniform(19, 40)
        dist = rng.uniform(24, 49)
        nodes.append(dir_from(az, dist))

node_mat = lib.make_pbr("Node", (0.02, 0.05, 0.08, 1), roughness=0.4, emission=(0.55, 0.9, 1.0, 7.5))   # 25 -> 7.5 (0.3x)
node_mesh = None
for i, d in enumerate(nodes):
    p = surf(d, 0.05)
    if node_mesh is None:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.055, segments=12, ring_count=6, location=p)
        o = bpy.context.active_object
        node_mesh = o.data
        node_mesh.materials.append(node_mat)
    else:
        o = bpy.data.objects.new(f"Node{i}", node_mesh)
        bpy.context.collection.objects.link(o)
        o.location = p
    o.parent = planet_root
    o.location = p
    o.visible_shadow = False

# Picking node pairs: for each node, one random partner 7-26 m away on the same side (looking only at the nearest neighbour yields almost no pairs)
pairs = []
for i, a in enumerate(nodes):
    cands = [j for j, b in enumerate(nodes)
             if j != i and (a.x > 0) == (b.x > 0) and 6 < (a - b).length * R < 18
             and (j, i) not in pairs and (i, j) not in pairs]
    if cands:
        pairs.append((i, rng.choice(cands)))
rng.shuffle(pairs)
pairs = ([p for p in pairs if nodes[p[0]].x < 0][:6]         # 6 per side: keeps the banner from getting too crowded
         + [p for p in pairs if nodes[p[0]].x > 0][:6])
print(f"[cdn_planet] arcs: {len(pairs)}")


def build_arcs(pairs, radius, name, segs=64, ring=6):
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    for k, (i, j) in enumerate(pairs):
        a, b = nodes[i], nodes[j]
        span = (surf(a) - surf(b)).length
        hgt = 0.24 * span + 0.6
        rng.random()                                    # (preserve random-number order)
        # spread phases evenly over 0..1: k*5 mod n is a permutation for n=12 -> launch times are spread evenly on each of the left/right sides too
        n_arc = len(pairs)
        phase = (((k * 5) % n_arc) + 0.5) / n_arc if n_arc % 5 else (k + 0.5) / n_arc
        rings = []
        for s in range(segs + 1):
            t = s / segs
            d = a.slerp(b, t) if hasattr(a, "slerp") else (a * (1 - t) + b * t)
            p = surf(d, 0.05 + hgt * math.sin(math.pi * t))
            rings.append(p)
        verts = []
        for s, p in enumerate(rings):
            tan = (rings[min(s + 1, segs)] - rings[max(s - 1, 0)]).normalized()
            up = p.normalized()
            side = tan.cross(up).normalized()
            up2 = side.cross(tan).normalized()
            ring_v = []
            for r in range(ring):
                ang = 2 * math.pi * r / ring
                ring_v.append(bm.verts.new(p + (side * math.cos(ang) + up2 * math.sin(ang)) * radius))
            verts.append(ring_v)
        for s in range(segs):
            for r in range(ring):
                f = bm.faces.new((verts[s][r], verts[s][(r + 1) % ring], verts[s + 1][(r + 1) % ring], verts[s + 1][r]))
                for loop in f.loops:
                    vi = loop.vert
                    ss = s + (1 if vi in verts[s + 1] else 0)
                    loop[uv].uv = (ss / segs, phase + k * 0.0)   # u = along the arc, v = per-arc phase
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    obj.parent = planet_root
    for p in me.polygons:
        p.use_smooth = True
    obj.visible_shadow = False
    return obj


def arc_material(name, core):
    mat, nb, out = new_mat(name)
    uvn = nb.node("ShaderNodeUVMap")
    sep = nb.node("ShaderNodeSeparateXYZ")
    nb.link(uvn.outputs[0], sep.inputs[0])
    u, ph = sep.outputs["X"], sep.outputs["Y"]
    t = time_socket(nb)
    # each arc fires once per 150 frames (integer period) - head position head = fract(t + phase)*1.5 - 0.1
    head = nb.math("SUBTRACT", nb.math("MULTIPLY", nb.math("FRACT", nb.math("ADD", nb.math("MULTIPLY", t, 1.0), ph)), 1.5), 0.1)
    d = nb.math("SUBTRACT", head, u)
    a = nb.math("SUBTRACT", 1.0, nb.math("DIVIDE", d, 0.42), clamp=True)
    on = nb.math("GREATER_THAN", d, 0.0)
    trail = nb.math("MULTIPLY", nb.math("POWER", a, 2.5), on)
    tip = nb.math("EXPONENT", nb.math("MULTIPLY", nb.math("ABSOLUTE", d), -40.0))
    base = 0.012
    inten = nb.math("ADD", base, nb.math("ADD", trail, nb.math("MULTIPLY", tip, 1.5)))
    em = nb.node("ShaderNodeEmission", Color=(0.45, 0.85, 1.0, 1.0))
    if core:
        nb.link(nb.math("MULTIPLY", inten, 22.0), em.inputs["Strength"])
        nb.link(em.outputs[0], out.inputs["Surface"])
    else:
        geo = nb.node("ShaderNodeNewGeometry")
        fac = nb.math("POWER", nb.math("ABSOLUTE", nb.vmath("DOT_PRODUCT", geo.outputs["Normal"], geo.outputs["Incoming"])), 3.0)
        nb.link(nb.math("MULTIPLY", nb.math("MULTIPLY", inten, fac), 2.2), em.inputs["Strength"])
        tr = nb.node("ShaderNodeBsdfTransparent")
        add = nb.node("ShaderNodeAddShader")
        nb.link(tr.outputs[0], add.inputs[0])
        nb.link(em.outputs[0], add.inputs[1])
        nb.link(add.outputs[0], out.inputs["Surface"])
    return mat


state = rng.getstate()
core = build_arcs(pairs, 0.022, "ArcCore")
rng.setstate(state)
halo = build_arcs(pairs, 0.16, "ArcHalo", ring=10)
core.data.materials.append(arc_material("Arc Core", True))
halo.data.materials.append(arc_material("Arc Halo", False))

# ------------------------------------------------------------------ loop: planet sine sway (end = start)
SWAY = math.radians(1.2)
fc = planet_root.driver_add("rotation_euler", 1)     # driver (keyframes get eased in 5.2)
fc.driver.type = "SCRIPTED"
fc.driver.expression = f"{SWAY}*sin(2*pi*(frame-1)/{N_FRAMES})"

# ------------------------------------------------------------------ camera
cam_data = bpy.data.cameras.new("Cam")
cam_data.sensor_fit = "HORIZONTAL"
cam_data.sensor_width = 36
cam_data.lens = 23.5
cam_data.clip_end = 2000
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
dip = math.degrees(math.acos(R / (R + H)))
cam.location = (0, 0, H)
cam.rotation_euler = (math.radians(90 - dip + 4.6), 0, 0)
scene.camera = cam


# ------------------------------------------------------------------ compositor: subtle bloom
def add_bloom(strength=0.5, threshold=0.7, size=0.75):
    try:
        ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
        ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl = ng.nodes.new("CompositorNodeRLayers")
        gl = ng.nodes.new("CompositorNodeGlare")
        gl.inputs["Type"].default_value = "Fog Glow"
        gl.inputs["Quality"].default_value = "High"
        gl.inputs["Threshold"].default_value = threshold
        gl.inputs["Strength"].default_value = strength
        gl.inputs["Size"].default_value = size
        o = ng.nodes.new("NodeGroupOutput")
        ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
        ng.links.new(gl.outputs[0], o.inputs[0])
        scene.compositing_node_group = ng
        scene.render.use_compositing = True
    except Exception as e:  # noqa: BLE001
        print(f"[cdn_planet] bloom skipped: {e}")


add_bloom()
if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N_FRAMES
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # chunked: encode separately after collecting all chunks
else:
    lib.render(args)
