"""Monocular "is this person near the car" estimation for a single
stationary camera — pure geometry, no ML model.

The classic monocular ambiguity is that two objects at very different
real-world distances can occupy adjacent or overlapping pixels if one
sits between the camera and the other along the same viewing ray (someone
walking on a sidewalk far behind the car, in the same part of the frame).
Depth Anything-style monocular depth models are one way to resolve this;
for a *stationary* camera, comparable-triangles reasoning from a person's
apparent size does the same job without an extra model to bundle, download,
and run on every analyzed frame:

A pinhole camera projects an object of real height H at distance Z to
pixel height h = f*H/Z, for some fixed (unknown) focal length f. The
vehicle's own outline, plus its real-world length (entered by the
homeowner), gives a local pixels-per-foot scale *at the vehicle's
distance*. A detected person's apparent height, compared against what an
average-height adult would measure at that same distance, tells us
whether they're plausibly standing at the vehicle's depth at all — before
we ever ask "how many feet away, laterally" using the outline. A person
who measures far smaller or larger than that expectation is at a
meaningfully different distance from the camera than the vehicle is, so
no lateral-distance claim is made for them, regardless of 2D overlap.

This is an approximation (an isotropic local scale, an average adult
height, a flat local ground plane) — the error margin returned alongside
every estimate says so honestly rather than implying survey-grade
precision.
"""

import math
from dataclasses import dataclass

Point = tuple[float, float]

AVERAGE_ADULT_HEIGHT_FEET = 5.6
"""Rough US adult average across sexes — a deliberate approximation, not a
per-person measurement; see module docstring."""

DEPTH_MISMATCH_TOLERANCE = 0.4
"""A person's apparent height must fall within +/-40% of "what an average
adult would measure at the vehicle's distance" to be treated as plausibly
at the same depth as the vehicle at all."""

ERROR_MARGIN_FRACTION = 0.3
"""Every distance estimate carries a +/-30% error band, reflecting the
isotropic-scale and average-height assumptions above."""


@dataclass
class ProximityEstimate:
    distance_feet: float
    error_margin_feet: float
    breached: bool


def _to_pixels(points: list[Point], frame_width: int, frame_height: int) -> list[Point]:
    return [(x * frame_width, y * frame_height) for x, y in points]


def _polygon_bounds(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _polygon_max_span(points: list[Point]) -> float:
    min_x, min_y, max_x, max_y = _polygon_bounds(points)
    return max(max_x - min_x, max_y - min_y)


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Standard ray-casting point-in-polygon test."""
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        crosses = (y1 > y) != (y2 > y)
        if crosses:
            x_at_y = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_at_y:
                inside = not inside
    return inside


def _point_to_segment_distance(point: Point, a: Point, b: Point) -> float:
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    nearest_x, nearest_y = ax + t * dx, ay + t * dy
    return math.hypot(px - nearest_x, py - nearest_y)


def distance_to_polygon(point: Point, polygon: list[Point]) -> float:
    """Pixel distance from ``point`` to the nearest edge of ``polygon``, or
    0.0 if the point falls inside it. A single-point "polygon" degrades to
    plain point-to-point distance; an empty one has nothing to measure to."""
    if not polygon:
        return 0.0
    if len(polygon) == 1:
        return math.hypot(point[0] - polygon[0][0], point[1] - polygon[0][1])
    if _point_in_polygon(point, polygon):
        return 0.0
    return min(
        _point_to_segment_distance(point, polygon[i], polygon[(i + 1) % len(polygon)])
        for i in range(len(polygon))
    )


def bbox_foot_point(bbox: tuple[float, float, float, float]) -> Point:
    """The bottom-center of a normalized [x, y, w, h] bounding box — the
    point where a standing person's feet meet the ground."""
    x, y, w, h = bbox
    return (x + w / 2, y + h)


def estimate_proximity(
    *,
    vehicle_outline: list[Point],
    vehicle_length_feet: float,
    distance_threshold_feet: float,
    person_bbox: tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
) -> ProximityEstimate | None:
    """Estimate how far (in feet) a detected person is from a vehicle's
    outline, or ``None`` if the person's apparent size says they're at a
    meaningfully different distance from the camera than the vehicle is —
    the case this module exists to catch, rather than reporting a
    confident-looking number for a physically implausible reading.
    """
    if len(vehicle_outline) < 3 or vehicle_length_feet <= 0:
        return None

    outline_px = _to_pixels(vehicle_outline, frame_width, frame_height)
    vehicle_span_px = _polygon_max_span(outline_px)
    if vehicle_span_px <= 0:
        return None
    pixels_per_foot = vehicle_span_px / vehicle_length_feet

    person_height_px = person_bbox[3] * frame_height
    expected_height_px = AVERAGE_ADULT_HEIGHT_FEET * pixels_per_foot
    depth_ratio = person_height_px / expected_height_px
    if abs(depth_ratio - 1.0) > DEPTH_MISMATCH_TOLERANCE:
        return None

    foot_point_px = _to_pixels([bbox_foot_point(person_bbox)], frame_width, frame_height)[0]
    pixel_distance = distance_to_polygon(foot_point_px, outline_px)
    distance_feet = pixel_distance / pixels_per_foot
    error_margin_feet = distance_feet * ERROR_MARGIN_FRACTION

    return ProximityEstimate(
        distance_feet=round(distance_feet, 1),
        error_margin_feet=round(error_margin_feet, 1),
        breached=distance_feet <= distance_threshold_feet,
    )
