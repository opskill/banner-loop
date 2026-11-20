"""Concept 09: server rack front close-up (cold aisle).

In a narrow cold aisle, hugging the left rack row (grazing angle), looking toward the end of the aisle.
Status LEDs on near racks are crisp dots, far racks blur into bokeh, and the frame centre falls into dark out-of-focus depth.
Loop (5 s): the camera moves parallel to the rack row by exactly one rack (PITCH). All racks share the same mesh,
and the LED blink phase is offset by i*T (mod period) for rack index i, so the last frame = the first frame.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import bmesh  # noqa: E402
import mathutils  # noqa: E402

import lib  # noqa: E402



def _extra(p):
    p.add_argument("--start", type=int, default=None, help="animation start frame (chunked render)")
    p.add_argument("--end", type=int, default=None, help="animation end frame (chunked render)")
    p.add_argument("--spp", type=int, default=None)
    p.add_argument("--draft", action="store_true", help="fast draft: 960x270, <=32spp + adaptive sampling + GPU denoise")


args = lib.parse_args("concept_rack_closeup", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x, scene.render.resolution_y = 1920, 540
if args.engine == "cycles":
    scene.cycles.samples = args.spp or (48 if args.preview else 128)
    scene.cycles.seed = 0                      # fixed seed (same noise pattern at the loop seam too)
    scene.cycles.use_animated_seed = False
    scene.render.use_persistent_data = True    # only camera and shader values change, so reuse the BVH
    scene.cycles.transparent_max_bounces = 16
    scene.cycles.max_bounces = 8
    if args.draft:
        scene.render.resolution_x, scene.render.resolution_y = 960, 270
        scene.cycles.samples = args.spp or 32
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = 0.03
        scene.cycles.max_bounces = 4
        scene.cycles.use_denoising = True
        try:
            scene.cycles.denoising_use_gpu = True
        except Exception:  # noqa: BLE001
            pass
        scene.render.use_persistent_data = True
scene.view_settings.view_transform = "AgX"
for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
    try:
        scene.view_settings.look = look
        break
    except TypeError:
        continue
lib.set_world(color=(0.004, 0.006, 0.012, 1.0), strength=1.0)

world_nt = scene.world.node_tree
haze = world_nt.nodes.new("ShaderNodeVolumeScatter")
haze.inputs["Density"].default_value = 0.0004
haze.inputs["Color"].default_value = (0.7, 0.85, 1.0, 1.0)
# Fog is not connected: the ceiling light strips made a V-shaped light shaft above the frame
# centre that intruded on the headline area, and it also slows the render.
# world_nt.links.new(haze.outputs["Volume"], world_nt.nodes["World Output"].inputs["Volume"])

N = args.frames
FPS = args.fps
T = N / FPS                       # loop length (s)
rng = random.Random(9)

PITCH = 0.6                       # rack width = loop travel distance
RACK_H, RACK_D = 2.1, 1.07
AISLE = 1.2                       # cold aisle width (between rack fronts)
NRACK = 65
Y_START = -6.0                    # 10 racks behind the camera: so the effect of the rear row's end on lighting does not change during the loop

# ------------------------------------------------------------------ Materials
M = lib.make_pbr
frame_mat = M("Rack Frame", (0.012, 0.013, 0.016, 1), metallic=0.7, roughness=0.42, bump=0.01, bump_scale=600.0)
bezel_mat = M("Server Bezel", (0.05, 0.053, 0.06, 1), metallic=0.8, roughness=0.35, bump=0.02, bump_scale=900.0)
bezel2_mat = M("Server Bezel Dark", (0.022, 0.023, 0.027, 1), metallic=0.6, roughness=0.5)
bay_mat = M("Drive Bay", (0.11, 0.115, 0.125, 1), metallic=0.85, roughness=0.28)
vent_mat = M("Vent", (0.005, 0.005, 0.006, 1), roughness=0.8)
floor_mat = lib.make_tiled_pbr("Floor", "grey_tiles", tile=0.6, tint=(0.035, 0.042, 0.055, 1), rough_scale=0.25)
ceil_mat = M("Containment Roof", (0.02, 0.022, 0.026, 1), metallic=0.5, roughness=0.6)
strip_mat = M("Ceiling Strip", (0.6, 0.7, 0.8, 1), roughness=0.5, emission=(0.62, 0.8, 1.0, 6.0))


def frame_time_node(nt):
    """Value node that outputs #frame/fps (simple-expression driver, so it works without Python auto-exec)."""
    v = nt.nodes.new("ShaderNodeValue")
    fc = v.outputs[0].driver_add("default_value")
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = f"frame/{FPS}"
    return v


