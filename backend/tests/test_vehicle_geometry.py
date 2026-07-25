"""Vehicle proximity geometry: pure math, no DB/network, fully deterministic.

All cases use a 1000x1000 frame and a vehicle outline chosen so the pixel
math works out to round numbers (pixels_per_foot = 10.0), so expected
values are hand-verifiable rather than approximate.
"""

import pytest

from app.vehicles.geometry import (
    ProximityEstimate,
    bbox_foot_point,
    distance_to_polygon,
    estimate_proximity,
)

FRAME = (1000, 1000)
# Bounding box 150x100px -> max span 150px; length_feet=15.0 -> 10 px/ft.
VEHICLE_OUTLINE = [(0.4, 0.6), (0.55, 0.6), (0.55, 0.7), (0.4, 0.7)]
VEHICLE_LENGTH_FEET = 15.0
EXPECTED_HEIGHT_NORMALIZED = 0.056  # 5.6ft average adult * 10px/ft / 1000px


def test_bbox_foot_point_is_bottom_center() -> None:
    assert bbox_foot_point((0.2, 0.3, 0.1, 0.05)) == pytest.approx((0.25, 0.35))


def test_distance_to_polygon_is_zero_when_inside() -> None:
    polygon = [(400.0, 600.0), (600.0, 600.0), (600.0, 700.0), (400.0, 700.0)]
    assert distance_to_polygon((450.0, 650.0), polygon) == 0.0


def test_distance_to_polygon_measures_to_the_nearest_edge() -> None:
    polygon = [(400.0, 600.0), (600.0, 600.0), (600.0, 700.0), (400.0, 700.0)]
    assert distance_to_polygon((650.0, 650.0), polygon) == pytest.approx(50.0)
    assert distance_to_polygon((450.0, 550.0), polygon) == pytest.approx(50.0)


def test_distance_to_polygon_single_point_falls_back_to_point_distance() -> None:
    assert distance_to_polygon((0.0, 0.0), [(3.0, 4.0)]) == pytest.approx(5.0)


def test_distance_to_polygon_empty_polygon_is_zero() -> None:
    assert distance_to_polygon((1.0, 1.0), []) == 0.0


def test_distance_to_polygon_handles_a_repeated_vertex() -> None:
    # A zero-length edge (two identical consecutive points) shouldn't crash
    # the segment-distance math; it degrades to a point distance for that
    # edge, and the overall min still finds the true nearest edge.
    polygon = [(400.0, 600.0), (400.0, 600.0), (600.0, 600.0), (600.0, 700.0), (400.0, 700.0)]
    assert distance_to_polygon((650.0, 650.0), polygon) == pytest.approx(50.0)


def test_estimate_proximity_same_depth_moderate_distance_not_breached() -> None:
    # Foot point 47px right of the vehicle's right edge.
    bbox = (0.587, 0.594, 0.02, EXPECTED_HEIGHT_NORMALIZED)
    result = estimate_proximity(
        vehicle_outline=VEHICLE_OUTLINE,
        vehicle_length_feet=VEHICLE_LENGTH_FEET,
        distance_threshold_feet=3.0,
        person_bbox=bbox,
        frame_width=FRAME[0],
        frame_height=FRAME[1],
    )
    assert result == ProximityEstimate(distance_feet=4.7, error_margin_feet=1.4, breached=False)


def test_estimate_proximity_same_depth_close_is_breached() -> None:
    # Foot point 20px right of the vehicle's right edge.
    bbox = (0.56, 0.594, 0.02, EXPECTED_HEIGHT_NORMALIZED)
    result = estimate_proximity(
        vehicle_outline=VEHICLE_OUTLINE,
        vehicle_length_feet=VEHICLE_LENGTH_FEET,
        distance_threshold_feet=6.0,
        person_bbox=bbox,
        frame_width=FRAME[0],
        frame_height=FRAME[1],
    )
    assert result == ProximityEstimate(distance_feet=2.0, error_margin_feet=0.6, breached=True)


def test_estimate_proximity_foot_point_inside_outline_is_zero_distance() -> None:
    bbox = (0.44, 0.594, 0.02, EXPECTED_HEIGHT_NORMALIZED)
    result = estimate_proximity(
        vehicle_outline=VEHICLE_OUTLINE,
        vehicle_length_feet=VEHICLE_LENGTH_FEET,
        distance_threshold_feet=6.0,
        person_bbox=bbox,
        frame_width=FRAME[0],
        frame_height=FRAME[1],
    )
    assert result is not None
    assert result.distance_feet == 0.0
    assert result.breached is True


