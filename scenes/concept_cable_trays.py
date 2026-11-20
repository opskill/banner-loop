"""컨셉 10: 데이터센터 천장의 사다리형 케이블 트레이를 올려다보는 샷 (히어로 배너 루프).

트레이(사다리형: 양쪽 레일 + 가로 렁)가 화면 좌우에서 원근으로 깊이 빠지고, 정리된 케이블 다발은 대부분 어둡게,
아쿠아 광케이블을 따라 작은 빛 펄스가 흐른다. 화면 양 끝 바깥 낮은 트레이에는 노란(싱글모드) 광점퍼 다발과
앰버 펄스(카메라에서 멀어지면 꺼져서 가운데 40% 안으로는 들어오지 않는다). 천장은 격자 보(와플 슬래브)와
나사봉 행거로 '올려다보는 천장'임을 알려 주고, 가운데는 어둡게 비운다.

속도: 지오메트리는 행거 한 칸(SUP) 분량의 메시 하나만 파이썬으로 만들고 Array 모디파이어로 반복한다
(오브젝트 1개). 모든 형상/텍스처가 SUP 주기라 루프가 정확하다.
루프(5초): 카메라가 SUP(=1.2m)만큼 선형 전진. 펄스는 공간 주기 L, 속도 v 에서 (v*T - SUP)/L 이 정수.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

import lib  # noqa: E402


def _extra(p):
    p.add_argument("--start", type=int, default=None, help="애니메이션 시작 프레임 (청크 렌더)")
    p.add_argument("--end", type=int, default=None, help="애니메이션 끝 프레임 (청크 렌더)")
    p.add_argument("--spp", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--size", default="1920x540", help="예: 3840x1080")


args = lib.parse_args("concept_cable_trays", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x, scene.render.resolution_y = (int(v) for v in args.size.split("x"))
scene.render.resolution_percentage = 100          # 미리보기도 1920x540 그대로
if args.engine == "cycles":
    scene.cycles.samples = args.spp or 128
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.01
    scene.cycles.max_bounces = 5
    scene.cycles.seed = args.seed
    scene.render.use_persistent_data = True       # 카메라만 움직이므로 BVH 재사용
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

SUP = 1.2                       # 트레이 지지대(행거) 간격 = 루프 이동 거리 = 타일 길이
RUNG = 0.3                      # 사다리 렁 간격 (SUP 의 약수)
Y0 = -6.0                       # SUP 의 정수배
COUNT = 55                      # 타일 반복 수 (66 m)
CEIL = 4.6
PULSE_L = 3 * SUP               # 아쿠아 펄스 공간 주기
PULSE_V = 7 * SUP / T           # (v*T - SUP)/L = 6*SUP/(3*SUP) = 2
AMBER_L = 2 * SUP               # 앰버 펄스는 조금 느리게
AMBER_V = 5 * SUP / T           # (5-1)*SUP/(2*SUP) = 2
CAM_Y = f"({SUP}*(frame-1)/{N})"   # 카메라 y (드라이버 식)

M = lib.make_pbr
# 트레이/케이블 알베도는 리뷰 뒤 약 30% 낮췄다 (양옆 트레이가 문구보다 밝게 튀지 않도록)
steel = M("Tray Steel", (0.14, 0.147, 0.161, 1), metallic=1.0, roughness=0.4)
strut = M("Strut", (0.126, 0.133, 0.14, 1), metallic=1.0, roughness=0.4)
rod_mat = M("Rod", (0.3, 0.3, 0.31, 1), metallic=1.0, roughness=0.3)
# 타일 1.2 m = SUP 이라 콘크리트 무늬도 루프 주기와 맞는다
slab = lib.make_tiled_pbr("Ceiling Slab", "concrete_wall_007", tile=SUP, tint=(0.03, 0.033, 0.042, 1))
blk = [M("Cable Black", (0.0084, 0.0084, 0.0098, 1), roughness=0.45),
       M("Cable Charcoal", (0.021, 0.0224, 0.0252, 1), roughness=0.5),
       M("Cable Slate", (0.0175, 0.0245, 0.035, 1), roughness=0.45)]


def make_fiber(name, base, glow, strength, offset, L, V, idle=0.03, near_only=False, far_fade=None):
    """광케이블: 기본은 은은한 색, 월드 y 를 따라 흐르는 짧은 펄스(앞이 밝고 뒤로 꼬리).

    near_only: 카메라에서 4~8 m 사이에서 발광이 꺼진다 (멀리서 화면 가운데로 모이는 구간에 색이 안 남게).
    far_fade=(d0, d1, floor): 카메라에서 d0~d1 m 사이에서 발광이 floor 배까지 줄어든다 (문구 자리로 들어가는 먼 펄스를 가라앉힌다).
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
    # u in [0,1): 펄스 머리에서 뒤로 잰 거리 / L
    u = m("FRACT", m("DIVIDE", m("SUBTRACT", m("ADD", m("MULTIPLY", t, V), offset), y), L))
    tail = m("POWER", m("SUBTRACT", 1.0, m("MINIMUM", m("DIVIDE", u, 0.22), 1.0)), 3.0)   # 꼬리 = 0.22*L
    head = m("LESS_THAN", u, 0.985)   # 머리 앞은 바로 꺼짐
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


