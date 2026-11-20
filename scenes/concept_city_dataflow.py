"""Concept 04 - data flow in an abstract night city: a low, dark block city seen from a high oblique viewpoint.

The city is clustered on two shores at the left and right of the frame; the centre is a dark bay (water) opening toward the horizon, so it stays calm.
Thin streaks of light (data flow) run along the streets, and the flow on the shore avenues converges at the horizon centre (vanishing area).

Loop (5 s, 150 frames): the streak pattern shifts by an integer K wavelengths via fract(u/L - K*t) -> end = start.
The camera sways very slightly with sin(2pi t) and returns.
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
    p.add_argument("--seed", type=int, default=0)


args = lib.parse_args("concept_city_dataflow", frames=150, engine="cycles", extra=_extra)
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
rng = random.Random(11)

CAM_H = 350.0
BLOCK, STREET = 58.0, 16.0
PITCH = BLOCK + STREET
Y_MIN, Y_MAX = 280.0, 8000.0
BAY0, BAY = 120.0, 0.08         # half-width of the river/bay = BAY0 + BAY*y  -> wide in front, converging at the horizon centre
FOG_K = 0.00048
FOG_COL = (0.006, 0.012, 0.027)


def hw(y):
    return BAY0 + BAY * y


def xmax(y):
    return 0.80 * y + 160


# ------------------------------------------------------------------ node helpers
class NB:
    def __init__(self, nt):
        self.nt = nt

    def node(self, kind, **inputs):
        n = self.nt.nodes.new(kind)
        for k, v in inputs.items():
            self.set(n.inputs[k], v)
        return n

    def set(self, sock, v):
        if hasattr(v, "is_output"):
            self.nt.links.new(v, sock)
        else:
            sock.default_value = v

    def math(self, op, a, b=None, clamp=False):
        n = self.nt.nodes.new("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if v is not None:
                self.set(n.inputs[i], v)
        return n.outputs[0]

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


def finish_fog(nb, out, shader_socket):
    """Camera-distance fog: mixes in fog-colour emission by 1-exp(-k*d) (cleaner and faster than a volume)."""
    cam = nb.node("ShaderNodeCameraData")
    f = nb.math("SUBTRACT", 1.0, nb.math("EXPONENT", nb.math("MULTIPLY", cam.outputs["View Distance"], -FOG_K)))
    fog = nb.node("ShaderNodeEmission", Color=FOG_COL + (1.0,), Strength=1.0)
    # fog on camera rays only (reflection/indirect light use the original shader)
    lp = nb.node("ShaderNodeLightPath")
    f = nb.math("MULTIPLY", f, lp.outputs["Is Camera Ray"])
    mix = nb.node("ShaderNodeMixShader")
    nb.link(f, mix.inputs[0])
    nb.link(shader_socket, mix.inputs[1])
    nb.link(fog.outputs[0], mix.inputs[2])
    nb.link(mix.outputs[0], out.inputs["Surface"])


def loop_time():
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

# ------------------------------------------------------------------ world: only a very faint glow toward the horizon
lib.set_world(color=(0, 0, 0, 1), strength=1.0)
wnt = scene.world.node_tree
wb = NB(wnt)
tc = wb.node("ShaderNodeTexCoord")
sep = wb.node("ShaderNodeSeparateXYZ")
wb.link(tc.outputs["Generated"], sep.inputs[0])
hz = wb.math("EXPONENT", wb.math("MULTIPLY", wb.math("MAXIMUM", sep.outputs["Z"], 0.0), -14.0))
ramp = wb.node("ShaderNodeMix")
ramp.data_type = "RGBA"
wb.link(hz, ramp.inputs["Factor"])
ramp.inputs["A"].default_value = (0.002, 0.004, 0.010, 1)
ramp.inputs["B"].default_value = FOG_COL + (1,)
# subtle glow in the vanishing area (horizon centre)
cg = wb.math("MULTIPLY", wb.math("EXPONENT", wb.math("MULTIPLY", wb.math("ABSOLUTE", sep.outputs["Z"]), -40.0)),
             wb.math("EXPONENT", wb.math("MULTIPLY", wb.math("ABSOLUTE", sep.outputs["X"]), -5.0)))
sky_add = wb.node("ShaderNodeMix")
sky_add.data_type = "RGBA"
sky_add.blend_type = "ADD"
sky_add.inputs["Factor"].default_value = 1.0
wb.link(ramp.outputs["Result"], sky_add.inputs["A"])
cgc = wb.node("ShaderNodeCombineXYZ")
wb.link(wb.math("MULTIPLY", cg, 0.05), cgc.inputs[0])
wb.link(wb.math("MULTIPLY", cg, 0.12), cgc.inputs[1])
wb.link(wb.math("MULTIPLY", cg, 0.22), cgc.inputs[2])
wb.link(cgc.outputs[0], sky_add.inputs["B"])
lp = wb.node("ShaderNodeLightPath")
amb = wb.node("ShaderNodeMix")          # weak for lighting
amb.data_type = "RGBA"
wb.link(lp.outputs["Is Camera Ray"], amb.inputs["Factor"])
amb.inputs["A"].default_value = (0.006, 0.010, 0.020, 1)
wb.link(sky_add.outputs["Result"], amb.inputs["B"])
wb.link(amb.outputs["Result"], wnt.nodes["Background"].inputs["Color"])

# ------------------------------------------------------------------ materials
# ground (asphalt) - slightly glossy so the light streaks reflect faintly
mat, nb, out = new_mat("Ground")
b = nb.node("ShaderNodeBsdfPrincipled", **{"Base Color": (0.010, 0.012, 0.016, 1), "Roughness": 0.45})
finish_fog(nb, out, b.outputs[0])
ground_mat = mat

# water - dark, nearly mirror-like surface with ripple bump
mat, nb, out = new_mat("Water")
b = nb.node("ShaderNodeBsdfPrincipled", **{"Base Color": (0.002, 0.004, 0.007, 1), "Roughness": 0.06})
wn = nb.node("ShaderNodeTexNoise", Scale=0.02, Detail=6.0)
tco = nb.node("ShaderNodeTexCoord")
mp = nb.node("ShaderNodeMapping")
mp.inputs["Scale"].default_value = (1.0, 0.25, 1.0)
nb.link(tco.outputs["Object"], mp.inputs["Vector"])
nb.link(mp.outputs[0], wn.inputs["Vector"])
bump = nb.node("ShaderNodeBump", Strength=0.25)
nb.link(wn.outputs["Fac"], bump.inputs["Height"])
nb.link(bump.outputs[0], b.inputs["Normal"])
finish_fog(nb, out, b.outputs[0])
water_mat = mat

# buildings - dark concrete + sparsely lit windows
mat, nb, out = new_mat("Building")
geo = nb.node("ShaderNodeNewGeometry")
sp = nb.node("ShaderNodeSeparateXYZ")
nb.link(geo.outputs["Position"], sp.inputs[0])
sn = nb.node("ShaderNodeSeparateXYZ")
nb.link(geo.outputs["Normal"], sn.inputs[0])
wall = nb.math("LESS_THAN", nb.math("ABSOLUTE", sn.outputs["Z"]), 0.5)
hcoord = nb.math("ADD", sp.outputs["X"], sp.outputs["Y"])
fl = nb.math("DIVIDE", sp.outputs["Z"], 3.6)
co = nb.math("DIVIDE", hcoord, 3.2)
win = nb.math("MULTIPLY", nb.math("LESS_THAN", nb.math("FRACT", fl), 0.5), nb.math("LESS_THAN", nb.math("FRACT", co), 0.55))
cmb = nb.node("ShaderNodeCombineXYZ")
nb.link(nb.math("FLOOR", co), cmb.inputs[0])
nb.link(nb.math("FLOOR", fl), cmb.inputs[1])
wnz = nb.node("ShaderNodeTexWhiteNoise")
wnz.noise_dimensions = "3D"
nb.link(cmb.outputs[0], wnz.inputs["Vector"])
rnd = wnz.outputs["Value"]
lit = nb.math("GREATER_THAN", rnd, 0.988)
cool = nb.math("GREATER_THAN", rnd, 0.992)
we = nb.math("MULTIPLY", nb.math("MULTIPLY", win, wall), lit)
wcol = nb.node("ShaderNodeMix")
wcol.data_type = "RGBA"
nb.link(cool, wcol.inputs["Factor"])
wcol.inputs["A"].default_value = (1.0, 0.62, 0.30, 1)
wcol.inputs["B"].default_value = (0.55, 0.8, 1.0, 1)
b = nb.node("ShaderNodeBsdfPrincipled", **{"Base Color": (0.018, 0.021, 0.028, 1), "Roughness": 0.62,
                                           "Specular IOR Level": 0.4})
nb.link(wcol.outputs["Result"], b.inputs["Emission Color"])
nb.link(nb.math("MULTIPLY", we, 2.2), b.inputs["Emission Strength"])
finish_fog(nb, out, b.outputs[0])
building_mat = mat


def stream_mat(name, color, k1, l1, k2, l2, gain, base=0.03):
    """A strip carrying u (metres, flow direction) and v (per-strip phase) in its UVs. Shifts an integer K wavelengths over t -> loop."""
    mat, nb, out = new_mat(name)
    uvn = nb.node("ShaderNodeUVMap")
    s = nb.node("ShaderNodeSeparateXYZ")
    nb.link(uvn.outputs[0], s.inputs[0])
    u, ph = s.outputs["X"], s.outputs["Y"]
    g = nb.nt.nodes.new("ShaderNodeGroup")
    g.node_tree = LOOP
    t = g.outputs[0]

    def pulse(k, lam, sharp, ph_mul):
        x = nb.math("FRACT", nb.math("ADD", nb.math("SUBTRACT", nb.math("DIVIDE", u, lam), nb.math("MULTIPLY", t, float(k))),
                                     nb.math("MULTIPLY", ph, ph_mul)))
        return nb.math("POWER", x, sharp)

    p = nb.math("ADD", pulse(k1, l1, 7.0, 1.0), nb.math("MULTIPLY", pulse(k2, l2, 14.0, 3.7), 0.7))
    # brightness variation per strip (differs by strip): overall strength weighted by phase
    w = nb.math("ADD", 0.45, nb.math("MULTIPLY", nb.math("FRACT", nb.math("MULTIPLY", ph, 7.3)), 0.55))
    inten = nb.math("ADD", base, nb.math("MULTIPLY", p, w))
    em = nb.node("ShaderNodeEmission", Color=color + (1.0,))
    nb.link(nb.math("MULTIPLY", inten, gain), em.inputs["Strength"])
    finish_fog(nb, out, em.outputs[0])
    return mat


cyan = stream_mat("Stream Cyan", (0.35, 0.78, 1.0), 2, 90.0, 3, 47.0, 34.0)
white = stream_mat("Stream Main", (0.62, 0.88, 1.0), 3, 120.0, 5, 61.0, 20.0, base=0.04)
amber = stream_mat("Stream Amber", (1.0, 0.52, 0.18), 2, 75.0, 3, 41.0, 16.0)


# ------------------------------------------------------------------ geometry builder
class MeshBuilder:
    def __init__(self, name, uv=False):
        self.bm = bmesh.new()
        self.name = name
        self.uv = self.bm.loops.layers.uv.new("UVMap") if uv else None

    def quad(self, pts, uvs=None):
        vs = [self.bm.verts.new(p) for p in pts]
        f = self.bm.faces.new(vs)
        if self.uv is not None and uvs:
            for loop, uvv in zip(f.loops, uvs):
                loop[self.uv].uv = uvv
        return f

    def box(self, x0, y0, x1, y1, h):
        bm = self.bm
        v = [bm.verts.new(p) for p in ((x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0),
                                        (x0, y0, h), (x1, y0, h), (x1, y1, h), (x0, y1, h))]
        for idx in ((4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            bm.faces.new([v[i] for i in idx])

    def finish(self, mat):
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        obj = bpy.data.objects.new(self.name, me)
        bpy.context.collection.objects.link(obj)
        me.materials.append(mat)
        return obj


def strip(mb, p0, p1, width, z, phase, reverse=False):
    """Light strip flowing from p0 to p1. u is the distance travelled in metres (flows the other way if reverse)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    nx, ny = -dy / L * width / 2, dx / L * width / 2
    u0 = 0.0 if not reverse else L
    u1 = L if not reverse else 0.0
    # tie the start coordinate to the world position so the pattern continues across broken segments
    off = (p0[0] * dx + p0[1] * dy) / L
    u0 += off if not reverse else -off
    u1 += off if not reverse else -off
    mb.quad([(p0[0] - nx, p0[1] - ny, z), (p1[0] - nx, p1[1] - ny, z), (p1[0] + nx, p1[1] + ny, z), (p0[0] + nx, p0[1] + ny, z)],
            [(u0, phase), (u1, phase), (u1, phase), (u0, phase)])


