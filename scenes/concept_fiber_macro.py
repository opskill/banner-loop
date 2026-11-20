"""Concept 02 fiber macro: a very close, head-on view of rows of patch-panel (LC duplex) ports, drifting slowly sideways.

Shallow depth of field: focus on the panel face; fiber-tip light points right in front of the camera become large bokeh.
The whole scene repeats along x with period PERIOD and the camera (+ light rig) moves exactly PERIOD,
frame N+1 == frame 1 (seamless loop). The screen centre is kept dark with lighting/emission masks.

Post-review changes: half the travel speed (period = 2 modules = 0.18m); removed the bokeh discs floating in front of the camera and the aperture filter (edge ring);
added a very weak centre fill light so the centre does not go pure black.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

import lib  # noqa: E402



def _extra(p):
    p.add_argument("--range", type=int, nargs=2, default=None, help="render only frames in this range (a chunk, for sharing the GPU)")
    p.add_argument("--start", type=int, default=None, help="start frame, usable instead of --range")
    p.add_argument("--end", type=int, default=None, help="end frame, usable instead of --range")
    p.add_argument("--spp", type=int, default=None, help="max sample count")
    p.add_argument("--seed", type=int, default=0, help="Cycles noise seed (for loop verification)")
    p.add_argument("--uhd", action="store_true", help="3840x1080 (default 1920x540)")


args = lib.parse_args("concept_fiber_macro", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x, scene.render.resolution_y = (3840, 1080) if args.uhd else (1920, 540)   # 32:9
if args.range is None and (args.start or args.end):
    args.range = [args.start or 1, args.end or args.frames]
if args.range:
    scene.frame_start, scene.frame_end = args.range
if args.engine == "cycles":
    scene.cycles.samples = args.spp or (64 if args.preview else 256)
    scene.cycles.adaptive_min_samples = 32
    scene.cycles.adaptive_threshold = 0.015
    scene.cycles.max_bounces = 6
    scene.cycles.seed = args.seed
    scene.render.use_motion_blur = True
    scene.render.motion_blur_shutter = 0.25
scene.view_settings.view_transform = "AgX"
for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
    try:
        scene.view_settings.look = look
        break
    except TypeError:
        continue
lib.set_world(color=(0.003, 0.004, 0.007, 1.0), strength=1.0)

N = args.frames
PORT = 0.0135                  # LC duplex adapter pitch (m)
PER_MOD = 6
GAP = 0.009
MOD_W = PORT * PER_MOD + GAP   # module width
MODS_PER_PERIOD = 2                # 4 -> 2: halves the travel per loop (= travel speed)
PERIOD = MOD_W * MODS_PER_PERIOD   # the scene repeats every this distance = camera travel over the loop (0.18m)
COPIES = range(-4, 6)              # range of period copies (screen + travel + cable length margin)
ROW_Z = (0.0445, 0.0, -0.0445)
CAM_D = 0.38                       # frame width about 0.40m. The period is 0.18m so the same layout appears twice, but the centre is dark,
#                                    and the bright side bands (about 0.12m wide each) are 0.28m apart and show different phases. Module order also differs per row
LENS = 34.0
FSTOP = 2.8
HALF_TAN = 18.0 / LENS             # tan of the camera's horizontal half-angle (sensor 36)
FOCUS = CAM_D - 0.012
R_AP = LENS / 1000 / (2 * FSTOP)   # aperture radius (m)

# Each module has its own character (colour ratio / plugged ratio / sag / flow direction). Module order is shifted per row so nothing repeats vertically either.
MODULES = [
    dict(w=(7, 1, 0.15), fill=0.94, droop=(0.9, 1.1), side=0.85),    # dense aqua (OM3/4)
    dict(w=(1.5, 6, 0.0), fill=0.80, droop=(1.15, 1.5), side=0.15),  # mostly navy, deep sag
    dict(w=(4, 2, 1.6), fill=0.68, droop=(0.8, 1.0), side=0.6),      # mixed + orange (multimode) accent
    dict(w=(3, 3, 0.0), fill=0.42, droop=(1.2, 1.6), side=0.35),     # sparse, many empty ports/dust caps
]
ROW_SHIFT = (0, 2, 1)              # the period is 2 modules, so each row alternates modules (0,1) / (2,3) / (1,2)


# ------------------------------------------------------------------ screen-position mask (dark centre)
def _math(nt, op, a, b=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def screen_mask(nt, lo=0.28, hi=0.72, floor=0.12):
    """Derive the horizontal screen position u (0=centre, 1=edge) from camera-space coordinates and reduce emission at the centre."""
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Camera"], sep.inputs[0])
    u = _math(nt, "DIVIDE", _math(nt, "ABSOLUTE", sep.outputs["X"]),
              _math(nt, "MAXIMUM", _math(nt, "ABSOLUTE", sep.outputs["Z"]), 0.01))
    u = _math(nt, "DIVIDE", u, HALF_TAN)
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.interpolation_type = "SMOOTHERSTEP"
    mr.inputs["From Min"].default_value = lo
    mr.inputs["From Max"].default_value = hi
    mr.inputs["To Min"].default_value = floor
    nt.links.new(u, mr.inputs["Value"])
    return mr.outputs["Result"]


def glow_mat(name, color, strength, lo=0.44, hi=0.8, floor=0.0):
    """Emissive material. Fully off at the screen centre (|u| < lo, where the headline goes)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = color
    nt.links.new(_math(nt, "MULTIPLY", screen_mask(nt, lo, hi, floor), strength), em.inputs["Strength"])
    nt.links.new(em.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return mat


# ------------------------------------------------------------------ materials
M = lib.make_pbr
panel_mat = M("Panel", (0.018, 0.019, 0.022, 1), metallic=0.85, roughness=0.38, bump=0.02, bump_scale=2500.0)
adapter_mat = M("Adapter", (0.012, 0.012, 0.014, 1), roughness=0.45)
flange_mat = M("Adapter Flange", (0.03, 0.031, 0.034, 1), metallic=0.9, roughness=0.32)
hole_mat = M("Port Hole", (0.0, 0.0, 0.0, 1), roughness=0.9)
sleeve_mat = M("Ceramic Sleeve", (0.16, 0.16, 0.15, 1), roughness=0.3)
cap_mat = M("Dust Cap", (0.02, 0.025, 0.035, 1), roughness=0.55)
conn_mats = {
    "aqua": M("LC Aqua", (0.02, 0.32, 0.38, 1), roughness=0.3, coat=0.4),
    "blue": M("LC Blue", (0.01, 0.05, 0.28, 1), roughness=0.3, coat=0.4),
    "beige": M("LC Beige", (0.45, 0.4, 0.3, 1), roughness=0.35, coat=0.3),
}
boot_mats = {   # boots are matte rubber in the same colour family
    "aqua": M("Boot Aqua", (0.015, 0.22, 0.27, 1), roughness=0.6),
    "blue": M("Boot Blue", (0.008, 0.035, 0.2, 1), roughness=0.6),
    "beige": M("Boot Beige", (0.3, 0.27, 0.2, 1), roughness=0.6),
}
fiber_mats = {
    "aqua": M("Fiber Aqua", (0.03, 0.30, 0.36, 1), roughness=0.42),
    "blue": M("Fiber Blue", (0.012, 0.06, 0.22, 1), roughness=0.42),
    "beige": M("Fiber Orange", (0.5, 0.17, 0.03, 1), roughness=0.42),   # multimode OM1/2 orange
}
tip_cool = glow_mat("Tip Cool", (0.25, 0.75, 1.0, 1), 18.0)
tip_warm = glow_mat("Tip Warm", (1.0, 0.5, 0.15, 1), 14.0)
led_g = glow_mat("LED Cool", (0.2, 0.8, 1.0, 1), 4.0)
led_a = glow_mat("LED Amber", (1.0, 0.45, 0.1, 1), 4.5)


# ------------------------------------------------------------------ decide one period's worth of 'design' (random) first, then copy it
rng = random.Random(21)
design = []   # (row, slot_x, kind, color, side, droop, seed) ; kind: plug | empty_glow | cap | empty
for r, _ in enumerate(ROW_Z):
    for m in range(MODS_PER_PERIOD):
        spec = MODULES[(m + ROW_SHIFT[r]) % len(MODULES)]
        for j in range(PER_MOD):
            x = m * MOD_W + GAP / 2 + (j + 0.5) * PORT
            roll = rng.random()
            if roll < spec["fill"]:
                kind = "plug"
            else:
                kind = rng.choices(["empty_glow", "cap", "empty"], weights=[4, 4, 2])[0]
            col = rng.choices(["aqua", "blue", "beige"], weights=spec["w"])[0]
            side = 1 if rng.random() < spec["side"] else -1
            design.append((r, x, kind, col, side, rng.uniform(*spec["droop"]), rng.random()))
leds = [(r, m * MOD_W + MOD_W - GAP * 0.5, rng.random()) for r in range(len(ROW_Z)) for m in range(MODS_PER_PERIOD)]

# Bokeh: loose fiber tips floating between the camera and the panel (in front of focus). Fewer of them, with varied distance/brightness.
# Disc size is set by the real depth of field (distance); emission strength is back-solved from the desired disc brightness t.
bokeh = []
brng = random.Random(7)
N_BOKEH = 0                    # removed after review (the floating discs were distracting and produced rings under super-resolution upscaling). Raise the value to bring them back
B_PERIOD = PERIOD * 2 / 3      # bokeh layout period. The bokeh rig follows by PERIOD/3 over the loop, so the motion relative to the camera is exactly one period
for i in range(N_BOKEH):
    d = (0.135, 0.20, 0.16, 0.21, 0.175, 0.19)[i] + brng.uniform(-0.006, 0.006)   # distance from the camera
    bx = (i + brng.uniform(0.25, 0.75)) * B_PERIOD / N_BOKEH
    bz = 0.004 + brng.uniform(-0.115, 0.115) * d
    r_disc = R_AP * (FOCUS - d) / FOCUS
    r_e = r_disc * brng.uniform(0.2, 0.26)
    t = (0.42, 0.6, 0.28, 0.5, 0.36, 0.7)[i]
    warm = i == 3
    col = (1.0, 0.42, 0.08, 1) if warm else brng.choice(((0.08, 0.5, 1.0, 1), (0.04, 0.8, 0.9, 1), (0.15, 0.4, 1.0, 1)))
    mat = glow_mat(f"Bokeh {i}", col, t * ((r_disc + r_e) / r_e) ** 2, lo=0.5, hi=0.86, floor=0.0)
    bokeh.append((bx, d - CAM_D, bz, r_e, mat))


def fiber(name, pts, radius, mat):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 3
    sp = cu.splines.new("NURBS")
    sp.points.add(len(pts) - 1)
    for p, c in zip(sp.points, pts):
        p.co = (*c, 1.0)
    sp.use_endpoint_u = True
    sp.order_u = 4
    sp.resolution_u = 10
    ob = bpy.data.objects.new(name, cu)
    bpy.context.collection.objects.link(ob)
    cu.materials.append(mat)
    return ob


def join(name, parts):
    """Join several shapes (after applying modifiers/transforms) into one mesh. Origin at (0,0,0)."""
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.convert(target="MESH")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if len(parts) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    return ob


def place(tpl, loc):
    ob = tpl.copy()          # shared mesh
    ob.location = loc
    bpy.context.collection.objects.link(ob)
    return ob


RX = math.radians(90)
DX = 0.0031                    # left/right offset of the two duplex cores


def rbox(name, size, loc, mat, rot_x=0.0, bevel=0.0003):
    ob = lib.box(name, size, loc, mat, bevel=bevel)
    ob.rotation_euler = (rot_x, 0, 0)
    return ob


def make_adapter():
    """LC duplex adapter: metal flange + black body + two holes (key slots) + inner ceramic sleeve."""
    parts = [lib.box("a", (0.0128, 0.0008, 0.0114), (0, -0.0004, 0), flange_mat, bevel=0.0003),
             lib.box("a", (0.0118, 0.004, 0.0098), (0, -0.0015, 0), adapter_mat, bevel=0.0004)]
    for dx in (-DX, DX):
        parts.append(lib.box("a", (0.0042, 0.001, 0.0046), (dx, -0.0036, 0), hole_mat, bevel=0.0))
        parts.append(lib.box("a", (0.0018, 0.001, 0.0012), (dx, -0.0036, 0.0027), hole_mat, bevel=0.0))   # latch key slot
        parts.append(lib.cyl("a", 0.00125, 0.0012, (dx, -0.0038, -0.0003), sleeve_mat, rot=(RX, 0, 0), bevel=0.0, verts=20))
        parts.append(lib.cyl("a", 0.0007, 0.0013, (dx, -0.0039, -0.0003), hole_mat, rot=(RX, 0, 0), bevel=0.0, verts=16))
    return join("Adapter T", parts)


def make_plug(col):
    """LC duplex plug: 2 bodies + 2 latches + duplex clip (trigger) + 2 tapered boots with ribs."""
    body, boot = conn_mats[col], boot_mats[col]
    parts = []
    for dx in (-DX, DX):
        parts.append(lib.box("p", (0.0045, 0.0125, 0.0050), (dx, -0.00925, -0.0002), body, bevel=0.0005))
        # latch: the front (panel side) is attached to the body and lifts toward the back
        parts.append(rbox("p", (0.0024, 0.0100, 0.0006), (dx, -0.0098, 0.0034), body, rot_x=math.radians(-9)))
        parts.append(rbox("p", (0.0026, 0.0016, 0.0012), (dx, -0.0052, 0.0027), body))        # latch catch lip
        # rear collar + boot (tapering in three steps) + ribs
        parts.append(lib.cyl("p", 0.0023, 0.0022, (dx, -0.0166, -0.0002), body, rot=(RX, 0, 0), bevel=0.0002, verts=20))
        for k, (rad, y0, y1) in enumerate(((0.00205, -0.0177, -0.0235), (0.00175, -0.0235, -0.0290), (0.0014, -0.0290, -0.0345))):
            parts.append(lib.cyl("p", rad, y0 - y1, (dx, (y0 + y1) / 2, -0.0002), boot, rot=(RX, 0, 0), bevel=0.0002, verts=20))
        for k in range(4):
            parts.append(lib.cyl("p", 0.00232, 0.0006, (dx, -0.0188 - k * 0.0013, -0.0002), boot, rot=(RX, 0, 0), bevel=0.0,
                                 verts=20))
    # duplex clip: joins the two bodies and the upper trigger covers both latches
    parts.append(lib.box("p", (0.0112, 0.0036, 0.0058), (0, -0.0140, -0.0002), body, bevel=0.0005))
    parts.append(rbox("p", (0.0100, 0.0062, 0.0007), (0, -0.0142, 0.0046), body, rot_x=math.radians(7)))
    return join(f"Plug T {col}", parts)


def make_cap():
    parts = []
    for dx in (-DX, DX):
        parts.append(lib.cyl("c", 0.0019, 0.0055, (dx, -0.0062, -0.0003), cap_mat, rot=(RX, 0, 0), bevel=0.0003, verts=20))
        parts.append(lib.cyl("c", 0.0023, 0.0009, (dx, -0.0094, -0.0003), cap_mat, rot=(RX, 0, 0), bevel=0.0002, verts=20))
    return join("Cap T", parts)


adapter_t = make_adapter()
plug_t = {c: make_plug(c) for c in conn_mats}
cap_t = make_cap()
tip_t = {m.name: lib.ball("Tip T", 0.0007, (0, 0, 0), m) for m in (tip_cool, tip_warm)}
led_t = {m.name: lib.box("LED T", (0.0013, 0.001, 0.0013), (0, 0, 0), m, bevel=0.0) for m in (led_g, led_a)}
bokeh_t = [lib.ball(f"Bokeh T {i}", b[3], (0, 0, 0), b[4]) for i, b in enumerate(bokeh)]
templates = [adapter_t, cap_t, *plug_t.values(), *tip_t.values(), *led_t.values(), *bokeh_t]

# panel body (several consecutive 1U plates)
X_LO = COPIES.start * PERIOD - 0.05
X_HI = COPIES.stop * PERIOD + 0.05
# One plate per period (shared mesh): the surface noise bump is based on object coordinates, so this is what makes even the texture periodic
panel_t = lib.box("Panel T", (PERIOD, 0.004, 0.0430), (0, 0, 0), panel_mat, bevel=0.0006)
for poly in panel_t.data.polygons:      # smooth shading on a large flat face tilts normals toward the plate ends and makes brightness step at the seams
    poly.use_smooth = False
for c in COPIES:
    for r, z in enumerate(ROW_Z):
        place(panel_t, ((c + 0.5) * PERIOD, 0.002, z))
bpy.data.objects.remove(panel_t)
lib.box("Rack Back", (X_HI - X_LO, 0.01, 0.4), ((X_LO + X_HI) / 2, 0.03, 0), M("Back", (0.005, 0.005, 0.006, 1), roughness=0.7),
        bevel=0.0)

# Per row, a trunk bundle running horizontally along the bottom (where patch cords merge). The waves are integer multiples of the period, so they do not break the loop.
trng = random.Random(5)
STEPS = 12
for r, z0 in enumerate(ROW_Z):
    for k in range(7):
        col = trng.choices(["aqua", "blue", "beige"], weights=(5, 4, 0.5))[0]
        ph, amp, harm = trng.uniform(0, 6.28), trng.uniform(0.0008, 0.0022), trng.choice((1, 2, 3))
        yk, zk = -0.040 - 0.0035 * (k % 3) - trng.uniform(0, 0.002), z0 - 0.0225 - 0.0021 * (k // 3) - trng.uniform(0, 0.0012)
        pts = []
        for i in range((len(COPIES) + 1) * STEPS + 1):
            x = X_LO + 0.05 - PERIOD / 2 + i * PERIOD / STEPS
            a = 2 * math.pi * harm * x / PERIOD + ph
            pts.append((x, yk + 0.6 * amp * math.cos(a), zk + amp * math.sin(a)))
        fiber(f"Trunk {r}{k}", pts, 0.00095, fiber_mats[col])

n = 0
for c in COPIES:
    ox = c * PERIOD
    for (r, x, kind, col, side, droop, seed) in design:
        X = ox + x
        z = ROW_Z[r] + 0.004
        place(adapter_t, (X, 0, z))
        if kind == "plug":
            place(plug_t[col], (X, 0, z))
            # zip cord: leaves the boot end slightly forward, then sags down, flows sideways and joins the lower trunk bundle
            zb = ROW_Z[r] - 0.019 * min(droop, 1.25)
            yb = -0.042 - 0.012 * seed
            pts = [(X, -0.031, z), (X, -0.041, z - 0.002), (X + side * 0.003, yb, z - 0.010 * droop),
                   (X + side * 0.014 * droop, yb - 0.003, zb), (X + side * 0.05, yb - 0.006, zb - 0.004),
                   (X + side * 0.11, -0.043 - 0.006 * seed, ROW_Z[r] - 0.0235), (X + side * 0.20, -0.043 - 0.006 * seed, ROW_Z[r] - 0.0245)]
            for k, dx in enumerate((-DX, DX)):
                # the two strands split apart at the connector and soon join into a zip cord
                fiber(f"Fiber {n}{k}", [(p[0] + (dx if i < 2 else dx * 0.36), p[1], p[2]) for i, p in enumerate(pts)], 0.00095,
                      fiber_mats[col])
        elif kind == "empty_glow":
            # the ferrule end inside an empty port glows (fiber-tip light point). Masked off at the screen centre.
            for dx in (-DX, DX):
                place(tip_t[(tip_warm if seed < 0.18 else tip_cool).name], (X + dx, -0.0044, z - 0.0003))
        elif kind == "cap":
            place(cap_t, (X, 0, z))
        n += 1
    for (r, x, seed) in leds:
        if seed < 0.6:
            place(led_t[(led_a if seed < 0.12 else led_g).name], (ox + x, -0.0006, ROW_Z[r] - 0.016))
# Bokeh emitters: attached to a rig that follows at half the camera speed (the foreground flows calmly instead of whipping past)
bokeh_rig = lib.group("Bokeh Rig")
for j in range(-2, 5):
    for i, (bx, by, bz, r_e, mat) in enumerate(bokeh):
        place(bokeh_t[i], (j * B_PERIOD + bx, by, bz)).parent = bokeh_rig
for t in templates:
    bpy.data.objects.remove(t)
print(f"[fiber_macro] ports: {n}, period {PERIOD:.4f} m")

# ------------------------------------------------------------------ camera + light rig (moving together by PERIOD along x)
rig = lib.group("Rig")
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = LENS
cam_data.sensor_fit = "HORIZONTAL"
cam_data.clip_start = 0.0004
cam = bpy.data.objects.new("Camera", cam_data)
bpy.context.collection.objects.link(cam)
cam.parent = rig
cam.location = (0, -CAM_D, 0.004)
cam.rotation_euler = (math.radians(90), 0, 0)
scene.camera = cam
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = FOCUS
cam_data.dof.aperture_fstop = FSTOP
cam_data.dof.aperture_blades = 0          # circular bokeh


def add_aperture_filter():
    """Put a transparency filter right in front of the lens (1.2mm) to vary the transmittance across the aperture by radius.

    Distribution slightly dark at the centre and bright at the edge (spherical-aberration over-corrected lens) + weak concentric rings (onion rings).
    In-focus areas keep their sharpness; only out-of-focus light points become real-lens bokeh with bright rims.
    Toward the screen edges the filter and aperture misalign slightly, making the bokeh weakly asymmetric.
    """
    mat = bpy.data.materials.new("Aperture Filter")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Camera"], sep.inputs[0])
    r = _math(nt, "SQRT", _math(nt, "ADD", _math(nt, "POWER", sep.outputs["X"], 2.0), _math(nt, "POWER", sep.outputs["Y"], 2.0)))
    r = _math(nt, "DIVIDE", r, R_AP)
    rim = nt.nodes.new("ShaderNodeMapRange")
    rim.interpolation_type = "SMOOTHSTEP"
    rim.inputs["From Min"].default_value = 0.62
    rim.inputs["From Max"].default_value = 0.93
    rim.inputs["To Min"].default_value = 0.42
    rim.inputs["To Max"].default_value = 1.0
    nt.links.new(r, rim.inputs["Value"])
    ring = _math(nt, "MULTIPLY", _math(nt, "SINE", _math(nt, "MULTIPLY", r, 34.0)), 0.045)
    val = _math(nt, "ADD", rim.outputs["Result"], ring)
    rgb = nt.nodes.new("ShaderNodeCombineColor")
    for i in range(3):
        nt.links.new(val, rgb.inputs[i])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    nt.links.new(rgb.outputs[0], tr.inputs["Color"])
    nt.links.new(tr.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    bpy.ops.mesh.primitive_plane_add(size=0.06)
    ob = bpy.context.active_object
    ob.name = "Aperture Filter"
    ob.data.materials.append(mat)
    ob.parent = cam
    ob.location = (0, 0, -0.0012)
    for attr in ("visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter", "visible_shadow"):
        setattr(ob, attr, False)
    scene.view_settings.exposure = 0.75      # compensates the filter's average transmittance (about 0.6)


if N_BOKEH:                    # the aperture filter is for bokeh discs. Without discs it would leave only the rim ring, so it is dropped too
    add_aperture_filter()
else:
    scene.view_settings.exposure = 0.1       # same brightness as the filter (average transmittance about 0.64) + exposure 0.75 combination


def spot(name, loc, target, energy, color, size=0.03, angle=40):
    data = bpy.data.lights.new(name, "SPOT")
    data.energy = energy
    data.color = color
    data.spot_size = math.radians(angle)
    data.spot_blend = 0.9
    data.shadow_soft_size = size
    ob = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(ob)
    ob.parent = rig
    ob.location = loc
    tgt = bpy.data.objects.new(name + " T", None)
    bpy.context.collection.objects.link(tgt)
    tgt.parent = rig
    tgt.location = target
    lib.look_at(ob, tgt)
    return ob


# Cool key light from the left/right outside at an angle (falls off dark toward the centre)
spot("Key L", (-0.32, -0.17, 0.07), (-0.15, 0, -0.005), 4.2, (0.6, 0.82, 1.0))
spot("Key R", (0.32, -0.17, 0.07), (0.15, 0, -0.005), 4.2, (0.6, 0.82, 1.0))
# Very weak warm rim from below (one side only)
spot("Warm Rim", (0.23, -0.10, -0.09), (0.13, 0, 0.0), 0.4, (1.0, 0.6, 0.3), angle=30)

# Centre fill: leaves a very faint panel/cable outline in the formerly pure-black centre (headline area) so the mobile 16:10 crop does not look empty
CENTER_FILL = float(os.environ.get("FIBER_CENTER_FILL", 0.5))
if CENTER_FILL:
    spot("Centre Fill", (0.0, -0.30, 0.10), (0.0, 0, -0.005), CENTER_FILL, (0.55, 0.78, 1.0), size=0.05, angle=34)

# Move exactly PERIOD at constant speed from frame 1 to N+1.
# (In Blender 5.x, setting the default keyframe interpolation has no effect and Bezier ease in/out appears, so a driver is used directly.
#  frame is a float including subframes, so motion blur is identical at the loop seam too.)
def linear_x(ob, dist):
    d = ob.driver_add("location", 0).driver
    d.type = "SCRIPTED"
    d.expression = f"{dist!r}*(frame-1)/{N}"


linear_x(rig, PERIOD)
linear_x(bokeh_rig, PERIOD - B_PERIOD)


# ------------------------------------------------------------------ compositor: subtle bloom
def add_bloom(strength=0.45, threshold=0.7, size=0.7):
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
        out = ng.nodes.new("NodeGroupOutput")
        ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
        ng.links.new(gl.outputs[0], out.inputs[0])
        scene.compositing_node_group = ng
        scene.render.use_compositing = True
    except Exception as e:  # noqa: BLE001
        print(f"[fiber_macro] bloom skipped: {e}")


add_bloom()

if args.still is None and args.range:
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # chunk: encoding is done separately after all chunks are gathered
else:
    lib.render(args)
