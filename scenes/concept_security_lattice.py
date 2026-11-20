"""Concept 07 security lattice: looking up from slightly below and to the side at the inside of
a huge glass hexagonal-lattice shield (a sphere) wrapped around the camera.
Frame edges have a thin cyan rim and the glass panes refract. Scan light bands sweep across the shield from left to right.
The centre (straight ahead) is masked to stay dark and calm.

Loop: scan band phase t goes 0 at frame 1 → 1 at frame N+1 (wrapped with fract, so period =
clip length). The lattice is static (periodic structure).
Usage: node bin/blender.mjs concept_security_lattice --still 1 --engine cycles --out out/concepts/07_security_lattice
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import bmesh  # noqa: E402

import lib  # noqa: E402



def _extra(p):
    p.add_argument("--start", type=int, default=None, help="animation start frame (chunked render)")
    p.add_argument("--end", type=int, default=None, help="animation end frame (chunked render)")
    p.add_argument("--spp", type=int, default=None)
    p.add_argument("--size", default="1920x540", help="e.g. 960x270 (draft), 3840x1080")
    p.add_argument("--draft", action="store_true", help="fast draft: low samples/bounces + adaptive sampling + GPU denoise")


args = lib.parse_args("concept_security_lattice", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x, scene.render.resolution_y = (int(v) for v in args.size.split("x"))
if args.engine == "cycles":
    scene.cycles.samples = args.spp or (48 if args.preview else 128)
    scene.cycles.seed = 0
    scene.cycles.use_animated_seed = False        # loop: fixed noise pattern
    scene.render.use_persistent_data = True
    scene.cycles.max_bounces = 10
    scene.cycles.transmission_bounces = 10
    scene.cycles.glossy_bounces = 4
    scene.cycles.diffuse_bounces = 2
    scene.cycles.sample_clamp_indirect = 3.0
    if args.draft:
        scene.cycles.samples = args.spp or 32
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = 0.03
        scene.cycles.max_bounces = 4
        scene.cycles.transmission_bounces = 4
        scene.cycles.glossy_bounces = 3
        scene.cycles.diffuse_bounces = 2
        scene.cycles.sample_clamp_indirect = 3.0      # 10 blows out the refracted backlight to white, so keep the original value
        try:
            scene.cycles.denoising_use_gpu = True
        except AttributeError:
            pass
scene.view_settings.view_transform = "AgX"
for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
    try:
        scene.view_settings.look = look
        break
    except TypeError:
        continue

N = args.frames
rng = random.Random(7)
R = 11.0                 # shield sphere radius
A = math.radians(2.4)    # hex cell circumradius (angle)
BANDS = 6                # number of scan bands (within the 3.8 rad span, ~36 deg apart): they alternate left and right so average brightness stays nearly constant
CAM_YAW = math.radians(7.0)     # camera yaw (+ is left)
CAM_PITCH = math.radians(5.0)
CAM_U = math.radians(-1.0)      # shield longitude at the frame centre (mask centre)

# ---------------------------------------------------------------- World: deep navy outside the shield + a subtle gradient
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
wnt = world.node_tree
bg = wnt.nodes["Background"]
grad_tc = wnt.nodes.new("ShaderNodeTexCoord")
sep = wnt.nodes.new("ShaderNodeSeparateXYZ")
ramp = wnt.nodes.new("ShaderNodeValToRGB")
wnt.links.new(grad_tc.outputs["Generated"], sep.inputs[0])
wnt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
ramp.color_ramp.elements[0].position = 0.35
ramp.color_ramp.elements[0].color = (0.002, 0.003, 0.006, 1)
ramp.color_ramp.elements[1].position = 0.75
ramp.color_ramp.elements[1].color = (0.010, 0.022, 0.045, 1)
wnt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 1.0


# ---------------------------------------------------------------- Spherical hex lattice mesh (convex shield, camera-side hemisphere only)
SC = (0.0, 19.0, 0.0)   # shield sphere centre


def sph(u, v, r):
    """Direction relative to the shield centre: u=0 faces the camera (-y), u is longitude, v is latitude"""
    return (r * math.sin(u) * math.cos(v), -r * math.cos(u) * math.cos(v), r * math.sin(v))


def ring(uc, vc, k, r):
    pts = []
    for i in range(6):
        ang = math.radians(60 * i + 30)
        u = uc + k * A * math.cos(ang) / max(math.cos(vc), 0.3)
        v = vc + k * A * math.sin(ang)
        pts.append(sph(u, v, r))
    return pts


frame_bm = bmesh.new()
pane_bm = bmesh.new()
DEPTH = 0.07
K_OUT, K_IN = 0.99, 0.93

dx = math.sqrt(3) * A
dy = 1.5 * A
cells = 0
for row in range(-int(math.radians(30) / dy), int(math.radians(30) / dy) + 1):
    vc = row * dy
    for col in range(-60, 61):
        uc = (col + (0.5 if row % 2 else 0.0)) * dx / max(math.cos(vc), 0.3)
        if abs(uc) > math.radians(98):
            continue
        # Frame: outer ring/inner ring, outer face (R, camera side)/inner face (R-DEPTH)
        of = ring(uc, vc, K_OUT, R)
        ob = ring(uc, vc, K_OUT, R - DEPTH)
        inf = ring(uc, vc, K_IN, R)
        inb = ring(uc, vc, K_IN, R - DEPTH)
        vof = [frame_bm.verts.new(p) for p in of]
        vob = [frame_bm.verts.new(p) for p in ob]
        vif = [frame_bm.verts.new(p) for p in inf]
        vib = [frame_bm.verts.new(p) for p in inb]
        for i in range(6):
            j = (i + 1) % 6
            frame_bm.faces.new((vof[i], vof[j], vif[j], vif[i]))
            frame_bm.faces.new((vob[j], vob[i], vib[i], vib[j]))
            frame_bm.faces.new((vof[j], vof[i], vob[i], vob[j]))
            frame_bm.faces.new((vif[i], vif[j], vib[j], vib[i]))
        # Glass pane: closed hexagonal slab with thickness (slightly recessed inside the frame)
        pf = ring(uc, vc, K_IN + 0.02, R - 0.015)
        pb = ring(uc, vc, K_IN + 0.02, R - 0.05)
        vpf = [pane_bm.verts.new(p) for p in pf]
        vpb = [pane_bm.verts.new(p) for p in pb]
        pane_bm.faces.new(vpf)
        pane_bm.faces.new(list(reversed(vpb)))
        for i in range(6):
            j = (i + 1) % 6
            pane_bm.faces.new((vpf[j], vpf[i], vpb[i], vpb[j]))
        cells += 1
print(f"[lattice] cells={cells}")


def bm_object(bm, name):
    me = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = SC
    scene.collection.objects.link(obj)
    return obj


frame_obj = bm_object(frame_bm, "lattice_frame")
pane_obj = bm_object(pane_bm, "lattice_pane")
bev = frame_obj.modifiers.new("Bevel", "BEVEL")
bev.width = 0.006
bev.segments = 2
bev.limit_method = "ANGLE"


# ---------------------------------------------------------------- Scan band node group (based on world-space longitude)
def scan_group():
    g = bpy.data.node_groups.new("ScanBand", "ShaderNodeTree")
    g.interface.new_socket("Band", in_out="OUTPUT", socket_type="NodeSocketFloat")
    g.interface.new_socket("Side", in_out="OUTPUT", socket_type="NodeSocketFloat")
    n, L = g.nodes, g.links
    out = n.new("NodeGroupOutput")
    tc = n.new("ShaderNodeTexCoord")
    sp = n.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Object"], sp.inputs[0])
    u = n.new("ShaderNodeMath"); u.operation = "ARCTAN2"          # longitude u = atan2(x, -y)
    neg_y = n.new("ShaderNodeMath"); neg_y.operation = "MULTIPLY"; neg_y.inputs[1].default_value = -1.0
    L.new(sp.outputs["Y"], neg_y.inputs[0])
    L.new(sp.outputs["X"], u.inputs[0]); L.new(neg_y.outputs[0], u.inputs[1])

    def m(op, a, b=None, clamp=False):
        node = n.new("ShaderNodeMath"); node.operation = op; node.use_clamp = clamp
        for idx, val in enumerate((a, b)):
            if val is None:
                continue
            if isinstance(val, (int, float)):
                node.inputs[idx].default_value = val
            else:
                L.new(val, node.inputs[idx])
        return node.outputs[0]

    U = 1.9                                                         # wrap span (rad): out past the frame
    w = m("DIVIDE", m("ADD", u.outputs[0], U), 2 * U)                # 0..1
    t = n.new("ShaderNodeValue"); t.name = "scan_t"; t.label = "scan_t"
    # BANDS bands sit evenly spaced within the span 2U and move right by one spacing per loop -> frame N+1 = frame 1
    s = m("FRACT", m("ADD", m("SUBTRACT", m("MULTIPLY", w, BANDS), t.outputs[0]), 0.5 - 0.385 * BANDS))
    d = m("SUBTRACT", s, 0.5)
    core = m("EXPONENT", m("MULTIPLY", m("POWER", m("DIVIDE", d, 0.012 * BANDS), 2.0), -1.0))
    halo = m("EXPONENT", m("MULTIPLY", m("POWER", m("DIVIDE", m("ADD", d, 0.025 * BANDS), 0.05 * BANDS), 2.0), -1.0))
    band = m("ADD", core, m("MULTIPLY", halo, 0.35))
    # Centre (straight ahead of camera) mask: 1 the farther from straight ahead
    du = m("ABSOLUTE", m("SUBTRACT", u.outputs[0], CAM_U))
    side = m("MULTIPLY", m("SUBTRACT", du, 0.10), 1 / 0.45, clamp=True)
    bmask = m("POWER", side, 2.0)                                   # bands switch off completely in the centre (headline area)
    side = m("ADD", m("MULTIPLY", m("POWER", side, 1.5), 0.95), 0.05)
    L.new(m("MULTIPLY", band, bmask), out.inputs["Band"])
    L.new(side, out.inputs["Side"])
    return g, t


SCAN, scan_t = scan_group()
# Loop: 0 → 1 from frame 1 → N+1, linear (frame N+1 = frame 1). Blender 5.2 eases keyframes, so supply it via a driver
_fc = scan_t.outputs[0].driver_add("default_value")
_fc.driver.type = "SCRIPTED"
_fc.driver.expression = f"(frame-1)/{N}"

CYAN = (0.35, 0.78, 1.0, 1.0)
WARM = (1.0, 0.62, 0.32, 1.0)


def frame_material():
    mat = bpy.data.materials.new("lattice_frame")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    lib.set_input(bsdf, "Base Color", (0.03, 0.04, 0.05, 1))
    lib.set_input(bsdf, "Metallic", 0.9)
    lib.set_input(bsdf, "Roughness", 0.22)
    grp = nt.nodes.new("ShaderNodeGroup"); grp.node_tree = SCAN
    lib.set_input(bsdf, "Emission Color", CYAN)
    # base rim 0.35*side + scan band
    base = nt.nodes.new("ShaderNodeMath"); base.operation = "MULTIPLY"; base.inputs[1].default_value = 0.08
    nt.links.new(grp.outputs["Side"], base.inputs[0])
    band = nt.nodes.new("ShaderNodeMath"); band.operation = "MULTIPLY"; band.inputs[1].default_value = 5.0
    nt.links.new(grp.outputs["Band"], band.inputs[0])
    tot = nt.nodes.new("ShaderNodeMath"); tot.operation = "ADD"
    nt.links.new(base.outputs[0], tot.inputs[0]); nt.links.new(band.outputs[0], tot.inputs[1])
    nt.links.new(tot.outputs[0], bsdf.inputs["Emission Strength"])
    return mat


def pane_material():
    mat = bpy.data.materials.new("lattice_pane")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    lib.set_input(bsdf, "Base Color", (0.86, 0.95, 1.0, 1))
    lib.set_input(bsdf, "Transmission Weight", 1.0)
    lib.set_input(bsdf, "IOR", 1.5)
    lib.set_input(bsdf, "Roughness", 0.06)
    lib.set_input(bsdf, "Coat Weight", 0.0)
    # Slightly different roughness per cell (a few frosted panes): position-based Voronoi cell random
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.inputs["Scale"].default_value = 1.6
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(tc.outputs["Object"], vor.inputs["Vector"])
    rr = nt.nodes.new("ShaderNodeMapRange")
    rr.inputs["From Min"].default_value = 0.0
    rr.inputs["From Max"].default_value = 1.0
    rr.inputs["To Min"].default_value = 0.02
    rr.inputs["To Max"].default_value = 0.12
    nt.links.new(vor.outputs["Color"], rr.inputs["Value"])
    nt.links.new(rr.outputs["Result"], bsdf.inputs["Roughness"])
    grp = nt.nodes.new("ShaderNodeGroup"); grp.node_tree = SCAN
    lib.set_input(bsdf, "Emission Color", (0.25, 0.65, 1.0, 1))
    band = nt.nodes.new("ShaderNodeMath"); band.operation = "MULTIPLY"; band.inputs[1].default_value = 0.35
    nt.links.new(grp.outputs["Band"], band.inputs[0])
    nt.links.new(band.outputs[0], bsdf.inputs["Emission Strength"])
    return mat


lib.assign(frame_obj, frame_material(), smooth=False)
lib.assign(pane_obj, pane_material(), smooth=False)

# ---------------------------------------------------------------- Lighting: large softbox above (glass reflection), backlight behind the shield (edge refraction), warm accent point
def light_at(name, loc, target, energy, size, color):
    tgt = bpy.data.objects.new(name + "_t", None)
    tgt.location = target
    scene.collection.objects.link(tgt)
    return lib.add_area_light(name, loc, tgt, energy, size=size, color=color)


def strip(light, w, h):
    light.data.shape = "RECTANGLE"
    light.data.size = w
    light.data.size_y = h
    return light


strip(light_at("soft_top", (-2.0, 4.0, 13.0), (0, 16, 0), 260, 16, (0.55, 0.75, 1.0)), 24, 2)
light_at("back_l", (-16.0, 32.0, 3.0), (-6, 19, 0), 14000, 6, (0.30, 0.65, 1.0))
light_at("back_r", (17.0, 31.0, -2.0), (6, 19, 0), 14000, 6, (0.35, 0.70, 1.0))
strip(light_at("warm_r", (13.0, 7.0, -3.0), (6, 17, 0), 700, 12, (1.0, 0.55, 0.25)), 2, 10)
# ---------------------------------------------------------------- Camera (looking up slightly from below)
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 24
cam_data.sensor_width = 36
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
cam.location = (0.6, 0.0, -1.3)
cam.rotation_euler = (math.radians(90) + CAM_PITCH, 0.0, CAM_YAW)

# ---------------------------------------------------------------- Compositor: soft bloom
def add_bloom(strength=0.6, threshold=0.7, size=0.6):
    ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ng.nodes.new("CompositorNodeRLayers")
    gl = ng.nodes.new("CompositorNodeGlare")
    gl.inputs["Type"].default_value = "Bloom"
    gl.inputs["Quality"].default_value = "High"
    gl.inputs["Threshold"].default_value = threshold
    gl.inputs["Strength"].default_value = strength
    gl.inputs["Size"].default_value = size
    out = ng.nodes.new("NodeGroupOutput")
    ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
    ng.links.new(gl.outputs["Image"], out.inputs[0])
    scene.compositing_node_group = ng


try:
    add_bloom()
except Exception as e:  # noqa: BLE001
    print(f"[lattice] bloom skipped: {e}")

if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # chunked: encode separately after all chunks are collected
else:
    scene.frame_set(args.still if args.still is not None else 1)
    lib.render(args)
