from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Build a BatiForge Blender validation scene")
    parser.add_argument("--building", type=Path, required=True)
    parser.add_argument("--terrain", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output-blend", type=Path, required=True)
    parser.add_argument("--output-render", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)
    root = bpy.context.scene.collection
    default = bpy.data.collections.get("Collection")
    if default is not None:
        for obj in list(default.objects):
            default.objects.unlink(obj)
        if default.name in root.children:
            root.children.unlink(default)
        bpy.data.collections.remove(default)


def new_collection(name: str, color_tag: str | None = None) -> bpy.types.Collection:
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    if color_tag and hasattr(collection, "color_tag"):
        collection.color_tag = color_tag
    return collection


def move_objects(objects: list[bpy.types.Object], collection: bpy.types.Collection) -> None:
    for obj in objects:
        for old in list(obj.users_collection):
            old.objects.unlink(obj)
        collection.objects.link(obj)


def import_obj(path: Path, collection: bpy.types.Collection, role: str, smooth: bool) -> list[bpy.types.Object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    before = set(bpy.data.objects)
    try:
        bpy.ops.wm.obj_import(
            filepath=str(path),
            forward_axis="Y",
            up_axis="Z",
            use_split_objects=True,
            use_split_groups=False,
            validate_meshes=True,
        )
    except TypeError:
        bpy.ops.wm.obj_import(filepath=str(path))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    if not imported:
        raise RuntimeError(f"Blender imported no objects from {path}")
    move_objects(imported, collection)
    for i, obj in enumerate(imported, start=1):
        obj.name = f"{role}_{i:02d}"
        obj["batiforge_role"] = role
        obj["batiforge_source"] = str(path)
        if obj.type == "MESH":
            for polygon in obj.data.polygons:
                polygon.use_smooth = smooth
    return imported


def material(name: str, base_color: tuple[float, float, float, float], roughness: float) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = base_color
        principled.inputs["Roughness"].default_value = roughness
    return mat


def ensure_material(objects: list[bpy.types.Object], mat: bpy.types.Material, only_if_empty: bool) -> None:
    for obj in objects:
        if obj.type != "MESH":
            continue
        if only_if_empty and len(obj.data.materials):
            continue
        obj.data.materials.clear()
        obj.data.materials.append(mat)


def bbox(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points: list[Vector] = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        raise RuntimeError("No mesh bounds available")
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return lo, hi


def add_camera_and_lights(objects: list[bpy.types.Object], collection: bpy.types.Collection) -> bpy.types.Object:
    lo, hi = bbox(objects)
    center = (lo + hi) * 0.5
    size = hi - lo
    horizontal = max(size.x, size.y, 1.0)
    vertical = max(size.z, 1.0)

    camera_data = bpy.data.cameras.new("BatiForge_Camera")
    camera = bpy.data.objects.new("BatiForge_Camera", camera_data)
    collection.objects.link(camera)
    camera_data.lens = 52.0
    camera_data.sensor_width = 36.0
    camera_data.clip_start = 0.05
    camera_data.clip_end = 5000.0
    distance = max(horizontal * 1.35, vertical * 4.5)
    camera.location = center + Vector((distance * 0.72, -distance, max(vertical * 1.8, distance * 0.48)))
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera

    sun_data = bpy.data.lights.new("BatiForge_Sun", type="SUN")
    sun = bpy.data.objects.new("BatiForge_Sun", sun_data)
    collection.objects.link(sun)
    sun.rotation_euler = (math.radians(28.0), math.radians(-18.0), math.radians(32.0))
    sun_data.energy = 2.0
    sun_data.angle = math.radians(18.0)

    area_data = bpy.data.lights.new("BatiForge_Fill", type="AREA")
    area = bpy.data.objects.new("BatiForge_Fill", area_data)
    collection.objects.link(area)
    area.location = center + Vector((-horizontal * 0.35, -horizontal * 0.1, horizontal * 0.85))
    area.rotation_euler = (center - area.location).to_track_quat("-Z", "Y").to_euler()
    area_data.energy = 1100.0
    area_data.shape = "DISK"
    area_data.size = max(horizontal * 0.8, 10.0)

    return camera


def configure_scene(output_render: Path) -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        pass
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output_render)
    scene.render.film_transparent = False
    scene.world.color = (0.035, 0.035, 0.045)
    if hasattr(scene, "view_settings"):
        try:
            scene.view_settings.look = "AgX - Medium High Contrast"
        except Exception:
            pass


def evidence_images(directory: Path) -> list[Path]:
    extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".webp"}
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in extensions)


