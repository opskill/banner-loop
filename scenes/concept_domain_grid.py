"""Concept 08 domain grid: a lattice of small dot nodes on a dark plane stretching to the horizon
(the address space).
Some nodes light up on both sides, and thin light paths arc from node to node
(lookup path: resolver→root→TLD→authoritative server).
In the centre only the dots recede, calm and quiet.

Loop: the dot grid and path layout repeat in y with period TILE (an integer multiple of the grid
spacing S). The camera advances exactly TILE over the clip.
Path pulses are computed as fract(time(0→1, frames 1→N+1) * integer freq + phase) -> frame N+1 = frame 1.
Usage: node bin/blender.mjs concept_domain_grid --still 1 --engine cycles --out out/concepts/08_domain_grid
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
    p.add_argument("--draft", action="store_true", help="fast draft: 960x270, <=32spp + adaptive sampling + GPU denoise")


args = lib.parse_args("concept_domain_grid", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x = 1920
scene.render.resolution_y = 540
if args.engine == "cycles":
    scene.cycles.samples = args.spp or (48 if args.preview else 160)
    scene.cycles.seed = 0                      # fixed seed: same noise pattern every frame (also at the loop seam)
    scene.cycles.use_animated_seed = False
    scene.cycles.max_bounces = 4
    scene.cycles.glossy_bounces = 2
    scene.cycles.diffuse_bounces = 1
    scene.cycles.sample_clamp_indirect = 4.0
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

N = args.frames
S = 0.5                  # dot spacing (m) = grid period
TILE_CELLS = 16
TILE = S * TILE_CELLS    # layout repeat period = camera travel distance (8 m)
CENTER_HALF = 2.4        # |x| < this is the calm centre band (no lit nodes/paths)
CYAN = (0.30, 0.72, 1.0, 1.0)
WARM = (1.0, 0.60, 0.30, 1.0)
rng = random.Random(11)
HORIZON = (0.016, 0.034, 0.068, 1.0)

# ---------------------------------------------------------------- World: black + a pale navy band at the horizon
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
wnt = world.node_tree
bg = wnt.nodes["Background"]
wtc = wnt.nodes.new("ShaderNodeTexCoord")
wsep = wnt.nodes.new("ShaderNodeSeparateXYZ")
wnt.links.new(wtc.outputs["Generated"], wsep.inputs[0])
wabs = wnt.nodes.new("ShaderNodeMath"); wabs.operation = "ABSOLUTE"
wnt.links.new(wsep.outputs["Z"], wabs.inputs[0])
wmul = wnt.nodes.new("ShaderNodeMath"); wmul.operation = "MULTIPLY"; wmul.inputs[1].default_value = -9.0
wnt.links.new(wabs.outputs[0], wmul.inputs[0])
wexp = wnt.nodes.new("ShaderNodeMath"); wexp.operation = "EXPONENT"
wnt.links.new(wmul.outputs[0], wexp.inputs[0])
wramp = wnt.nodes.new("ShaderNodeValToRGB")
wramp.color_ramp.elements[0].color = (0.0015, 0.002, 0.004, 1)
wramp.color_ramp.elements[1].color = (0.020, 0.045, 0.090, 1)
wnt.links.new(wexp.outputs[0], wramp.inputs["Fac"])
wramp.color_ramp.elements[1].color = HORIZON
wnt.links.new(wramp.outputs["Color"], bg.inputs["Color"])


# ---------------------------------------------------------------- Shader math helpers
def mathf(nt, op, a, b=None, clamp=False):
    node = nt.nodes.new("ShaderNodeMath"); node.operation = op; node.use_clamp = clamp
    for idx, val in enumerate((a, b)):
        if val is None:
            continue
        if isinstance(val, (int, float)):
            node.inputs[idx].default_value = val
        else:
            nt.links.new(val, node.inputs[idx])
    return node.outputs[0]


# ---------------------------------------------------------------- Floor: dot node grid (procedural, infinite)
def floor_material():
    mat = bpy.data.materials.new("grid_floor")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    lib.set_input(bsdf, "Base Color", (0.004, 0.005, 0.007, 1))
    lib.set_input(bsdf, "Roughness", 0.30)
    lib.set_input(bsdf, "Specular IOR Level", 0.45)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sp = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sp.inputs[0])
    x, y = sp.outputs["X"], sp.outputs["Y"]
    cx, cy = mathf(nt, "DIVIDE", x, S), mathf(nt, "DIVIDE", y, S)
    fx = mathf(nt, "SUBTRACT", mathf(nt, "FRACT", mathf(nt, "ADD", cx, 0.5)), 0.5)
    fy = mathf(nt, "SUBTRACT", mathf(nt, "FRACT", mathf(nt, "ADD", cy, 0.5)), 0.5)
    d = mathf(nt, "MULTIPLY", mathf(nt, "SQRT", mathf(nt, "ADD", mathf(nt, "MULTIPLY", fx, fx),
                                                         mathf(nt, "MULTIPLY", fy, fy))), S)   # distance to node (m)

    def disc(radius):
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.interpolation_type = "SMOOTHSTEP"
        mr.inputs["From Min"].default_value = radius
        mr.inputs["From Max"].default_value = radius * 0.45
        nt.links.new(d, mr.inputs["Value"])
        return mr.outputs["Result"]

    # cell hash: (round(cx), round(cy) mod TILE_CELLS) -> lit node
    ix = mathf(nt, "ROUND", cx)
    iy = mathf(nt, "FLOORED_MODULO", mathf(nt, "ROUND", cy), TILE_CELLS)
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(ix, comb.inputs["X"]); nt.links.new(iy, comb.inputs["Y"])
    wn = nt.nodes.new("ShaderNodeTexWhiteNoise"); wn.noise_dimensions = "3D"
    nt.links.new(comb.outputs[0], wn.inputs["Vector"])
    sepc = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(wn.outputs["Color"], sepc.inputs["Color"])
    lit = mathf(nt, "GREATER_THAN", wn.outputs["Value"], 0.972)
    side = mathf(nt, "MULTIPLY", mathf(nt, "SUBTRACT", mathf(nt, "ABSOLUTE", x), CENTER_HALF), 0.6, clamp=True)
    lit = mathf(nt, "MULTIPLY", lit, side)
    warm = mathf(nt, "GREATER_THAN", sepc.outputs["Red"], 0.82)

    # distance falloff (camera ray length)
    lp = nt.nodes.new("ShaderNodeLightPath")
    fade = mathf(nt, "EXPONENT", mathf(nt, "DIVIDE", lp.outputs["Ray Length"], -28.0))
    base_dot = mathf(nt, "MULTIPLY", disc(0.020), 0.9)
    lit_dot = mathf(nt, "MULTIPLY", mathf(nt, "MULTIPLY", disc(0.042), lit), 14.0)
    strength = mathf(nt, "MULTIPLY", mathf(nt, "ADD", base_dot, lit_dot), fade)
    col = nt.nodes.new("ShaderNodeMix"); col.data_type = "RGBA"
    nt.links.new(mathf(nt, "MULTIPLY", warm, lit), col.inputs["Factor"])
    col.inputs["A"].default_value = (0.42, 0.66, 1.0, 1)
    col.inputs["B"].default_value = WARM
    nt.links.new(col.outputs["Result"], bsdf.inputs["Emission Color"])
    nt.links.new(strength, bsdf.inputs["Emission Strength"])
    # Aerial perspective: farther points melt into the horizon colour (removes the hard edge of the plane)
    fog_emit = nt.nodes.new("ShaderNodeEmission")
    fog_emit.inputs["Color"].default_value = HORIZON
    fog_emit.inputs["Strength"].default_value = 1.0
    fog_fac = mathf(nt, "SUBTRACT", 1.0, mathf(nt, "EXPONENT", mathf(nt, "DIVIDE", lp.outputs["Ray Length"], -70.0)))
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(fog_fac, mix.inputs["Fac"])
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(fog_emit.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return mat


bpy.ops.mesh.primitive_plane_add(size=1)
floor = bpy.context.active_object
floor.name = "floor"
floor.scale = (400, 400, 1)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
floor.location = (0, 150, 0)
# To keep the floor origin at 0 so Object coordinates match world, move the mesh instead of the object location
for v in floor.data.vertices:
    v.co.y += 150
floor.location = (0, 0, 0)
lib.assign(floor, floor_material(), smooth=False)

# ---------------------------------------------------------------- Lookup path (arc) mesh
time_mat = bpy.data.materials.new("lookup_path")
time_mat.use_nodes = True
pnt = time_mat.node_tree
pbsdf = pnt.nodes["Principled BSDF"]
pnt.nodes.remove(pbsdf)
pout = pnt.nodes["Material Output"]
t_val = pnt.nodes.new("ShaderNodeValue"); t_val.name = "time"


def attr(name):
    a = pnt.nodes.new("ShaderNodeAttribute"); a.attribute_type = "OBJECT"; a.attribute_name = name
    return a.outputs["Fac"]


uvn = pnt.nodes.new("ShaderNodeUVMap")
uvsep = pnt.nodes.new("ShaderNodeSeparateXYZ")
pnt.links.new(uvn.outputs["UV"], uvsep.inputs[0])
u = uvsep.outputs["X"]
# x = fract(time*freq + phase); head position of hop k: h = (x - k*delta)/delta  (0..1 is this hop's span)
xph = mathf(pnt, "FRACT", mathf(pnt, "ADD", mathf(pnt, "MULTIPLY", t_val.outputs[0], attr("freq")), attr("phase")))
h = mathf(pnt, "DIVIDE", mathf(pnt, "SUBTRACT", xph, mathf(pnt, "MULTIPLY", attr("hop"), attr("delta"))), attr("delta"))
dd = mathf(pnt, "SUBTRACT", h, u)                       # distance behind the head (fraction of arc length)
TRAIL = 0.55
inside = mathf(pnt, "MULTIPLY", mathf(pnt, "GREATER_THAN", dd, -0.002), mathf(pnt, "LESS_THAN", dd, TRAIL))
tail = mathf(pnt, "POWER", mathf(pnt, "SUBTRACT", 1.0, mathf(pnt, "DIVIDE", dd, TRAIL), clamp=True), 2.2)
head = mathf(pnt, "EXPONENT", mathf(pnt, "MULTIPLY", mathf(pnt, "POWER", mathf(pnt, "DIVIDE", dd, 0.03), 2.0), -1.0))
pulse = mathf(pnt, "ADD", mathf(pnt, "MULTIPLY", mathf(pnt, "MULTIPLY", tail, inside), 6.0),
              mathf(pnt, "MULTIPLY", head, 22.0))
plp = pnt.nodes.new("ShaderNodeLightPath")
pfade = mathf(pnt, "EXPONENT", mathf(pnt, "DIVIDE", plp.outputs["Ray Length"], -30.0))
strength = mathf(pnt, "MULTIPLY", mathf(pnt, "ADD", pulse, attr("base")), pfade)
emi = pnt.nodes.new("ShaderNodeEmission")
cmix = pnt.nodes.new("ShaderNodeMix"); cmix.data_type = "RGBA"
pnt.links.new(attr("warm"), cmix.inputs["Factor"])
cmix.inputs["A"].default_value = CYAN
cmix.inputs["B"].default_value = WARM
pnt.links.new(cmix.outputs["Result"], emi.inputs["Color"])
pnt.links.new(strength, emi.inputs["Strength"])
pnt.links.new(emi.outputs[0], pout.inputs["Surface"])

# time = 0→1 (frames 1→N+1). Supplied via driver (in Blender 5.2 keyframes don't take LINEAR and get eased)
_fc = t_val.outputs[0].driver_add("default_value")
_fc.driver.type = "SCRIPTED"
_fc.driver.expression = f"(frame-1)/{N}"


def arc_mesh(name, a, b, height, radius=0.0055, segs=64, sides=6):
    """a->b parabolic arc tube. UV x = along the length, 0..1"""
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    rings = []
    ax, ay = a
    bx, by = b
    for i in range(segs + 1):
        t = i / segs
        cx = ax + (bx - ax) * t
        cy = ay + (by - ay) * t
        cz = 4 * height * t * (1 - t) + radius
        # tangent
        tx, ty = bx - ax, by - ay
        tz = 4 * height * (1 - 2 * t)
        ln = math.sqrt(tx * tx + ty * ty + tz * tz)
        tx, ty, tz = tx / ln, ty / ln, tz / ln
        # horizontal normal n1, its cross product n2
        hx, hy = -ty, tx
        hl = math.hypot(hx, hy) or 1.0
        n1 = (hx / hl, hy / hl, 0.0)
        n2 = (ty * n1[2] - tz * n1[1], tz * n1[0] - tx * n1[2], tx * n1[1] - ty * n1[0])
        ring_v = []
        for k in range(sides):
            ang = 2 * math.pi * k / sides
            c, s = math.cos(ang) * radius, math.sin(ang) * radius
            ring_v.append(bm.verts.new((cx + n1[0] * c + n2[0] * s, cy + n1[1] * c + n2[1] * s,
                                        cz + n1[2] * c + n2[2] * s)))
        rings.append((t, ring_v))
    for (t0, r0), (t1, r1) in zip(rings, rings[1:]):
        for k in range(sides):
            k2 = (k + 1) % sides
            f = bm.faces.new((r0[k], r0[k2], r1[k2], r1[k]))
            for loop in f.loops:
                tt = t0 if loop.vert in r0 else t1
                loop[uv_layer].uv = (tt, 0.0)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    scene.collection.objects.link(obj)
    obj.data.materials.append(time_mat)
    return obj


node_mat = bpy.data.materials.new("path_node")
node_mat.use_nodes = True
nnt = node_mat.node_tree
nnt.nodes.remove(nnt.nodes["Principled BSDF"])
nem = nnt.nodes.new("ShaderNodeEmission")
na = nnt.nodes.new("ShaderNodeAttribute"); na.attribute_type = "OBJECT"; na.attribute_name = "warm"
nm = nnt.nodes.new("ShaderNodeMix"); nm.data_type = "RGBA"
nnt.links.new(na.outputs["Fac"], nm.inputs["Factor"])
nm.inputs["A"].default_value = CYAN
nm.inputs["B"].default_value = WARM
nnt.links.new(nm.outputs["Result"], nem.inputs["Color"])
nlp = nnt.nodes.new("ShaderNodeLightPath")
ndiv = nnt.nodes.new("ShaderNodeMath"); ndiv.operation = "DIVIDE"; ndiv.inputs[1].default_value = -30.0
nexp = nnt.nodes.new("ShaderNodeMath"); nexp.operation = "EXPONENT"
nmul = nnt.nodes.new("ShaderNodeMath"); nmul.operation = "MULTIPLY"; nmul.inputs[1].default_value = 7.0
nnt.links.new(nlp.outputs["Ray Length"], ndiv.inputs[0]); nnt.links.new(ndiv.outputs[0], nexp.inputs[0])
nnt.links.new(nexp.outputs[0], nmul.inputs[0]); nnt.links.new(nmul.outputs[0], nem.inputs["Strength"])
nnt.links.new(nem.outputs[0], nnt.nodes["Material Output"].inputs["Surface"])


def node_marker(name, p, warm):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.024, segments=16, ring_count=8, location=(p[0], p[1], 0.02))
    o = bpy.context.active_object
    o.name = name
    o.scale = (1, 1, 0.35)
    o.data.materials.append(node_mat)
    o["warm"] = warm
    return o


# Lookup path (chain) design within one tile: sides only, node coordinates on the grid
chains = []
for side in (-1, 1):
    for c in range(3):
        n_hops = rng.choice([2, 3, 3, 4])
        gx = side * (rng.randint(6, 12) if c == 0 else rng.randint(8, 22))              # x in grid cells (|x| >= 3 m)
        gy = rng.randint(0, TILE_CELLS - 1) + c * 5
        pts = [(gx, gy)]
        for _ in range(n_hops):
            px, py = pts[-1]
            nx = px + side * rng.randint(1, 5) * rng.choice([1, 1, -1])
            if abs(nx) < 5:
                nx = side * 5
            ny = py + rng.randint(2, 7)
            pts.append((nx, ny))
        chains.append(dict(pts=pts, phase=rng.random(), freq=rng.choice([1, 1, 2]),
                           warm=1.0 if rng.random() < 0.22 else 0.0))

# A single chain spans up to ~27 m in y, so keep generous tiles behind the camera too (no arc vanishing at the seam).
# Far side falls off as exp(-d/30), 0.5% at 160 m -> dropping the last tile is invisible.
COPIES = range(-5, 20)
for ci, ch in enumerate(chains):
    n_h = len(ch["pts"]) - 1
    delta = 0.55 / n_h                                   # whole chain plays over 55% of the cycle
    for j in COPIES:
        oy = j * TILE
        world_pts = [(gx * S, gy * S + oy) for gx, gy in ch["pts"]]
        for k in range(n_h):
            a, b = world_pts[k], world_pts[k + 1]
            dist = math.hypot(b[0] - a[0], b[1] - a[1])
            o = arc_mesh(f"arc_{ci}_{j}_{k}", a, b, height=0.16 + 0.22 * dist)
            o["phase"], o["freq"], o["hop"], o["delta"] = ch["phase"], float(ch["freq"]), float(k), delta
            o["warm"], o["base"] = ch["warm"], 0.12
        for k, p in enumerate(world_pts):
            node_marker(f"node_{ci}_{j}_{k}", p, ch["warm"])

# ---------------------------------------------------------------- Camera: advances exactly TILE over the clip
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 24
cam_data.sensor_width = 36
cam_data.clip_end = 400
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
cam.rotation_euler = (math.radians(90 - 6.5), 0, 0)
cam.location = (0.0, -1.0, 1.05)
_fc = cam.driver_add("location", 1)            # linear advance (driver): frame 151 = frame 1 + TILE
_fc.driver.type = "SCRIPTED"
_fc.driver.expression = f"-1.0+{TILE}*(frame-1)/{N}"


# ---------------------------------------------------------------- Compositor bloom
def add_bloom(strength=0.55, threshold=0.6, size=0.55):
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
    print(f"[grid] bloom skipped: {e}")

scene.frame_set(args.still if args.still is not None else 1)
if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # chunked: encode separately after all chunks are collected
else:
    lib.render(args)
