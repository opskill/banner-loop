"""Concept 01 IX hub: thin fibre-optic light strands entering from the left and right edges converge
on a dark interconnect core deep in the frame.

Light pulses flow along the strands toward the core. Pulse phase is (distance to core / wavelength + time * integer),
so after --frames frames it matches the start exactly (seamless loop). Camera is fixed.
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


args = lib.parse_args("concept_ix_hub", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_y = 540                     # 32:9
if args.engine == "cycles":
    scene.cycles.samples = args.spp or (24 if args.preview else 96)
    scene.cycles.seed = args.seed                 # fixed seed (same noise pattern every frame -> no loop seam)
    scene.cycles.use_animated_seed = False
    scene.render.use_persistent_data = True
    try:
        scene.cycles.denoising_use_gpu = True
    except AttributeError:
        pass
    scene.cycles.adaptive_threshold = 0.02
    scene.cycles.max_bounces = 4
scene.view_settings.view_transform = "AgX"
for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
    try:
        scene.view_settings.look = look
        break
    except TypeError:
        continue
lib.set_world(color=(0.004, 0.006, 0.012, 1.0), strength=1.0)

N = args.frames
rng = random.Random(11)
CORE = (0.0, 62.0, 0.35)
LAMBDA = 34.0          # pulse spacing (m)
CYCLES_PER_LOOP = 1    # pulse moves exactly LAMBDA per loop -> integer multiple, no seam


# ------------------------------------------------------------------ Loop time (0..1, linear)
def make_loop_time():
    """Shared material time value: frame 1 -> 0, frame N+1 -> 1 (linear). N+1 == 1, so the loop closes."""
    holder = bpy.data.node_groups.new("LoopTime", "ShaderNodeTree")
    holder.interface.new_socket("t", in_out="OUTPUT", socket_type="NodeSocketFloat")
    out = holder.nodes.new("NodeGroupOutput")
    val = holder.nodes.new("ShaderNodeValue")
    holder.links.new(val.outputs[0], out.inputs[0])
    # linear time via driver (keyframes get eased in Blender 5.2). frame N+1 -> 1.0 == frame 1 (fract)
    fc = val.outputs[0].driver_add("default_value")
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = f"(frame-1)/{N}"
    return holder


LOOP = make_loop_time()


def math_node(nt, op, a=None, b=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def strand_material(name, base_col, pulse_col, base_e, pulse_e, sharp):
    """Thin fibre strand: bright at the edges (large |x|), darker toward the core, plus flowing pulses."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    out = nt.nodes["Material Output"]
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    info = nt.nodes.new("ShaderNodeObjectInfo")
    t = nt.nodes.new("ShaderNodeGroup")
    t.node_tree = LOOP

    # distance to core
    core = nt.nodes.new("ShaderNodeCombineXYZ")
    for i, v in enumerate(CORE):
        core.inputs[i].default_value = v
    vd = nt.nodes.new("ShaderNodeVectorMath")
    vd.operation = "DISTANCE"
    nt.links.new(geo.outputs["Position"], vd.inputs[0])
    nt.links.new(core.outputs[0], vd.inputs[1])
    dist = vd.outputs["Value"]

    # horizontal screen-position weight: |x|/y (tan angle from camera). Nearly off at <= 0.13 (centre ~30% of frame), max at >= 0.5
    ax = math_node(nt, "ABSOLUTE", sep.outputs["X"])
    ratio = math_node(nt, "DIVIDE", ax, math_node(nt, "MAXIMUM", sep.outputs["Y"], 0.5))
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.interpolation_type = "SMOOTHERSTEP"
    mr.inputs["From Min"].default_value = 0.10
    mr.inputs["From Max"].default_value = 0.55
    nt.links.new(ratio, mr.inputs["Value"])
    edge = mr.outputs["Result"]

    # pulse: fract(d/L + t*k + rand) ^ sharp  (head toward the core, tail outward)
    ph = math_node(nt, "DIVIDE", dist, LAMBDA)
    ph = math_node(nt, "ADD", ph, math_node(nt, "MULTIPLY", t.outputs[0], float(CYCLES_PER_LOOP)))
    ph = math_node(nt, "ADD", ph, math_node(nt, "MULTIPLY", info.outputs["Random"], 7.0))
    fr = math_node(nt, "FRACT", ph)
    pulse = math_node(nt, "POWER", fr, sharp)
    # Pulses are visible only toward the edges and fade out toward the core (the centre headline area).
    # Nearly 0 at |x|/y <= 0.26 (centre ~32%), max at >= 0.56 -> lowers the peak luma in the centre.
    mp_ = nt.nodes.new("ShaderNodeMapRange")
    mp_.interpolation_type = "SMOOTHERSTEP"
    mp_.inputs["From Min"].default_value = 0.26
    mp_.inputs["From Max"].default_value = 0.56
    nt.links.new(ratio, mp_.inputs["Value"])
    pw = math_node(nt, "ADD", math_node(nt, "MULTIPLY", mp_.outputs["Result"], 0.995), 0.005)
    pulse = math_node(nt, "MULTIPLY", pulse, pw)

    e_base = nt.nodes.new("ShaderNodeEmission")
    e_base.inputs["Color"].default_value = base_col
    nt.links.new(math_node(nt, "MULTIPLY", math_node(nt, "ADD", math_node(nt, "MULTIPLY", edge, 0.96), 0.04), base_e),
                 e_base.inputs["Strength"])
    e_pulse = nt.nodes.new("ShaderNodeEmission")
    e_pulse.inputs["Color"].default_value = pulse_col
    nt.links.new(math_node(nt, "MULTIPLY", pulse, pulse_e), e_pulse.inputs["Strength"])
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(e_base.outputs[0], add.inputs[0])
    nt.links.new(e_pulse.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], out.inputs["Surface"])
    return mat