# ground / water
ground = MeshBuilder("Ground")
ground.quad([(-40000, 0, 0), (40000, 0, 0), (40000, 40000, 0), (-40000, 40000, 0)])
ground.finish(ground_mat)
water = MeshBuilder("Water")
YW = 40000
water.quad([(-hw(0) + 6, 0, 0.6), (hw(0) - 6, 0, 0.6), (hw(YW) - 6, YW, 0.6), (-hw(YW) + 6, YW, 0.6)])
water.finish(water_mat)

blocks = MeshBuilder("Blocks")
cy_s = MeshBuilder("StreamsCyan", uv=True)
am_s = MeshBuilder("StreamsAmber", uv=True)
main_s = MeshBuilder("StreamsMain", uv=True)

COAST = 26.0            # waterfront promenade width
i_max = int(xmax(Y_MAX) / PITCH) + 1
j_min, j_max = int(Y_MIN / PITCH), int(Y_MAX / PITCH)

for sgn in (-1, 1):
    # blocks
    for j in range(j_min, j_max):
        y0 = j * PITCH + STREET / 2
        y1 = y0 + BLOCK
        for i in range(0, i_max):
            ax0 = i * PITCH + STREET / 2
            ax1 = ax0 + BLOCK
            if ax0 < hw(y1) + COAST or ax0 > xmax(y0):
                continue
            # split each block into 1-4 buildings
            splits = rng.choice((1, 2, 2, 3, 4))
            dist = (ax0 ** 2 + y0 ** 2) ** 0.5
            near_coast = ax0 < hw(y1) + COAST + PITCH * 2
            for s in range(splits):
                fx0 = ax0 + (BLOCK / splits) * s + 2
                fx1 = ax0 + (BLOCK / splits) * (s + 1) - 2
                inset = rng.uniform(2, 8)
                h = rng.choice((9, 12, 14, 18, 22, 26, 32)) * rng.uniform(0.8, 1.25)
                if rng.random() < 0.06:
                    h *= rng.uniform(2.0, 3.2)
                if near_coast and rng.random() < 0.35:
                    h *= 1.5
                x0, x1 = sorted((sgn * fx0, sgn * fx1))
                blocks.box(x0, y0 + inset, x1, y1 - inset, h)
    # longitudinal streets (y direction, flowing into the screen -> vanishing area)
    for i in range(0, i_max):
        x = i * PITCH
        ytop = min(Y_MAX, (x - COAST - BAY0) / BAY)
        ybot = max(Y_MIN, (x - 160) / 0.80)
        if ytop - ybot < PITCH:
            continue
        for lane, off in ((0, -3.2), (1, 3.2)):
            r = rng.random()
            if r < 0.7:
                strip(cy_s, (sgn * x + off, ybot, 0), (sgn * x + off, ytop, 0), 1.6, 0.25, rng.random())
            elif r < 0.82:
                strip(am_s, (sgn * x + off, ybot, 0), (sgn * x + off, ytop, 0), 1.4, 0.25, rng.random(), reverse=True)
    # cross streets (x direction, flowing toward the waterfront)
    for j in range(j_min, j_max + 1):
        y = j * PITCH
        xin = hw(y) + COAST * 0.6
        xout = min(xmax(y), xin + rng.uniform(4, 14) * PITCH)
        if xout - xin < PITCH:
            continue
        for lane, off in ((0, -3.2), (1, 3.2)):
            r = rng.random()
            if r < 0.5:
                strip(cy_s, (sgn * xout, y + off, 0), (sgn * xin, y + off, 0), 1.6, 0.25, rng.random())
            elif r < 0.68:
                strip(am_s, (sgn * xout, y + off, 0), (sgn * xin, y + off, 0), 1.4, 0.25, rng.random(), reverse=True)
    # shore avenue: the brightest flow, converging on the vanishing area (3 lanes)
    for k, off in enumerate((7.0, 13.0)):
        strip(main_s, (sgn * (hw(Y_MIN) + off), Y_MIN, 0), (sgn * (hw(YW) + off), YW, 0), 1.8, 0.3, rng.random())

