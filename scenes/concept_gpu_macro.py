"""컨셉 06 GPU 매크로: AI/GPU 보드 위를 낮게 앞으로 천천히 미끄러지는 매크로 샷.

실제 크기(미터) 그대로 만든다: GPU 패키지(기판 + 인터포저 + 다이 + HBM 6스택 + 금속 보강 링)가
화면 좌우 두 줄(x = ±XC)로 놓이고 진행 방향(y)으로 PY 마다 반복된다. 가운데 줄(문구 자리)은 진행 방향과
나란한 병렬 버스 배선뿐이라 카메라가 가도 가운데는 거의 움직이지 않는다(패키지가 가운데를 지나지 않는다).
배선 위로 가는 빛 펄스가 흐른다(가운데는 꺼짐). 브랜드/글자 없음.

루프(기본 150프레임=5초): 카메라+조명 리그가 y 로 정확히 PY 만큼 전진 + 펄스 위상은 정수 바퀴 -> 끝 = 처음.
조명이 리그에 붙어 있고 장면이 y 로 주기적이라 프레임 평균 밝기가 거의 일정하다.
절차 텍스처 좌표도 y 를 PY 주기로 접어 쓴다(셀마다 같은 무늬 -> 프레임 N+1 = 프레임 1).

인자: --start/--end 청크 렌더, --spp 샘플 수. 환경변수 GPU_SPP/GPU_SEED/GPU_F0/GPU_F1 도 그대로 듣는다.
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
    p.add_argument("--start", type=int, default=None, help="애니메이션 시작 프레임 (청크 렌더)")
    p.add_argument("--end", type=int, default=None, help="애니메이션 끝 프레임 (청크 렌더)")
    p.add_argument("--spp", type=int, default=None)


args = lib.parse_args("concept_gpu_macro", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x, scene.render.resolution_y = 1920, 540
if args.engine == "cycles":
    scene.cycles.samples = args.spp or int(os.environ.get("GPU_SPP", 48 if args.preview else 192))
    scene.cycles.sample_clamp_indirect = 2.0
    scene.cycles.seed = int(os.environ.get("GPU_SEED", 0))
# 리그는 드라이버로 서브프레임까지 등속이라 루프 이음매에서도 블러가 같다 (전진 속도는 초점면에서 프레임당 약 2.5px)
scene.render.use_motion_blur = True
scene.render.motion_blur_shutter = 0.4
if args.still is None and (args.start or args.end or os.environ.get("GPU_F0")):
    scene.frame_start = args.start or int(os.environ.get("GPU_F0", 1))
    scene.frame_end = args.end or int(os.environ.get("GPU_F1", args.frames))
scene.view_settings.view_transform = "AgX"
for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
    try:
        scene.view_settings.look = look
        break
    except TypeError:
        continue
lib.set_world(color=(0.0006, 0.0012, 0.004, 1.0), strength=1.0)

N = args.frames
XC = 0.075          # 패키지 줄 중심 x (좌우 대칭). 안쪽 보강 링 모서리 |x| = 0.046 -> 초점면에서 화면 반폭의 53%
PY = 0.096          # 진행 방향 반복 피치 (m) = 루프당 카메라 이동량
ROWS = range(-3, 7)      # 리그(조명)가 PY 만큼 움직여도 반사에 걸리는 이웃 셀이 같도록 넉넉히
Y_SEAM = PY / 2 + 0.031  # 절차 텍스처를 접는 자리: 보강 링과 VRM 사이(무늬 없는 PCB/콘덴서뿐)
rng = random.Random(7)

M = lib.make_pbr
mask_mat = M("Solder Mask", (0.003, 0.006, 0.016, 1), roughness=0.42, coat=0.2)
lib.set_input(mask_mat.node_tree.nodes["Principled BSDF"], "Coat Roughness", 0.28)
trace_mat = M("Trace", (0.006, 0.011, 0.026, 1), metallic=0.2, roughness=0.28, coat=0.6)
substrate_mat = M("Substrate", (0.012, 0.018, 0.032, 1), roughness=0.45, bump=0.03, bump_scale=4000.0)
silicon_mat = M("Interposer", (0.022, 0.028, 0.045, 1), metallic=0.5, roughness=0.2)
die_mat = M("Die", (0.04, 0.05, 0.075, 1), metallic=0.9, roughness=0.07)
lib.set_input(die_mat.node_tree.nodes["Principled BSDF"], "Thin Film Thickness", 180.0)
hbm_mat = M("HBM", (0.022, 0.026, 0.036, 1), metallic=0.7, roughness=0.18)
hbm_top = M("HBM Top", (0.016, 0.02, 0.03, 1), metallic=0.6, roughness=0.34)
fill_mat = M("Underfill", (0.004, 0.005, 0.008, 1), roughness=0.38, coat=0.3)
ring_mat = M("Stiffener", (0.25, 0.26, 0.28, 1), metallic=1.0, roughness=0.32, bump=0.02, bump_scale=3000.0)
choke_mat = M("Choke", (0.03, 0.03, 0.032, 1), roughness=0.6, bump=0.05, bump_scale=3000.0)
choke_top = M("Choke Top", (0.18, 0.18, 0.19, 1), metallic=1.0, roughness=0.45)
ps_mat = M("Power Stage", (0.01, 0.01, 0.012, 1), roughness=0.25)
mlcc_mat = M("MLCC", (0.22, 0.15, 0.09, 1), roughness=0.5)
end_mat = M("Cap End", (0.6, 0.6, 0.6, 1), metallic=1.0, roughness=0.3)
alu_mat = M("Polymer Cap", (0.25, 0.26, 0.28, 1), metallic=1.0, roughness=0.3)
via_mat = M("Via", (0.5, 0.42, 0.3, 1), metallic=1.0, roughness=0.3)
led_mat = M("Amber LED", (0.02, 0.012, 0.004, 1), roughness=0.4, emission=(1.0, 0.42, 0.08, 14.0))


# ------------------------------------------------------------------ bmesh 헬퍼
class Batch:
    """재질별로 박스/원기둥을 한 메시에 모은다 (오브젝트 수를 줄여 빌드/렌더를 빠르게)."""

    def __init__(self, name, mat, bevel=0.0):
        self.name, self.mat, self.bevel, self.bm = name, mat, bevel, bmesh.new()
        self.lane_layer, self.lane = None, 0.0   # 펄스 배선 번호(정점 속성 "lane")

    def box(self, c, s, rot_z=0.0):
        vs = bmesh.ops.create_cube(self.bm, size=1.0)["verts"]
        if self.lane_layer is not None:
            for v in vs:
                v[self.lane_layer] = self.lane
        bmesh.ops.scale(self.bm, vec=mathutils.Vector(s), verts=vs)
        if rot_z:
            bmesh.ops.rotate(self.bm, verts=vs, cent=(0, 0, 0), matrix=mathutils.Matrix.Rotation(rot_z, 3, "Z"))
        bmesh.ops.translate(self.bm, vec=mathutils.Vector(c), verts=vs)

    def cyl(self, c, r, h, seg=16):
        vs = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=h)["verts"]
        bmesh.ops.translate(self.bm, vec=mathutils.Vector(c), verts=vs)

    def seg(self, p0, p1, w, h, z):
        """p0->p1 직선 배선 조각 (모서리 이음을 위해 양끝을 w/2 씩 늘린다)."""
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        L = math.hypot(dx, dy)
        if L < 1e-9:
            return
        self.box(((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, z + h / 2), (L + w, w, h), math.atan2(dy, dx))

    def build(self):
        mesh = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        obj = bpy.data.objects.new(self.name, mesh)
        bpy.context.collection.objects.link(obj)
        lib.assign(obj, self.mat, smooth=False)
        if self.bevel:
            mod = obj.modifiers.new("Bevel", "BEVEL")
            mod.width, mod.segments, mod.limit_method = self.bevel, 2, "ANGLE"
        return obj


PCB_T = 0.0016
Z0 = 0.0  # PCB 윗면
pcb = lib.box("PCB", (0.8, 2.4, PCB_T), (0, 0.5, -PCB_T / 2), mask_mat, bevel=0.0)
# 베벨 없는 상자를 스무스 셰이딩하면 윗면 법선이 모서리 쪽으로 기울어(보드 중심이 y=0.5) 반사가 좌우 비대칭이 되고
# 위치에 따라 달라져 루프도 안 닫힌다 -> 평면 셰이딩
for poly in pcb.data.polygons:
    poly.use_smooth = False

B = {k: Batch(k, m, bv) for k, m, bv in (
    ("trace", trace_mat, 0.0), ("ring", ring_mat, 0.0004), ("substrate", substrate_mat, 0.0003),
    ("silicon", silicon_mat, 0.0), ("die", die_mat, 0.00015), ("hbm", hbm_mat, 0.0002),
    ("hbm_top", hbm_top, 0.0), ("fill", fill_mat, 0.0), ("led", led_mat, 0.0),
    ("choke", choke_mat, 0.0006), ("choke_top", choke_top, 0.0003), ("ps", ps_mat, 0.0002),
    ("mlcc", mlcc_mat, 0.0), ("end", end_mat, 0.0), ("alu", alu_mat, 0.0), ("via", via_mat, 0.0),
)}
pulse = Batch("Pulse Traces", None)
pulse.lane_layer = pulse.bm.verts.layers.float.new("lane")
TW, TH = 0.00035, 0.00004   # 배선 폭/두께


def mlcc(x, y, rot=0.0, L=0.002, W=0.00125, H=0.0011, z=Z0):
    """적층 세라믹 콘덴서: 몸통 + 양끝 금속 전극."""
    cx, cy = math.cos(rot), math.sin(rot)
    B["mlcc"].box((x, y, z + H / 2), (L * 0.7, W, H * 0.98), rot)
    for s in (-1, 1):
        B["end"].box((x + s * cx * L * 0.42, y + s * cy * L * 0.42, z + H / 2),
                     (L * 0.16, W * 1.02, H), rot)


# ------------------------------------------------------------------ 셀 반복 (y 로 PY 주기, 좌우 두 줄)
LANE = 0.0011               # 가운데 버스 배선 간격
N_LANE = 36                 # |x| <= 0.040 까지 (패키지 안쪽 모서리 0.046 앞에서 끝난다)
for r in ROWS:
    cy = (r + 0.5) * PY     # 패키지 중심 y. 프레임 1 의 화면 가운데(y=0)는 두 패키지 줄 사이(VRM 줄)
    for side in (-1, 1):
        cx = side * XC
        # GPU 패키지
        SUB = 0.055
        B["substrate"].box((cx, cy, Z0 + 0.0006), (SUB, SUB, 0.0012))
        rz = Z0 + 0.0012
        for (ox, oy, sx, sy) in ((0, 0.0275, 0.058, 0.0035), (0, -0.0275, 0.058, 0.0035),
                                 (0.0275, 0, 0.0035, 0.051), (-0.0275, 0, 0.0035, 0.051)):
            B["ring"].box((cx + ox, cy + oy, rz + 0.0011), (sx, sy, 0.0022))
        B["silicon"].box((cx, cy, rz + 0.0003), (0.039, 0.029, 0.0006))
        iz = rz + 0.0006            # 인터포저 윗면
        B["die"].box((cx, cy, iz + 0.00045), (0.0205, 0.0255, 0.0009))
        B["fill"].box((cx, cy, iz + 0.00011), (0.0217, 0.0267, 0.00022))          # 언더필 필렛
        for sx in (-1, 1):
            hx = cx + sx * (0.0205 / 2 + 0.0008 + 0.0042)
            for oy in (-0.0092, 0.0, 0.0092):
                B["hbm"].box((hx, cy + oy, iz + 0.00055), (0.0084, 0.0086, 0.0011))
                B["fill"].box((hx, cy + oy, iz + 0.00011), (0.0092, 0.0094, 0.00022))
                # 윗면: 한 단 낮은 테두리 안쪽의 무광 몰드 면 + 1번 핀 표시 + 적층 경계선(옆면)
                B["hbm_top"].box((hx, cy + oy, iz + 0.0011 + 0.00002), (0.0074, 0.0076, 0.00004))
                B["end"].cyl((hx - sx * 0.0030, cy + oy - 0.0031, iz + 0.0011 + 0.00005), 0.00028, 0.00002, seg=12)
                for lz in (0.00028, 0.00055, 0.00082):
                    B["fill"].box((hx, cy + oy, iz + lz), (0.00846, 0.00866, 0.00004))
            # 인터포저 가장자리 테스트 패드 줄
            for i in range(12):
                B["via"].box((cx + sx * 0.0186, cy - 0.0121 + i * 0.0022, iz + 0.00001), (0.0005, 0.0009, 0.00002))
        # 기판 위 디커플링 콘덴서 (보강 링 안쪽 가장자리)
        for i in range(16):
            t = -0.021 + i * 0.0028
            for yy in (0.0185, -0.0185):
                mlcc(cx + t, cy + yy, rot=math.pi / 2, L=0.001, W=0.0005, H=0.0005, z=rz)
            if abs(t) < 0.016:
                for xx in (0.0225, -0.0225):
                    mlcc(cx + xx, cy + t, L=0.001, W=0.0005, H=0.0005, z=rz)

        # VRM 줄: 패키지 뒤(다음 패키지와의 사이). 가운데 버스(|x| < 0.046) 위로는 놓지 않는다
        row_y = cy + 0.047
        for i in range(12):
            x = cx + side * (-0.0525 + i * 0.0095)
            if abs(x) < 0.050:
                continue
            B["choke"].box((x, row_y, Z0 + 0.0022), (0.0078, 0.0078, 0.0044))
            B["choke_top"].box((x, row_y, Z0 + 0.0044), (0.0060, 0.0052, 0.0002))
            B["ps"].box((x, row_y - 0.0075, Z0 + 0.00045), (0.005, 0.0042, 0.0009))
            mlcc(x - 0.0028, row_y - 0.0112, rot=math.pi / 2)
            mlcc(x + 0.0028, row_y - 0.0112, rot=math.pi / 2)
            B["via"].cyl((x, row_y - 0.0135, Z0 + 0.00002), 0.00025, 0.00004, seg=10)
        for i in range(4):
            x = cx + side * (-0.045 + i * 0.03)
            if abs(x) < 0.055:
                continue
            B["alu"].cyl((x, row_y + 0.0085, Z0 + 0.0028), 0.0029, 0.0056, seg=32)

        # 호박색 상태 LED (셀마다 같은 자리 = 주기적, 깜빡이지 않음). 전해 콘덴서 사이, 패키지 줄 위(가운데 밖)
        B["led"].box((cx + side * 0.001, row_y + 0.0105, Z0 + 0.0003), (0.0012, 0.0007, 0.0006))

        # 패키지 바깥쪽 잡 배선 (맨해튼 + 45도). 셀마다 같은 난수열 -> 모든 셀이 똑같다(루프 조건)
        rng = random.Random(7 + (side > 0))
        for _ in range(14):
            y = cy + rng.uniform(-0.026, 0.026)
            x0 = cx + side * 0.031
            x1 = x0 + side * rng.uniform(0.004, 0.01)
            y1 = y + rng.choice((-1, 1)) * rng.uniform(0.002, 0.008)
            x2 = x1 + side * abs(y1 - y)
            B["trace"].seg((x0, y), (x1, y), TW, TH, Z0)
            B["trace"].seg((x1, y), (x2, y1), TW, TH, Z0)
            B["via"].cyl((x2, y1, Z0 + 0.00002), 0.00028, 0.00004, seg=10)
        # 패키지 안쪽: 버스로 내려가는 비아 줄 (짧은 스터브 + 비아, 안쪽 층으로 연결된다는 뜻)
        for i in range(14):
            y = cy - 0.026 + i * 0.004
            xe = cx - side * 0.0305
            B["trace"].seg((xe, y), (xe - side * 0.0022, y), TW, TH, Z0)
            B["via"].cyl((xe - side * 0.0026, y, Z0 + 0.00002), 0.00028, 0.00004, seg=10)

    # 가운데 버스: 진행 방향(y)과 나란한 병렬 배선. 카메라가 y 로 가도 무늬가 그대로라 문구 자리가 가만히 있다
    for j in range(-N_LANE, N_LANE + 1):
        x = j * LANE
        tgt = pulse if j % 3 == 0 else B["trace"]
        pulse.lane = float(j)
        tgt.seg((x, r * PY), (x, (r + 1) * PY), TW, TH, Z0)

for b in B.values():
    b.build()

# ------------------------------------------------------------------ 펄스 재질: 월드 y 를 따라 흐르는 빛 (주기 PY, 루프당 정수 바퀴)
pmat = bpy.data.materials.new("Pulse")
pmat.use_nodes = True
nt = pmat.node_tree
bsdf = nt.nodes["Principled BSDF"]
for n, v in (("Base Color", (0.014, 0.019, 0.026, 1)), ("Roughness", 0.28), ("Coat Weight", 0.6),
             ("Emission Color", (0.12, 0.55, 1.0, 1))):
    lib.set_input(bsdf, n, v)
tc = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])


def mnode(op, a=None, b=None, va=None, vb=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    if a is not None:
        nt.links.new(a, n.inputs[0])
    elif va is not None:
        n.inputs[0].default_value = va
    if b is not None:
        nt.links.new(b, n.inputs[1])
    elif vb is not None:
        n.inputs[1].default_value = vb
    return n.outputs[0]


LAMBDA = PY
# 루프 한 번에 펄스가 LOOPS 바퀴(LOOPS*LAMBDA) 진행, 카메라는 1*LAMBDA 전진.
# LOOPS=2 -> 화면 기준 +1(멀어지는 쪽, 느리게) / -3(다가오는 쪽) LAMBDA: 방향마다 다른 속도로 흐른다
LOOPS = 2
frame_val = nt.nodes.new("ShaderNodeValue")
drv = frame_val.outputs[0].driver_add("default_value").driver
drv.type = "SCRIPTED"
drv.expression = f"(frame - 1) / {N} * {LOOPS}"
# 배선마다 다른 위상/방향: y 를 배선 간격으로 양자화한 해시
lane_attr = nt.nodes.new("ShaderNodeAttribute")
lane_attr.attribute_name = "lane"
lane = mnode("ROUND", lane_attr.outputs["Fac"])
h = mnode("FRACT", mnode("MULTIPLY", mnode("SINE", mnode("MULTIPLY", lane, vb=12.9898)), vb=43758.5453))
sign = mnode("SUBTRACT", mnode("MULTIPLY", mnode("GREATER_THAN", h, vb=0.5), vb=2.0), vb=1.0)
u = mnode("SUBTRACT", mnode("DIVIDE", sep.outputs["Y"], vb=LAMBDA), mnode("MULTIPLY", sign, frame_val.outputs[0]))
u = mnode("FRACT", mnode("ADD", u, mnode("MULTIPLY", h, vb=7.0)))
# 진행 방향 쪽이 머리: sign>0 이면 u 가 작을수록 앞
# (u 는 fract(y/LAMBDA - sign*t): sign>0 이면 무늬가 +y 로 흐르고 머리는 u 가 큰 쪽)
u = mnode("ADD", mnode("MULTIPLY", sign, mnode("SUBTRACT", u, vb=0.5)), vb=0.5)
tail = mnode("POWER", u, vb=7.0)
head = mnode("POWER", u, vb=60.0)
e = mnode("MULTIPLY", mnode("ADD", mnode("MULTIPLY", tail, vb=6.0), mnode("MULTIPLY", head, vb=40.0)), vb=1.6)
# 화면 가운데(문구 자리)에서는 펄스를 낮춘다: 카메라 좌표 |x/z| 로 화면 위치를 구한다 (카메라가 움직여도 화면 기준)
csep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Camera"], csep.inputs["Vector"])
sx_ = mnode("ABSOLUTE", mnode("DIVIDE", csep.outputs["X"], mnode("ABSOLUTE", csep.outputs["Z"])))
mr = nt.nodes.new("ShaderNodeMapRange")
mr.interpolation_type = "SMOOTHSTEP"
# 화면 반폭 = 0.36. 가운데 33%(|x/z| < 0.12)는 완전히 끄고 바깥으로 갈수록 켠다
mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = 0.12, 0.20
mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.0, 1.0
nt.links.new(sx_, mr.inputs["Value"])
e = mnode("MULTIPLY", e, mr.outputs["Result"])
nt.links.new(e, bsdf.inputs["Emission Strength"])
pulse.mat = pmat
pulse_obj = pulse.build()



# ------------------------------------------------------------------ 절차 텍스처를 PY 주기로: y -> fract((y - Y_SEAM)/PY)*PY
def make_periodic(mat):
    """노이즈/보로노이 좌표의 y 를 셀 피치로 접는다. 접는 자리(Y_SEAM)는 무늬 없는 PCB/콘덴서뿐이라 이음매가 안 보인다."""
    t = mat.node_tree
    texs = [n for n in t.nodes if n.type in ("TEX_NOISE", "TEX_VORONOI") and not n.inputs["Vector"].is_linked]
    if not texs:
        return
    tcn = t.nodes.new("ShaderNodeTexCoord")
    sp = t.nodes.new("ShaderNodeSeparateXYZ")
    t.links.new(tcn.outputs["Object"], sp.inputs["Vector"])
    sh = t.nodes.new("ShaderNodeMath")
    sh.operation = "SUBTRACT"
    sh.inputs[1].default_value = Y_SEAM
    t.links.new(sp.outputs["Y"], sh.inputs[0])
    d = t.nodes.new("ShaderNodeMath")
    d.operation = "DIVIDE"
    d.inputs[1].default_value = PY
    t.links.new(sh.outputs[0], d.inputs[0])
    fr = t.nodes.new("ShaderNodeMath")
    fr.operation = "FRACT"
    t.links.new(d.outputs[0], fr.inputs[0])
    mu = t.nodes.new("ShaderNodeMath")
    mu.operation = "MULTIPLY"
    mu.inputs[1].default_value = PY
    t.links.new(fr.outputs[0], mu.inputs[0])
    cb = t.nodes.new("ShaderNodeCombineXYZ")
    t.links.new(sp.outputs["X"], cb.inputs["X"])       # 미터 단위 그대로, y 만 셀 안 좌표
    t.links.new(mu.outputs[0], cb.inputs["Y"])
    t.links.new(sp.outputs["Z"], cb.inputs["Z"])
    for n in texs:
        t.links.new(cb.outputs[0], n.inputs["Vector"])


# 다이: 회로 블록(플로어플랜)이 박막 간섭색/거칠기 차이로 은은하게 비친다
dnt = die_mat.node_tree
dbsdf = dnt.nodes["Principled BSDF"]
vor = dnt.nodes.new("ShaderNodeTexVoronoi")
vor.distance = "CHEBYCHEV"
vor.inputs["Scale"].default_value = 380.0
if "Randomness" in vor.inputs:
    vor.inputs["Randomness"].default_value = 0.3
for sock, lo, hi in (("Roughness", 0.06, 0.11), ("Thin Film Thickness", 170.0, 192.0)):
    if sock in dbsdf.inputs:
        m = dnt.nodes.new("ShaderNodeMapRange")
        m.inputs["To Min"].default_value, m.inputs["To Max"].default_value = lo, hi
        dnt.links.new(vor.outputs["Color"], m.inputs["Value"])
        dnt.links.new(m.outputs["Result"], dbsdf.inputs[sock])
for m_ in bpy.data.materials:
    make_periodic(m_)

# ------------------------------------------------------------------ 리그: 카메라와 조명이 함께 y 로 PY 만큼 전진 (조명이 고정이면 루프가 안 닫히고 밝기가 출렁인다)
rig = lib.group("Rig", (0, 0, 0))


def on_rig(obj):
    obj.parent = rig
    return obj


# ------------------------------------------------------------------ 조명
# 뒤쪽 림 조명을 좌우로 갈라 반사 띠가 패키지(양옆)에 걸리고 가운데 버스는 어둡게 남는다.
# PCB 에 비치는 광원의 거울상(x = ±0.12, y = 0.11)은 화면 위쪽 양 구석. 솔더마스크를 무광에 가깝게 해서 거울상이 하얗게 타지 않고
# 넓고 옅은 네이비 광택으로 퍼지게 했다 (다이/HBM/보강 링은 같은 조명을 또렷하게 반사)
for sx, col in ((-1, (0.24, 0.48, 1.0)), (1, (0.30, 0.54, 1.0))):
    a = on_rig(lib.group("Aim S", (sx * 0.09, 0.0, 0)))
    l = on_rig(lib.add_area_light("Back Rim", (sx * 0.25, 0.45, 0.1), a, 0.9, size=0.085, color=col))
    l.visible_camera = False
warm = on_rig(lib.add_area_light("Warm", (0.36, -0.04, 0.075), on_rig(lib.group("Aim W", (0.085, 0, 0))), 0.8, size=0.05,
                                 color=(1.0, 0.55, 0.22)))
warm.visible_camera = False
cool = on_rig(lib.add_area_light("Cool", (-0.4, 0.04, 0.035), on_rig(lib.group("Aim K", (-0.085, 0, 0))), 0.14, size=0.06,
                                 color=(0.25, 0.5, 1.0)))
cool.visible_camera = False
# 위에서 내려오는 약한 면광: 거울상은 화면 아래 밖(y=-0.17). 가운데 배선에 아래쪽부터 옅은 광택만 주고 위로 갈수록 사라진다
top = on_rig(lib.add_area_light("Top Sheen", (0, -0.02, 0.30), on_rig(lib.group("Aim T", (0, -0.02, 0))), 0.6, size=0.25,
                                color=(0.3, 0.5, 1.0)))
top.visible_camera = False

# ------------------------------------------------------------------ 카메라: 낮은 각도 매크로, y 로 PY 만큼 선형 전진
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 50
cam_data.sensor_width = 36
cam_data.clip_start = 0.005
cam = bpy.data.objects.new("Camera", cam_data)
bpy.context.collection.objects.link(cam)
scene.camera = cam
ELEV = math.radians(23)
DIST = 0.24
cam.rotation_euler = (math.radians(90) - ELEV, 0, 0)
cam.location = (0.0, -DIST * math.cos(ELEV), DIST * math.sin(ELEV) + 0.001)
on_rig(cam)
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = DIST
cam_data.dof.aperture_fstop = 2.8
cam_data.dof.aperture_blades = 7
cam_data.dof.aperture_rotation = math.radians(12)
# 등속 이동은 드라이버로 준다: 프레임 1 -> N+1 동안 정확히 PY.
# (Blender 5.2 에서는 lib.set_default_interpolation("LINEAR") 가 듣지 않아 키프레임이 베지어 가감속이 되고,
#  루프 이음매에서 카메라가 멈췄다 가는 것처럼 보인다.)
rig_drv = rig.driver_add("location", 1).driver
rig_drv.type = "SCRIPTED"
rig_drv.expression = f"{PY!r}*(frame-1)/{N}"


# ------------------------------------------------------------------ 컴포지터: 문구 자리(가운데) 노출을 낮추고 전체를 네이비로 그레이딩
def add_grade(center_stops=-0.6, tint=(0.84, 0.96, 1.18)):
    try:
        ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
        ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl = ng.nodes.new("CompositorNodeRLayers")
        co = ng.nodes.new("CompositorNodeImageCoordinates")
        ng.links.new(rl.outputs["Image"], co.inputs["Image"])
        sp = ng.nodes.new("ShaderNodeSeparateXYZ")
        ng.links.new(co.outputs["Normalized"], sp.inputs["Vector"])

        def m(op, a, vb):
            n = ng.nodes.new("ShaderNodeMath")
            n.operation = op
            ng.links.new(a, n.inputs[0])
            n.inputs[1].default_value = vb
            return n.outputs[0]

        dx = m("ABSOLUTE", m("SUBTRACT", sp.outputs["X"], 0.5), 0.0)
        mr = ng.nodes.new("ShaderNodeMapRange")
        mr.interpolation_type = "SMOOTHSTEP"
        # 가운데 40%(|dx| < 0.2)는 끝까지 낮추고 0.36 에서 0 으로 부드럽게 풀린다
        mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = 0.17, 0.37
        mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = center_stops, 0.0
        ng.links.new(dx, mr.inputs["Value"])
        ex = ng.nodes.new("CompositorNodeExposure")
        ng.links.new(rl.outputs["Image"], ex.inputs["Image"])
        ng.links.new(mr.outputs["Result"], ex.inputs["Exposure"])
        mix = ng.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        col_in = [i for i in mix.inputs if i.type == "RGBA"]       # 같은 이름 소켓이 타입별로 있어 타입으로 고른다
        col_out = [o for o in mix.outputs if o.type == "RGBA"][0]
        mix.inputs[0].default_value = 1.0
        ng.links.new(ex.outputs["Image"], col_in[0])
        col_in[1].default_value = tint + (1.0,)
        out = ng.nodes.new("NodeGroupOutput")
        ng.links.new(col_out, out.inputs[0])
        scene.compositing_node_group = ng
        scene.render.use_compositing = True
    except Exception as e:  # noqa: BLE001
        print(f"[gpu_macro] grade 건너뜀: {e}")


add_grade()

for o in bpy.data.objects:              # 디버그: GPU_OFF="Warm,Cool" 처럼 조명을 끈다
    if o.type == "LIGHT" and o.name in os.environ.get("GPU_OFF", "").split(","):
        o.data.energy = 0.0
if os.environ.get("GPU_INSPECT"):   # 렌더 없이 리그/조명 배치만 확인
    for f in (1, 2, 76, N + 1):
        scene.frame_set(f)
        bpy.context.view_layer.update()
        print("[inspect] frame", f, "rig y", round(rig.matrix_world.translation.y, 6))
    scene.frame_set(1)
    bpy.context.view_layer.update()
    for o in bpy.data.objects:
        if o.type in ("LIGHT", "CAMERA"):
            mw = o.matrix_world
            d = -(mw.to_3x3() @ mathutils.Vector((0, 0, 1)))
            print("[inspect]", o.name, [round(v, 3) for v in mw.translation], "dir", [round(v, 3) for v in d],
                  getattr(o.data, "energy", ""), getattr(o.data, "shape", ""))
    sys.exit(0)
if args.still is None and (args.start or args.end):
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # 청크: 인코딩은 다 모은 뒤 따로
else:
    lib.render(args)