def make_led(name, color, strength, period):
    """Blinking LED material. Phase = rack-local coordinate hash + rack index*T. Period is `period` (s)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    out = nodes["Material Output"]
    nodes.remove(nodes["Principled BSDF"])
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = color + (1.0,)
    links.new(emit.outputs[0], out.inputs["Surface"])

    tc = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexWhiteNoise")      # fixed random number per LED (object coordinates)
    noise.noise_dimensions = "3D"
    vm = nodes.new("ShaderNodeVectorMath")
    vm.operation = "SCALE"
    vm.inputs["Scale"].default_value = 37.0
    links.new(tc.outputs["Object"], vm.inputs[0])
    links.new(vm.outputs[0], noise.inputs["Vector"])

    info = nodes.new("ShaderNodeObjectInfo")           # rack index i = object y / PITCH
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(info.outputs["Location"], sep.inputs[0])

    def m(op, a, b=None):
        n = nodes.new("ShaderNodeMath")
        n.operation = op
        for k, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[k].default_value = x
            else:
                links.new(x, n.inputs[k])
        return n.outputs[0]

    t = frame_time_node(nt).outputs[0]
    idx = m("DIVIDE", sep.outputs["Y"], PITCH)
    phase = m("ADD", m("MULTIPLY", noise.outputs["Value"], period), m("MULTIPLY", idx, T))
    cyc = m("FRACT", m("DIVIDE", m("ADD", t, phase), period))
    duty = m("ADD", 0.55, m("MULTIPLY", noise.outputs["Value"], 0.4))
    on = m("LESS_THAN", cyc, duty)
    level = m("ADD", 0.25, m("MULTIPLY", on, 0.75))
    links.new(m("MULTIPLY", level, strength), emit.inputs["Strength"])
    return mat


led_g = make_led("LED Green", (0.25, 1.0, 0.45), 14.0, 0.5)
led_b = make_led("LED Blue", (0.2, 0.55, 1.0), 16.0, 1.25)
led_a = make_led("LED Amber", (1.0, 0.5, 0.08), 12.0, 2.5)
led_w = make_led("LED White", (0.75, 0.85, 1.0), 9.0, 0.25)


def make_mesh_door():
    """Perforated mesh door: black metal plate with round holes at 6 mm pitch punched out as transparent."""
    mat = bpy.data.materials.new("Mesh Door")
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes["Principled BSDF"]
    lib.set_input(bsdf, "Base Color", (0.015, 0.016, 0.019, 1))
    lib.set_input(bsdf, "Metallic", 0.75)
    lib.set_input(bsdf, "Roughness", 0.38)
    out = nodes["Material Output"]
    transp = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    tc = nodes.new("ShaderNodeTexCoord")
    mp = nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / 0.006,) * 3
    links.new(tc.outputs["Object"], mp.inputs["Vector"])
    vor = nodes.new("ShaderNodeTexVoronoi")      # randomness 0 gives regular grid cells
    vor.voronoi_dimensions = "2D"
    vor.inputs["Randomness"].default_value = 0.0
    vor.inputs["Scale"].default_value = 1.0
    sep = nodes.new("ShaderNodeSeparateXYZ")
    comb = nodes.new("ShaderNodeCombineXYZ")
    links.new(mp.outputs["Vector"], sep.inputs[0])
    links.new(sep.outputs["Y"], comb.inputs["X"])
    links.new(sep.outputs["Z"], comb.inputs["Y"])
    links.new(comb.outputs[0], vor.inputs["Vector"])
    hole = nodes.new("ShaderNodeMath")
    hole.operation = "LESS_THAN"
    hole.inputs[1].default_value = 0.36
    links.new(vor.outputs["Distance"], hole.inputs[0])
    links.new(hole.outputs[0], mix.inputs["Fac"])
    links.new(bsdf.outputs[0], mix.inputs[1])
    links.new(transp.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


door_mat = make_mesh_door()

MATS = [frame_mat, bezel_mat, bezel2_mat, bay_mat, vent_mat, door_mat, led_g, led_b, led_a, led_w]
MI = {m.name: i for i, m in enumerate(MATS)}


def add_box(bm, center, size, mat):
    verts = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    bmesh.ops.scale(bm, vec=mathutils.Vector(size), verts=verts)
    bmesh.ops.translate(bm, vec=mathutils.Vector(center), verts=verts)
    for f in {f for v in verts for f in v.link_faces}:
        f.material_index = MI[mat.name]


def build_rack_mesh():
    """One rack (local: width y, depth x, front = +x, front plate at x=0, floor z=0)."""
    bm = bmesh.new()
    W = PITCH
    # Frame: left/right posts, top/bottom rails, side panels (boundary with neighbouring racks)
    for sy in (-1, 1):
        add_box(bm, (-0.01, sy * (W / 2 - 0.022), RACK_H / 2), (0.05, 0.04, RACK_H), frame_mat)
        add_box(bm, (-RACK_D / 2, sy * (W / 2 - 0.003), RACK_H / 2), (RACK_D, 0.006, RACK_H), frame_mat)
    add_box(bm, (-0.01, 0, RACK_H - 0.05), (0.05, W, 0.1), frame_mat)
    add_box(bm, (-0.01, 0, 0.04), (0.05, W, 0.08), frame_mat)
    add_box(bm, (-RACK_D / 2, 0, RACK_H + 0.01), (RACK_D, W, 0.02), frame_mat)
    # Servers: 1U/2U/4U, some blanks
    U = 0.0445
    z = 0.11
    inner = W - 0.1
    while z < RACK_H - 0.16:
        u = rng.choices([1, 2, 4, 1], weights=[5, 4, 1, 2])[0]
        h = u * U
        if z + h > RACK_H - 0.12:
            break
        kind = rng.choices(["server", "blank", "storage", "switch"], weights=[6, 2, 2, 2])[0]
        x0 = -0.055
        if kind == "blank":
            add_box(bm, (x0, 0, z + h / 2), (0.01, inner, h - 0.002), bezel2_mat)
        else:
            add_box(bm, (x0 - 0.01, 0, z + h / 2), (0.02, inner, h - 0.003), bezel_mat)
            if kind == "storage" or (kind == "server" and u >= 2):
                nb = 8 if u >= 2 else 6
                bw = (inner - 0.12) / nb
                for b in range(nb):
                    yb = -inner / 2 + 0.09 + (b + 0.5) * bw
                    add_box(bm, (x0 + 0.002, yb, z + h / 2), (0.006, bw - 0.004, h * 0.72), bay_mat)
                    if rng.random() < 0.7:
                        add_box(bm, (x0 + 0.006, yb + bw * 0.32, z + h * 0.22), (0.004, 0.003, 0.003),
                                rng.choice([led_g, led_g, led_b]))
            elif kind == "switch":
                for p in range(12):
                    yp = -inner / 2 + 0.1 + p * 0.03
                    add_box(bm, (x0 + 0.001, yp, z + h / 2), (0.004, 0.022, h * 0.5), vent_mat)
                    add_box(bm, (x0 + 0.004, yp, z + h * 0.85), (0.004, 0.003, 0.0025),
                            rng.choice([led_g, led_g, led_g, led_a, led_w]))
            else:
                add_box(bm, (x0 + 0.001, 0.04, z + h / 2), (0.004, inner * 0.55, h * 0.55), vent_mat)
            # power/status LEDs (left end)
            for k in range(rng.choice([1, 2, 2, 3])):
                add_box(bm, (x0 + 0.004, -inner / 2 + 0.025 + k * 0.012, z + h * 0.5), (0.005, 0.005, 0.005),
                        rng.choices([led_g, led_b, led_a, led_w], weights=[5, 3, 1, 1])[0])
        z += h
    # Mesh door (in front of the posts) + handle
    add_box(bm, (0.03, 0, RACK_H / 2 + 0.01), (0.002, W - 0.03, RACK_H - 0.12), door_mat)
    for sy in (-1, 1):
        add_box(bm, (0.032, sy * (W / 2 - 0.022), RACK_H / 2 + 0.01), (0.008, 0.02, RACK_H - 0.12), frame_mat)
    add_box(bm, (0.045, W / 2 - 0.05, 1.15), (0.02, 0.018, 0.22), bezel_mat)
    mesh = bpy.data.meshes.new("Rack")
    bm.to_mesh(mesh)
    bm.free()
    for mat in MATS:
        mesh.materials.append(mat)
    return mesh


rack_mesh = build_rack_mesh()
for i in range(NRACK):
    y = Y_START + i * PITCH
    for side in (-1, 1):   # -1: left row (front +x), +1: right row (front -x)
        o = bpy.data.objects.new(f"Rack {i}{'L' if side < 0 else 'R'}", rack_mesh)
        bpy.context.collection.objects.link(o)
        o.location = (side * AISLE / 2, y, 0)
        o.rotation_euler = (0, 0, 0 if side < 0 else math.pi)

LEN = NRACK * PITCH
CY = Y_START + LEN / 2 - PITCH / 2
lib.box("Floor", (6.0, LEN + 4, 0.1), (0, CY, -0.05), floor_mat, bevel=0.0)
# Cold aisle containment roof + light strips under the roof
lib.box("Roof", (AISLE + 2 * RACK_D, LEN + 4, 0.04), (0, CY, RACK_H + 0.32), ceil_mat, bevel=0.0)
for sx in (-0.38, 0.38):
    s = lib.box("Strip", (0.05, LEN, 0.02), (sx, CY, RACK_H + 0.29), strip_mat, bevel=0.0)
    s.visible_glossy = False
    s.visible_camera = False   # avoids a bright V above the centre (light comes from the area lights below)
# Lights that sweep the rack fronts at an angle: one per rack (same as the loop period), leaving the floor/aisle centre dark
for i in range(NRACK):
    y = Y_START + i * PITCH
    for side in (-1, 1):
        d = bpy.data.lights.new("Face Light", "AREA")
        d.shape, d.size, d.size_y = "RECTANGLE", 0.06, PITCH * 0.9
        d.energy = 70
        d.color = (0.6, 0.78, 1.0)
        lo = bpy.data.objects.new("Face Light", d)
        lo.location = (side * 0.3, y, RACK_H + 0.27)
        lo.rotation_euler = (0, -math.radians(40) * side, 0)   # looks down, then tilts toward its own rack front
        lo.visible_camera = False
        lo.visible_glossy = False
        bpy.context.collection.objects.link(lo)
# Aisle end: dark containment door
end_door = lib.box("End Door", (AISLE + 0.4, 0.05, RACK_H + 0.3), (0, Y_START + LEN, (RACK_H + 0.3) / 2), ceil_mat,
                   bevel=0.0)


def drive_y(obj, y0):
    """y = y0 + PITCH*(frame-1)/N. Exactly linear because it is a driver (Blender 5.2 keyframes ignore the LINEAR default and get eased)."""
    fc = obj.driver_add("location", 1)
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = f"{y0}+{PITCH}*(frame-1)/{N}"


drive_y(end_door, Y_START + LEN)   # the aisle-end door moves with the camera too, keeping the camera-door distance constant (frame 151 = frame 1)

# ------------------------------------------------------------------ Camera
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 26
cam_data.clip_start = 0.02
cam = bpy.data.objects.new("Camera", cam_data)
bpy.context.collection.objects.link(cam)
scene.camera = cam
CAM_X, CAM_Z = -AISLE / 2 + 0.3, 1.05
cam.rotation_euler = (math.radians(91), 0, 0)
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = 0.75
cam_data.dof.aperture_fstop = 1.8
cam_data.dof.aperture_blades = 0

Y0 = 0.0
cam.location = (CAM_X, Y0, CAM_Z)
drive_y(cam, Y0)                   # frame N+1 = same scene as frame 1 -> seamless loop

if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # chunked: encode separately after all chunks are collected
else:
    lib.render(args)