# 펄스 세기를 리뷰 뒤 낮췄다 (머리가 하얗게 타지 않고 색이 남도록). 0.6배로는 AgX 에서 여전히 흰색으로 타서
# 아쿠아는 0.15배 + 발광색을 더 짙게, 앰버는 0.4배. 아쿠아는 멀어질수록(= 화면 가운데로 갈수록) 더 줄인다
PULSE_GAIN = float(os.environ.get("TRAYS_PULSE_GAIN", 0.15))
AMBER_GAIN = float(os.environ.get("TRAYS_AMBER_GAIN", 0.4))
aqua = [make_fiber(f"Fiber Aqua {k}", (0.02, 0.22, 0.25, 1), (0.1, 0.85, 1.0), 40.0 * PULSE_GAIN, k * 1.37, PULSE_L, PULSE_V,
                   far_fade=(4.0, 8.0, 0.1)) for k in range(3)]
amber = [make_fiber(f"Fiber Amber {k}", (0.5, 0.2, 0.01, 1), (1.0, 0.42, 0.05), 18.0 * AMBER_GAIN, k * 0.83, AMBER_L, AMBER_V,
                    idle=0.05, near_only=True) for k in range(3)]


# ------------------------------------------------------------------ 타일 메시 빌더 (오브젝트 1개)
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
        """pts 를 따라가는 관. vertical=False 면 y 방향(단면 xz), True 면 z 방향(단면 xy)."""
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
SEG = 16                        # 케이블 한 타일의 분할 수 (렁 사이 4분할)


