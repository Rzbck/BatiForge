from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--base-blend", type=Path, required=True)
    p.add_argument("--detail-json", type=Path, required=True)
    p.add_argument("--output-blend", type=Path, required=True)
    p.add_argument("--overview", type=Path, required=True)
    p.add_argument("--front", type=Path, required=True)
    p.add_argument("--side", type=Path, required=True)
    return p.parse_args(argv)


def mat(name: str, rgba: tuple[float,float,float,float], roughness: float = 0.45, metallic: float = 0.0) -> bpy.types.Material:
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = rgba
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
    return m


def clear_collection(name: str) -> bpy.types.Collection:
    old = bpy.data.collections.get(name)
    if old:
        for o in list(old.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(old)
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def point3(op: dict, du: float, dz: float, offset: float) -> tuple[float,float,float]:
    plane = op["plane"]
    n = plane["normal_xy"]
    out = plane["outward_normal_xy"]
    uax = plane["u_axis_xy"]
    d = float(plane["d"])
    u = float(op["u_center"]) + float(du)
    z = float(op["z_center"]) + float(dz)
    x = float(n[0]) * d + float(uax[0]) * u + float(out[0]) * offset
    y = float(n[1]) * d + float(uax[1]) * u + float(out[1]) * offset
    return (x,y,z)


def add_polygon_fill(collection: bpy.types.Collection, op: dict, material: bpy.types.Material, offset: float, name: str) -> bpy.types.Object:
    poly = op["polygon_local_uz"]
    verts = [point3(op, p[0], p[1], offset) for p in poly]
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], [list(range(len(verts)))])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def add_frame(collection: bpy.types.Collection, op: dict, material: bpy.types.Material, offset: float, scale: float = 1.12) -> bpy.types.Object:
    inner = [(float(p[0]),float(p[1])) for p in op["polygon_local_uz"]]
    outer = [(u*scale,z*scale) for u,z in inner]
    verts = [point3(op,u,z,offset) for u,z in outer] + [point3(op,u,z,offset+0.018) for u,z in inner]
    n = len(inner)
    faces = []
    for i in range(n):
        j = (i+1)%n
        faces.append((i,j,n+j,n+i))
    mesh = bpy.data.meshes.new(op["id"] + "_frame_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(op["id"] + "_frame", mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def add_mullion(collection: bpy.types.Collection, op: dict, frac: float, material: bpy.types.Material) -> None:
    width = float(op["width_m"])
    height = float(op["height_m"])
    u = (frac - 0.5) * width * 0.72
    z = -height * 0.08
    w = max(0.045, width * 0.035)
    h = height * 0.72
    poly = [(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)]
    temp = dict(op)
    temp["u_center"] = float(op["u_center"]) + u
    temp["z_center"] = float(op["z_center"]) + z
    temp["polygon_local_uz"] = poly
    add_polygon_fill(collection,temp,material,0.075,op["id"]+f"_mullion_{int(frac*100):02d}")


def camera() -> bpy.types.Object:
    c = bpy.data.objects.get("BatiForge_Camera")
    if c is None or c.type != "CAMERA":
        cd = bpy.data.cameras.new("BatiForge_Camera")
        c = bpy.data.objects.new("BatiForge_Camera",cd)
        bpy.context.scene.collection.objects.link(c)
    bpy.context.scene.camera = c
    return c


def aim(c: bpy.types.Object, target: Vector) -> None:
    c.rotation_euler = (target-c.location).to_track_quat("-Z","Y").to_euler()


def region_center(data: dict, region_id: str) -> Vector:
    ops = [o for o in data["openings"] if o["region"] == region_id]
    if not ops:
        return Vector((0,0,5))
    pts=[]
    for o in ops:
        p=point3(o,0,0,0)
        pts.append(Vector(p))
    return sum(pts,Vector())/len(pts)


def outward(data: dict, region_id: str) -> Vector:
    op = next(o for o in data["openings"] if o["region"] == region_id)
    n = op["plane"]["outward_normal_xy"]
    return Vector((float(n[0]),float(n[1]),0.0)).normalized()


def render(path: Path) -> None:
    scene=bpy.context.scene
    scene.render.resolution_x=1400
    scene.render.resolution_y=1000
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format="PNG"
    scene.render.filepath=str(path.resolve())
    bpy.ops.render.render(write_still=True)


def main() -> None:
    a=args()
    bpy.ops.wm.open_mainfile(filepath=str(a.base_blend.resolve()))
    data=json.loads(a.detail_json.read_text(encoding="utf-8"))

    for name in ("05_FACADE_OPENING_CANDIDATES","06_FACADE_DETAIL_V4"):
        old=bpy.data.collections.get(name)
        if old:
            for o in list(old.objects): bpy.data.objects.remove(o,do_unlink=True)
            bpy.data.collections.remove(old)
    col=clear_collection("06_FACADE_DETAIL_V4")
    if hasattr(col,"color_tag"): col.color_tag="COLOR_04"

    stone=mat("MAT_Facade_Stone_Frame",(0.52,0.50,0.45,1),0.8)
    glass=mat("MAT_Facade_Glass",(0.025,0.07,0.10,1),0.18)
    door=mat("MAT_Facade_Door",(0.16,0.045,0.025,1),0.65)
    tracery=mat("MAT_Facade_Tracery",(0.40,0.39,0.36,1),0.75)

    for op in data["openings"]:
        fill_mat = door if op["class"] == "door" else glass
        add_polygon_fill(col,op,fill_mat,0.035,op["id"]+"_inset")
        add_frame(col,op,stone,0.065,1.14 if op["class"] != "quatrefoil" else 1.18)
        if int(op.get("mullions",0)) >= 2:
            add_mullion(col,op,0.38,tracery)
            add_mullion(col,op,0.62,tracery)

    info=bpy.data.objects.new("FACADE_DETAIL_V4_INFO",None)
    col.objects.link(info)
    info["status"]="REGISTERED_EVIDENCE_DETAIL"
    info["source_image"]=data["source_image"]
    info["opening_count"]=int(data["opening_count"])
    info["method"]=data["method"]

    c=camera()
    c.data.type="PERSP"
    c.data.lens=52
    c.data.clip_start=0.05
    c.data.clip_end=5000

    front_c=region_center(data,"front_gable")
    side_c=region_center(data,"side_upper")
    front_n=outward(data,"front_gable")
    side_n=outward(data,"side_upper")
    target=(front_c+side_c)*0.5
    view=(front_n+side_n).normalized()
    c.location=target+view*34+Vector((0,0,8.0))
    aim(c,target+Vector((0,0,1.5)))
    render(a.overview)

    c.location=front_c+front_n*23+Vector((0,0,1.0))
    aim(c,front_c+Vector((0,0,1.0)))
    c.data.lens=58
    render(a.front)

    side_low=region_center(data,"side_lower")
    side_target=(side_c+side_low)*0.5
    c.location=side_target+side_n*28+Vector((0,0,1.8))
    aim(c,side_target+Vector((0,0,1.0)))
    c.data.lens=62
    render(a.side)

    a.output_blend.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(a.output_blend.resolve()))
    print(f"detail openings: {data['opening_count']}")
    print(f"blend: {a.output_blend}")


if __name__ == "__main__":
    main()