CYAN = (0.25, 0.75, 1.0, 1.0)
DEEP = (0.10, 0.35, 1.0, 1.0)
WARM = (1.0, 0.55, 0.18, 1.0)
# Pulse head: shorter (sharp 60->80 etc.), less white (about half the intensity, deeper colour) -> does not blow out to white
mat_cool = strand_material("Strand Cool", CYAN, (0.30, 0.72, 1.0, 1.0), 1.0, 16.0, 80.0)
mat_deep = strand_material("Strand Deep", DEEP, (0.22, 0.55, 1.0, 1.0), 0.6, 13.0, 65.0)
mat_warm = strand_material("Strand Warm", DEEP, WARM, 0.65, 30.0, 90.0)
mat_fg = strand_material("Strand FG", DEEP, (0.30, 0.68, 1.0, 1.0), 0.3, 0.35, 10.0)   # thick foreground (out-of-focus) strands: long, very weak pulses (a large blurred area flashing causes brightness pumping)


# ------------------------------------------------------------------ Fibre strands
def strand(name, pts, radius, mat):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 2
    cu.use_fill_caps = True
    sp = cu.splines.new("NURBS")
    sp.points.add(len(pts) - 1)
    for p, c in zip(sp.points, pts):
        p.co = (c[0], c[1], c[2], 1.0)
    sp.use_endpoint_u = True
    sp.order_u = 4
    sp.resolution_u = 6
    ob = bpy.data.objects.new(name, cu)
    bpy.context.collection.objects.link(ob)
    cu.materials.append(mat)
    return ob


def path(x0, y0, z0, bundle_z, steps=34):
    """Starts at an edge (x0,y0,z0): first runs along the side wall in depth, then curves into the core."""
    pts = []
    for i in range(steps + 1):
        s = i / steps
        # progress in depth is fast, lateral convergence is late (stays to the side, then wraps inward)
        y = y0 + (CORE[1] - y0) * (1 - (1 - s) ** 1.35)
        k = s ** 2.1
        x = x0 * (1 - k)
        z = z0 + (bundle_z - z0) * min(1.0, s * 1.6) * (1 - k) + (CORE[2] - bundle_z) * k
        pts.append((x, y, z))
    return pts


count = 0
for side in (-1, 1):
    # Strands arrive in several bundles: each bundle has similar height/depth
    for b in range(6):
        bz = rng.uniform(-1.3, 1.6)
        by = rng.uniform(2.5, 14.0)
        bx = rng.uniform(5.5, 11.0)
        for _ in range(rng.randint(6, 10)):
            x0 = side * (bx + rng.uniform(-0.6, 0.6))
            y0 = by + rng.uniform(-1.2, 1.2)
            z0 = bz + rng.uniform(-0.9, 0.9)
            r = rng.choice((0.0045, 0.006, 0.006, 0.008, 0.011))
            roll = rng.random()
            mat = mat_warm if roll < 0.11 else (mat_deep if roll < 0.45 else mat_cool)
            strand(f"Strand {count}", path(x0, y0, z0, bz + rng.uniform(-0.25, 0.25)), r, mat)
            count += 1
# A few thick foreground strands: pass right beside the camera (0.6-1.2 m) and blur far out of focus -> breaks the 'warp' feel.
rng_fg = random.Random(4)
for k, (side, x0, y0, z0) in enumerate([(-1, 0.62, 0.25, 0.20), (1, 0.70, 0.30, -0.17), (1, 1.05, 0.40, 0.26)]):
    strand(f"Strand FG {k}", path(side * x0, y0, z0, z0 * 4.0 + rng_fg.uniform(-0.2, 0.2)), 0.0055, mat_fg)
    count += 1
