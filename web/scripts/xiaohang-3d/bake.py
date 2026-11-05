"""Bake Xiaohang's editable ellipsoid model (Python 3.10+, NumPy, Pillow).

    uv run --with numpy --with pillow web/scripts/xiaohang-3d/bake.py [--out DIR]

The WebGL model, static glTF scene and transparent sprites use the same named
parts, degree rotations and orthographic camera. No display or GPU is needed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import struct

import numpy as np
from PIL import Image


CELL = 124
TILE = CELL * 3
SAMPLES = 2
ANCHOR = (62, 119)
YAW, PITCH = 14.0, 4.0
FRAME_COUNT = 16
DEFAULT_OUT = Path(__file__).resolve().parents[2] / 'public' / 'assets'


def unit(vector):
    vector = np.asarray(vector, dtype=np.float32)
    return vector / np.linalg.norm(vector, axis=-1, keepdims=True)


def basis(toward_camera):
    z = unit(toward_camera)
    x = unit(np.cross([0, 1, 0], z))
    return np.array([x, np.cross(z, x), z], dtype=np.float32)


def euler_matrix(angles):
    """Local X, then Y, then Z; identical to the glTF node quaternion below."""
    x, y, z = np.radians(angles)
    sx, sy, sz = np.sin((x, y, z))
    cx, cy, cz = np.cos((x, y, z))
    return np.array([[cz*cy, cz*sy*sx - sz*cx, cz*sy*cx + sz*sx],
                     [sz*cy, sz*sy*sx + cz*cx, sz*sy*cx - cz*sx],
                     [-sy, cy*sx, cy*cx]], dtype=np.float32)


def quaternion(angles):
    sx, sy, sz = np.sin(np.radians(angles) / 2)
    cx, cy, cz = np.cos(np.radians(angles) / 2)
    return [float(v) for v in (sx*cy*cz - cx*sy*sz, cx*sy*cz + sx*cy*sz,
                               cx*cy*sz - sx*sy*cz, cx*cy*cz + sx*sy*sz)]


def linear_color(hex_color):
    srgb = np.frombuffer(bytes.fromhex(hex_color[1:]), dtype=np.uint8).astype(np.float32) / 255
    return np.where(srgb <= .04045, srgb / 12.92, ((srgb + .055) / 1.055) ** 2.4)


def load_poses(part_factory):
    poses = []
    for frame in range(FRAME_COUNT):
        rows = []
        for part in part_factory(frame):
            name = part['name']
            if not isinstance(name, str) or not name.strip() or not re.fullmatch(r'#[0-9a-fA-F]{6}', part['color']):
                raise ValueError(f'Invalid part name or color in frame {frame}: {name!r}')
            row = {'name': name, 'color': part['color'].upper()}
            for key in ('center', 'radii', 'rot'):
                if key == 'rot' and key not in part:
                    continue
                values = np.asarray(part[key], dtype=np.float64)
                if values.shape != (3,) or not np.isfinite(values).all() or (key == 'radii' and np.any(values <= 0)):
                    raise ValueError(f'Invalid {key} for {name!r} in frame {frame}')
                row[key] = values.tolist()
            rows.append(row)
        names = [row['name'] for row in rows]
        if not names or len(names) != len(set(names)):
            raise ValueError(f'Part names must be nonempty and unique in frame {frame}')
        if poses and names != [row['name'] for row in poses[0]]:
            raise ValueError(f'Part names or order changed in frame {frame}')
        if poses and any(row['color'] != base['color'] for row, base in zip(rows, poses[0])):
            raise ValueError(f'Pose overrides cannot change paint colors in frame {frame}')
        poses.append(rows)
    return poses


@dataclass
class Shape:
    center: np.ndarray
    covariance: np.ndarray
    precision: np.ndarray
    color: np.ndarray

    @classmethod
    def of(cls, row):
        r = np.asarray(row['radii'], dtype=np.float32)
        rot = euler_matrix(row.get('rot', [0, 0, 0]))
        return cls(np.asarray(row['center'], dtype=np.float32), (rot * r**2) @ rot.T,
                   (rot * (1 / r**2)) @ rot.T, linear_color(row['color']))


def projected_bounds(shapes, axes):
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for shape in shapes:
        c = axes @ shape.center
        extent = np.sqrt(np.diag(axes @ shape.covariance @ axes.T))
        lo, hi = np.minimum(lo, c - extent), np.maximum(hi, c + extent)
    return lo, hi


@dataclass
class Plane:
    axes: np.ndarray
    left: float
    top: float
    unit: float
    size: int


def frame_camera(scenes):
    yaw, pitch = np.radians([YAW, PITCH])
    axes = basis([np.sin(yaw) * np.cos(pitch), np.sin(pitch), np.cos(yaw) * np.cos(pitch)])
    lo, hi = projected_bounds((shape for scene in scenes for shape in scene), axes)
    units_per_pixel = float(max((hi[1] - lo[1]) / 112, -lo[0] / 61, hi[0] / 61))
    camera = {'yawDegrees': YAW, 'pitchDegrees': PITCH, 'projectedBottom': float(lo[1]),
              'unitsPerPixel': units_per_pixel, 'anchor': list(ANCHOR)}
    size = TILE * SAMPLES
    plane = Plane(axes, -ANCHOR[0] * units_per_pixel, float(lo[1]) + ANCHOR[1] * units_per_pixel,
                  units_per_pixel * CELL / size, size)
    return camera, plane


def rasterize(shapes, plane, *, normals=False):
    """Intersect orthographic rays with exact quadrics; nearest toward camera wins."""
    depth = np.full((plane.size, plane.size), -np.inf, dtype=np.float32)
    ids = np.full(depth.shape, -1, dtype=np.int32) if normals else None
    norm = np.zeros((*depth.shape, 3), dtype=np.float32) if normals else None
    for i, shape in enumerate(shapes):
        c = plane.axes @ shape.center
        radius = np.sqrt(np.diag(plane.axes @ shape.covariance @ plane.axes.T))
        x0 = max(0, math.floor((c[0] - radius[0] - plane.left) / plane.unit))
        x1 = min(plane.size, math.ceil((c[0] + radius[0] - plane.left) / plane.unit))
        y0 = max(0, math.floor((plane.top - c[1] - radius[1]) / plane.unit))
        y1 = min(plane.size, math.ceil((plane.top - c[1] + radius[1]) / plane.unit))
        if x0 >= x1 or y0 >= y1:
            continue
        x = (plane.left + (np.arange(x0, x1, dtype=np.float32)[None, :] + .5) * plane.unit) - c[0]
        y = (plane.top - (np.arange(y0, y1, dtype=np.float32)[:, None] + .5) * plane.unit) - c[1]
        q = plane.axes @ shape.precision @ plane.axes.T
        a, b = q[2, 2], q[0, 2] * x + q[1, 2] * y
        d = b*b - a * (q[0, 0]*x*x + 2*q[0, 1]*x*y + q[1, 1]*y*y - 1)
        z = (np.sqrt(np.maximum(d, 0)) - b) / a
        box = np.s_[y0:y1, x0:x1]
        visible = (d >= 0) & (z + c[2] > depth[box])
        depth[box][visible] = (z + c[2])[visible]
        if normals:
            ids[box][visible] = i
            # The quadric gradient at its visible surface gives the true curved normal.
            nx = q[0, 0]*x + q[0, 1]*y + q[0, 2]*z
            ny = q[1, 0]*x + q[1, 1]*y + q[1, 2]*z
            nz = b + a*z
            norm[box][visible] = unit(np.stack([nx[visible], ny[visible], nz[visible]], axis=1))
    return depth, ids, norm


KEY = unit([-.65, 1.25, 1.65])
FILL = unit([.95, .35, 1.1])
RIM = unit([.75, .95, -.9])


def key_visibility(shapes, points, normals):
    """Filtered light-depth samples keep the brow, visor and collar in contact."""
    axes = basis(KEY)
    lo, hi = projected_bounds(shapes, axes)
    span = float(max(hi[0] - lo[0], hi[1] - lo[1]) + .16)
    plane = Plane(axes, float((hi[0] + lo[0] - span) / 2), float((hi[1] + lo[1] + span) / 2), span / 480, 480)
    depths, _, _ = rasterize(shapes, plane)
    p = points @ axes.T
    n = normals @ axes.T
    px, py = (p[:, 0] - plane.left) / plane.unit - .5, (plane.top - p[:, 1]) / plane.unit - .5
    shade = np.zeros(len(points), dtype=np.float32)
    # Account for the receiving surface's slope at neighbouring texels: curved
    # shapes should not cast striped shadows on their own sunlit faces.
    slopes = np.clip(n[:, :2] / np.maximum(n[:, 2:3], .18), -3, 3)
    offsets = [(0, 0), (-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)]
    for dx, dy in offsets:
        ix = np.clip(np.rint(px + dx).astype(int), 0, plane.size - 1)
        iy = np.clip(np.rint(py + dy).astype(int), 0, plane.size - 1)
        receiver = p[:, 2] - ((ix - px)*slopes[:, 0] - (iy - py)*slopes[:, 1]) * plane.unit
        shade += depths[iy, ix] > receiver + plane.unit * 1.05
    return 1 - shade / len(offsets)


def contact_light(depth, y, x, n, pixel_unit):
    """Finite-radius ambient occlusion between nearby surfaces in camera space."""
    total = np.zeros(len(x), dtype=np.float32)
    z = depth[y, x]
    for radius in (.045, .105, .20):
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(.707,.707),(-.707,.707),(.707,-.707),(-.707,-.707)):
            ix, iy = round(dx * radius / pixel_unit), round(dy * radius / pixel_unit)
            other = depth[np.clip(y + iy, 0, depth.shape[0] - 1), np.clip(x + ix, 0, depth.shape[1] - 1)]
            present = np.isfinite(other)
            dz = np.where(present, other - z, 0)
            dist = np.sqrt(((ix*pixel_unit)**2 + (iy*pixel_unit)**2) + dz*dz)
            dot = (n[:, 0]*ix*pixel_unit - n[:, 1]*iy*pixel_unit + n[:, 2]*dz) / np.maximum(dist, 1e-6)
            total += np.where(present, np.maximum(dot - .09, 0) * np.exp(-dist/.24), 0)
    return np.clip(1 - 2.3 * total / 24, .63, 1)


def render(shapes, plane):
    depth, ids, normals = rasterize(shapes, plane, normals=True)
    y, x = np.nonzero(ids >= 0)
    n_view = normals[y, x]
    n = n_view @ plane.axes
    view_points = np.stack([plane.left + (x+.5)*plane.unit, plane.top - (y+.5)*plane.unit, depth[y, x]], axis=1).astype(np.float32)
    points = view_points @ plane.axes
    visibility = key_visibility(shapes, points, n)
    ao = contact_light(depth, y, x, n_view, plane.unit)
    paint = np.asarray([shape.color for shape in shapes])[ids[y, x]]
    front = np.maximum(n @ KEY, 0)
    hemi = .5 + .5 * n[:, 1]
    light = (.38 + .20*hemi + .64*front*(.22 + .78*visibility))[:, None]
    light = light + np.maximum(n @ FILL, 0)[:, None] * [.105, .13, .17]
    light = light + np.maximum(n @ RIM, 0)[:, None] * [.10, .12, .155]
    half_vector = unit(KEY + plane.axes[2])
    nh = np.maximum(n @ half_vector, 0)
    highlight = (.105*nh**24 + .115*nh**125) * visibility * np.sqrt(front)
    # A soft studio rim reveals rounded blue and dark edges without a black outline.
    fresnel = (1 - np.clip(n_view[:, 2], 0, 1))**3
    sheen = np.maximum(n @ RIM, 0)**2 * fresnel
    rgb = paint * light * ao[:, None] + highlight[:, None] + sheen[:, None] * [.075, .095, .135]
    rgb = np.clip(rgb, 0, 1)
    rgb = np.where(rgb <= .0031308, 12.92*rgb, 1.055*rgb**(1/2.4) - .055)
    pixels = np.zeros((plane.size, plane.size, 4), dtype=np.uint8)
    pixels[y, x, :3] = np.rint(rgb*255).astype(np.uint8)
    pixels[y, x, 3] = 255
    return Image.fromarray(pixels)


def sphere_mesh():
    """Shared unit sphere; counterclockwise triangles, with no degenerate poles."""
    rings, segments = 22, 40
    vertices, indices = [[0, -1, 0]], []
    for ring in range(1, rings):
        lat = -math.pi/2 + math.pi*ring/rings
        for segment in range(segments):
            lon = 2*math.pi*segment/segments
            vertices.append([math.cos(lat)*math.sin(lon), math.sin(lat), math.cos(lat)*math.cos(lon)])
    top = len(vertices)
    vertices.append([0, 1, 0])
    for s in range(segments):
        a, b = 1 + s, 1 + (s+1) % segments
        indices.extend((0, b, a))
        for ring in range(rings - 2):
            a, b = 1 + ring*segments + s, 1 + ring*segments + (s+1) % segments
            indices.extend((a, b, b+segments, a, b+segments, a+segments))
        i = 1 + (rings-2)*segments
        indices.extend((i+s, i+(s+1) % segments, top))
    return np.asarray(vertices, dtype='<f4'), np.asarray(indices, dtype='<u2')


def write_glb(path, rows, camera, plane):
    vertices, indices = sphere_mesh()
    vsize, isize = vertices.nbytes, indices.nbytes
    binary = vertices.tobytes() + indices.tobytes()
    colors = list(dict.fromkeys(row['color'] for row in rows))
    material_ids = {color: i for i, color in enumerate(colors)}
    nodes = [{'name': 'Xiaohang', 'children': list(range(1, len(rows)+1))}]
    for row in rows:
        node = {'name': row['name'], 'mesh': material_ids[row['color']], 'translation': row['center'], 'scale': row['radii']}
        if any(row.get('rot', ())):
            node['rotation'] = quaternion(row['rot'])
        nodes.append(node)
    half = camera['unitsPerPixel'] * CELL / 2
    center_v = camera['projectedBottom'] + (ANCHOR[1] - CELL/2) * camera['unitsPerPixel']
    eye = plane.axes[1] * center_v + plane.axes[2] * 8
    camera_matrix = np.eye(4, dtype=np.float32)
    camera_matrix[:3, :3], camera_matrix[:3, 3] = plane.axes.T, eye
    camera_node = len(nodes)
    nodes.append({'name': 'Portrait Camera', 'camera': 0, 'matrix': camera_matrix.T.ravel().tolist()})
    doc = {
        'asset': {'version': '2.0', 'generator': 'Xiaohang CPU baker'}, 'scene': 0,
        'scenes': [{'name': 'Xiaohang neutral pose', 'nodes': [0, camera_node]}], 'nodes': nodes,
        'cameras': [{'type': 'orthographic', 'orthographic': {'xmag': half, 'ymag': half, 'znear': .01, 'zfar': 20}}],
        'meshes': [{'name': f'Ellipsoids {color}', 'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 0},
                    'indices': 1, 'material': i}]} for i, color in enumerate(colors)],
        'materials': [{'name': f'Paint {color}', 'pbrMetallicRoughness': {
            'baseColorFactor': [*linear_color(color).tolist(), 1], 'metallicFactor': .02, 'roughnessFactor': .38,
        }} for color in colors],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': vsize, 'byteStride': 12, 'target': 34962},
                        {'buffer': 0, 'byteOffset': vsize, 'byteLength': isize, 'target': 34963}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': len(vertices), 'type': 'VEC3',
                       'min': vertices.min(axis=0).tolist(), 'max': vertices.max(axis=0).tolist()},
                      {'bufferView': 1, 'componentType': 5123, 'count': len(indices), 'type': 'SCALAR'}],
    }
    data = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    data += b' ' * (-len(data) % 4)
    binary += b'\0' * (-len(binary) % 4)
    chunks = struct.pack('<I4s', len(data), b'JSON') + data + struct.pack('<I4s', len(binary), b'BIN\0') + binary
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 12+len(chunks)) + chunks)


def web_model(poses, camera):
    base, changes = poses[0], []
    for pose in poses:
        delta = {}
        for rest, part in zip(base, pose):
            overrides = {key: part.get(key, [0,0,0]) for key in ('center', 'radii', 'rot')
                         if part.get(key, [0,0,0]) != rest.get(key, [0,0,0])}
            if overrides:
                delta[part['name']] = overrides
        changes.append(delta)
    return {'parts': base, 'poses': changes, 'camera': camera}


def bake(part_factory, out):
    poses = load_poses(part_factory)
    scenes = [[Shape.of(row) for row in pose] for pose in poses]
    camera, plane = frame_camera(scenes)
    out.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGBA', (4*TILE, 4*TILE))
    frames = []
    for i, scene in enumerate(scenes):
        high = render(scene, plane)
        if i == 0:
            high.resize((512, 512), Image.Resampling.LANCZOS).save(out / 'xiaohang-3d-portrait.png', optimize=True)
        x, y = (i % 4)*TILE, (i // 4)*TILE
        sheet.paste(high.resize((TILE, TILE), Image.Resampling.LANCZOS), (x, y))
        frames.append({'rect': {'x': x, 'y': y, 'width': TILE, 'height': TILE},
                       'anchor': {'x': x + TILE*ANCHOR[0]/CELL, 'y': y + TILE*ANCHOR[1]/CELL}})
    sheet.save(out / 'xiaohang-3d.png', optimize=True)
    meta = {'image': '/assets/xiaohang-3d.png', 'width': sheet.width, 'height': sheet.height,
            'columns': 4, 'rows': 4, 'frameCount': len(frames), 'frames': frames}
    (out / 'xiaohang-3d.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out / 'xiaohang-3d-model.json').write_text(json.dumps(web_model(poses, camera), ensure_ascii=False,
                                                           separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8')
    write_glb(out / 'xiaohang-3d.glb', poses[0], camera, plane)
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    from model import parts
    destination = bake(parts, args.out)
    for file in sorted(destination.glob('xiaohang-3d*')):
        print(f'{file.name}: {file.stat().st_size:,} bytes', flush=True)
