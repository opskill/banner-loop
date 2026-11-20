"""Shared scene helpers: argument parsing, render setup, PBR materials, keyframes."""
import argparse
import math
import os
import sys

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEXTURE_DIR = os.path.join(ROOT, "assets", "textures")


def _texture_dir(folder):
    """assets/textures/<folder>, or a clear error if the textures were never downloaded."""
    d = os.path.join(TEXTURE_DIR, folder)
    if not os.path.isdir(d) or not os.listdir(d):
        raise FileNotFoundError(f"textures missing — run `npm run assets` (expected {d})")
    return d


# ---------------------------------------------------------------- arguments
def parse_args(name, frames=150, extra=None, engine="eevee"):
    """Parse the common arguments. extra(parser) can add scene-specific ones."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    if extra:
        extra(p)
    p.add_argument("--out", default=os.path.join(ROOT, "out", name))
    p.add_argument("--frames", type=int, default=frames)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--preview", action="store_true", help="half resolution, low samples")
    p.add_argument("--still", type=int, default=None, help="render only this frame as PNG")
    p.add_argument("--engine", choices=["eevee", "cycles"], default=engine)
    return p.parse_args(argv)


# ---------------------------------------------------------------- scene / render
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
        # suppress sparkle noise (fireflies) in reflective interiors
        scene.cycles.sample_clamp_indirect = 5.0
        scene.cycles.caustics_reflective = False
        scene.cycles.caustics_refractive = False
    else:
        # Blender 4.2-4.5 uses BLENDER_EEVEE_NEXT, everything else BLENDER_EEVEE
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
        # write a PNG sequence so rendering can resume if Blender dies midway, then build the mp4 with ffmpeg at the end
        scene.render.image_settings.file_format = "PNG"
        scene.render.use_overwrite = False      # skip frames that already exist (resume)
        scene.render.use_placeholder = True
        scene.render.filepath = os.path.join(args.out + "_frames", "f_")


def _enable_gpu(scene):
    """Use the GPU if there is one (MacBook Metal, NVIDIA OptiX/CUDA, etc.). Otherwise quietly stay on CPU."""
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
                # On Apple Silicon, using the CPU too is usually faster. With RENDER_GPU_ONLY=1
                # only the GPU is used and the CPU is left idle (less heat/fan noise)
                gpu_only = os.environ.get("RENDER_GPU_ONLY") == "1"
                for d in prefs.devices:
                    d.use = (d.type != "CPU") if gpu_only else True
                if gpu_only:
                    scene.render.threads_mode = "FIXED"
                    scene.render.threads = 2
                scene.cycles.device = "GPU"
                print(f"[lib] Cycles GPU: {kind} ({', '.join(d.name for d in gpus)})")
                return
        print("[lib] no GPU - CPU render")
    except Exception as e:  # noqa: BLE001
        print(f"[lib] GPU setup skipped: {e}")


def _view_transforms(scene):
    return [i.identifier for i in scene.view_settings.bl_rna.properties["view_transform"].enum_items]


def render(args):
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    bpy.ops.render.render(animation=args.still is None, write_still=args.still is not None)
    if args.still is None:
        _encode_mp4(args)


def _encode_mp4(args):
    """Encode the PNG frame sequence into an mp4 (H.264). The frames folder is kept (for resuming)."""
    import shutil
    import subprocess
    frames_dir = args.out + "_frames"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print(f"[lib] no ffmpeg - leaving only the PNG sequence: {frames_dir}")
        return
    missing = [f for f in range(1, args.frames + 1)
               if not os.path.exists(os.path.join(frames_dir, f"f_{f:04d}.png"))]
    if missing:
        print(f"[lib] missing {len(missing)} frames - skipping encode: {frames_dir}")
        return
    subprocess.run([ffmpeg, "-y", "-framerate", str(args.fps), "-i", os.path.join(frames_dir, "f_%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", args.out + ".mp4"], check=True)
    print(f"[lib] Saved: {args.out}.mp4")


# ---------------------------------------------------------------- world / lighting
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


# ---------------------------------------------------------------- materials
def set_input(bsdf, name, value):
    """Socket names differ between Blender versions, so skip quietly if missing."""
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = value


def make_pbr(name, base, metallic=0.0, roughness=0.5, bump=0.0, bump_scale=40.0,
             coat=0.0, emission=None):
    """Procedural PBR material. With bump>0, noise adds surface texture."""
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
    """Build a PBR material from the images in assets/textures/<folder>/.

    Files whose names contain color|basecolor|albedo, roughness, metallic, normal are linked automatically.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    base_dir = _texture_dir(folder)

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