print(f"[ix_hub] strands: {count}")

# ------------------------------------------------------------------ Core (small, distant, dark)
core_dim = lib.make_pbr("Core Shell", (0.01, 0.012, 0.016, 1), metallic=0.8, roughness=0.35)
core_glow = lib.make_pbr("Core Ring", (0.02, 0.04, 0.06, 1), roughness=0.4, emission=(0.3, 0.7, 1.0, 0.35))
cx, cy, cz = CORE
lib.cyl("Core Body", 1.1, 2.6, (cx, cy + 1.6, cz), core_dim, rot=(math.radians(90), 0, 0), bevel=0.02)
# Core front face: small port dots faintly lit in a grid, like an interconnect fabric
port_mat = lib.make_pbr("Core Port", (0.02, 0.04, 0.06, 1), roughness=0.4, emission=(0.35, 0.75, 1.0, 0.7))
port_warm = lib.make_pbr("Core Port Warm", (0.06, 0.03, 0.01, 1), roughness=0.4, emission=(1.0, 0.55, 0.2, 0.5))
for ix in range(-9, 10):
    for iz in range(-3, 4):
        if ix * ix / 90.0 + iz * iz / 12.0 > 1.0 or rng.random() < 0.35:
            continue
        m = port_warm if rng.random() < 0.06 else port_mat
        lib.box(f"Port {ix} {iz}", (0.035, 0.02, 0.022), (cx + ix * 0.1, cy + 0.25, cz + iz * 0.1), m, bevel=0.0)

# Subtle halo behind the core (only adds depth, not a bright blob)
halo = bpy.data.materials.new("Halo")
halo.use_nodes = True
hn = halo.node_tree
hn.nodes.remove(hn.nodes["Principled BSDF"])
tc = hn.nodes.new("ShaderNodeTexCoord")
grad = hn.nodes.new("ShaderNodeTexGradient")
grad.gradient_type = "SPHERICAL"
mp = hn.nodes.new("ShaderNodeMapping")
mp.inputs["Scale"].default_value = (0.09, 0.09, 0.09)
hn.links.new(tc.outputs["Object"], mp.inputs["Vector"])
hn.links.new(mp.outputs["Vector"], grad.inputs["Vector"])
pw_ = hn.nodes.new("ShaderNodeMath")
pw_.operation = "POWER"
pw_.inputs[1].default_value = 2.5
hn.links.new(grad.outputs["Fac"], pw_.inputs[0])
em = hn.nodes.new("ShaderNodeEmission")
em.inputs["Color"].default_value = (0.12, 0.35, 0.9, 1.0)
mul = hn.nodes.new("ShaderNodeMath")
mul.operation = "MULTIPLY"
mul.inputs[1].default_value = 0.14
hn.links.new(pw_.outputs[0], mul.inputs[0])
hn.links.new(mul.outputs[0], em.inputs["Strength"])
tr = hn.nodes.new("ShaderNodeBsdfTransparent")
addh = hn.nodes.new("ShaderNodeAddShader")
hn.links.new(em.outputs[0], addh.inputs[0])
hn.links.new(tr.outputs[0], addh.inputs[1])
hn.links.new(addh.outputs[0], hn.nodes["Material Output"].inputs["Surface"])
bpy.ops.mesh.primitive_plane_add(size=24, location=(cx, cy + 3.5, cz), rotation=(math.radians(90), 0, 0))
lib.assign(bpy.context.active_object, halo, smooth=False)

# Floor: very dark reflective surface (strands reflect faintly)
floor = lib.make_pbr("Floor", (0.006, 0.007, 0.009, 1), metallic=0.3, roughness=0.32, bump=0.002, bump_scale=60.0)
lib.box("Floor", (60, 120, 0.1), (0, 55, -1.75), floor, bevel=0.0)

# ------------------------------------------------------------------ Camera (fixed)
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 22
cam_data.sensor_fit = "HORIZONTAL"
cam_data.clip_end = 300
cam = bpy.data.objects.new("Camera", cam_data)
bpy.context.collection.objects.link(cam)
cam.location = (0, 0, 0.05)
cam.rotation_euler = (math.radians(90.6), 0, 0)
scene.camera = cam
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = 9.0
cam_data.dof.aperture_fstop = 2.8


# ------------------------------------------------------------------ Compositor: subtle glow (Blender 5.x node-group approach)
def add_bloom(strength=0.4, threshold=0.6, size=0.8):
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
        print(f"[ix_hub] bloom skipped: {e}")


add_bloom()

if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # chunked: encode separately after all chunks are collected
else:
    lib.render(args)