blocks.finish(building_mat)
cy_s.finish(cyan)
am_s.finish(amber)
main_s.finish(white)

# ------------------------------------------------------------------ lighting: very weak moonlight from the horizon side (building outlines)
moon = lib.add_sun("Moon", (0, 0, 0), energy=0.08, color=(0.6, 0.75, 1.0))
moon.rotation_euler = (math.radians(-75), 0, math.radians(180))

# ------------------------------------------------------------------ camera (high oblique) + loop sway
cam_data = bpy.data.cameras.new("Cam")
cam_data.sensor_fit = "HORIZONTAL"
cam_data.sensor_width = 36
cam_data.lens = 24
cam_data.clip_end = 60000
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
scene.camera = cam
PITCH_DOWN = 10.0
cam.location = (0.0, 0.0, CAM_H)
cam.rotation_euler = (math.radians(90 - PITCH_DOWN), 0, 0)
_PH = f"(2*pi*(frame-1)/{N_FRAMES})"                  # driver (keyframes get eased in 5.2)
for path, idx, expr in (("location", 0, f"5.0*sin({_PH})"),
                        ("location", 2, f"{CAM_H}+2.5*sin(2*{_PH})"),
                        ("rotation_euler", 2, f"{math.radians(0.25)}*sin({_PH})")):
    fc = cam.driver_add(path, idx)
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = expr


def add_bloom(strength=0.45, threshold=0.8, size=0.7):
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
        print(f"[city_dataflow] bloom skipped: {e}")


add_bloom()
if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N_FRAMES
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # chunked: encode separately after collecting all chunks
else:
    lib.render(args)
