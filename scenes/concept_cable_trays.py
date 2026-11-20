"""Concept 10: looking up at ladder-type cable trays on a data-center ceiling (hero banner loop).

Trays (ladder type: two side rails + cross rungs) recede in perspective on both sides of the frame; the tidy cable bundles
are mostly dark, and small light pulses run along the aqua fiber cables. The low outer trays at both frame edges carry yellow
(single-mode) fiber jumper bundles with amber pulses (they fade out away from the camera, so they never enter the central 40%).
The ceiling (coffered waffle slab with threaded-rod hangers) conveys 'looking up at a ceiling', and the centre is kept dark and empty.

Speed: geometry is a single mesh covering one hanger bay (SUP), built in Python and repeated with an Array modifier
(1 object). Every shape/texture has period SUP, so the loop is exact.
Loop (5 s): the camera advances linearly by SUP (=1.2 m). Pulses have spatial period L and speed v such that (v*T - SUP)/L is an integer.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

import lib  # noqa: E402


def _extra(p):
    p.add_argument("--start", type=int, default=None, help="animation start frame (chunked render)")
    p.add_argument("--end", type=int, default=None, help="animation end frame (chunked render)")
    p.add_argument("--spp", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--size", default="1920x540", help="e.g. 3840x1080")


args = lib.parse_args("concept_cable_trays", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x, scene.render.resolution_y = (int(v) for v in args.size.split("x"))
scene.render.resolution_percentage = 100          # keep 1920x540 for previews too
if args.engine == "cycles":
    scene.cycles.samples = args.spp or 128
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.01
    scene.cycles.max_bounces = 5
    scene.cycles.seed = args.seed
    scene.render.use_persistent_data = True       # only the camera moves, so reuse the BVH
scene.view_settings.view_transform = "AgX"
for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
    try:
        scene.view_settings.look = look
        break
    except TypeError:
        continue
lib.set_world(color=(0.004, 0.006, 0.012, 1.0), strength=1.0)

N = args.frames
FPS = args.fps
T = N / FPS
rng = random.Random(10)

SUP = 1.2                       # tray support (hanger) spacing = loop travel distance = tile length
RUNG = 0.3                      # ladder rung spacing (divisor of SUP)
Y0 = -6.0                       # integer multiple of SUP
COUNT = 55                      # tile repeat count (66 m)
CEIL = 4.6
PULSE_L = 3 * SUP               # aqua pulse spatial period
PULSE_V = 7 * SUP / T           # (v*T - SUP)/L = 6*SUP/(3*SUP) = 2
AMBER_L = 2 * SUP               # amber pulses are a little slower
AMBER_V = 5 * SUP / T           # (5-1)*SUP/(2*SUP) = 2
CAM_Y = f"({SUP}*(frame-1)/{N})"   # camera y (driver expression)

M = lib.make_pbr
# Tray/cable albedo was lowered ~30% after review (so the side trays do not pop brighter than the headline)
steel = M("Tray Steel", (0.14, 0.147, 0.161, 1), metallic=1.0, roughness=0.4)
strut = M("Strut", (0.126, 0.133, 0.14, 1), metallic=1.0, roughness=0.4)
rod_mat = M("Rod", (0.3, 0.3, 0.31, 1), metallic=1.0, roughness=0.3)
# The tile is 1.2 m = SUP, so the concrete pattern also matches the loop period
slab = lib.make_tiled_pbr("Ceiling Slab", "concrete_wall_007", tile=SUP, tint=(0.03, 0.033, 0.042, 1))
blk = [M("Cable Black", (0.0084, 0.0084, 0.0098, 1), roughness=0.45),
       M("Cable Charcoal", (0.021, 0.0224, 0.0252, 1), roughness=0.5),
       M("Cable Slate", (0.0175, 0.0245, 0.035, 1), roughness=0.45)]


def make_fiber(name, base, glow, strength, offset, L, V, idle=0.03, near_only=False, far_fade=None):
    """Fiber cable: subtle base colour plus a short pulse flowing along world y (bright head, trailing tail).

    near_only: emission fades out between 4 and 8 m from the camera (so no colour remains where distant cables converge on the centre).
    far_fade=(d0, d1, floor): emission falls to floor x between d0 and d1 m from the camera (calms distant pulses entering the headline area).
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes["Principled BSDF"]
    lib.set_input(bsdf, "Base Color", base)
    lib.set_input(bsdf, "Roughness", 0.35)
    lib.set_input(bsdf, "Emission Color", glow + (1.0,))

    def drv(expr):
        v = nodes.new("ShaderNodeValue")
        fc = v.outputs[0].driver_add("default_value")
        fc.driver.type = "SCRIPTED"
        fc.driver.expression = expr
        return v.outputs[0]

    def m(op, a, b=None, clamp=False):
        n = nodes.new("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        for k, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[k].default_value = x
            else:
                links.new(x, n.inputs[k])
        return n.outputs[0]

    geo = nodes.new("ShaderNodeNewGeometry")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(geo.outputs["Position"], sep.inputs[0])
    y = sep.outputs["Y"]
    t = drv(f"frame/{FPS}")
    # u in [0,1): distance back from the pulse head / L
    u = m("FRACT", m("DIVIDE", m("SUBTRACT", m("ADD", m("MULTIPLY", t, V), offset), y), L))
    tail = m("POWER", m("SUBTRACT", 1.0, m("MINIMUM", m("DIVIDE", u, 0.22), 1.0)), 3.0)   # tail = 0.22*L
    head = m("LESS_THAN", u, 0.985)   # cuts off sharply ahead of the head
    e = m("ADD", idle, m("MULTIPLY", m("MULTIPLY", tail, head), strength))
    if near_only:
        d = m("SUBTRACT", y, drv(CAM_Y))
        e = m("MULTIPLY", e, m("SUBTRACT", 1.0, m("DIVIDE", m("SUBTRACT", d, 4.0), 4.0), clamp=True))
    if far_fade:
        d0, d1, floor = far_fade
        d = m("SUBTRACT", y, drv(CAM_Y))
        k = m("SUBTRACT", 1.0, m("DIVIDE", m("SUBTRACT", d, d0), d1 - d0), clamp=True)
        e = m("MULTIPLY", e, m("ADD", floor, m("MULTIPLY", k, 1.0 - floor)))
    links.new(e, bsdf.inputs["Emission Strength"])
    return mat


# Pulse strength was lowered after review (so the head does not burn to white and keeps its colour). At 0.6x it still burned to white in AgX,
# so aqua is 0.15x with a deeper emission colour, amber 0.4x. Aqua is reduced further with distance (= toward the frame centre)
PULSE_GAIN = float(os.environ.get("TRAYS_PULSE_GAIN", 0.15))
AMBER_GAIN = float(os.environ.get("TRAYS_AMBER_GAIN", 0.4))
aqua = [make_fiber(f"Fiber Aqua {k}", (0.02, 0.22, 0.25, 1), (0.1, 0.85, 1.0), 40.0 * PULSE_GAIN, k * 1.37, PULSE_L, PULSE_V,
                   far_fade=(4.0, 8.0, 0.1)) for k in range(3)]
amber = [make_fiber(f"Fiber Amber {k}", (0.5, 0.2, 0.01, 1), (1.0, 0.42, 0.05), 18.0 * AMBER_GAIN, k * 0.83, AMBER_L, AMBER_V,
                    idle=0.05, near_only=True) for k in range(3)]


# ------------------------------------------------------------------ tile mesh builder (1 object)
class Builder:
    def __init__(self):
        self.verts, self.faces, self.mat_idx, self.smooth, self.mats = [], [], [], [], []

    def _slot(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def box(self, size, loc, mat):
        sx, sy, sz = (s / 2 for s in size)
        x, y, z = loc
        b = len(self.verts)
        self.verts += [(x + dx * sx, y + dy * sy, z + dz * sz)
                       for dz in (-1, 1) for dy in (-1, 1) for dx in (-1, 1)]
        quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
        s = self._slot(mat)
        for q in quads:
            self.faces.append(tuple(b + i for i in q))
            self.mat_idx.append(s)
            self.smooth.append(False)

    def tube(self, pts, r, mat, n=8, vertical=False):
        """Tube along pts. vertical=False runs along y (cross-section in xz); True runs along z (cross-section in xy)."""
        b = len(self.verts)
        for (x, y, z) in pts:
            for j in range(n):
                a = 2 * math.pi * j / n
                if vertical:
                    self.verts.append((x + r * math.cos(a), y + r * math.sin(a), z))
                else:
                    self.verts.append((x + r * math.cos(a), y, z + r * math.sin(a)))
        s = self._slot(mat)
        for i in range(len(pts) - 1):
            for j in range(n):
                j2 = (j + 1) % n
                q = (b + i * n + j, b + (i + 1) * n + j, b + (i + 1) * n + j2, b + i * n + j2)
                self.faces.append(q if not vertical else q[::-1])
                self.mat_idx.append(s)
                self.smooth.append(True)

    def build(self, name):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.verts, [], self.faces)
        for mat in self.mats:
            me.materials.append(mat)
        me.polygons.foreach_set("material_index", self.mat_idx)
        me.polygons.foreach_set("use_smooth", self.smooth)
        me.update()
        obj = bpy.data.objects.new(name, me)
        bpy.context.collection.objects.link(obj)
        return obj


B = Builder()
SEG = 16                        # subdivisions per cable tile (4 per rung bay)


def cable_bundle(x, z, width, n_rows, mats, r=0.012, wander=0.006, sag=0.006):
    """Cable bundle on the tray floor (z). Split into groups of 3-5 strands; each group gets different thickness / sideways wander / sag.

    Wander has period SUP (feels tied with a tie at each hanger) and sag is between rungs (period RUNG), so tiles join seamlessly.
    """
    left = x - width / 2
    while left < x + width / 2 - 2 * r:
        k = rng.randint(3, 5)
        rr = r * rng.uniform(0.8, 1.15)
        k = min(k, max(1, int((x + width / 2 - left) / (2 * rr))))
        amp = rng.uniform(0.3, 1.0) * wander
        ph = rng.uniform(0, 2 * math.pi)
        amp2, ph2 = rng.uniform(0.0, 0.5) * wander, rng.uniform(0, 2 * math.pi)
        sg = sag * rng.uniform(0.4, 1.0)
        rows = max(1, n_rows - rng.randint(0, 1))
        for row in range(rows):
            for c in range(k - row):
                cx = left + rr + c * 2 * rr + row * rr
                cz = z + rr + row * 1.75 * rr
                mat = rng.choice(mats)
                pts = []
                for i in range(SEG + 1):
                    y = SUP * i / SEG
                    w = 2 * math.pi * y / SUP
                    dx = amp * math.sin(w + ph) + amp2 * math.sin(2 * w + ph2)
                    dz = -sg * math.sin(math.pi * y / RUNG) ** 2 * (1.0 if row == 0 else 0.6)
                    pts.append((cx + dx, y, cz + dz))
                B.tube(pts, rr, mat, n=8)
        left += k * 2 * rr + rng.uniform(0.004, 0.012) + 2 * wander * 0.5


def ladder_tray(x, z, w, rail_h=0.1):
    for dx in (-w / 2, w / 2):
        B.box((0.015, SUP, rail_h), (x + dx, SUP / 2, z + rail_h / 2), steel)
        B.box((0.04, SUP, 0.012), (x + dx - math.copysign(0.013, dx), SUP / 2, z + rail_h), steel)
        B.box((0.03, SUP, 0.01), (x + dx - math.copysign(0.008, dx), SUP / 2, z + 0.005), steel)
    for i in range(int(round(SUP / RUNG))):
        B.box((w, 0.025, 0.018), (x, i * RUNG + 0.15, z + 0.01), steel)


def support(x0, x1, z):
    """Trapeze hanger (placed at y=SUP/2 rather than the tile's y=0.6...: so it does not overlap the tile boundary).

    Two threaded rods descending from the ceiling anchor plate + nuts + a C-channel below.
    """
    y = SUP / 2
    B.box((x1 - x0 + 0.14, 0.042, 0.042), ((x0 + x1) / 2, y, z - 0.021), strut)
    for xr in (x0 - 0.045, x1 + 0.045):
        B.tube([(xr, y, z - 0.07), (xr, y, CEIL)], 0.007, rod_mat, n=6, vertical=True)
        B.box((0.024, 0.024, 0.012), (xr, y, z - 0.05), rod_mat)       # lower nut
        B.box((0.024, 0.024, 0.012), (xr, y, z + 0.006), rod_mat)      # upper nut
        B.box((0.07, 0.07, 0.008), (xr, y, CEIL - 0.004), strut)       # ceiling anchor plate


# Tray layout: (x centre, height, width, cable kind). The centre (|x|<1.2) is left empty
TRAYS = [
    (-2.6, 3.05, 0.6, "power"),
    (-1.55, 3.45, 0.45, "fiber"),
    (1.55, 3.45, 0.45, "fiber"),
    (2.6, 3.05, 0.6, "power"),
    (-3.3, 2.8, 0.36, "amber"),      # low outer trays at the frame edges: yellow fiber jumpers + amber pulses
    (3.3, 2.8, 0.36, "amber"),
]
for x, z, w, kind in TRAYS:
    ladder_tray(x, z, w)
    if kind == "power":
        cable_bundle(x, z + 0.02, w - 0.06, 3, blk, r=0.014)
    elif kind == "fiber":
        cable_bundle(x - w * 0.14, z + 0.02, w * 0.6, 3, blk + blk, r=0.009)
        cable_bundle(x + w * 0.3, z + 0.02, w * 0.2, 1, aqua, r=0.007, wander=0.003, sag=0.004)
    else:
        cable_bundle(x, z + 0.02, w - 0.05, 2, amber + amber + [blk[1]], r=0.0065, wander=0.004, sag=0.005)
    support(x - w / 2, x + w / 2, z)

# Ceiling: slab + coffered beams (waffle). One cross beam per tile (y=SUP/2 = hanger line), longitudinal beams every 1.5 m
B.box((16, SUP, 0.3), (0, SUP / 2, CEIL + 0.15 + 0.22), slab)
B.box((16, 0.16, 0.22), (0, SUP / 2, CEIL + 0.11), slab)
for i in range(-5, 6):
    xr = (i + 0.5) * 1.5
    if abs(xr) < 2.0:            # keep only the cross beam in the centre for calm
        continue
    B.box((0.16, SUP, 0.2), (xr, SUP / 2, CEIL + 0.12), slab)   # slightly shallower than the cross beam (avoids overlapping faces)

tile = B.build("Tray Tile")
tile.location = (0, Y0, 0)
arr = tile.modifiers.new("Array", "ARRAY")
arr.count = COUNT
arr.use_relative_offset = False
arr.use_constant_offset = True
arr.constant_offset_displace = (0, SUP, 0)
arr.use_merge_vertices = True
arr.merge_threshold = 0.0002
print(f"[cable_trays] tile verts={len(B.verts)} faces={len(B.faces)} x{COUNT}")

# ------------------------------------------------------------------ lighting (all area lights hidden from the camera)
LEN, CY = COUNT * SUP, Y0 + COUNT * SUP / 2


def strip(name, loc, roll_deg, energy, color, size=0.3, length=LEN, parent=None):
    d = bpy.data.lights.new(name, "AREA")
    d.shape, d.size, d.size_y = "RECTANGLE", size, length
    d.energy = energy
    d.color = color
    o = bpy.data.objects.new(name, d)
    o.location = loc
    o.rotation_euler = (0, math.radians(roll_deg), 0)
    o.visible_camera = False
    o.parent = parent
    bpy.context.collection.objects.link(o)
    return o


COOL = (0.62, 0.8, 1.0)
for sx in (-1, 1):
    strip("Side Fill", (sx * 2.95, CY, 2.2), 180, 1000, COOL)                  # lights upward (tray undersides / ceiling)
    strip("Inner Fill", (sx * 2.1, CY, 2.0), 180 - 25 * sx, 420, COOL)

# ------------------------------------------------------------------ camera: advance while looking up
rig = bpy.data.objects.new("Rig", None)
bpy.context.collection.objects.link(rig)
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 18
cam = bpy.data.objects.new("Camera", cam_data)
bpy.context.collection.objects.link(cam)
scene.camera = cam
cam.parent = rig
CAM_Z = 1.7
cam.location = (0, 0, CAM_Z)
cam.rotation_euler = (math.radians(90 + 26), 0, 0)
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = 4.0
cam_data.dof.aperture_fstop = 4.0
# Amber spill: warm light under the outer trays. It is a short strip that moves with the camera, so the far area (= frame centre) is not tinted
for sx in (-1, 1):
    strip("Amber Spill", (sx * 3.45, 2.5, 2.35), 180 + 12 * sx, 40, (1.0, 0.45, 0.1), size=0.25, length=6.0, parent=rig)
# Linear advance is done with a driver. (In Blender 5.2 lib.set_default_interpolation("LINEAR") has no effect, so
# keyframes become Bezier ease-in/out and the camera appears to stop at the loop seam.)
fc = rig.driver_add("location", 1)
fc.driver.type = "SCRIPTED"
fc.driver.expression = CAM_Y



# ------------------------------------------------------------------ compositor: light distance fade (calms stair-stepping/moire of distant cable stripes)
def add_distance_fade(start=4.0, depth=9.0, amount=0.65, fog=(0.004, 0.006, 0.012)):
    try:
        scene.view_layers[0].use_pass_mist = True
        ms = scene.world.mist_settings
        ms.start, ms.depth, ms.falloff = start, depth, "LINEAR"
        ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
        ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl = ng.nodes.new("CompositorNodeRLayers")
        mul = ng.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.use_clamp = True
        ng.links.new(rl.outputs["Mist"], mul.inputs[0])
        mul.inputs[1].default_value = amount
        mix = ng.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MIX"
        col_in = [i for i in mix.inputs if i.type == "RGBA"]       # same-named sockets exist per type, so pick by type
        col_out = [o for o in mix.outputs if o.type == "RGBA"][0]
        ng.links.new(mul.outputs[0], mix.inputs[0])
        ng.links.new(rl.outputs["Image"], col_in[0])
        col_in[1].default_value = fog + (1.0,)
        out = ng.nodes.new("NodeGroupOutput")
        ng.links.new(col_out, out.inputs[0])
        scene.compositing_node_group = ng
        scene.render.use_compositing = True
    except Exception as e:  # noqa: BLE001
        print(f"[cable_trays] distance fade skipped: {e}")


if not os.environ.get("TRAYS_NO_FADE"):
    add_distance_fade()

if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # chunked: encode separately after collecting all chunks
else:
    lib.render(args)
