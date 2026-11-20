"""씬 공용 헬퍼: 인자 파싱, 렌더 설정, PBR 재질, 키프레임."""
import argparse
import math
import os
import sys

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEXTURE_DIR = os.path.join(ROOT, "assets", "textures")


# ---------------------------------------------------------------- 인자
def parse_args(name, frames=150, extra=None, engine="eevee"):
    """공통 인자를 파싱한다. extra(parser) 로 씬 전용 인자를 추가할 수 있다."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    if extra:
        extra(p)
    p.add_argument("--out", default=os.path.join(ROOT, "out", name))
    p.add_argument("--frames", type=int, default=frames)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--preview", action="store_true", help="절반 해상도, 낮은 샘플")
    p.add_argument("--still", type=int, default=None, help="이 프레임만 PNG로 렌더")
    p.add_argument("--engine", choices=["eevee", "cycles"], default=engine)
    return p.parse_args(argv)


# ---------------------------------------------------------------- 씬/렌더
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def setup_render(scene, args):
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 50 if args.preview else 100
    scene.render.fps = args.fps
    scene.frame_start = 1
    scene.frame_end = args.frames

    if args.engine == "cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 48 if args.preview else 256
        scene.cycles.use_denoising = True
        scene.cycles.use_adaptive_sampling = True
        _enable_gpu(scene)
        # 반사가 많은 실내에서 생기는 반짝이 노이즈(fireflies) 억제
        scene.cycles.sample_clamp_indirect = 5.0
        scene.cycles.caustics_reflective = False
        scene.cycles.caustics_refractive = False
    else:
        # Blender 4.2~4.5 는 BLENDER_EEVEE_NEXT, 그 외는 BLENDER_EEVEE
        for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = engine
                break
            except TypeError:
                continue

    scene.view_settings.view_transform = "AgX" if "AgX" in _view_transforms(scene) else "Filmic"

    if args.still is not None:
        scene.frame_set(args.still)
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = args.out + ".png"
    else:
        # 중간에 Blender 가 죽어도 이어서 렌더하도록 PNG 시퀀스로 쓰고, 끝나면 ffmpeg 로 mp4 를 만든다
        scene.render.image_settings.file_format = "PNG"
        scene.render.use_overwrite = False      # 이미 있는 프레임은 건너뜀(이어하기)
        scene.render.use_placeholder = True
        scene.render.filepath = os.path.join(args.out + "_frames", "f_")


def _enable_gpu(scene):
    """GPU 가 있으면 쓴다 (맥북 Metal, NVIDIA OptiX/CUDA 등). 없으면 조용히 CPU 로 남는다."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"):
            try:
                prefs.compute_device_type = kind
            except TypeError:
                continue
            prefs.refresh_devices() if hasattr(prefs, "refresh_devices") else prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type != "CPU"]
            if gpus:
                # Apple Silicon 은 CPU 도 같이 쓰는 편이 빠르다. RENDER_GPU_ONLY=1 이면 GPU 만 쓰고 CPU 는 비워 둔다(발열/팬 소음 완화)
                gpu_only = os.environ.get("RENDER_GPU_ONLY") == "1"
                for d in prefs.devices:
                    d.use = (d.type != "CPU") if gpu_only else True
                if gpu_only:
                    scene.render.threads_mode = "FIXED"
                    scene.render.threads = 2
                scene.cycles.device = "GPU"
                print(f"[lib] Cycles GPU: {kind} ({', '.join(d.name for d in gpus)})")
                return
        print("[lib] GPU 없음 - CPU 렌더")
    except Exception as e:  # noqa: BLE001
        print(f"[lib] GPU 설정 건너뜀: {e}")


def _view_transforms(scene):
    return [i.identifier for i in scene.view_settings.bl_rna.properties["view_transform"].enum_items]


def render(args):
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=args.still is None, write_still=args.still is not None)
    if args.still is None:
        _encode_mp4(args)