def cable_bundle(x, z, width, n_rows, mats, r=0.012, wander=0.006, sag=0.006):
    """트레이 바닥(z)에 놓인 케이블 다발. 3~5 가닥씩 묶음으로 나눠 묶음마다 굵기/좌우 흔들림/처짐을 다르게 준다.

    흔들림은 SUP 주기(행거마다 타이로 묶인 느낌), 처짐은 렁 사이(RUNG 주기)라 타일이 이음매 없이 이어진다.
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
    """트래피즈 행거 (타일 y=0.6... 가 아니라 y=SUP/2 에 둔다: 타일 경계와 겹치지 않게).

    천장 앵커 플레이트에서 내려온 나사봉 2개 + 너트 + 아래 C 형강.
    """
    y = SUP / 2
    B.box((x1 - x0 + 0.14, 0.042, 0.042), ((x0 + x1) / 2, y, z - 0.021), strut)
    for xr in (x0 - 0.045, x1 + 0.045):
        B.tube([(xr, y, z - 0.07), (xr, y, CEIL)], 0.007, rod_mat, n=6, vertical=True)
        B.box((0.024, 0.024, 0.012), (xr, y, z - 0.05), rod_mat)       # 아래 너트
        B.box((0.024, 0.024, 0.012), (xr, y, z + 0.006), rod_mat)      # 위 너트
        B.box((0.07, 0.07, 0.008), (xr, y, CEIL - 0.004), strut)       # 천장 앵커 플레이트


# 트레이 배치: (x 중심, 높이, 폭, 케이블 종류). 가운데(|x|<1.2)는 비워 둔다
TRAYS = [
    (-2.6, 3.05, 0.6, "power"),
    (-1.55, 3.45, 0.45, "fiber"),
    (1.55, 3.45, 0.45, "fiber"),
    (2.6, 3.05, 0.6, "power"),
    (-3.3, 2.8, 0.36, "amber"),      # 화면 양 끝 바깥 낮은 트레이: 노란 광점퍼 + 앰버 펄스
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

# 천장: 슬래브 + 격자 보(와플). 보는 타일마다 가로 1개(y=SUP/2 = 행거 줄), 세로는 1.5 m 간격
B.box((16, SUP, 0.3), (0, SUP / 2, CEIL + 0.15 + 0.22), slab)
B.box((16, 0.16, 0.22), (0, SUP / 2, CEIL + 0.11), slab)
for i in range(-5, 6):
    xr = (i + 0.5) * 1.5
    if abs(xr) < 2.0:            # 가운데는 가로 보만 남겨 조용하게
        continue
    B.box((0.16, SUP, 0.2), (xr, SUP / 2, CEIL + 0.12), slab)   # 가로 보보다 살짝 얕게(겹친 면 방지)

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

# ------------------------------------------------------------------ 조명 (전부 카메라에 안 보이는 면광원)
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
    strip("Side Fill", (sx * 2.95, CY, 2.2), 180, 1000, COOL)                  # 위(트레이 밑면/천장)를 비춘다
    strip("Inner Fill", (sx * 2.1, CY, 2.0), 180 - 25 * sx, 420, COOL)

# ------------------------------------------------------------------ 카메라: 위로 올려다보며 전진
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
# 앰버 스필: 바깥 트레이 아래의 따뜻한 빛. 카메라와 같이 움직이는 짧은 띠라 먼 곳(=화면 가운데)은 물들지 않는다
for sx in (-1, 1):
    strip("Amber Spill", (sx * 3.45, 2.5, 2.35), 180 + 12 * sx, 40, (1.0, 0.45, 0.1), size=0.25, length=6.0, parent=rig)
# 선형 전진은 드라이버로 준다. (Blender 5.2 에서는 lib.set_default_interpolation("LINEAR") 가 먹지 않아
# 키프레임이 베지어 ease-in/out 이 되고, 루프 이음매에서 카메라가 멈췄다 가는 것처럼 보인다.)
fc = rig.driver_add("location", 1)
fc.driver.type = "SCRIPTED"
fc.driver.expression = CAM_Y



# ------------------------------------------------------------------ 컴포지터: 약한 거리 페이드 (먼 케이블 줄무늬의 계단/모아레를 가라앉힌다)
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
        col_in = [i for i in mix.inputs if i.type == "RGBA"]       # 같은 이름 소켓이 타입별로 있어 타입으로 고른다
        col_out = [o for o in mix.outputs if o.type == "RGBA"][0]
        ng.links.new(mul.outputs[0], mix.inputs[0])
        ng.links.new(rl.outputs["Image"], col_in[0])
        col_in[1].default_value = fog + (1.0,)
        out = ng.nodes.new("NodeGroupOutput")
        ng.links.new(col_out, out.inputs[0])
        scene.compositing_node_group = ng
        scene.render.use_compositing = True
    except Exception as e:  # noqa: BLE001
        print(f"[cable_trays] distance fade 건너뜀: {e}")


if not os.environ.get("TRAYS_NO_FADE"):
    add_distance_fade()

if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # 청크: 인코딩은 다 모은 뒤 따로
else:
    lib.render(args)
