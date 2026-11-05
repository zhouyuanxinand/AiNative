"""Xiaohang, a blue and ivory flight companion. +Y is up and +Z is forward."""

from math import atan2, cos, degrees, hypot, radians, sin, sqrt


IVORY = '#F6F6EF'
SHELL = '#EBF0ED'
SHADOW = '#C9DBE1'
BLUE = '#197CB8'
BRIGHT = '#3499CE'
NAVY = '#244D68'
SKIN = '#FFD6BD'
BLUSH = '#F8C9B6'
IRIS = '#885836'
INK = '#392B31'


def parts(frame=0):
    """Return the same named ellipsoids in every pose; angles are in degrees."""
    frame = max(0, min(15, int(frame)))
    result = []

    def oval(name, center, radii, color, rot=(0.0, 0.0, 0.0)):
        result.append(dict(name=name, center=center, radii=radii, color=color, rot=rot))

    def span(name, start, end, width, depth, color, overlap=0.035):
        """A tapered soft part whose local long axis follows its two joints."""
        dx, dy, dz = (b - a for a, b in zip(start, end))
        horizontal = hypot(dx, dy)
        rotation = (degrees(atan2(dz, horizontal)), 0.0, degrees(atan2(-dx, dy)))
        center = tuple((a + b) * 0.5 for a, b in zip(start, end))
        oval(name, center, (width, hypot(horizontal, dz) * 0.5 + overlap, depth), color, rotation)

    # A low, rounded toe on a slightly wider sole makes each foot legible at 70px.
    for side, tag in ((-1, 'right'), (1, 'left')):
        x = side * 0.211
        oval(f'{tag}_trouser', (side * 0.184, 0.548, -0.010), (0.172, 0.259, 0.178), SHELL)
        oval(f'{tag}_boot_ankle', (x, 0.299, 0.004), (0.185, 0.206, 0.190), IVORY)
        oval(f'{tag}_boot_band', (x, 0.367, 0.017), (0.192, 0.062, 0.193), BLUE)
        oval(f'{tag}_boot_sole', (x, 0.066, 0.104), (0.212, 0.066, 0.283), SHADOW)
        oval(f'{tag}_boot_toe', (x, 0.167, 0.112), (0.210, 0.147, 0.281), IVORY)

    # The back unit is visible in profile; the two swept fins recall the old winged suit.
    oval('flight_pack', (0.0, 1.104, -0.245), (0.378, 0.340, 0.193), NAVY)
    oval('pack_latch_base', (0.0, 1.113, -0.425), (.130, .063, .032), '#367698')
    oval('pack_latch', (0.0, 1.117, -0.450), (.075, .033, .014), SHADOW)
    for side, tag in ((-1, 'right'), (1, 'left')):
        oval(f'{tag}_pack_canister', (side * 0.315, 1.112, -0.298), (0.123, 0.265, 0.135), BRIGHT)
        oval(f'{tag}_pack_nozzle', (side * 0.315, 0.912, -0.291), (0.105, 0.078, 0.105), NAVY)
        span(f'{tag}_pack_fin', (side * 0.310, 1.225, -0.266), (side * 0.717, 0.964, -0.251),
             0.083, 0.105, BLUE, overlap=0.050)
    oval('suit_hips', (0.0, 0.751, -0.012), (0.371, 0.209, 0.214), SHELL)
    oval('suit_torso', (0.0, 1.062, -0.005), (0.397, 0.372, 0.256), IVORY)
    oval('flight_bib', (0.0, 1.240, 0.036), (0.406, 0.275, 0.275), BLUE)
    oval('neck_seal', (0.0, 1.481, 0.020), (0.256, 0.074, 0.191), NAVY)
    oval('suit_fastener', (0.0, 1.047, 0.264), (0.012, 0.066, 0.013), SHADOW)
    for side, tag in ((-1, 'right'), (1, 'left')):
        oval(f'{tag}_chest_wing', (side * 0.102, 1.259, 0.299), (0.088, 0.022, 0.017),
             IVORY, (0.0, side * 8.0, side * 15.0))
        oval(f'{tag}_chest_feather', (side * 0.079, 1.215, 0.301), (0.057, 0.014, 0.014),
             SHADOW, (0.0, side * 6.0, side * 12.0))
    oval('chest_roundel', (0.0, 1.245, 0.316), (0.042, 0.047, 0.019), IVORY)
    oval('chest_roundel_core', (0.0, 1.245, 0.331), (0.019, 0.022, 0.012), BRIGHT)

    # The anatomical right hand waves (the viewer's left). Rotating fixed-length
    # bones, instead of interpolating glove positions, keeps the bent elbow full.
    lift = (0, 0, 0, 0, .13, .34, .60, .84, 1, 1, 1, .88, .67, .43, .20, 0)[frame]
    wrist_wave = (0, 0, 0, 0, 0, 0, 0, -3, -8, 10, -9, 7, 0, 0, 0, 0)[frame]
    for side, tag in ((-1, 'right'), (1, 'left')):
        k = lift if side == -1 else 0
        # Fold the forearm before lifting the shoulder: the glove follows the
        # cheek rather than sweeping sideways beyond the launcher footprint.
        a = radians(17 + 109 * max(0.0, (k - .24) / .76))
        b = radians(13 + 147 * min(1.0, 2.4 * k) + (wrist_wave if side == -1 else 0))
        shoulder = (side * .387, 1.298, .015)
        elbow = (shoulder[0] + side * .316 * sin(a), shoulder[1] - .316 * cos(a), .047 + .065 * k)
        wrist = (elbow[0] + side * .268 * sin(b), elbow[1] - .268 * cos(b), .084 + .124 * k)
        palm = (wrist[0] + side * .079 * sin(b), wrist[1] - .079 * cos(b), wrist[2] + .021)
        oval(f'{tag}_shoulder', shoulder, (.155, .145, .173), BLUE)
        span(f'{tag}_upper_sleeve', shoulder, elbow, .118, .131, IVORY)
        oval(f'{tag}_elbow_joint', elbow, (.103, .100, .114), SHADOW)
        span(f'{tag}_forearm', elbow, wrist, .108, .125, SHELL)
        tilt = degrees(atan2(-side * sin(b), -cos(b)))
        oval(f'{tag}_glove_cuff', wrist, (.113, .057, .125), BLUE, (0, 0, tilt))
        oval(f'{tag}_glove', palm, (.111, .132, .121), IVORY, (0, 0, tilt))
        oval(f'{tag}_glove_thumb', (palm[0] - side * .083, palm[1] + .016, palm[2] + .061),
             (.050, .067, .054), IVORY, (10, 0, -side * 24))

    oval('helmet_shell', (0.0, 2.054, -.026), (.732, .596, .577), IVORY)
    oval('face', (0.0, 1.978, .167), (.620, .524, .526), SKIN)
    def face_surface(x, y):
        return .167 + .526 * sqrt(1 - (x / .620) ** 2 - ((y - 1.978) / .524) ** 2)

    for side, tag in ((-1, 'right'), (1, 'left')):
        oval(f'{tag}_jaw_guard', (side * .581, 1.799, .141), (.122, .224, .195),
             IVORY, (0.0, side * 6, -side * 13))
        oval(f'{tag}_ear_cushion', (side * .703, 2.005, -.041), (.141, .244, .194), NAVY)
        oval(f'{tag}_ear_cup', (side * .787, 2.011, -.031), (.121, .212, .182), BLUE)
        oval(f'{tag}_ear_plate', (side * .866, 2.018, -.021), (.065, .156, .133), BRIGHT)
        oval(f'{tag}_ear_pin', (side * .926, 2.019, -.022), (.018, .039, .037), IVORY)

    # Each eye faces slightly outward along the cheek. The whites and irises
    # sink into the face as they close; a single soft lash takes over the line.
    aperture = (1.0, .965, .46, .035)[frame] if frame < 4 else 1.0
    for side, tag in ((-1, 'right'), (1, 'left')):
        yaw = radians(side * 19)
        def eye_part(suffix, local, radius, color, roll=0):
            dx, dy, dz = local
            center = (side * .234 + cos(yaw) * dx + sin(yaw) * dz,
                      2.015 + dy, .638 - sin(yaw) * dx + cos(yaw) * dz)
            oval(f'{tag}_{suffix}', center, radius, color, (0, degrees(yaw), roll))

        retreat = -.098 * (1 - aperture)
        eye_part('sclera', (0, 0, retreat), (.145, .148 * aperture, .042), IVORY, -side * 3)
        eye_part('iris', (-side * .009, -.006 * aperture, .041 + retreat),
                 (.103, .119 * aperture, .022), IRIS)
        eye_part('pupil', (-side * .011, -.004 * aperture, .057 + retreat),
                 (.071, .090 * aperture, .014), INK)
        eye_part('eye_glint', (-.039 * aperture, .048 * aperture, .073 + retreat),
                 (.025 * aperture, .031 * aperture, .007), '#FFFDF4')
        eye_part('eye_glimmer', (.029 * aperture, -.041 * aperture, .072 + retreat),
                 (.011 * aperture, .012 * aperture, .005), '#FFF9E9')
        eye_part('upper_lash', (0, .132 * aperture, .034 - .012 * aperture),
                 (.133, .011, .013), INK, -side * 4)
        points = [(side * x, y, face_surface(side * x, y) + .003) for x, y in
                  ((.127, 2.194), (.222, 2.223), (.331, 2.196))]
        span(f'{tag}_brow_inner', points[0], points[1], .018, .012, '#60423B', overlap=.009)
        span(f'{tag}_brow_tip', points[1], points[2], .015, .011, '#60423B', overlap=.009)
        x, y = side * .392, 1.840
        oval(f'{tag}_cheek', (x, y, face_surface(x, y) - .003), (.080, .035, .009),
             BLUSH, (14, side * 35, side * 5))

    oval('nose', (0.0, 1.892, .677), (.056, .042, .039), '#F5BBA2')
    # A curved, nearly flush smile follows the cheek sphere all the way to the
    # raised corners; a single protruding dark oval reads like an open mouth.
    smile = [(x, y, face_surface(x, y) + .003) for x, y in
             ((-.157, 1.802), (-.108, 1.771), (-.055, 1.752), (0, 1.747),
              (.055, 1.752), (.108, 1.771), (.157, 1.802))]
    for i, (a, b) in enumerate(zip(smile, smile[1:])):
        span(f'smile_arc_{i}', a, b, .013 if i in (0, 5) else .017, .010,
             '#794942', overlap=.009)

    oval('cap_crown', (0.0, 2.407, -.029), (.695, .259, .567), BLUE)
    oval('cap_band', (0.0, 2.360, .025), (.704, .091, .570), '#216D9F')
    oval('visor_underside', (0.0, 2.303, .347), (.664, .056, .405), NAVY, (6, 0, 0))
    oval('visor', (0.0, 2.329, .353), (.666, .066, .408), BLUE, (6, 0, 0))
    oval('rotor_spindle', (0.0, 2.677, -.045), (.048, .045, .048), NAVY)
    for side, tag in ((-1, 'right'), (1, 'left')):
        oval(f'{tag}_rotor_blade', (side * .215, 2.714, -.045 + side * .064),
             (.244, .018, .076), BRIGHT, (4, -18, side * 2.5))
    oval('rotor_hub', (0.0, 2.730, -.045), (.055, .020, .056), BLUE)
    oval('cap_badge', (0.0, 2.477, .510), (.094, .062, .023), IVORY, (-16, 0, 0))
    oval('cap_badge_core', (0.0, 2.476, .530), (.045, .030, .014), BRIGHT, (-16, 0, 0))
    return result
