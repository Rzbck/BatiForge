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
    parser = argparse.ArgumentParser(description="Visualize ranked facade opening candidates in Blender")
    parser.add_argument("--base-blend", type=Path, required=True)
    parser.add_argument("--candidates-json", type=Path, required=True)
    parser.add_argument("--candidate-index", type=int, default=1)
    parser.add_argument("--output-blend", type=Path, required=True)
    parser.add_argument("--output-render", type=Path, required=True)
    return parser.parse_args(argv)


def material(name: str, rgba: tuple[float, float, float, float], emission_strength: float = 0.0) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if principled is not None:
        principled.inputs["Base Color"].default_value = rgba
        principled.inputs["Roughness"].default_value = 0.4
        if "Emission Color" in principled.inputs:
            principled.inputs["Emission Color"].default_value = rgba
            principled.inputs["Emission Strength"].default_value = emission_strength
    return mat


def remove_collection(name: str) -> None:
    collection = bpy.data.collections.get(name)
    if collection is None:
        return
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)


def collection_bbox_center(name: str) -> Vector:
    collection = bpy.data.collections.get(name)
    if collection is None:
        return Vector((0.0, 0.0, 0.0))
    points: list[Vector] = []
    for obj in collection.all_objects:
        if obj.type != "MESH":
            continue
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        return Vector((0.0, 0.0, 0.0))
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return (lo + hi) * 0.5


def exterior_normal(wall_center: Vector, normal_xy: tuple[float, float], building_center: Vector) -> tuple[float, float]:
    nx, ny = normal_xy
    outward = Vector((wall_center.x - building_center.x, wall_center.y - building_center.y, 0.0))
    if outward.length > 1e-9 and outward.dot(Vector((nx, ny, 0.0))) < 0.0:
        nx, ny = -nx, -ny
    return nx, ny


def add_candidate_panel(
    collection: bpy.types.Collection,
    opening: dict,
    normal_xy: tuple[float, float],
    u_axis_xy: tuple[float, float],
    mat: bpy.types.Material,
    index: int,
) -> bpy.types.Object:
    nx, ny = normal_xy
    ux, uy = u_axis_xy
    center = Vector(opening["center_xyz"])
    center += Vector((nx, ny, 0.0)) * 0.12

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = bpy.context.object
    assert obj is not None
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    collection.objects.link(obj)

    obj.name = f"opening_{opening['class']}_{index:02d}"
    obj.dimensions = (
        max(0.08, float(opening["width_m"])),
        0.12,
        max(0.08, float(opening["height_m"])),
    )
    angle = math.atan2(uy, ux)
    obj.rotation_euler = (0.0, 0.0, angle)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.select_set(False)
    obj.data.materials.append(mat)
    obj["batiforge_role"] = "facade_opening_candidate"
    obj["opening_class"] = opening["class"]
    obj["mean_confidence"] = float(opening.get("mean_confidence", 0.0))
    obj["source_bbox_px"] = json.dumps(opening.get("bbox_px", []))
    return obj


def point_camera_at(camera: bpy.types.Object, target: Vector) -> None:
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def main() -> None:
    args = parse_args()
    if not args.base_blend.is_file():
        raise FileNotFoundError(args.base_blend)
    if not args.candidates_json.is_file():
        raise FileNotFoundError(args.candidates_json)

    bpy.ops.wm.open_mainfile(filepath=str(args.base_blend.resolve()))
    data = json.loads(args.candidates_json.read_text(encoding="utf-8"))
    mappings = data.get("candidate_mappings", [])
    if not mappings:
        raise RuntimeError("No candidate mappings in JSON")
    candidate_index = max(1, min(int(args.candidate_index), len(mappings)))
    mapping = mappings[candidate_index - 1]
    wall = mapping["wall"]

    remove_collection("05_FACADE_OPENING_CANDIDATES")
    collection = bpy.data.collections.new("05_FACADE_OPENING_CANDIDATES")
    bpy.context.scene.collection.children.link(collection)
    if hasattr(collection, "color_tag"):
        collection.color_tag = "COLOR_01"

    window_mat = material("MAT_Candidate_Window", (0.05, 0.55, 1.0, 1.0), 0.15)
    door_mat = material("MAT_Candidate_Door", (1.0, 0.34, 0.04, 1.0), 0.15)
    balcony_mat = material("MAT_Candidate_Balcony", (0.8, 0.1, 0.95, 1.0), 0.15)
    mats = {"window": window_mat, "door": door_mat, "balcony": balcony_mat}

    wall_center = Vector(wall["centroid_xyz"])
    building_center = collection_bbox_center("02_BUILDING_CORE")
    raw_normal = tuple(float(v) for v in wall["normal_xy"])
    normal_xy = exterior_normal(wall_center, raw_normal, building_center)
    u_axis_xy = tuple(float(v) for v in wall["u_axis_xy"])

    for i, opening in enumerate(mapping.get("openings", []), start=1):
        add_candidate_panel(
            collection,
            opening,
            normal_xy,
            u_axis_xy,
            mats.get(opening["class"], window_mat),
            i,
        )

    label = bpy.data.objects.new("FACADE_CANDIDATE_INFO", None)
    collection.objects.link(label)
    label["candidate_id"] = mapping["candidate_id"]
    label["aspect_score"] = float(mapping["aspect_score"])
    label["status"] = "EXPERIMENTAL_NOT_METRICALLY_ACCEPTED"
    label["source_image"] = data["source_image"]
    label["camera_side"] = "building_exterior"

    camera = bpy.data.objects.get("BatiForge_Camera")
    if camera is None or camera.type != "CAMERA":
        camera_data = bpy.data.cameras.new("BatiForge_Camera")
        camera = bpy.data.objects.new("BatiForge_Camera", camera_data)
        bpy.context.scene.collection.objects.link(camera)
        bpy.context.scene.camera = camera

    nx, ny = normal_xy
    width = float(wall["width_m"])
    height = float(wall["height_m"])
    distance = max(width, height) * 1.45 + 8.0
    target = wall_center
    camera.location = target + Vector((nx, ny, 0.0)) * distance + Vector((0.0, 0.0, max(1.2, height * 0.10)))
    point_camera_at(camera, target)
    camera.data.type = "PERSP"
    camera.data.lens = 58.0
    camera.data.sensor_width = 36.0
    camera.data.clip_start = 0.05
    camera.data.clip_end = 5000.0
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(args.output_render.resolve())
    scene["batiforge_facade_candidate_id"] = mapping["candidate_id"]
    scene["batiforge_facade_candidate_index"] = candidate_index
    scene["batiforge_facade_candidate_status"] = "EXPERIMENTAL_NOT_METRICALLY_ACCEPTED"
    scene["batiforge_facade_camera_side"] = "building_exterior"

    args.output_blend.parent.mkdir(parents=True, exist_ok=True)
    args.output_render.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output_blend.resolve()))
    bpy.ops.render.render(write_still=True)
    print(f"candidate: {mapping['candidate_id']}")
    print(f"opening panels: {len(mapping.get('openings', []))}")
    print(f"camera side: building exterior")
    print(f"blend: {args.output_blend}")
    print(f"render: {args.output_render}")


if __name__ == "__main__":
    main()
