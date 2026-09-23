from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def _argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def read_obj_geometry(path: Path) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif line.startswith("f "):
            indices: list[int] = []
            for token in line.split()[1:]:
                head = token.split("/", 1)[0]
                if not head:
                    continue
                value = int(head)
                index = value - 1 if value > 0 else len(vertices) + value
                indices.append(index)
            if len(indices) >= 3:
                faces.append(tuple(indices))

    if not vertices or not faces:
        raise RuntimeError(f"OBJ has no usable mesh geometry: {path}")
    return vertices, faces


def make_material(name: str, rgba: tuple[float, float, float, float]):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = rgba
    material.roughness = 0.8
    return material


def add_obj_exact(path: Path, name: str, collection: bpy.types.Collection, *, smooth: bool, material):
    vertices, faces = read_obj_geometry(path)
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj["batiforge_source"] = str(path)
    obj["batiforge_axes"] = "X east / Y north / Z up"
    obj.data.materials.append(material)

    for polygon in mesh.polygons:
        polygon.use_smooth = bool(smooth)

    return obj


def ensure_collection(name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)


def add_reference_axes() -> None:
    axes = ensure_collection("REFERENCE")
    empty = bpy.data.objects.new("BatiForge_Local_Origin", None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = 2.0
    axes.objects.link(empty)


def main() -> None:
    parser = argparse.ArgumentParser(description="Open BatiForge geometry in Blender without axis reinterpretation")
    parser.add_argument("--building", type=Path, required=True)
    parser.add_argument("--terrain", type=Path)
    parser.add_argument("--save", type=Path)
    args = parser.parse_args(_argv_after_double_dash())

    if not args.building.exists():
        raise FileNotFoundError(args.building)
    if args.terrain and not args.terrain.exists():
        raise FileNotFoundError(args.terrain)

    clear_scene()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0

    building_collection = ensure_collection("BUILDING")
    context_collection = ensure_collection("CONTEXT")
    building_mat = make_material("BatiForge_Building", (0.72, 0.72, 0.72, 1.0))
    terrain_mat = make_material("BatiForge_Terrain", (0.38, 0.38, 0.38, 1.0))

    building = add_obj_exact(
        args.building,
        "building_c070",
        building_collection,
        smooth=False,
        material=building_mat,
    )
    if args.terrain:
        add_obj_exact(
            args.terrain,
            "context_surface",
            context_collection,
            smooth=True,
            material=terrain_mat,
        )

    add_reference_axes()

    bpy.ops.object.select_all(action="DESELECT")
    building.select_set(True)
    bpy.context.view_layer.objects.active = building

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.save))

    print(f"BatiForge Blender preview loaded: {args.building}")
    if args.terrain:
        print(f"Context: {args.terrain}")
    print("Coordinates preserved numerically: X east / Y north / Z up")


if __name__ == "__main__":
    main()