def _encode_mp4(args):
    """프레임 PNG 시퀀스를 mp4(H.264)로 묶는다. 프레임 폴더는 남겨 둔다(이어하기용)."""
    import shutil
    import subprocess
    frames_dir = args.out + "_frames"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print(f"[lib] ffmpeg 없음 - PNG 시퀀스만 남김: {frames_dir}")
        return
    missing = [f for f in range(1, args.frames + 1)
               if not os.path.exists(os.path.join(frames_dir, f"f_{f:04d}.png"))]
    if missing:
        print(f"[lib] 빠진 프레임 {len(missing)}개 - 인코딩 건너뜀: {frames_dir}")
        return
    subprocess.run([ffmpeg, "-y", "-framerate", str(args.fps), "-i", os.path.join(frames_dir, "f_%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", args.out + ".mp4"], check=True)
    print(f"[lib] Saved: {args.out}.mp4")


# ---------------------------------------------------------------- 월드/조명
def set_world(color=(0.02, 0.02, 0.03, 1.0), strength=1.0):
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = color
    bg.inputs["Strength"].default_value = strength


def add_area_light(name, location, target, energy, size=3.0, color=(1, 1, 1)):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    obj.location = location
    bpy.context.collection.objects.link(obj)
    look_at(obj, target)
    return obj


def look_at(obj, target):
    c = obj.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"


# ---------------------------------------------------------------- 재질
def set_input(bsdf, name, value):
    """Blender 버전별로 소켓 이름이 달라서, 없으면 조용히 건너뛴다."""
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = value


def make_pbr(name, base, metallic=0.0, roughness=0.5, bump=0.0, bump_scale=40.0,
             coat=0.0, emission=None):
    """절차적 PBR 재질. bump>0 이면 노이즈로 표면 질감을 준다."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    set_input(bsdf, "Base Color", base)
    set_input(bsdf, "Metallic", metallic)
    set_input(bsdf, "Roughness", roughness)
    set_input(bsdf, "Coat Weight", coat)
    if emission is not None:
        set_input(bsdf, "Emission Color", emission[:3] + (1.0,))
        set_input(bsdf, "Emission Strength", emission[3])

    if bump > 0:
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = bump_scale
        noise.inputs["Detail"].default_value = 8.0
        bnode = nt.nodes.new("ShaderNodeBump")
        bnode.inputs["Strength"].default_value = bump
        nt.links.new(noise.outputs["Fac"], bnode.inputs["Height"])
        nt.links.new(bnode.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def make_pbr_from_textures(name, folder):
    """assets/textures/<folder>/ 안의 이미지로 PBR 재질을 만든다.

    파일명에 color|basecolor|albedo, roughness, metallic, normal 이 들어가면 자동 연결.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    base_dir = os.path.join(TEXTURE_DIR, folder)

    def find(*keys):
        for f in sorted(os.listdir(base_dir)):
            if any(k in f.lower() for k in keys):
                return os.path.join(base_dir, f)
        return None

    def image_node(path, colorspace):
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(path)
        node.image.colorspace_settings.name = colorspace
        return node

    if (p := find("basecolor", "albedo", "color", "diffuse")):
        nt.links.new(image_node(p, "sRGB").outputs["Color"], bsdf.inputs["Base Color"])
    if (p := find("roughness")):
        nt.links.new(image_node(p, "Non-Color").outputs["Color"], bsdf.inputs["Roughness"])
    if (p := find("metallic", "metalness")):
        nt.links.new(image_node(p, "Non-Color").outputs["Color"], bsdf.inputs["Metallic"])
    if (p := find("normal")):
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(image_node(p, "Non-Color").outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def assign(obj, mat, smooth=True):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    if smooth:
        for poly in obj.data.polygons:
            poly.use_smooth = True


# ---------------------------------------------------------------- 키프레임
def keyframe(obj, frame, **props):
    """keyframe(obj, 10, location=(0,0,1), rotation_euler=(0,0,0))"""
    for path, value in props.items():
        setattr(obj, path, value)
        obj.keyframe_insert(data_path=path, frame=frame)


def set_default_interpolation(kind):
    """이후 삽입되는 키프레임의 보간 방식 (LINEAR | BEZIER). 버전 무관하게 동작."""
    bpy.context.preferences.edit.keyframe_new_interpolation_type = kind


def deg(x):
    return math.radians(x)


# ---------------------------------------------------------------- 에셋 (Poly Haven 등)
def make_tiled_pbr(name, folder, tile=1.0, tint=None, normal_strength=1.0, rough_scale=1.0):
    """assets/textures/<folder>/ 의 맵을 '미터 단위로 타일링'해서 쓰는 PBR 재질.

    오브젝트 좌표 + 박스 투영이라 UV 가 없어도 모든 면에 늘어짐 없이 붙는다.
    (도형은 scale 이 적용된 상태여야 한다 - lib.box 가 그렇게 만든다.)
    tile: 텍스처 한 장이 덮는 실제 크기(m). tint: 색을 곱해서 톤을 바꾼다.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    base_dir = os.path.join(TEXTURE_DIR, folder)

    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1 / tile,) * 3
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    def find(key):
        for f in sorted(os.listdir(base_dir)):
            if key in f.lower():
                return os.path.join(base_dir, f)
        return None

    def image(key, colorspace):
        path = find(key)
        if path is None:
            return None
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(path, check_existing=True)
        node.image.colorspace_settings.name = colorspace
        node.projection = "BOX"
        node.projection_blend = 0.25
        nt.links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    diffuse = image("diffuse", "sRGB")
    if diffuse:
        color_out = diffuse.outputs["Color"]
        if tint is not None:
            mix = nt.nodes.new("ShaderNodeMixRGB")
            mix.blend_type = "MULTIPLY"
            mix.inputs["Fac"].default_value = 1.0
            mix.inputs["Color2"].default_value = tint
            nt.links.new(color_out, mix.inputs["Color1"])
            color_out = mix.outputs["Color"]
        nt.links.new(color_out, bsdf.inputs["Base Color"])

    rough = image("roughness", "Non-Color")
    if rough:
        out = rough.outputs["Color"]
        if rough_scale != 1.0:
            math_node = nt.nodes.new("ShaderNodeMath")
            math_node.operation = "MULTIPLY"
            math_node.use_clamp = True
            math_node.inputs[1].default_value = rough_scale
            nt.links.new(out, math_node.inputs[0])
            out = math_node.outputs["Value"]
        nt.links.new(out, bsdf.inputs["Roughness"])

    metal = image("metallic", "Non-Color")
    if metal:
        nt.links.new(metal.outputs["Color"], bsdf.inputs["Metallic"])

    normal = image("normal", "Non-Color")
    if normal:
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = normal_strength
        nt.links.new(normal.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def import_kit(model_id):
    """모듈형 키트를 가져와 {부품이름 접미사: 오브젝트} 로 돌려준다 (씬에는 원본이 남는다)."""
    path = os.path.join(ROOT, "assets", "models", model_id, f"{model_id}.gltf")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    return {o.name.replace(model_id + "_", ""): o for o in new if o.type == "MESH"}, new


def world_center(obj):
    from mathutils import Vector
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return Vector([(min(p[i] for p in pts) + max(p[i] for p in pts)) / 2 for i in range(3)])


def instance(src, center, parent=None, rot_z_deg=0.0):
    """키트 부품 src 의 복제(메시 공유)를 만들어 바운딩박스 중심이 center 에 오게 놓는다."""
    from mathutils import Vector
    new = src.copy()
    bpy.context.collection.objects.link(new)
    new.parent = None
    new.matrix_world = src.matrix_world
    new.location += Vector(center) - world_center(src)
    if rot_z_deg:
        new.rotation_euler.rotate_axis("Z", math.radians(rot_z_deg))
    if parent is not None:
        new.parent = parent
    return new


def import_model(model_id, name=None, loc=(0, 0, 0), rot=(0, 0, 0), scale=1.0):
    """assets/models/<id>/<id>.gltf 를 가져와 하나의 그룹(빈 오브젝트) 아래로 묶는다.

    fly_in 등으로 그룹 전체를 움직일 수 있다. 반환: (그룹, 가져온 오브젝트 목록)
    """
    path = os.path.join(ROOT, "assets", "models", model_id, f"{model_id}.gltf")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    root = group(name or model_id, loc)
    for o in new:
        if o.parent is None or o.parent not in new:
            o.parent = root
    root.rotation_euler = rot
    root.scale = (scale,) * 3
    return root, new


# ---------------------------------------------------------------- 도형 (만화풍 디오라마용)
def group(name, loc=(0, 0, 0)):
    """여러 도형을 묶어서 한 번에 움직이기 위한 빈 오브젝트."""
    obj = bpy.data.objects.new(name, None)
    obj.location = loc
    bpy.context.collection.objects.link(obj)
    return obj


def _finish(obj, name, mat, parent, bevel):
    obj.name = name
    assign(obj, mat)
    if bevel > 0:
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 3
    if parent is not None:
        obj.parent = parent  # 부모 기준 로컬 좌표로 해석된다
    return obj


def box(name, size, loc, mat, parent=None, bevel=0.06):
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.active_object
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.location = loc
    return _finish(obj, name, mat, parent, bevel)


def cyl(name, radius, depth, loc, mat, parent=None, rot=(0, 0, 0), bevel=0.03, verts=48):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, vertices=verts)
    obj = bpy.context.active_object
    obj.location = loc
    obj.rotation_euler = rot
    return _finish(obj, name, mat, parent, bevel)


def cone(name, radius, depth, loc, mat, parent=None, verts=32):
    bpy.ops.mesh.primitive_cone_add(radius1=radius, depth=depth, vertices=verts)
    obj = bpy.context.active_object
    obj.location = loc
    return _finish(obj, name, mat, parent, 0.0)


def ball(name, radius, loc, mat, parent=None, scale=(1, 1, 1)):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, segments=32, ring_count=16)
    obj = bpy.context.active_object
    obj.location = loc
    obj.scale = scale
    return _finish(obj, name, mat, parent, 0.0)


# ---------------------------------------------------------------- 만화풍 룩
def enable_outline(scene, thickness=2.0, color=(0.04, 0.04, 0.07)):
    """Freestyle 외곽선. EEVEE/Cycles 둘 다 동작."""
    scene.render.use_freestyle = True
    scene.render.line_thickness_mode = "ABSOLUTE"
    scene.render.line_thickness = thickness
    vl = scene.view_layers[0]
    vl.use_freestyle = True
    fs = vl.freestyle_settings
    lineset = fs.linesets[0] if len(fs.linesets) else fs.linesets.new("outline")
    if lineset.linestyle is None:  # 빈 파일에서는 linestyle 이 비어 있다
        lineset.linestyle = bpy.data.linestyles.new("outline")
    lineset.linestyle.color = color


def add_sun(name, rotation_deg, energy=3.0, color=(1.0, 0.96, 0.88)):
    data = bpy.data.lights.new(name, "SUN")
    data.energy = energy
    data.color = color
    obj = bpy.data.objects.new(name, data)
    obj.rotation_euler = tuple(deg(a) for a in rotation_deg)
    bpy.context.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------- 조립 모션
def fly_in(obj, start, duration, offset, spin_deg=(0, 0, 0), squash=True):
    """흩어진 위치(offset, spin)에서 대기하다가 start 에 날아와 제자리에 조립된다.

    착지 순간에 살짝 눌렸다 펴지는(squash) 스케일로 만화 같은 느낌을 준다.
    실사풍 씬은 squash=False 로 끈다 (크기 변화 없이 감속하며 내려앉는다).
    키프레임 직전의 현재 location/rotation/scale 이 '조립된 상태'로 간주된다.
    """
    rest_loc = tuple(obj.location)
    rest_rot = tuple(obj.rotation_euler)
    away_loc = tuple(a + b for a, b in zip(rest_loc, offset))
    away_rot = tuple(a + deg(b) for a, b in zip(rest_rot, spin_deg))
    land = start + int(duration * 0.7)
    end = start + duration

    keyframe(obj, 1, location=away_loc, rotation_euler=away_rot, scale=(1, 1, 1))
    keyframe(obj, start, location=away_loc, rotation_euler=away_rot, scale=(1, 1, 1))
    keyframe(obj, land, location=rest_loc, rotation_euler=rest_rot, scale=(1.12, 1.12, 0.86) if squash else (1, 1, 1))
    keyframe(obj, end, location=rest_loc, rotation_euler=rest_rot, scale=(1, 1, 1))


def drift(obj, frames, dx=0.0, dy=0.0):
    """구름처럼 천천히 흘러가는 직선 이동."""
    set_default_interpolation("LINEAR")
    x, y, z = obj.location
    keyframe(obj, 1, location=(x, y, z))
    keyframe(obj, frames, location=(x + dx, y + dy, z))
    set_default_interpolation("BEZIER")


# ---------------------------------------------------------------- 에셋 (Sketchfab 등 크기/방향이 제각각인 모델)
def load_template(uid, height, subdir="sketchfab"):
    """assets/models/<subdir>/<uid>/scene.gltf 를 가져와 '높이 height(m), 바닥 z=0, xy 중심 0' 으로 정규화할 행렬을 계산한다.

    원본은 템플릿으로 남는다. place_template 으로 메시를 공유한 인스턴스를 만들고,
    다 만든 뒤 drop_template 으로 원본을 지운다. glTF 는 앞면이 -Y 를 향한다고 가정.
    """
    from mathutils import Matrix, Vector
    path = os.path.join(ROOT, "assets", "models", subdir, uid, "scene.gltf")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    bpy.context.view_layer.update()
    meshes = [o for o in new if o.type == "MESH"]
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    s = height / (hi.z - lo.z)
    norm = Matrix.Diagonal((s, s, s, 1.0)) @ Matrix.Translation(
        (-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))
    return dict(meshes=meshes, all=new, norm=norm, size=(hi - lo) * s)


def place_template(tpl, parent):
    """템플릿의 모든 메시를 parent(빈 오브젝트) 아래에 복제한다 (메시 데이터 공유)."""
    from mathutils import Matrix
    for src in tpl["meshes"]:
        n = src.copy()
        bpy.context.collection.objects.link(n)
        n.parent = parent
        n.matrix_parent_inverse = Matrix.Identity(4)
        n.matrix_basis = tpl["norm"] @ src.matrix_world


def drop_template(tpl):
    for o in tpl["all"]:
        bpy.data.objects.remove(o, do_unlink=True)
