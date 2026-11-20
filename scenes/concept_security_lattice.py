"""컨셉 07 보안 격자: 카메라를 감싸는 거대한 유리 육각 격자 방패(구면) 안쪽을 약간 아래/옆에서 올려다본다.
프레임 가장자리는 얇은 시안 림, 유리 판은 굴절. 스캔 빛띠가 왼쪽에서 오른쪽으로 방패를 훑고 지나간다.
가운데(시선 정면)는 어둡고 고요하게 마스크한다.

루프: 스캔 띠 위상 t 가 1프레임 0 → N+1프레임 1 (fract 로 감싸서 주기 = 클립 길이). 격자는 정지(주기 구조).
사용: node bin/blender.mjs concept_security_lattice --still 1 --engine cycles --out out/concepts/07_security_lattice
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
    p.add_argument("--start", type=int, default=None, help="애니메이션 시작 프레임 (청크 렌더)")
    p.add_argument("--end", type=int, default=None, help="애니메이션 끝 프레임 (청크 렌더)")
    p.add_argument("--spp", type=int, default=None)
    p.add_argument("--size", default="1920x540", help="예: 960x270 (드래프트), 3840x1080")
    p.add_argument("--draft", action="store_true", help="빠른 드래프트: 낮은 샘플/바운스 + 적응 샘플링 + GPU 디노이즈")


args = lib.parse_args("concept_security_lattice", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x, scene.render.resolution_y = (int(v) for v in args.size.split("x"))
if args.engine == "cycles":
    scene.cycles.samples = args.spp or (48 if args.preview else 128)
    scene.cycles.seed = 0
    scene.cycles.use_animated_seed = False        # 루프: 노이즈 패턴 고정
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
        scene.cycles.sample_clamp_indirect = 3.0      # 10 은 굴절 역광이 하얗게 날아가서 원래 값 유지
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
R = 11.0                 # 방패 구 반지름
A = math.radians(2.4)    # 육각 셀 외접 반지름(각도)
BANDS = 6                # 스캔 띠 개수(감싸는 범위 3.8 rad 안, 간격 약 36도): 좌우에 번갈아 보여 평균 밝기가 거의 일정
CAM_YAW = math.radians(7.0)     # 카메라 좌우 회전(+ 는 왼쪽)
CAM_PITCH = math.radians(5.0)
CAM_U = math.radians(-1.0)      # 화면 가운데에 오는 방패 경도(마스크 중심)

# ---------------------------------------------------------------- 월드: 방패 밖 깊은 남색 + 은은한 그라디언트
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


# ---------------------------------------------------------------- 구면 육각 격자 메시 (볼록 방패, 카메라 쪽 반구만)
SC = (0.0, 19.0, 0.0)   # 방패 구 중심


def sph(u, v, r):
    """방패 중심 기준 방향: u=0 이 카메라 쪽(-y), u 는 좌우 경도, v 는 위도"""
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
        # 프레임: 바깥 고리/안쪽 고리, 바깥면(R, 카메라 쪽)/안쪽면(R-DEPTH)
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
        # 유리 판: 두께 있는 닫힌 육각판 (프레임 안쪽에 살짝 들어가 있음)
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


# ---------------------------------------------------------------- 스캔 띠 노드 그룹 (월드 좌표 경도 기반)
def scan_group():
    g = bpy.data.node_groups.new("ScanBand", "ShaderNodeTree")
    g.interface.new_socket("Band", in_out="OUTPUT", socket_type="NodeSocketFloat")
    g.interface.new_socket("Side", in_out="OUTPUT", socket_type="NodeSocketFloat")
    n, L = g.nodes, g.links
    out = n.new("NodeGroupOutput")
    tc = n.new("ShaderNodeTexCoord")
    sp = n.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Object"], sp.inputs[0])
    u = n.new("ShaderNodeMath"); u.operation = "ARCTAN2"          # 경도 u = atan2(x, -y)
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

    U = 1.9                                                         # 감싸는 범위(rad): 화면 밖까지
    w = m("DIVIDE", m("ADD", u.outputs[0], U), 2 * U)                # 0..1
    t = n.new("ShaderNodeValue"); t.name = "scan_t"; t.label = "scan_t"
    # 띠 BANDS 개가 범위 2U 안에 같은 간격으로 있고, 한 루프 동안 한 간격만큼 오른쪽으로 이동 -> N+1 프레임 = 1 프레임
    s = m("FRACT", m("ADD", m("SUBTRACT", m("MULTIPLY", w, BANDS), t.outputs[0]), 0.5 - 0.385 * BANDS))
    d = m("SUBTRACT", s, 0.5)
    core = m("EXPONENT", m("MULTIPLY", m("POWER", m("DIVIDE", d, 0.012 * BANDS), 2.0), -1.0))
    halo = m("EXPONENT", m("MULTIPLY", m("POWER", m("DIVIDE", m("ADD", d, 0.025 * BANDS), 0.05 * BANDS), 2.0), -1.0))
    band = m("ADD", core, m("MULTIPLY", halo, 0.35))
    # 가운데(카메라 정면) 마스크: 정면에서 멀수록 1
    du = m("ABSOLUTE", m("SUBTRACT", u.outputs[0], CAM_U))
    side = m("MULTIPLY", m("SUBTRACT", du, 0.10), 1 / 0.45, clamp=True)
    bmask = m("POWER", side, 2.0)                                   # 띠는 가운데에서 완전히 꺼진다(문구 자리)
    side = m("ADD", m("MULTIPLY", m("POWER", side, 1.5), 0.95), 0.05)
    L.new(m("MULTIPLY", band, bmask), out.inputs["Band"])
    L.new(side, out.inputs["Side"])
    return g, t


SCAN, scan_t = scan_group()
# 루프: 1 → N+1 에서 0 → 1, 선형 (N+1 프레임 = 1 프레임). Blender 5.2 는 키프레임이 ease 되므로 드라이버로 준다
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
    # 기본 림 0.35*side + 스캔 띠
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
    # 셀마다 살짝 다른 거칠기(서리 낀 판 몇 개): 위치 기반 보로노이 셀 랜덤
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

# ---------------------------------------------------------------- 조명: 위쪽 큰 소프트박스(유리 반사), 방패 뒤 역광(가장자리 굴절), 따뜻한 포인트
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
# ---------------------------------------------------------------- 카메라 (약간 아래에서 올려다봄)
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 24
cam_data.sensor_width = 36
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
cam.location = (0.6, 0.0, -1.3)
cam.rotation_euler = (math.radians(90) + CAM_PITCH, 0.0, CAM_YAW)

# ---------------------------------------------------------------- 컴포지터: 부드러운 블룸
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
    print(f"[lattice] bloom 건너뜀: {e}")

if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # 청크: 인코딩은 다 모은 뒤 따로
else:
    scene.frame_set(args.still if args.still is not None else 1)
    lib.render(args)