# ---------------------------------------------------------------- keyframes
def keyframe(obj, frame, **props):
    """keyframe(obj, 10, location=(0,0,1), rotation_euler=(0,0,0))"""
    for path, value in props.items():
        setattr(obj, path, value)
        obj.keyframe_insert(data_path=path, frame=frame)


def set_default_interpolation(kind):
    """Interpolation mode for keyframes inserted afterwards (LINEAR | BEZIER). Works across versions."""
    bpy.context.preferences.edit.keyframe_new_interpolation_type = kind


def deg(x):
    return math.radians(x)


# ---------------------------------------------------------------- assets (Poly Haven etc.)
def make_tiled_pbr(name, folder, tile=1.0, tint=None, normal_strength=1.0, rough_scale=1.0):
    """PBR material that uses the maps in assets/textures/<folder>/ 'tiled in metres'.

    Object coordinates + box projection, so it sticks to every face without stretching even with no UVs.
    (Shapes must have scale applied - lib.box builds them that way.)
    tile: real-world size covered by one texture tile (m). tint: multiplies the colour to shift the tone.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    base_dir = _texture_dir(folder)

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
    """Import a modular kit and return {part-name suffix: object} (the originals stay in the scene)."""
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
    """Make a copy (shared mesh) of kit part src and place it so its bounding-box centre lands on center."""
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
    """Import assets/models/<id>/<id>.gltf and gather it under one group (empty object).

    The whole group can then be moved with fly_in etc. Returns: (group, list of imported objects)
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


# ---------------------------------------------------------------- shapes (for the cartoon diorama)
def group(name, loc=(0, 0, 0)):
    """Empty object for grouping several shapes so they move together."""
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
        obj.parent = parent  # interpreted as local coordinates relative to the parent
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


# ---------------------------------------------------------------- cartoon look
def enable_outline(scene, thickness=2.0, color=(0.04, 0.04, 0.07)):
    """Freestyle outlines. Works with both EEVEE and Cycles."""
    scene.render.use_freestyle = True
    scene.render.line_thickness_mode = "ABSOLUTE"
    scene.render.line_thickness = thickness
    vl = scene.view_layers[0]
    vl.use_freestyle = True
    fs = vl.freestyle_settings
    lineset = fs.linesets[0] if len(fs.linesets) else fs.linesets.new("outline")
    if lineset.linestyle is None:  # in an empty file, linestyle is None
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


# ---------------------------------------------------------------- assembly motion
def fly_in(obj, start, duration, offset, spin_deg=(0, 0, 0), squash=True):
    """Waits at a scattered position (offset, spin), flies in at start and assembles in place.

    A scale that squashes slightly on landing and springs back gives a cartoon feel.
    Photoreal scenes turn it off with squash=False (they decelerate and settle with no size change).
    The current location/rotation/scale just before keyframing is treated as the 'assembled state'.
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
    """Straight-line motion that drifts slowly like a cloud."""
    set_default_interpolation("LINEAR")
    x, y, z = obj.location
    keyframe(obj, 1, location=(x, y, z))
    keyframe(obj, frames, location=(x + dx, y + dy, z))
    set_default_interpolation("BEZIER")


# ---------------------------------------------------------------- assets (Sketchfab etc., models of arbitrary size/orientation)
def load_template(uid, height, subdir="sketchfab"):
    """Import assets/models/<subdir>/<uid>/scene.gltf and compute the matrix that normalizes it to 'height height (m), floor z=0, xy centre 0'.

    The original stays as a template. place_template makes instances that share the mesh,
    and drop_template deletes the original when done. Assumes the glTF front faces -Y.
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
    """Copy every mesh of the template under parent (an empty object) (mesh data shared)."""
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
