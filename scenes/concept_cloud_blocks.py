"""컨셉 05 클라우드 블록: 어두운 볼류메트릭 공간에 반투명(서리 유리) 큐브가 떠 있고, 일부는 격자로 정렬된다.

32:9 배너용 (1920x540). 가운데 40% 는 비워 두고 좌우에 디테일을 둔다.
루프(기본 150프레임=5초): 떠 있는 큐브는 정수 주기의 sin/cos 궤도로 흔들리고,
들어오는 중인 큐브는 빈 칸 쪽으로 다가갔다 물러난다(전부 frame 드라이버) -> 마지막 프레임 다음이 첫 프레임과 같다.
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
    p.add_argument("--size", default="1920x540", help="예: 960x270 (드래프트), 3840x1080")
    p.add_argument("--draft", action="store_true", help="빠른 드래프트: 낮은 샘플/바운스 + 적응 샘플링 + GPU 디노이즈")


args = lib.parse_args("concept_cloud_blocks", frames=150, engine="cycles", extra=_extra)
scene = lib.reset_scene()
lib.setup_render(scene, args)
scene.render.resolution_x, scene.render.resolution_y = (int(v) for v in args.size.split("x"))
if args.engine == "cycles":
    scene.cycles.samples = args.spp or (48 if args.preview else 160)
    scene.cycles.seed = 0
    scene.cycles.use_animated_seed = False        # 루프: 노이즈 패턴 고정
    scene.render.use_persistent_data = True
    scene.cycles.max_bounces = 10
    scene.cycles.transmission_bounces = 10
    scene.cycles.glossy_bounces = 4
    scene.cycles.volume_bounces = 0
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
rng = random.Random(11)

# ------------------------------------------------------------------ 월드: 깊은 남색 + 옅은 안개
lib.set_world(color=(0.004, 0.007, 0.014, 1.0), strength=1.0)
wnt = scene.world.node_tree
fog = wnt.nodes.new("ShaderNodeVolumeScatter")
fog.inputs["Density"].default_value = 0.0035
fog.inputs["Anisotropy"].default_value = 0.55
fog.inputs["Color"].default_value = (0.7, 0.85, 1.0, 1.0)
wnt.links.new(fog.outputs["Volume"], wnt.nodes["World Output"].inputs["Volume"])


# ------------------------------------------------------------------ 재질
def glass(name, tint, rough):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    lib.set_input(b, "Base Color", tint)
    lib.set_input(b, "Transmission Weight", 1.0)
    lib.set_input(b, "Roughness", rough)
    lib.set_input(b, "IOR", 1.45)
    lib.set_input(b, "Coat Weight", 0.25)
    lib.set_input(b, "Coat Roughness", 0.05)
    return mat


def emit(name, color, strength):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = color + (1.0,)
    e.inputs["Strength"].default_value = strength
    nt.links.new(e.outputs["Emission"], nt.nodes["Material Output"].inputs["Surface"])
    return mat


frost = glass("Frost", (0.50, 0.62, 0.80, 1), 0.28)
frost_clear = glass("Frost Clear", (0.55, 0.68, 0.85, 1), 0.1)
edge_c = emit("Edge Cyan", (0.12, 0.48, 1.0), 2.3)     # 3.2 -> 2.3: AI 업스케일에서 밝은 모서리가 번지지 않게
edge_dim = emit("Edge Dim", (0.12, 0.42, 1.0), 1.1)
core_c = emit("Core Cyan", (0.30, 0.62, 1.0), 1.5)     # 3.0 -> 1.5: 흰 면(코어) 밝기 낮춤
edge_far = emit("Edge Far", (0.10, 0.36, 0.9), 0.15)     # 가운데 뒤쪽 어두운 큐브용
core_w = emit("Core Warm", (1.0, 0.58, 0.28), 1.9)


def make_cube(name, size, loc, rot, mat=frost, edge=edge_dim, core=None):
    """서리 유리 큐브 + 모서리 발광(와이어프레임) + (선택) 안쪽 발광 코어."""
    root = lib.group(name, loc)
    root.rotation_euler = rot
    c = lib.box(name + " Glass", (size,) * 3, (0, 0, 0), mat, parent=root, bevel=size * 0.04)
    if edge is not None:
        bpy.ops.mesh.primitive_cube_add(size=size * 0.985)
        w = bpy.context.active_object
        w.name = name + " Edge"
        w.parent = root
        w.location = (0, 0, 0)
        mod = w.modifiers.new("Wire", "WIREFRAME")
        mod.thickness = size * 0.012
        mod.use_even_offset = True
        lib.assign(w, edge, smooth=False)
        w.visible_shadow = False
    if core is not None:
        k = lib.box(name + " Core", (size * 0.42,) * 3, (0, 0, 0), core, parent=root, bevel=size * 0.02)
        k.visible_shadow = False
    return root


# ------------------------------------------------------------------ 카메라 (+y 를 본다)
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 35
cam_data.sensor_width = 36
cam = bpy.data.objects.new("Camera", cam_data)
cam.rotation_euler = (math.radians(90), 0, 0)
bpy.context.collection.objects.link(cam)
scene.camera = cam
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = 10.5
cam_data.dof.aperture_fstop = 2.2

HALF = 18 / 35  # 깊이 d 에서 화면 반폭 = d*HALF, 반높이 = d*HALF*540/1920

floaters = []   # (obj, base_loc, base_rot, amp, phase)
incoming = []   # (obj, slot_loc, start_loc, start_rot)

# ------------------------------------------------------------------ 오른쪽: 정렬된 격자 (4x3x2), 몇 칸은 비어 있고 큐브가 들어오는 중
GRID_S, GAP = 0.42, 0.07
grid = lib.group("Grid", (4.1, 11.0, -0.05))
grid.rotation_euler = (math.radians(8), 0, math.radians(-32))
empty_cells = {(0, 2, 0), (3, 0, 1), (2, 1, 0)}
cells = []
for ix in range(4):
    for iz in range(3):
        for iy in range(2):
            cells.append((ix, iy, iz))
for ix, iy, iz in cells:
    if (ix, iz, iy) in empty_cells:
        continue
    p = ((ix - 1.5) * (GRID_S + GAP), (iy - 0.5) * (GRID_S + GAP), (iz - 1) * (GRID_S + GAP))
    core = core_c if (ix, iy, iz) in {(1, 0, 1), (2, 1, 2)} else (core_w if (ix, iy, iz) == (3, 0, 0) else None)
    c = make_cube(f"G{ix}{iy}{iz}", GRID_S, p, (0, 0, 0), edge=edge_c if iy == 0 else edge_dim, core=core)
    c.parent = grid
# 빈 칸으로 들어오는 중인 큐브 (격자 앞쪽에서 살짝 비껴 있음)
for (ix, iz, iy), off in zip(sorted(empty_cells), [(-0.15, -0.55, 0.35), (0.5, -0.4, -0.2), (0.2, -0.9, 0.1)]):
    slot = ((ix - 1.5) * (GRID_S + GAP), (iy - 0.5) * (GRID_S + GAP), (iz - 1) * (GRID_S + GAP))
    p = (slot[0] + off[0], slot[1] + off[1], slot[2] + off[2])
    r0 = (math.radians(rng.uniform(-14, 14)), math.radians(rng.uniform(-14, 14)), math.radians(rng.uniform(-20, 20)))
    c = make_cube(f"In{ix}{iz}", GRID_S, p, r0, edge=edge_c)
    c.parent = grid
    incoming.append((c, slot, p, r0))

# ------------------------------------------------------------------ 왼쪽: 작은 정렬 클러스터 (2x2x2, 하나 빠짐)
clus = lib.group("Cluster", (-4.9, 12.5, 0.35))
clus.rotation_euler = (math.radians(-6), 0, math.radians(28))
S2 = 0.5
for ix in range(2):
    for iy in range(2):
        for iz in range(2):
            if (ix, iy, iz) == (1, 0, 1):
                continue
            p = ((ix - 0.5) * (S2 + 0.08), (iy - 0.5) * (S2 + 0.08), (iz - 0.5) * (S2 + 0.08))
            c = make_cube(f"C{ix}{iy}{iz}", S2, p, (0, 0, 0), edge=edge_c,
                          core=core_c if (ix, iy, iz) == (0, 0, 0) else None)
            c.parent = clus
_p, _r = (0.29 + 0.35, -0.29 - 0.6, 0.29 + 0.45), (math.radians(18), math.radians(-12), math.radians(22))
c = make_cube("C_in", S2, _p, _r, edge=edge_c)
c.parent = clus
incoming.append((c, (0.29, -0.29, 0.29), _p, _r))


# ------------------------------------------------------------------ 떠다니는 큐브 (양쪽, 여러 깊이/크기)
def side_x(d, lo, hi, side):
    return side * d * HALF * rng.uniform(lo, hi)


specs = []
# 앞쪽 큰 큐브 (초점 밖, 화면 가장자리에 걸침)
specs += [(-1, 5.0, 0.45, 0.93, 1.02, -0.09), (1, 5.4, 0.42, 0.95, 1.05, -0.1)]
# 중간 깊이
for side in (-1, 1):
    for _ in range(5):
        d = rng.uniform(7.5, 14.0)
        specs.append((side, d, rng.uniform(0.25, 0.6), 0.52, 0.98, None))
# 먼 작은 큐브 (안개 속 점)
for side in (-1, 1):
    for _ in range(9):
        d = rng.uniform(16.0, 30.0)
        specs.append((side, d, rng.uniform(0.45, 1.0), 0.45, 1.0, None))

for k, (side, d, size, lo, hi, z) in enumerate(specs):
    x = side_x(d, lo, hi, side)
    zmax = d * HALF * 540 / 1920
    zz = z * d if z is not None else rng.uniform(-0.75, 0.75) * zmax
    rot = tuple(math.radians(rng.uniform(-40, 40)) for _ in range(3))
    core = None
    r = rng.random()
    if d < 15 and r < 0.08:
        core = core_w
    elif r < 0.22:
        core = core_c
    obj = make_cube(f"F{k}", size, (x, d, zz), rot, mat=frost if rng.random() < 0.7 else frost_clear,
                    edge=edge_c if d < 15 and rng.random() < 0.5 else edge_dim, core=core)
    ph = rng.random() * math.tau
    if k == 0:
        # 좌하단 앞쪽 큰 큐브는 화면 가장자리에서 잘려 보여서 뺀다 (난수 순서는 그대로 두어 나머지 배치 유지)
        for ch in list(obj.children):
            bpy.data.objects.remove(ch, do_unlink=True)
        bpy.data.objects.remove(obj, do_unlink=True)
        continue
    floaters.append((obj, (x, d, zz), rot, 0.06 + 0.012 * d, ph))

# 가운데 뒤쪽의 어둡고 흐린 큐브 3개 (림 조명 y=22 보다 뒤에 두어 직접광을 받지 않게): 모바일(16:10) 크롭이 빈 그라데이션이 되지 않게. 문구 자리라 루마 40 미만, 움직임도 작게.
rng2 = random.Random(5)
for k, (fx, d, size, fz) in enumerate([(-0.36, 27.0, 1.6, 0.42), (0.40, 30.0, 1.8, -0.38), (-0.07, 35.0, 1.8, 0.50)]):
    x, zz = fx * d * HALF, fz * d * HALF * 540 / 1920
    rot = tuple(math.radians(rng2.uniform(-40, 40)) for _ in range(3))
    obj = make_cube(f"Far{k}", size, (x, d, zz), rot, mat=frost, edge=edge_far)
    floaters.append((obj, (x, d, zz), rot, 0.2, rng2.random() * math.tau))

# ------------------------------------------------------------------ 조명: 좌우 뒤쪽 림(청), 낮은 따뜻한 보조, 위 소프트키
aim_l = lib.group("Aim L", (-4.5, 11.5, 0))
aim_r = lib.group("Aim R", (4.5, 11.0, 0))
for aim, x in ((aim_l, -6.5), (aim_r, 6.8)):
    l = lib.add_area_light("Rim", (x, 22.0, 2.5), aim, 280, size=4.0, color=(0.45, 0.68, 1.0))
    l.visible_camera = False
lib.add_area_light("Key", (0.0, 8.0, 9.0), lib.group("Aim C", (0, 11, 0)), 30, size=6.0, color=(0.75, 0.85, 1.0))
warm = lib.add_area_light("Warm", (9.0, 7.0, -2.5), aim_r, 260, size=3.0, color=(1.0, 0.62, 0.32))
warm.visible_camera = False
warm2 = lib.add_area_light("Warm L", (-9.0, 9.0, -3.0), aim_l, 140, size=3.0, color=(1.0, 0.62, 0.32))
warm2.visible_camera = False

# 아주 먼 배경 발광 판: 가장자리 쪽만 은은한 청색 (가운데는 어둡게)
bg_mat = bpy.data.materials.new("Backdrop")
bg_mat.use_nodes = True
nt = bg_mat.node_tree
nt.nodes.remove(nt.nodes["Principled BSDF"])
em = nt.nodes.new("ShaderNodeEmission")
tc = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
ab = nt.nodes.new("ShaderNodeMath")
ab.operation = "ABSOLUTE"
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].position = 0.25
ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1)
ramp.color_ramp.elements[1].position = 1.0
ramp.color_ramp.elements[1].color = (0.012, 0.03, 0.07, 1)
nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
sub = nt.nodes.new("ShaderNodeMath")
sub.operation = "SUBTRACT"
sub.inputs[1].default_value = 0.5
nt.links.new(sep.outputs["X"], sub.inputs[0])
mul = nt.nodes.new("ShaderNodeMath")
mul.operation = "MULTIPLY"
mul.inputs[1].default_value = 2.0
nt.links.new(sub.outputs["Value"], ab.inputs[0])
nt.links.new(ab.outputs["Value"], mul.inputs[0])
nt.links.new(mul.outputs["Value"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
em.inputs["Strength"].default_value = 1.0
nt.links.new(em.outputs["Emission"], nt.nodes["Material Output"].inputs["Surface"])
bpy.ops.mesh.primitive_plane_add(size=1)
bd = bpy.context.active_object
bd.scale = (60, 18, 1)
bd.location = (0, 45, 0)
bd.rotation_euler = (math.radians(90), 0, 0)
lib.assign(bd, bg_mat, smooth=False)

# ------------------------------------------------------------------ 루프 애니메이션
# 전부 frame 의 드라이버 식(주기 N 프레임의 정수 배) -> N+1 프레임 = 1 프레임.
# (Blender 5.2 에서는 lib.set_default_interpolation("LINEAR") 가 먹지 않아 키프레임 대신 드라이버를 쓴다.)
W = f"{math.tau!r}*(frame-1)/{N}"


def drive(obj, path, idx, expr):
    fc = obj.driver_add(path, idx)
    fc.driver.type = "SCRIPTED"
    fc.driver.expression = expr


# 떠다니는 큐브: 작은 타원 궤도 + 미세한 흔들림
for obj, (x, y, z), rot, amp, ph in floaters:
    drive(obj, "location", 0, f"{x!r}+{amp * 0.6!r}*sin({W}+{ph!r})")
    drive(obj, "location", 1, f"{y!r}+{amp * 0.4!r}*cos({W}+{ph!r})")
    drive(obj, "location", 2, f"{z!r}+{amp!r}*sin({W}+{ph * 1.7!r})")
    drive(obj, "rotation_euler", 0, f"{rot[0]!r}+0.05*sin({W}+{ph!r})")
    drive(obj, "rotation_euler", 1, f"{rot[1]!r}+0.05*cos({W}+{ph!r})")
    drive(obj, "rotation_euler", 2, f"{rot[2]!r}+0.08*sin({W})")

# 들어오는 중인 큐브: 슬롯 쪽으로 다가갔다(자세도 정렬 쪽으로) 다시 물러난다. s = 0.5-0.5cos -> 0..1..0, 주기 N
for k, (obj, slot, loc0, rot0) in enumerate(incoming):
    ph = k * math.tau / len(incoming)
    s_expr = f"(0.32*(0.5-0.5*cos({W}+{ph!r})))"
    for i in range(3):
        drive(obj, "location", i, f"{loc0[i]!r}+({slot[i] - loc0[i]!r})*{s_expr}")
        drive(obj, "rotation_euler", i, f"{rot0[i]!r}*(1-{s_expr})")

# 격자/클러스터 전체: 아주 느린 호흡(±1.2도 요, 주기 N)
drive(grid, "rotation_euler", 2, f"{math.radians(-32)!r}+{math.radians(1.2)!r}*sin({W})")
drive(clus, "rotation_euler", 2, f"{math.radians(28)!r}+{math.radians(1.5)!r}*sin({W}+2.0)")

if args.still is None and (args.start or args.end):
    scene.frame_start = args.start or 1
    scene.frame_end = args.end or N
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=True)      # 청크: 인코딩은 다 모은 뒤 따로
else:
    lib.render(args)