def main() -> None:
    args = parse_args()
    args.output_blend.parent.mkdir(parents=True, exist_ok=True)
    args.output_render.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)

    clear_scene()
    terrain_collection = new_collection("01_SITE_TERRAIN", "COLOR_05")
    building_collection = new_collection("02_BUILDING_CORE", "COLOR_03")
    facade_collection = new_collection("03_FACADE_WORK", "COLOR_02")
    reference_collection = new_collection("04_FACADE_EVIDENCE", "COLOR_04")
    helper_collection = new_collection("90_HELPERS", "COLOR_08")

    terrain = import_obj(args.terrain.resolve(), terrain_collection, "terrain", smooth=True)
    building = import_obj(args.building.resolve(), building_collection, "building_core", smooth=False)

    terrain_mat = material("MAT_Terrain_Fallback", (0.30, 0.32, 0.30, 1.0), 0.92)
    building_mat = material("MAT_Building_Core", (0.72, 0.74, 0.78, 1.0), 0.72)
    ensure_material(terrain, terrain_mat, only_if_empty=True)
    ensure_material(building, building_mat, only_if_empty=False)

    work_origin = bpy.data.objects.new("FACADE_WORK_ORIGIN", None)
    facade_collection.objects.link(work_origin)
    work_origin.empty_display_type = "PLAIN_AXES"
    work_origin.empty_display_size = 2.0
    work_origin["batiforge_role"] = "facade_work_origin"

    photos = evidence_images(args.evidence_dir)
    reference_anchor = bpy.data.objects.new("FACADE_EVIDENCE_NOT_CALIBRATED", None)
    reference_collection.objects.link(reference_anchor)
    reference_anchor.empty_display_type = "CIRCLE"
    reference_anchor.empty_display_size = 1.5
    reference_anchor["photo_count"] = len(photos)
    reference_anchor["note"] = "Photos remain unplaced until COLMAP/metric registration."

    all_geometry = terrain + building
    add_camera_and_lights(all_geometry, helper_collection)
    configure_scene(args.output_render.resolve())

    lo, hi = bbox(all_geometry)
    scene = bpy.context.scene
    scene["batiforge_building_source"] = str(args.building.resolve())
    scene["batiforge_terrain_source"] = str(args.terrain.resolve())
    scene["batiforge_facade_evidence_dir"] = str(args.evidence_dir.resolve())
    scene["batiforge_facade_evidence_count"] = len(photos)
    scene["batiforge_axes"] = "X east / Y north / Z up"

    bpy.ops.wm.save_as_mainfile(filepath=str(args.output_blend.resolve()))
    bpy.ops.render.render(write_still=True)

    manifest = {
        "schema_version": 1,
        "building_obj": str(args.building.resolve()),
        "terrain_obj": str(args.terrain.resolve()),
        "facade_evidence_dir": str(args.evidence_dir.resolve()),
        "facade_evidence_photo_count": len(photos),
        "facade_evidence_files": [str(path.resolve()) for path in photos],
        "output_blend": str(args.output_blend.resolve()),
        "output_render": str(args.output_render.resolve()),
        "local_axes": "X east / Y north / Z up",
        "bbox_local": {
            "min": [float(lo.x), float(lo.y), float(lo.z)],
            "max": [float(hi.x), float(hi.y), float(hi.z)],
        },
        "collections": [
            "01_SITE_TERRAIN",
            "02_BUILDING_CORE",
            "03_FACADE_WORK",
            "04_FACADE_EVIDENCE",
            "90_HELPERS",
        ],
        "evidence_status": "registered" if False else "awaiting_metric_registration",
    }
    args.output_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"blend: {args.output_blend}")
    print(f"preview: {args.output_render}")
    print(f"manifest: {args.output_manifest}")
    print(f"facade evidence photos: {len(photos)}")


if __name__ == "__main__":
    main()