def test_estimate_proximity_returns_none_when_person_appears_much_smaller() -> None:
    # Height ratio ~0.36 of expected -> plausibly much farther from the
    # camera than the vehicle, despite whatever 2D position is given.
    bbox = (0.59, 0.63, 0.02, 0.02)
    result = estimate_proximity(
        vehicle_outline=VEHICLE_OUTLINE,
        vehicle_length_feet=VEHICLE_LENGTH_FEET,
        distance_threshold_feet=6.0,
        person_bbox=bbox,
        frame_width=FRAME[0],
        frame_height=FRAME[1],
    )
    assert result is None


def test_estimate_proximity_returns_none_when_person_appears_much_larger() -> None:
    # Height ratio ~2.68 of expected -> plausibly much closer to the camera
    # than the vehicle (foreground), not actually near it.
    bbox = (0.59, 0.5, 0.02, 0.15)
    result = estimate_proximity(
        vehicle_outline=VEHICLE_OUTLINE,
        vehicle_length_feet=VEHICLE_LENGTH_FEET,
        distance_threshold_feet=6.0,
        person_bbox=bbox,
        frame_width=FRAME[0],
        frame_height=FRAME[1],
    )
    assert result is None


def test_estimate_proximity_accepts_moderate_depth_deviation() -> None:
    # ~1.3x expected height: still within the +/-40% tolerance band.
    bbox = (0.59, 0.65 - 0.056 * 1.3, 0.02, 0.056 * 1.3)
    result = estimate_proximity(
        vehicle_outline=VEHICLE_OUTLINE,
        vehicle_length_feet=VEHICLE_LENGTH_FEET,
        distance_threshold_feet=100.0,
        person_bbox=bbox,
        frame_width=FRAME[0],
        frame_height=FRAME[1],
    )
    assert result is not None


def test_estimate_proximity_rejects_larger_depth_deviation() -> None:
    # ~1.5x expected height: outside the +/-40% tolerance band.
    bbox = (0.59, 0.65 - 0.056 * 1.5, 0.02, 0.056 * 1.5)
    result = estimate_proximity(
        vehicle_outline=VEHICLE_OUTLINE,
        vehicle_length_feet=VEHICLE_LENGTH_FEET,
        distance_threshold_feet=100.0,
        person_bbox=bbox,
        frame_width=FRAME[0],
        frame_height=FRAME[1],
    )
    assert result is None


def test_estimate_proximity_rejects_degenerate_outline() -> None:
    bbox = (0.5, 0.5, 0.02, EXPECTED_HEIGHT_NORMALIZED)
    assert (
        estimate_proximity(
            vehicle_outline=[(0.4, 0.6), (0.55, 0.6)],  # only 2 points
            vehicle_length_feet=VEHICLE_LENGTH_FEET,
            distance_threshold_feet=6.0,
            person_bbox=bbox,
            frame_width=FRAME[0],
            frame_height=FRAME[1],
        )
        is None
    )


def test_estimate_proximity_rejects_zero_length_feet() -> None:
    bbox = (0.5, 0.5, 0.02, EXPECTED_HEIGHT_NORMALIZED)
    assert (
        estimate_proximity(
            vehicle_outline=VEHICLE_OUTLINE,
            vehicle_length_feet=0.0,
            distance_threshold_feet=6.0,
            person_bbox=bbox,
            frame_width=FRAME[0],
            frame_height=FRAME[1],
        )
        is None
    )


def test_estimate_proximity_rejects_a_zero_area_outline() -> None:
    bbox = (0.5, 0.5, 0.02, EXPECTED_HEIGHT_NORMALIZED)
    assert (
        estimate_proximity(
            vehicle_outline=[(0.5, 0.5), (0.5, 0.5), (0.5, 0.5)],  # all points identical
            vehicle_length_feet=VEHICLE_LENGTH_FEET,
            distance_threshold_feet=6.0,
            person_bbox=bbox,
            frame_width=FRAME[0],
            frame_height=FRAME[1],
        )
        is None
    )
