"""컨셉 02 광섬유 매크로: 패치 패널(LC 듀플렉스 포트) 줄을 아주 가까이에서 정면으로 보며 옆으로 천천히 이동한다.

얕은 심도: 패널 면에 초점, 카메라 바로 앞의 광섬유 끝 빛점은 큰 보케가 된다.
장면 전체가 x 방향으로 PERIOD 주기로 반복되고 카메라(+조명 리그)가 정확히 PERIOD 만큼 이동하므로
frame N+1 == frame 1 (끊김 없는 루프). 화면 가운데는 조명/발광 마스크로 어둡게 둔다.

리뷰 뒤 수정: 이동 속도 절반(주기 = 모듈 2개 = 0.18m), 카메라 앞에 떠 있던 보케 원반과 조리개 필터(테두리 링) 삭제,
가운데가 순검정이 되지 않게 아주 약한 가운데 필 조명 추가.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

import lib  # noqa: E402



def _extra(p):
    p.add_argument("--range", type=int, nargs=2, default=None, help="이 구간 프레임만 렌더 (GPU 를 나눠 쓰기 위한 청크)")
    p.add_argument("--start", type=int, default=None, help="--range 대신 쓸 수 있는 시작 프레임")
    p.add_argument("--end", type=int, default=None, help="--range 대신 쓸 수 있는 끝 프레임")
    p.add_argument("--spp", type=int, default=None, help="최대 샘플 수")
    p.add_argument("--seed", type=int, default=0, help="Cycles 노이즈 시드 (루프 검증용)")
    p.add_argument("--uhd", action="store_true", help="3840x1080 (기본 1920x540)")


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
PORT = 0.0135                  # LC 듀플렉스 어댑터 간격 (m)
PER_MOD = 6
GAP = 0.009
MOD_W = PORT * PER_MOD + GAP   # 모듈 폭
MODS_PER_PERIOD = 2                # 4 -> 2: 루프당 이동량(=이동 속도)을 절반으로
PERIOD = MOD_W * MODS_PER_PERIOD   # 이 거리마다 장면이 반복된다 = 루프 동안 카메라 이동량 (0.18m)
COPIES = range(-4, 6)              # 주기 복사 범위 (화면 + 이동량 + 케이블 길이 여유)
ROW_Z = (0.0445, 0.0, -0.0445)
CAM_D = 0.38                       # 화면 가로 폭 ≈ 0.40m. 주기 0.18m 라 같은 배치가 두 번 들어오지만 가운데는 어둡고,
#                                    밝은 양옆 띠(각 폭 약 0.12m)는 서로 0.28m 떨어져 다른 위상을 보여 준다. 줄마다 모듈 순서도 다르다
LENS = 34.0
FSTOP = 2.8
HALF_TAN = 18.0 / LENS             # 카메라 가로 반화각 tan (sensor 36)
FOCUS = CAM_D - 0.012
R_AP = LENS / 1000 / (2 * FSTOP)   # 조리개 반지름 (m)

# 모듈마다 성격이 다르다 (색 비율 / 꽂힌 비율 / 처짐 / 흐르는 방향). 줄마다 모듈 순서를 밀어 세로로도 겹치지 않게 한다.
MODULES = [
    dict(w=(7, 1, 0.15), fill=0.94, droop=(0.9, 1.1), side=0.85),    # 빽빽한 아쿠아(OM3/4)
    dict(w=(1.5, 6, 0.0), fill=0.80, droop=(1.15, 1.5), side=0.15),  # 남색 위주, 깊게 처짐
    dict(w=(4, 2, 1.6), fill=0.68, droop=(0.8, 1.0), side=0.6),      # 섞임 + 주황(멀티모드) 포인트
    dict(w=(3, 3, 0.0), fill=0.42, droop=(1.2, 1.6), side=0.35),     # 듬성듬성, 빈 포트/더스트캡 많음
]
ROW_SHIFT = (0, 2, 1)              # 주기가 모듈 2개라 줄마다 (0,1) / (2,3) / (1,2) 번 모듈이 번갈아 나온다


# ------------------------------------------------------------------ 화면 위치 마스크 (가운데 어둡게)
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
    """카메라 공간 좌표로 화면 가로 위치 u(0=가운데, 1=가장자리)를 구해 가운데 발광을 줄인다."""
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
    """발광 재질. 화면 가운데(|u| < lo, 헤드라인 자리)에서는 완전히 꺼진다."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = color
    nt.links.new(_math(nt, "MULTIPLY", screen_mask(nt, lo, hi, floor), strength), em.inputs["Strength"])
    nt.links.new(em.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return mat


# ------------------------------------------------------------------ 재질
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
boot_mats = {   # 부츠는 같은 계열의 무광 고무
    "aqua": M("Boot Aqua", (0.015, 0.22, 0.27, 1), roughness=0.6),
    "blue": M("Boot Blue", (0.008, 0.035, 0.2, 1), roughness=0.6),
    "beige": M("Boot Beige", (0.3, 0.27, 0.2, 1), roughness=0.6),
}
fiber_mats = {
    "aqua": M("Fiber Aqua", (0.03, 0.30, 0.36, 1), roughness=0.42),
    "blue": M("Fiber Blue", (0.012, 0.06, 0.22, 1), roughness=0.42),
    "beige": M("Fiber Orange", (0.5, 0.17, 0.03, 1), roughness=0.42),   # 멀티모드 OM1/2 주황
}
tip_cool = glow_mat("Tip Cool", (0.25, 0.75, 1.0, 1), 18.0)
tip_warm = glow_mat("Tip Warm", (1.0, 0.5, 0.15, 1), 14.0)
led_g = glow_mat("LED Cool", (0.2, 0.8, 1.0, 1), 4.0)
led_a = glow_mat("LED Amber", (1.0, 0.45, 0.1, 1), 4.5)


# ------------------------------------------------------------------ 한 주기 분량의 '설계'(무작위)를 먼저 정하고 복사한다
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

# 보케: 카메라와 패널 사이(초점 앞)에 떠 있는 느슨한 광섬유 끝. 수를 줄이고 거리/밝기를 제각각으로.
# 원반 크기는 실제 심도(거리)로 정해지고, 원하는 원반 밝기 t 에 맞춰 발광 세기를 역산한다.
bokeh = []
brng = random.Random(7)
N_BOKEH = 0                    # 리뷰 뒤 삭제 (떠다니는 원반이 산만하고 초해상 업스케일에서 링이 생겼다). 값을 올리면 되살아난다
B_PERIOD = PERIOD * 2 / 3      # 보케 배치 주기. 보케 리그가 루프 동안 PERIOD/3 만큼 따라가므로 카메라와의 상대 이동이 정확히 한 주기
for i in range(N_BOKEH):
    d = (0.135, 0.20, 0.16, 0.21, 0.175, 0.19)[i] + brng.uniform(-0.006, 0.006)   # 카메라에서의 거리
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
    """여러 도형을 (모디파이어/변환 적용 후) 한 메시로 합친다. 원점은 (0,0,0)."""
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
    ob = tpl.copy()          # 메시 공유
    ob.location = loc
    bpy.context.collection.objects.link(ob)
    return ob


RX = math.radians(90)
DX = 0.0031                    # 듀플렉스 두 코어의 좌우 오프셋


def rbox(name, size, loc, mat, rot_x=0.0, bevel=0.0003):
    ob = lib.box(name, size, loc, mat, bevel=bevel)
    ob.rotation_euler = (rot_x, 0, 0)
    return ob


def make_adapter():
    """LC 듀플렉스 어댑터: 금속 플랜지 + 검은 몸체 + 두 구멍(키 홈) + 안쪽 세라믹 슬리브."""
    parts = [lib.box("a", (0.0128, 0.0008, 0.0114), (0, -0.0004, 0), flange_mat, bevel=0.0003),
             lib.box("a", (0.0118, 0.004, 0.0098), (0, -0.0015, 0), adapter_mat, bevel=0.0004)]
    for dx in (-DX, DX):
        parts.append(lib.box("a", (0.0042, 0.001, 0.0046), (dx, -0.0036, 0), hole_mat, bevel=0.0))
        parts.append(lib.box("a", (0.0018, 0.001, 0.0012), (dx, -0.0036, 0.0027), hole_mat, bevel=0.0))   # 래치 키 홈
        parts.append(lib.cyl("a", 0.00125, 0.0012, (dx, -0.0038, -0.0003), sleeve_mat, rot=(RX, 0, 0), bevel=0.0, verts=20))
        parts.append(lib.cyl("a", 0.0007, 0.0013, (dx, -0.0039, -0.0003), hole_mat, rot=(RX, 0, 0), bevel=0.0, verts=16))
    return join("Adapter T", parts)


def make_plug(col):
    """LC 듀플렉스 플러그: 몸체 2 + 래치 2 + 듀플렉스 클립(트리거) + 리브가 있는 테이퍼 부츠 2."""
    body, boot = conn_mats[col], boot_mats[col]
    parts = []
    for dx in (-DX, DX):
        parts.append(lib.box("p", (0.0045, 0.0125, 0.0050), (dx, -0.00925, -0.0002), body, bevel=0.0005))
        # 래치: 앞(패널 쪽)은 몸체에 붙고 뒤로 갈수록 들린다
        parts.append(rbox("p", (0.0024, 0.0100, 0.0006), (dx, -0.0098, 0.0034), body, rot_x=math.radians(-9)))
        parts.append(rbox("p", (0.0026, 0.0016, 0.0012), (dx, -0.0052, 0.0027), body))        # 래치 걸쇠 턱
        # 뒤쪽 칼라 + 부츠(세 단으로 가늘어짐) + 리브
        parts.append(lib.cyl("p", 0.0023, 0.0022, (dx, -0.0166, -0.0002), body, rot=(RX, 0, 0), bevel=0.0002, verts=20))
        for k, (rad, y0, y1) in enumerate(((0.00205, -0.0177, -0.0235), (0.00175, -0.0235, -0.0290), (0.0014, -0.0290, -0.0345))):
            parts.append(lib.cyl("p", rad, y0 - y1, (dx, (y0 + y1) / 2, -0.0002), boot, rot=(RX, 0, 0), bevel=0.0002, verts=20))
        for k in range(4):
            parts.append(lib.cyl("p", 0.00232, 0.0006, (dx, -0.0188 - k * 0.0013, -0.0002), boot, rot=(RX, 0, 0), bevel=0.0,
                                 verts=20))
    # 듀플렉스 클립: 두 몸체를 묶고 위쪽 트리거가 두 래치를 덮는다
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

# 패널 본체 (연속된 1U 판 여러 장)
X_LO = COPIES.start * PERIOD - 0.05
X_HI = COPIES.stop * PERIOD + 0.05
# 판은 주기마다 한 장씩(메시 공유) 둔다: 표면 노이즈 범프가 오브젝트 좌표 기준이라 이렇게 해야 질감까지 주기적이다
panel_t = lib.box("Panel T", (PERIOD, 0.004, 0.0430), (0, 0, 0), panel_mat, bevel=0.0006)
for poly in panel_t.data.polygons:      # 큰 평면에 스무스 셰이딩을 쓰면 노멀이 판 끝으로 기울어 이음매에서 밝기가 계단진다
    poly.use_smooth = False
for c in COPIES:
    for r, z in enumerate(ROW_Z):
        place(panel_t, ((c + 0.5) * PERIOD, 0.002, z))
bpy.data.objects.remove(panel_t)
lib.box("Rack Back", (X_HI - X_LO, 0.01, 0.4), ((X_LO + X_HI) / 2, 0.03, 0), M("Back", (0.005, 0.005, 0.006, 1), roughness=0.7),
        bevel=0.0)

# 줄마다 아래쪽을 가로로 지나는 트렁크 다발 (패치코드가 합류하는 곳). 물결은 주기의 정수배라 루프를 깨지 않는다.
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
            # 지퍼코드: 부츠 끝에서 앞으로 조금 나왔다가 아래로 처지며 옆으로 흘러 아래쪽 트렁크 다발에 합류
            zb = ROW_Z[r] - 0.019 * min(droop, 1.25)
            yb = -0.042 - 0.012 * seed
            pts = [(X, -0.031, z), (X, -0.041, z - 0.002), (X + side * 0.003, yb, z - 0.010 * droop),
                   (X + side * 0.014 * droop, yb - 0.003, zb), (X + side * 0.05, yb - 0.006, zb - 0.004),
                   (X + side * 0.11, -0.043 - 0.006 * seed, ROW_Z[r] - 0.0235), (X + side * 0.20, -0.043 - 0.006 * seed, ROW_Z[r] - 0.0245)]
            for k, dx in enumerate((-DX, DX)):
                # 두 가닥은 커넥터에서 벌어져 나와 곧 지퍼코드로 붙는다
                fiber(f"Fiber {n}{k}", [(p[0] + (dx if i < 2 else dx * 0.36), p[1], p[2]) for i, p in enumerate(pts)], 0.00095,
                      fiber_mats[col])
        elif kind == "empty_glow":
            # 빈 포트 안쪽 페룰 끝이 빛난다 (광섬유 끝 빛점). 화면 가운데에서는 마스크로 꺼진다.
            for dx in (-DX, DX):
                place(tip_t[(tip_warm if seed < 0.18 else tip_cool).name], (X + dx, -0.0044, z - 0.0003))
        elif kind == "cap":
            place(cap_t, (X, 0, z))
        n += 1
    for (r, x, seed) in leds:
        if seed < 0.6:
            place(led_t[(led_a if seed < 0.12 else led_g).name], (ox + x, -0.0006, ROW_Z[r] - 0.016))
# 보케 발광체: 카메라 속도의 절반으로 따라 흐르는 리그에 붙인다 (전경이 휙휙 지나가지 않고 차분하게 흐른다)
bokeh_rig = lib.group("Bokeh Rig")
for j in range(-2, 5):
    for i, (bx, by, bz, r_e, mat) in enumerate(bokeh):
        place(bokeh_t[i], (j * B_PERIOD + bx, by, bz)).parent = bokeh_rig
for t in templates:
    bpy.data.objects.remove(t)
print(f"[fiber_macro] ports: {n}, period {PERIOD:.4f} m")

# ------------------------------------------------------------------ 카메라 + 조명 리그 (함께 x 로 PERIOD 이동)
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
cam_data.dof.aperture_blades = 0          # 원형 보케


def add_aperture_filter():
    """렌즈 바로 앞(1.2mm)에 투명도 필터를 둬서 조리개 면의 투과율을 반지름에 따라 바꾼다.

    가운데는 조금 어둡고 가장자리가 밝은(구면수차 과보정 렌즈) 분포 + 약한 동심원(양파링).
    초점이 맞은 곳은 선명도가 그대로이고, 초점 밖 빛점만 테두리가 밝은 실제 렌즈 보케가 된다.
    화면 가장자리에서는 필터와 조리개가 살짝 어긋나 보케가 약하게 비대칭이 된다.
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
    scene.view_settings.exposure = 0.75      # 필터 평균 투과율(약 0.6) 보정


if N_BOKEH:                    # 조리개 필터는 보케 원반용. 원반이 없으면 테두리 링만 남기므로 같이 뺀다
    add_aperture_filter()
else:
    scene.view_settings.exposure = 0.1       # 필터(평균 투과율 약 0.64) + 노출 0.75 조합과 같은 밝기


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


# 좌우 바깥쪽에서 비스듬히 비추는 차가운 키 (가운데는 어둡게 떨어진다)
spot("Key L", (-0.32, -0.17, 0.07), (-0.15, 0, -0.005), 4.2, (0.6, 0.82, 1.0))
spot("Key R", (0.32, -0.17, 0.07), (0.15, 0, -0.005), 4.2, (0.6, 0.82, 1.0))
# 아래쪽에서 아주 약한 웜 림 (한쪽만)
spot("Warm Rim", (0.23, -0.10, -0.09), (0.13, 0, 0.0), 0.4, (1.0, 0.6, 0.3), angle=30)

# 가운데 필: 순검정이던 가운데(문구 자리)에 패널/케이블 윤곽이 아주 옅게 남도록 (모바일 16:10 크롭이 비어 보이지 않게)
CENTER_FILL = float(os.environ.get("FIBER_CENTER_FILL", 0.5))
if CENTER_FILL:
    spot("Centre Fill", (0.0, -0.30, 0.10), (0.0, 0, -0.005), CENTER_FILL, (0.55, 0.78, 1.0), size=0.05, angle=34)

# 프레임 1 → N+1 동안 정확히 PERIOD 를 등속으로 이동한다.
# (Blender 5.x 에서는 키프레임 보간 기본값 지정이 듣지 않아 베지어 가감속이 생기므로 드라이버로 직접 쓴다.
#  frame 은 서브프레임까지 실수로 들어오므로 모션블러도 루프 이음매에서 똑같다.)
def linear_x(ob, dist):
    d = ob.driver_add("location", 0).driver
    d.type = "SCRIPTED"
    d.expression = f"{dist!r}*(frame-1)/{N}"


linear_x(rig, PERIOD)
linear_x(bokeh_rig, PERIOD - B_PERIOD)


# ------------------------------------------------------------------ 컴포지터: 은은한 번짐
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
        print(f"[fiber_macro] bloom 건너뜀: {e}")


add_bloom()

if args.still is None and args.range:
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # 청크: 인코딩은 다 모은 뒤 따로
else:
    lib.render(args)
